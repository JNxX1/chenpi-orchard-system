import io
import tempfile

import cv2
import numpy as np
import pytest

from app import create_app
from app.config import TestConfig
from app.extensions import db


@pytest.fixture()
def app(tmp_path):
    app = create_app(TestConfig, STORAGE_DIR=tmp_path / "storage",
                     MODEL_PATH=str(tmp_path / "no_model.pt"))
    yield app
    with app.app_context():
        db.session.remove()
        db.drop_all()


@pytest.fixture()
def client(app):
    return app.test_client()


def make_image(fmt=".jpg", n_fruits=3, size=(480, 640)):
    """生成测试图：绿色背景上画 n 个橙色圆（供 OpenCV 演示模式检测）。"""
    img = np.zeros((size[0], size[1], 3), np.uint8)
    img[:] = (40, 120, 40)
    for i in range(n_fruits):
        cv2.circle(img, (80 + i * 150, 200), 40, (0, 140, 255), -1)
    ok, buf = cv2.imencode(fmt, img)
    assert ok
    return io.BytesIO(buf.tobytes())


@pytest.fixture()
def seeded(client):
    """建立 果园 → 地块 → 巡检计划，返回 id。"""
    client.post("/orchards/new", data={"code": "T-01", "name": "测试果园", "expected_trees": "200"})
    client.post("/plots/new", data={"orchard_id": "1", "code": "A01", "tree_count": "50"})
    client.post("/plans/new", data={"name": "测试巡检", "orchard_id": "1", "plot_id": "1",
                                    "planned_date": "2026-10-15", "method": "手持拍摄", "status": "待执行"})
    return {"orchard": 1, "plot": 1, "plan": 1}
