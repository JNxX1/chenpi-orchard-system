"""登录会话与密码处理。

密码使用 Werkzeug 的 PBKDF2-SHA256 哈希存储，源码和数据库中都不保存明文。
会话只保存用户 id，用户对象每次请求从数据库重新加载（被禁用后立即失效）。
"""
from datetime import datetime

from flask import current_app, g, session
from werkzeug.security import check_password_hash, generate_password_hash

from ..extensions import db
from ..models import User

PASSWORD_MIN_LEN = 6


class AuthError(ValueError):
    pass


def hash_password(password):
    return generate_password_hash(password, method="pbkdf2:sha256")


def verify_password(user, password):
    return bool(user and user.password_hash) and check_password_hash(user.password_hash, password)


def validate_new_password(raw, confirm):
    raw = (raw or "").strip()
    if len(raw) < PASSWORD_MIN_LEN:
        raise AuthError(f"新密码至少 {PASSWORD_MIN_LEN} 位")
    if raw != (confirm or "").strip():
        raise AuthError("两次输入的新密码不一致")
    return raw


def login_user(user):
    session.clear()
    session["uid"] = user.id
    session.permanent = True
    user.last_login_at = datetime.now()
    db.session.commit()


def logout_user():
    session.clear()


def current_user():
    return getattr(g, "user", None)


def load_current_user():
    """每个请求加载当前用户；用户被删除或禁用时立即失效。"""
    uid = session.get("uid")
    user = db.session.get(User, uid) if uid else None
    if user and not user.is_active:
        session.clear()
        user = None
    g.user = user
    return user


def ensure_default_admin(app):
    """首次启动且没有任何用户时创建初始管理员。"""
    if not app.config.get("AUTH_ENABLED", True):
        return None
    username = app.config["ADMIN_USERNAME"]
    if User.query.count():
        return None
    pw = app.config["ADMIN_PASSWORD"]
    admin = User(username=username, password_hash=hash_password(pw),
                 display_name="系统管理员", role="管理员", must_change_password=True)
    db.session.add(admin)
    db.session.commit()
    app.logger.warning("已创建初始管理员 %s（初始密码请在登录后立即修改）", username)
    return admin
