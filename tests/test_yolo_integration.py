"""YOLO 真实推理链路集成测试。

使用 Ultralytics 官方通用 COCO 预训练权重 yolov8n.pt + 官方示例图 bus.jpg，
仅用于验证“模型加载→推理→解析→绘制→入库”接口，不代表陈皮柑专用模型。
"""
from pathlib import Path

import pytest

from app.config import BASE_DIR
from app.models import RecognitionRun
from app.services import detector
from tests.test_images import upload

ultralytics = pytest.importorskip("ultralytics")
WEIGHTS = BASE_DIR / "models" / "yolov8n.pt"
BUS = Path(ultralytics.__file__).parent / "assets" / "bus.jpg"
pytestmark = pytest.mark.skipif(not WEIGHTS.is_file() or not BUS.is_file(),
                                reason="缺少 yolov8n.pt 或示例图")


def test_yolo_pipeline_with_generic_weights(client, app, seeded):
    app.config["MODEL_PATH"] = str(WEIGHTS)
    with app.app_context():
        assert detector.detector_status()["yolo_ready"]
    with open(BUS, "rb") as fh:
        r = upload(client, [(fh, "bus.jpg")], auto_recognize="1")
    assert "成功 1 张" in r.get_data(as_text=True)
    with app.app_context():
        run = RecognitionRun.query.one()
        assert run.mode == "yolo" and run.status == "成功"
        assert run.conf_threshold == app.config["MODEL_CONF"]
        assert "person" in run.class_counts and run.total_count >= 3
        d = run.detections.first()
        assert 0 <= d.confidence <= 1 and d.x2 > d.x1
        # 模型只加载一次（全局缓存）
        m1 = detector.get_yolo_model()
        m2 = detector.get_yolo_model()
        assert m1 is m2
