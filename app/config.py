"""统一配置：所有路径、模型参数均可通过环境变量 / .env 覆盖。"""
import os
from datetime import timedelta
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent


def _env_bool(name, default=False):
    val = os.environ.get(name)
    if val is None:
        return default
    return val.strip().lower() in ("1", "true", "yes", "on")


class Config:
    SECRET_KEY = os.environ.get("SECRET_KEY", "dev-only-change-me")
    SQLALCHEMY_DATABASE_URI = os.environ.get(
        "DATABASE_URL", "sqlite:///" + str(BASE_DIR / "instance" / "orchard.db")
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    # SQLite 默认写锁等待时间太短，Navicat 同时查看时容易 database is locked
    if SQLALCHEMY_DATABASE_URI.startswith("sqlite"):
        SQLALCHEMY_ENGINE_OPTIONS = {"connect_args": {"timeout": 15}}

    # 文件存储
    STORAGE_DIR = BASE_DIR / os.environ.get("STORAGE_DIR", "storage")  # 相对路径以项目根目录为准
    ALLOWED_IMAGE_EXTENSIONS = {"jpg", "jpeg", "png"}
    MAX_IMAGE_SIZE = int(os.environ.get("MAX_IMAGE_SIZE_MB", "15")) * 1024 * 1024
    MAX_CONTENT_LENGTH = int(os.environ.get("MAX_UPLOAD_TOTAL_MB", "200")) * 1024 * 1024

    # AI 识别
    MODEL_PATH = str(BASE_DIR / os.environ.get("MODEL_PATH", "models/chenpigan_best.pt"))
    MODEL_CONF = float(os.environ.get("MODEL_CONF", "0.25"))
    MODEL_IOU = float(os.environ.get("MODEL_IOU", "0.45"))
    MODEL_IMGSZ = int(os.environ.get("MODEL_IMGSZ", "960"))  # 推理分辨率，密集小目标可调大
    MODEL_DEVICE = os.environ.get("MODEL_DEVICE", "")  # "" 自动，"cpu"，"0"
    # 模型说明：加载模型后显示在页面提示条里，用于说明模型来源与适用边界
    MODEL_NOTE = os.environ.get("MODEL_NOTE", "")
    # 是否允许使用 OpenCV 颜色阈值演示模式（非深度学习，结果明确标注为演示）
    ALLOW_DEMO_DETECTOR = _env_bool("ALLOW_DEMO_DETECTOR", True)
    # 相对大小分级阈值：检测框面积占整幅图像面积的比例
    SIZE_GRADE_THRESHOLDS = (0.002, 0.008)  # <小, 中间为中, >大

    # 智能助手：默认接本机 Ollama；也可切到任意 OpenAI 兼容接口（DeepSeek、通义、Moonshot 等）
    LLM_PROVIDER = os.environ.get("LLM_PROVIDER", "ollama")   # ollama / openai（OpenAI 兼容）
    LLM_BASE_URL = os.environ.get("LLM_BASE_URL", "http://127.0.0.1:11434")
    LLM_MODEL = os.environ.get("LLM_MODEL", "qwen3:8b")
    LLM_API_KEY = os.environ.get("LLM_API_KEY", "")
    LLM_TIMEOUT = int(os.environ.get("LLM_TIMEOUT", "120"))
    LLM_ENABLED = _env_bool("LLM_ENABLED", True)

    # 登录与用户（本地单机部署；生产环境请用环境变量覆盖 SECRET_KEY 和初始密码）
    AUTH_ENABLED = _env_bool("AUTH_ENABLED", True)
    ADMIN_USERNAME = os.environ.get("ADMIN_USERNAME", "admin")
    ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "admin123")
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    PERMANENT_SESSION_LIFETIME = timedelta(hours=int(os.environ.get("SESSION_HOURS", "8")))
    MAX_LOGIN_FAILURES = 5


class TestConfig(Config):
    TESTING = True
    SECRET_KEY = "test"
    LLM_ENABLED = False  # 测试默认不访问本机模型，需要时单独 monkeypatch
    AUTH_ENABLED = False  # 大部分业务测试直接操作页面，登录测试单独启用
    SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"
    WTF_CSRF_ENABLED = False
