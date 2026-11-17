"""实时识别：浏览器摄像头/图片帧送服务端推理，返回检测框。

不写数据库，仅用于可视化演示；正式归档仍走“影像管理 → 上传”。
"""
import base64
import io

import cv2
import numpy as np
from flask import Blueprint, jsonify, render_template, request
from PIL import Image, UnidentifiedImageError

from ..models import Orchard
from ..services import detector

bp = Blueprint("live", __name__, url_prefix="/live")

MAX_SIDE = 1280
MAX_BYTES = 4 * 1024 * 1024


def _decode(data_url):
    if not isinstance(data_url, str) or not data_url:
        raise ValueError("缺少图像数据")
    if "," in data_url:
        data_url = data_url.split(",", 1)[1]
    raw = base64.b64decode(data_url, validate=True)
    if len(raw) > MAX_BYTES:
        raise ValueError("画面过大")
    with Image.open(io.BytesIO(raw)) as im:
        im = im.convert("RGB")
        im.thumbnail((MAX_SIDE, MAX_SIDE))
        return cv2.cvtColor(np.array(im), cv2.COLOR_RGB2BGR)


@bp.route("/")
def index():
    orchards = [{"name": o.name, "trees": o.expected_trees or o.plot_tree_total or 0}
                for o in Orchard.query.order_by(Orchard.id).all()]
    return render_template("live.html", status=detector.detector_status(), orchards=orchards)


@bp.route("/detect", methods=["POST"])
def detect():
    data = request.get_json(silent=True) or {}
    try:
        frame = _decode(data.get("image"))
    except (ValueError, UnidentifiedImageError, base64.binascii.Error):
        return jsonify(ok=False, error="画面解析失败"), 400
    try:
        mode = detector.resolve_mode("auto")
        out = detector.detect_array(frame, mode)
    except Exception as e:  # 模型缺失或推理失败
        return jsonify(ok=False, error=str(e)[:200]), 500
    h, w = frame.shape[:2]
    boxes = [{"x1": round(d["x1"], 1), "y1": round(d["y1"], 1),
              "x2": round(d["x2"], 1), "y2": round(d["y2"], 1),
              "label": d["class_name"],
              "conf": None if d["confidence"] is None else round(float(d["confidence"]), 3),
              "grade": d["size_grade"]} for d in out["detections"][:120]]
    return jsonify(ok=True, mode=out["model_name"], demo=out.get("demo", mode != "yolo"),
                   count=len(boxes), boxes=boxes, width=w, height=h,
                   ms=out["duration_ms"])
