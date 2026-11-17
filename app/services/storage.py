"""影像上传校验与安全存储。"""
import uuid
from datetime import datetime
from pathlib import Path

from flask import current_app
from PIL import Image, UnidentifiedImageError

PIL_FORMATS = {"JPEG": {"jpg", "jpeg"}, "PNG": {"png"}}


class UploadError(ValueError):
    pass


def storage_root() -> Path:
    return Path(current_app.config["STORAGE_DIR"]).resolve()


def resolve(rel_path: str) -> Path:
    """把数据库中的相对路径解析为绝对路径，并防止路径穿越。"""
    root = storage_root()
    full = (root / rel_path).resolve()
    if root not in full.parents:
        raise UploadError("非法文件路径")
    return full


def _ext(filename: str) -> str:
    return filename.rsplit(".", 1)[-1].lower() if "." in filename else ""


def save_upload(file_storage):
    """校验并保存一张上传图片，返回元数据 dict。文件名由系统生成，不使用用户文件名。"""
    original = (file_storage.filename or "").replace("\\", "/").split("/")[-1].strip()
    if not original:
        raise UploadError("文件名为空")
    ext = _ext(original)
    if ext not in current_app.config["ALLOWED_IMAGE_EXTENSIONS"]:
        raise UploadError(f"{original}：仅支持 JPG/JPEG/PNG 格式")

    data = file_storage.read()
    size = len(data)
    if size == 0:
        raise UploadError(f"{original}：文件为空")
    limit = current_app.config["MAX_IMAGE_SIZE"]
    if size > limit:
        raise UploadError(f"{original}：文件超过 {limit // 1024 // 1024} MB 限制")

    # 用 Pillow 校验真实内容，防止伪造扩展名
    from io import BytesIO
    try:
        with Image.open(BytesIO(data)) as img:
            fmt = img.format
            img.verify()
        with Image.open(BytesIO(data)) as img:
            width, height = img.size
            captured = _exif_time(img)
            exif_lat, exif_lng = _exif_gps(img)
    except (UnidentifiedImageError, OSError, SyntaxError):
        raise UploadError(f"{original}：不是有效的图片文件")
    if fmt not in PIL_FORMATS or ext not in PIL_FORMATS[fmt]:
        raise UploadError(f"{original}：文件内容与扩展名不符")

    sub = datetime.now().strftime("%Y%m")
    rel = f"originals/{sub}/{uuid.uuid4().hex}.{'jpg' if ext == 'jpeg' else ext}"
    full = resolve(rel)
    full.parent.mkdir(parents=True, exist_ok=True)
    with open(full, "xb") as fh:  # x 模式：绝不覆盖已有文件
        fh.write(data)
    return {"original_name": original[:255], "stored_path": rel, "file_size": size,
            "width": width, "height": height, "captured_at": captured,
            "exif_lat": exif_lat, "exif_lng": exif_lng}


def _exif_gps(img):
    """从 EXIF 读取 GPS（没有就返回 (None, None)），用于无人机/手机照片定位。"""
    try:
        gps = img.getexif().get_ifd(0x8825)
        if not gps:
            return None, None

        def deg(values):
            d, m, s = (float(v) for v in values)
            return d + m / 60 + s / 3600

        lat = deg(gps[2])
        lng = deg(gps[4])
        if str(gps.get(1, "N")).upper().startswith("S"):
            lat = -lat
        if str(gps.get(3, "E")).upper().startswith("W"):
            lng = -lng
        return round(lat, 6), round(lng, 6)
    except Exception:
        return None, None


def _exif_time(img):
    try:
        raw = img.getexif().get(306)  # DateTime
        return datetime.strptime(raw, "%Y:%m:%d %H:%M:%S") if raw else None
    except Exception:
        return None


def delete_file(rel_path):
    if not rel_path:
        return
    try:
        p = resolve(rel_path)
        if p.is_file():
            p.unlink()
    except UploadError:
        pass
