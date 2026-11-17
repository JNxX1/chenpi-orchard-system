import pytest
from openpyxl import load_workbook

from app.models import ReportRecord, YieldEstimate
from app.services import yield_service as ys
from tests.conftest import make_image
from tests.test_images import upload


def test_compute_formula():
    r = ys.compute(sample_fruit_count=300, sample_tree_count=3, target_tree_count=50,
                   correction_factor=1.2, avg_fruit_weight_g=80)
    assert r["avg_fruit_per_tree"] == 100
    assert r["est_fruit_count"] == 6000
    assert r["est_yield_kg"] == 480


@pytest.mark.parametrize("args,msg", [
    ((10, 0, 5, 1, 80), "样本树数"), ((10, 2, 0, 1, 80), "目标树数"),
    ((10, 2, 5, 0, 80), "校正系数"), ((10, 2, 5, 1, 0), "单果重"), ((-1, 2, 5, 1, 80), "样本检测果数")])
def test_compute_invalid(args, msg):
    with pytest.raises(ys.YieldError, match=msg):
        ys.compute(*args)


def _prepare(client):
    upload(client, [(make_image(n_fruits=3), "a.jpg"), (make_image(n_fruits=2), "b.jpg")],
           sample_trees="1", auto_recognize="1")


def test_yield_plot_level_from_samples(client, app, seeded):
    _prepare(client)
    data = client.get("/yields/samples/1").get_json()
    assert data["fruit"] == 5 and data["trees"] == 2 and data["plot_trees"] == 50
    r = client.post("/yields/new", data={"plan_id": "1", "level": "地块", "count_source": "model",
                                         "correction_factor": "1.0", "avg_fruit_weight_g": "100"},
                    follow_redirects=True)
    assert "估产记录已保存" in r.get_data(as_text=True)
    with app.app_context():
        y = YieldEstimate.query.one()
        # 5 果 / 2 树 = 2.5；× 50 株 × 1.0 = 125 个；× 100g = 12.5 kg
        assert y.avg_fruit_per_tree == 2.5 and y.est_fruit_count == 125 and y.est_yield_kg == 12.5
        assert y.plot_id == 1 and y.is_demo and "演示" in y.remark
        assert y.formula and y.class_breakdown


def test_yield_uses_reviewed_count(client, app, seeded):
    _prepare(client)
    client.post("/results/run/1/review", data={"reviewed_count": "13"})
    client.post("/yields/new", data={"plan_id": "1", "level": "全园", "count_source": "reviewed",
                                     "correction_factor": "1", "avg_fruit_weight_g": "100"})
    with app.app_context():
        y = YieldEstimate.query.one()
        assert y.sample_fruit_count == 15  # 13(复核) + 2(模型)
        assert y.target_tree_count == 200 and y.plot_id is None


def test_yield_single_tree_and_missing_params(client, app, seeded):
    _prepare(client)
    r = client.post("/yields/new", data={"plan_id": "1", "level": "单株", "correction_factor": "1",
                                         "avg_fruit_weight_g": ""})
    assert "平均单果重不能为空" in r.get_data(as_text=True)
    client.post("/yields/new", data={"plan_id": "1", "level": "单株", "correction_factor": "1",
                                     "avg_fruit_weight_g": "100"})
    with app.app_context():
        assert YieldEstimate.query.one().target_tree_count == 1


def test_yield_without_sample_trees(client, app, seeded):
    upload(client, [(make_image(), "a.jpg")], auto_recognize="1")
    r = client.post("/yields/new", data={"plan_id": "1", "level": "地块", "correction_factor": "1",
                                         "avg_fruit_weight_g": "100"})
    assert "样本树数必须大于 0" in r.get_data(as_text=True)


def test_reports_export_consistent(client, app, seeded):
    _prepare(client)
    client.post("/yields/new", data={"plan_id": "1", "level": "地块", "count_source": "model",
                                     "correction_factor": "1.0", "avg_fruit_weight_g": "100"})
    for rtype in ("inspection", "grading", "yield"):
        html = client.get(f"/reports/?report_type={rtype}&orchard_id=1").get_data(as_text=True)
        assert "演示" in html
        for fmt in ("xlsx", "pdf"):
            r = client.post("/reports/export", data={"report_type": rtype, "orchard_id": "1", "fmt": fmt},
                            follow_redirects=True)
            assert r.status_code == 200 and len(r.data) > 500
            if fmt == "pdf":
                assert r.data[:4] == b"%PDF"
    with app.app_context():
        recs = ReportRecord.query.all()
        assert len(recs) == 6
        xlsx = next(r for r in recs if r.report_type == "grading" and r.fmt == "xlsx")
        ws = load_workbook(app.config["STORAGE_DIR"] / xlsx.file_path).active
        values = [c.value for row in ws.iter_rows() for c in row]
        assert "橙色目标(演示)" in values and 5 in values  # 与数据库一致：共 5 个目标


