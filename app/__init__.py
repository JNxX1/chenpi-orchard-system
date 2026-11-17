"""陈皮柑果园智慧管理系统 —— Flask 应用工厂。"""
from pathlib import Path

from dotenv import load_dotenv
from flask import Flask, g, jsonify, redirect, render_template, request, url_for

BASE_DIR = Path(__file__).resolve().parent.parent
# 必须在导入 config 之前读取 .env，否则 Config 类属性在导入时就固定了默认值
load_dotenv(BASE_DIR / ".env")

from .config import Config  # noqa: E402
from .extensions import db  # noqa: E402


def _ensure_schema():
    """SQLite 轻量迁移：给已有库补新列（create_all 不会修改已存在的表）。"""
    from sqlalchemy import inspect, text

    wanted = {
        "detections": {"maturity": "VARCHAR(10)"},
        "recognition_runs": {"maturity_counts": "JSON"},
        "images": {"source": "VARCHAR(20)"},
    }
    with db.engine.begin() as conn:
        for table, columns in wanted.items():
            existing = {c["name"] for c in inspect(db.engine).get_columns(table)}
            for name, ddl in columns.items():
                if name not in existing:
                    conn.execute(text(f'ALTER TABLE "{table}" ADD COLUMN {name} {ddl}'))


def create_app(config_object=Config, **overrides):
    app = Flask(__name__, instance_path=str(BASE_DIR / "instance"))
    app.config.from_object(config_object)
    app.config.update(overrides)

    Path(app.instance_path).mkdir(parents=True, exist_ok=True)
    storage = Path(app.config["STORAGE_DIR"])
    for sub in ("originals", "results", "reports"):
        (storage / sub).mkdir(parents=True, exist_ok=True)

    db.init_app(app)

    from .routes import register_blueprints
    register_blueprints(app)

    from .utils import register_template_helpers
    register_template_helpers(app)

    from .services import security

    @app.before_request
    def _load_user():
        security.load_current_user()

    @app.before_request
    def _require_login():
        """未登录时：页面跳登录页，接口返回 401。登录页与静态资源除外。"""
        if not app.config.get("AUTH_ENABLED", True):
            return None
        if request.endpoint in ("static", "auth.login", "main.landing") or request.endpoint is None:
            return None
        if getattr(g, "user", None):
            return None
        if request.path.startswith(("/api/", "/assistant/ask")):
            return jsonify(error="未登录或会话已过期"), 401
        return redirect(url_for("auth.login", next=request.full_path))

    @app.context_processor
    def _inject_user():
        return {"current_user": getattr(g, "user", None)}

    @app.errorhandler(404)
    def not_found(e):
        return render_template("error.html", code=404, message="页面或资源不存在"), 404

    @app.errorhandler(413)
    def too_large(e):
        return render_template("error.html", code=413, message="上传内容过大"), 413

    @app.errorhandler(500)
    def server_error(e):
        return render_template("error.html", code=500, message="服务器内部错误"), 500

    with app.app_context():
        from . import models  # noqa: F401
        db.create_all()
        _ensure_schema()
        security.ensure_default_admin(app)

    return app
