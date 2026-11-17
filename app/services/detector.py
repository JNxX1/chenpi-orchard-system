"""AI 识别服务：模型加载（全局缓存）、推理、结果解析与结果图绘制。

两种后端：
- yolo：加载 MODEL_PATH 指定的 Ultralytics YOLOv8 权重做真实推理；
- opencv_demo：OpenCV HSV 颜色阈值 + 轮廓分析，仅用于无模型时演示流程，
  不是深度学习模型，结果在数据库与页面中均明确标注为“演示”。
"""
import threading
import time
from pathlib import Path

import cv2
import numpy as np
from flask import current_app
from PIL import Image, ImageDraw, ImageFont

_lock = threading.Lock()
_model_cache = {}  # {model_path: (mtime, model)}

FONT_CANDIDATES = ["C:/Windows/Fonts/simhei.ttf", "C:/Windows/Fonts/msyh.ttc",
                   "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc"]
PALETTE = [(255, 99, 71), (50, 205, 50), (30, 144, 255), (255, 215, 0),
           (186, 85, 211), (0, 206, 209), (255, 140, 0), (220, 20, 60)]


class DetectorError(RuntimeError):
    pass


def ultralytics_available():
    try:
        import ultralytics  # noqa: F401
        return True
    except Exception:
        return False


def detector_status():
    cfg = current_app.config
    path = Path(cfg["MODEL_PATH"])
    status = {
        "model_path": str(path),
        "model_exists": path.is_file(),
        "ultralytics": ultralytics_available(),
        "conf": cfg["MODEL_CONF"],
        "imgsz": cfg.get("MODEL_IMGSZ", 640),
        "device": cfg["MODEL_DEVICE"] or "自动",
        "demo_allowed": cfg["ALLOW_DEMO_DETECTOR"],
        "loaded": str(path) in _model_cache,
        "class_names": None,
        "note": cfg.get("MODEL_NOTE", ""),
    }
    status["yolo_ready"] = status["model_exists"] and status["ultralytics"]
    if status["loaded"]:
        status["class_names"] = list(_model_cache[str(path)][1].names.values())
    return status


def _missing_msg(st):
    if not st["ultralytics"]:
        return "未安装 ultralytics，无法使用 YOLO 模型（pip install ultralytics）"
    return f"未找到模型权重文件：{st['model_path']}，请将训练好的 .pt 文件放到该位置或设置 MODEL_PATH"


def resolve_mode(requested="auto"):
    """auto：有模型用 YOLO，否则在允许时退回演示模式。"""
    st = detector_status()
    if requested in ("auto", "yolo") and st["yolo_ready"]:
        return "yolo"
    if requested == "yolo" or not st["demo_allowed"]:
        raise DetectorError(_missing_msg(st))
    return "opencv_demo"


def get_yolo_model():
    path = current_app.config["MODEL_PATH"]
    p = Path(path)
    if not p.is_file():
        raise DetectorError(_missing_msg(detector_status()))
    mtime = p.stat().st_mtime
    with _lock:
        cached = _model_cache.get(path)
        if cached and cached[0] == mtime:
            return cached[1]
        try:
            from ultralytics import YOLO
        except Exception as e:
            raise DetectorError(f"ultralytics 导入失败：{e}")
        model = YOLO(path)
        _model_cache[path] = (mtime, model)
        return model


def read_image(path):
    """兼容中文路径的读图（返回 BGR）。"""
    data = np.fromfile(str(path), dtype=np.uint8)
    img = cv2.imdecode(data, cv2.IMREAD_COLOR)
    if img is None:
        raise DetectorError("图片读取失败")
    return img


def size_grade(area_ratio):
    """相对大小等级：基于检测框像素面积占整图比例，不代表真实果径。"""
    small, large = current_app.config["SIZE_GRADE_THRESHOLDS"]
    if area_ratio < small:
        return "小"
    if area_ratio > large:
        return "大"
    return "中"


def maturity_grade(img, det):
    """按检测框内颜色占比估算成熟度：青 / 转色 / 成熟。

    这不是模型分类：只统计框内橙黄色与绿色像素的比例，青果、逆光、套袋都会影响结果，
    页面上统一标注“颜色估算”。
    """
    h, w = img.shape[:2]
    x1 = max(0, min(w - 1, int(det["x1"])))
    x2 = max(x1 + 1, min(w, int(det["x2"])))
    y1 = max(0, min(h - 1, int(det["y1"])))
    y2 = max(y1 + 1, min(h, int(det["y2"])))
    roi = img[y1:y2, x1:x2]
    if roi.size == 0:
        return "未知"
    hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)
    hue, sat, val = cv2.split(hsv)
    orange = int(((hue >= 5) & (hue <= 28) & (sat >= 90) & (val >= 60)).sum())
    green = int(((hue >= 30) & (hue <= 90) & (sat >= 60) & (val >= 40)).sum())
    total = orange + green
    if total < 20:
        return "未知"
    ratio = orange / total
    if ratio >= 0.55:
        return "成熟"
    if ratio >= 0.2:
        return "转色"
    return "青"


def detect(image_path, mode):
    """对图片文件执行推理，返回 dict(detections, model_name, device, conf, duration_ms, image)。"""
    return detect_array(read_image(image_path), mode)


