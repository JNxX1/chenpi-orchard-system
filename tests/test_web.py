"""首页、实时识别与检测框接口。"""
import base64

from tests.conftest import make_image
from tests.test_images import upload


def test_landing_is_public(client):
    r = client.get("/")
    html = r.get_data(as_text=True)
    assert r.status_code == 200
    assert "让每一颗陈皮柑" in html and "进入系统" in html
    assert "mAP@50" in html or "mAP" in html


def test_live_page(client):
    r = client.get("/live/")
    assert r.status_code == 200
    assert "实时识别" in r.get_data(as_text=True)


def test_live_has_revenue_panel(client, seeded):
    html = client.get("/live/").get_data(as_text=True)
    assert "产值测算" in html and "测试果园" in html
    assert 'id="estValue"' in html and 'id="orchard"' in html


def test_live_detect_returns_boxes(client):
    payload = base64.b64encode(make_image(n_fruits=3).getvalue()).decode()
    r = client.post("/live/detect", json={"image": "data:image/jpeg;base64," + payload})
    assert r.status_code == 200
    data = r.get_json()
    assert data["ok"] is True and data["count"] >= 1
    assert data["boxes"] and {"x1", "y1", "x2", "y2", "label"} <= set(data["boxes"][0])
    assert data["width"] > 0 and data["height"] > 0


def test_live_detect_rejects_broken_image(client):
    r = client.post("/live/detect", json={"image": "data:image/jpeg;base64,bm90LWFuLWltYWdl"})
    assert r.status_code == 400
    assert r.get_json()["ok"] is False


def test_detections_json(client, seeded):
    upload(client, [(make_image(n_fruits=3), "a.jpg")], sample_trees="1", auto_recognize="1")
    r = client.get("/images/1/detections.json")
    assert r.status_code == 200
    data = r.get_json()
    assert data["ok"] and data["count"] == len(data["boxes"]) >= 1
    assert data["mode"] in ("yolo", "opencv_demo")


def test_detections_json_missing(client, seeded):
    assert client.get("/images/1/detections.json").status_code == 404
