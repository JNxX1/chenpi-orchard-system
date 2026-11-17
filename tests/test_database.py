"""只读数据浏览页面。"""
from app.extensions import db
from app.models import Orchard


def test_database_index_lists_tables(client, seeded):
    r = client.get("/database/")
    assert r.status_code == 200
    html = r.get_data(as_text=True)
    assert "数据浏览" in html and "orchards" in html and "果园" in html


def test_database_table_view(client, seeded):
    r = client.get("/database/?table=orchards")
    assert r.status_code == 200
    html = r.get_data(as_text=True)
    assert "T-01" in html and "测试果园" in html and "共 1 条记录" in html


def test_database_unknown_table_is_safe(client, seeded):
    r = client.get("/database/?table=sqlite_master;drop")
    assert r.status_code == 200
    assert "共 1 条记录" not in r.get_data(as_text=True)


def test_database_export_csv(client, seeded):
    r = client.get("/database/export?table=orchards")
    assert r.status_code == 200
    assert r.mimetype == "text/csv"
    body = r.get_data(as_text=True)
    assert body.startswith("\ufeff") and "编号" in body and "T-01" in body
    assert client.get("/database/export?table=not_exist").status_code == 404


def test_database_search_filter(client, app, seeded):
    with app.app_context():
        db.session.add(Orchard(code="T-02", name="另一个果园"))
        db.session.commit()
    html = client.get("/database/?table=orchards&q=T-02").get_data(as_text=True)
    assert "另一个果园" in html and "T-01" not in html
