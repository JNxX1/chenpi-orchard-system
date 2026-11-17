"""成熟度颜色估算、地块覆盖、采收记录与采集来源。"""
from app.extensions import db
from app.models import HarvestRecord, ImageRecord, RecognitionRun
from tests.conftest import make_image
from tests.test_images import upload


def test_color_maturity_saved(client, app, seeded):
    upload(client, [(make_image(n_fruits=3), "a.jpg")], sample_trees="1", auto_recognize="1")
    with app.app_context():
        run = RecognitionRun.query.first()
        assert run.maturity_counts
        assert set(run.maturity_counts) <= {"青", "转色", "成熟", "未知"}
        assert run.detections.first().maturity in {"青", "转色", "成熟", "未知"}
    html = client.get("/images/1").get_data(as_text=True)
    assert "成熟度" in html and "颜色估算" in html


def test_dashboard_has_plot_coverage(client, seeded):
    upload(client, [(make_image(), "a.jpg")], auto_recognize="1")
    html = client.get("/dashboard").get_data(as_text=True)
    assert "地块巡检覆盖" in html and "覆盖率" in html


def test_upload_records_source(client, app, seeded):
    upload(client, [(make_image(), "a.jpg")], source="无人机航拍")
    with app.app_context():
        assert ImageRecord.query.first().source == "无人机航拍"


def test_harvest_crud_and_compare(client, app, seeded):
    r = client.post("/harvest/new", data={"orchard_id": "1", "year": "2025",
                                          "actual_yield_kg": "1000", "avg_price": "18"},
                    follow_redirects=True)
    assert "采收记录已保存" in r.get_data(as_text=True)
    with app.app_context():
        rec = HarvestRecord.query.one()
        assert rec.actual_yield_kg == 1000 and rec.year == 2025
        rid = rec.id
    html = client.get("/yields/").get_data(as_text=True)
    assert "估产 vs 实际采收" in html and "1,000" in html
    html = client.get("/harvest/").get_data(as_text=True)
    assert "实际采收合计" in html and "新会" not in html  # seeded 果园名是“测试果园”
    client.post(f"/harvest/{rid}/delete", follow_redirects=True)
    with app.app_context():
        assert HarvestRecord.query.count() == 0


def test_harvest_validation(client, seeded):
    r = client.post("/harvest/new", data={"orchard_id": "1", "year": "1800",
                                          "actual_yield_kg": "10"}, follow_redirects=True)
    assert "年份应在" in r.get_data(as_text=True)
    r = client.post("/harvest/new", data={"orchard_id": "1", "year": "2025", "plot_id": "1",
                                          "actual_yield_kg": "10"}, follow_redirects=True)
    assert "采收记录已保存" in r.get_data(as_text=True)
