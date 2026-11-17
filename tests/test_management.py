from app.models import InspectionPlan, Orchard, Plot
from app.extensions import db


def test_orchard_crud(client, app):
    r = client.post("/orchards/new", data={"code": "XH-01", "name": "新会一号园", "area_mu": "30",
                                           "density": "45", "planting_date": "2018-03-01"},
                    follow_redirects=True)
    assert "果园已创建" in r.get_data(as_text=True)
    with app.app_context():
        o = Orchard.query.one()
        assert o.area_mu == 30 and o.planting_date.year == 2018
    client.post("/orchards/1/edit", data={"code": "XH-01", "name": "新会一号园(改)"})
    assert "新会一号园(改)" in client.get("/orchards/?q=改").get_data(as_text=True)
    client.post("/orchards/1/delete")
    with app.app_context():
        assert Orchard.query.count() == 0


def test_orchard_validation(client, app):
    r = client.post("/orchards/new", data={"code": "", "name": "x"})
    assert "果园编号不能为空" in r.get_data(as_text=True)
    r = client.post("/orchards/new", data={"code": "A", "name": "x", "area_mu": "abc"})
    assert "面积必须是数字" in r.get_data(as_text=True)
    client.post("/orchards/new", data={"code": "DUP", "name": "x"})
    r = client.post("/orchards/new", data={"code": "DUP", "name": "y"})
    assert "果园编号已存在" in r.get_data(as_text=True)
    with app.app_context():
        assert Orchard.query.count() == 1


def test_plot_and_plan_relations(client, app, seeded):
    with app.app_context():
        assert Plot.query.one().orchard.code == "T-01"
        assert InspectionPlan.query.one().plot_id == 1
    # 同一果园地块编号唯一
    r = client.post("/plots/new", data={"orchard_id": "1", "code": "A01"})
    assert "不能重复" in r.get_data(as_text=True)
    # 地块必须属于所选果园
    client.post("/orchards/new", data={"code": "T-02", "name": "另一个园"})
    r = client.post("/plans/new", data={"name": "x", "orchard_id": "2", "plot_id": "1",
                                        "planned_date": "2026-10-15"})
    assert "不属于该果园" in r.get_data(as_text=True)
    # 有关联数据时禁止删除
    r = client.post("/orchards/1/delete", follow_redirects=True)
    assert "仍有地块或巡检计划" in r.get_data(as_text=True)
    r = client.post("/plots/1/delete", follow_redirects=True)
    assert "不能删除" in r.get_data(as_text=True)


def test_plan_status_update(client, app, seeded):
    client.post("/plans/1/status", data={"status": "已完成"})
    with app.app_context():
        p = db.session.get(InspectionPlan, 1)
        assert p.status == "已完成" and p.executed_date is not None
    r = client.post("/plans/1/status", data={"status": "乱写"}, follow_redirects=True)
    assert "状态取值无效" in r.get_data(as_text=True)


def test_dashboard_empty_state(client):
    html = client.get("/dashboard").get_data(as_text=True)
    assert "暂无数据" in html
    data = client.get("/api/charts").get_json()
    assert data["class_counts"] == {} and data["daily"]["labels"] == []