def detect_array(img, mode):
    """对 BGR ndarray 执行推理（供实时识别等场景复用）。"""
    h, w = img.shape[:2]
    t0 = time.perf_counter()
    if mode == "yolo":
        dets, model_name, device = _detect_yolo(img)
        conf = current_app.config["MODEL_CONF"]
    elif mode == "opencv_demo":
        dets, model_name, device, conf = _detect_opencv_demo(img), "OpenCV-HSV-演示", "cpu", None
    else:
        raise DetectorError(f"未知识别模式：{mode}")
    duration = int((time.perf_counter() - t0) * 1000)
    for d in dets:
        d["area_ratio"] = (d["x2"] - d["x1"]) * (d["y2"] - d["y1"]) / float(w * h)
        d["size_grade"] = size_grade(d["area_ratio"])
        d["maturity"] = maturity_grade(img, d)
    return {"detections": dets, "model_name": model_name, "device": device,
            "conf": conf, "duration_ms": duration, "image": img}


def _pick_device(explicit):
    """未显式配置时：有 CUDA 用 0 号 GPU，否则用 CPU。"""
    if explicit:
        return explicit
    try:
        import torch
        return "0" if torch.cuda.is_available() else "cpu"
    except Exception:
        return "cpu"


def _detect_yolo(img):
    cfg = current_app.config
    model = get_yolo_model()
    dev = _pick_device(cfg["MODEL_DEVICE"])
    kwargs = dict(conf=cfg["MODEL_CONF"], iou=cfg["MODEL_IOU"],
                  imgsz=cfg.get("MODEL_IMGSZ", 640), verbose=False, device=dev)
    r = model.predict(img, **kwargs)[0]
    names = r.names
    dets = []
    if r.boxes is not None:
        for xyxy, conf, cls in zip(r.boxes.xyxy.cpu().numpy(), r.boxes.conf.cpu().numpy(),
                                   r.boxes.cls.cpu().numpy()):
            cid = int(cls)
            dets.append({"class_id": cid, "class_name": str(names.get(cid, cid)),
                         "confidence": float(conf), "x1": float(xyxy[0]), "y1": float(xyxy[1]),
                         "x2": float(xyxy[2]), "y2": float(xyxy[3])})
    return dets, Path(cfg["MODEL_PATH"]).name, str(dev)


def _detect_opencv_demo(img):
    """HSV 橙黄色阈值 + 形态学 + 轮廓圆度筛选。只能检出颜色偏橙黄的近圆形区域。"""
    h, w = img.shape[:2]
    hsv = cv2.cvtColor(cv2.GaussianBlur(img, (5, 5), 0), cv2.COLOR_BGR2HSV)
    mask = cv2.inRange(hsv, (5, 100, 90), (28, 255, 255))
    k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, k, iterations=2)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, k, iterations=2)
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    min_area = h * w * 0.0002
    dets = []
    for c in contours:
        area = cv2.contourArea(c)
        if area < min_area:
            continue
        peri = cv2.arcLength(c, True)
        circularity = 4 * np.pi * area / (peri * peri) if peri else 0
        if circularity < 0.45:
            continue
        x, y, bw, bh = cv2.boundingRect(c)
        dets.append({"class_id": 0, "class_name": "橙色目标(演示)", "confidence": None,
                     "x1": float(x), "y1": float(y), "x2": float(x + bw), "y2": float(y + bh)})
    return dets


def _font(size):
    for f in FONT_CANDIDATES:
        if Path(f).exists():
            return ImageFont.truetype(f, size)
    return ImageFont.load_default()


def draw_result(img_bgr, detections, out_path, demo=False):
    img = Image.fromarray(cv2.cvtColor(img_bgr, cv2.COLOR_BGR2RGB))
    draw = ImageDraw.Draw(img)
    lw = max(2, round(min(img.size) / 300))
    font = _font(max(14, round(min(img.size) / 45)))
    names = sorted({d["class_name"] for d in detections})
    for d in detections:
        color = PALETTE[names.index(d["class_name"]) % len(PALETTE)]
        draw.rectangle([d["x1"], d["y1"], d["x2"], d["y2"]], outline=color, width=lw)
        label = d["class_name"]
        if d.get("confidence") is not None:
            label += f" {d['confidence']:.2f}"
        tb = draw.textbbox((0, 0), label, font=font)
        tw, th = tb[2] - tb[0], tb[3] - tb[1]
        ty = max(0, d["y1"] - th - 6)
        draw.rectangle([d["x1"], ty, d["x1"] + tw + 4, ty + th + 6], fill=color)
        draw.text((d["x1"] + 2, ty), label, fill=(255, 255, 255), font=font)
    banner = f"目标数：{len(detections)}"
    if demo:
        banner += "  [演示模式·非深度学习模型]"
    bfont = _font(max(16, round(min(img.size) / 30)))
    tb = draw.textbbox((0, 0), banner, font=bfont)
    draw.rectangle([0, 0, tb[2] + 16, tb[3] + 12], fill=(0, 0, 0))
    draw.text((8, 4), banner, fill=(255, 255, 0), font=bfont)
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    img.save(out_path, "JPEG", quality=90)
