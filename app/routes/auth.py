"""登录、退出、修改密码。"""
from urllib.parse import urlparse

from flask import (Blueprint, current_app, flash, redirect, render_template, request, session,
                   url_for)

from ..extensions import db
from ..models import User
from ..services import security
from ..utils import FormError
from werkzeug.security import check_password_hash

bp = Blueprint("auth", __name__)

# 用户不存在时也做一次哈希校验，避免通过响应时间判断用户名是否存在
_DUMMY_HASH = security.hash_password("not-a-real-password")


def _safe_next(target):
    """只允许站内相对路径，防止开放重定向。"""
    if not target or not target.startswith("/") or target.startswith("//") or "\\" in target:
        return None
    parsed = urlparse(target)
    if parsed.scheme or parsed.netloc:
        return None
    return target


@bp.route("/login", methods=["GET", "POST"])
def login():
    if security.current_user():
        return redirect(url_for("main.dashboard"))
    next_url = _safe_next(request.values.get("next"))
    username = ""
    if request.method == "POST":
        username = (request.form.get("username") or "").strip()
        password = request.form.get("password") or ""
        failures = session.get("login_failures", 0)
        if failures >= current_app.config["MAX_LOGIN_FAILURES"]:
            flash("登录失败次数过多，请稍后再试或联系管理员重置密码", "danger")
            return render_template("auth/login.html", next=next_url, username=username), 429
        user = User.query.filter_by(username=username).first()
        if user is None:
            check_password_hash(_DUMMY_HASH, password)  # 与真实校验耗时一致
            ok = False
        else:
            ok = security.verify_password(user, password)
        if not ok or not user.is_active:
            session["login_failures"] = failures + 1
            flash("用户名或密码错误", "danger")
        else:
            session.pop("login_failures", None)
            security.login_user(user)
            flash(f"欢迎回来，{user.name}", "success")
            if user.must_change_password:
                return redirect(url_for("auth.password"))
            return redirect(next_url or url_for("main.dashboard"))
    return render_template("auth/login.html", next=next_url, username=username)


@bp.route("/logout", methods=["POST"])
def logout():
    security.logout_user()
    flash("已退出登录", "info")
    return redirect(url_for("auth.login"))


@bp.route("/account/password", methods=["GET", "POST"])
def password():
    user = security.current_user()
    if request.method == "POST":
        try:
            if not security.verify_password(user, request.form.get("old_password") or ""):
                raise FormError("原密码不正确")
            new = security.validate_new_password(request.form.get("new_password"),
                                                 request.form.get("confirm_password"))
            if new == (request.form.get("old_password") or ""):
                raise FormError("新密码不能与原密码相同")
            user.password_hash = security.hash_password(new)
            user.must_change_password = False
            db.session.commit()
            flash("密码已修改", "success")
            return redirect(url_for("main.dashboard"))
        except (FormError, security.AuthError) as e:
            flash(str(e), "danger")
    return render_template("auth/password.html", user=user)