def test_assistant_db_answers(client, seeded):
    _prepare(client)
    r = client.post("/assistant/ask", json={"question": "有哪些未完成的巡检任务"}).get_json()
    assert "测试巡检" in r["facts"] and r["source"] == "rules" and r["answer"] is None
    r = client.post("/assistant/ask", json={"question": "识别统计"}).get_json()
    assert "模型检测目标 5 个" in r["facts"] and "演示模式" in r["facts"]
    assert client.post("/assistant/ask", json={"question": ""}).status_code == 400


def test_assistant_disease_knowledge(client, seeded):
    r = client.post("/assistant/ask", json={"question": "果实上有溃疡病怎么办"}).get_json()
    assert "溃疡病" in r["facts"] and "辅助参考" in r["facts"]
    r = client.post("/assistant/ask", json={"question": "红蜘蛛怎么防治"}).get_json()
    assert "红蜘蛛" in r["facts"]


def test_assistant_uses_llm_when_ready(client, seeded, monkeypatch):
    from app.services import llm
    monkeypatch.setattr(llm, "status", lambda: {"ready": True, "model": "test-model",
                                                "enabled": True, "detail": ""})
    monkeypatch.setattr(llm, "ask", lambda q, facts: "根据数据库，当前有 1 个未完成任务。")
    r = client.post("/assistant/ask", json={"question": "还有哪些任务没完成"}).get_json()
    assert r["answer"].startswith("根据数据库") and r["source"] == "ai"
    assert "测试巡检" in r["facts"] and r["error"] is None


def test_assistant_falls_back_when_llm_fails(client, seeded, monkeypatch):
    from app.services import llm

    def boom(q, facts):
        raise llm.LLMError("连接超时")

    monkeypatch.setattr(llm, "status", lambda: {"ready": True, "model": "m", "enabled": True,
                                                "detail": ""})
    monkeypatch.setattr(llm, "ask", boom)
    r = client.post("/assistant/ask", json={"question": "系统概况"}).get_json()
    assert r["answer"] is None and r["source"] == "rules"
    assert "连接超时" in r["error"] and r["facts"]


def test_dashboard_with_data(client, seeded):
    _prepare(client)
    d = client.get("/api/charts").get_json()
    assert d["class_counts"] == {"橙色目标(演示)": 5}
    assert sum(d["daily"]["values"]) == 5

def test_yield_trend_mom_yoy(app):
    """环比取上月、同比取去年同月；缺失月份显示为 None。"""
    from datetime import datetime

    from app.extensions import db
    from app.models import Orchard, YieldEstimate
    from app.services import stats

    with app.app_context():
        o = Orchard(code="T-TREND", name="趋势测试园")
        db.session.add(o)
        db.session.flush()

        def add(ym, kg):
            db.session.add(YieldEstimate(
                level="全园", orchard_id=o.id, sample_fruit_count=10, sample_tree_count=1,
                avg_fruit_per_tree=10, target_tree_count=10, correction_factor=1,
                avg_fruit_weight_g=1, est_fruit_count=100, est_yield_kg=kg,
                created_at=datetime.strptime(ym + "-05", "%Y-%m-%d")))

        add("2025-10", 100)
        add("2026-09", 80)
        add("2026-10", 120)
        db.session.commit()

        t = stats.yield_trend()
        rows = {r["month"]: r for r in t["rows"]}
        assert rows["2026-10"]["mom"] == 50.0
        assert rows["2026-10"]["yoy"] == 20.0
        assert rows["2025-10"]["mom"] is None and rows["2025-10"]["yoy"] is None
        assert t["has_mom"] is True and t["has_yoy"] is True


def test_yield_trend_insufficient_data(app):
    from app.services import stats
    with app.app_context():
        t = stats.yield_trend()
        assert t["rows"] == [] and t["has_mom"] is False and t["has_yoy"] is False

