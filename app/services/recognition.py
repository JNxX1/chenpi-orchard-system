"""识别业务：调用检测服务并把结果持久化。"""
import uuid
from collections import Counter
from datetime import datetime

from ..extensions import db
from ..models import Detection, RecognitionRun
from . import detector
from .storage import resolve

DET_FIELDS = ("class_id", "class_name", "confidence", "x1", "y1", "x2", "y2",
              "area_ratio", "size_grade", "maturity")


def recognize_image(image, mode="auto"):
    """对一张影像执行识别，生成新的 RecognitionRun（失败也记录原因）。返回 run。"""
    run = RecognitionRun(image_id=image.id, mode="yolo" if mode == "auto" else mode, status="失败")
    try:
        run.mode = detector.resolve_mode(mode)
        out = detector.detect(resolve(image.stored_path), run.mode)
        dets = out["detections"]
        rel = f"results/{datetime.now():%Y%m}/{uuid.uuid4().hex}.jpg"
        detector.draw_result(out["image"], dets, resolve(rel), demo=run.mode != "yolo")
        run.model_name = out["model_name"]
        run.device = out["device"]
        run.conf_threshold = out["conf"]
        run.duration_ms = out["duration_ms"]
        run.result_path = rel
        run.total_count = len(dets)
        run.class_counts = dict(Counter(d["class_name"] for d in dets))
        run.size_counts = dict(Counter(d["size_grade"] for d in dets))
        run.maturity_counts = dict(Counter(d["maturity"] for d in dets))
        run.status = "成功"
        for d in dets:
            run.detections.append(Detection(**{k: d[k] for k in DET_FIELDS}))
    except Exception as e:  # 记录失败原因，不中断批量识别
        run.error_message = str(e)[:1000]
    db.session.add(run)
    db.session.flush()
    image.status = "已识别" if image.latest_run is not None else "识别失败"
    if image.plan.status == "待执行":
        image.plan.status = "进行中"
    db.session.commit()
    return run
