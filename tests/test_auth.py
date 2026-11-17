"""登录、会话保护与修改密码。"""
import pytest

from app import create_app
from app.config import TestConfig
from app.extensions import db
from app.models import User


@pytest.fixture()
def auth_app(tmp_path):
    app = create_app(TestConfig, AUTH_ENABLED=True, STORAGE_DIR=tmp_path / "storage",
                     MODEL_PATH=str(tmp_path / "no_model.pt"))
    yield app
    with app.app_context():
        db.session.remove()
        db.drop_all()


@pytest.fixture()
def c(auth_app):
    return auth_app.test_client()


def test_default_admin_created(auth_app):
    with auth_app.app_context():
        admin = User.query.filter_by(username="admin").one()
        assert admin.password_hash != "admin123" and admin.password_hash.startswith("pbkdf2:")
        assert admin.must_change_password is True


def test_login_required(c, auth_app):
    assert c.get("/").status_code == 200          # 宣传首页对外公开
    assert "陈皮柑果园智慧管理系统" in c.get("/").get_data(as_text=True)
    r = c.get("/dashboard")
    assert r.status_code == 302 and "/login" in r.headers["Location"]
    assert c.get("/orchards/").status_code == 302
    assert c.get("/live/").status_code == 302
    assert c.get("/api/charts").status_code == 401
    assert c.get("/login").status_code == 200


def test_wrong_password_rejected(c):
    r = c.post("/login", data={"username": "admin", "password": "wrong-pass"})
    assert "用户名或密码错误" in r.get_data(as_text=True)
    assert c.get("/dashboard").status_code == 302


def test_login_then_access(c):
    r = c.post("/login", data={"username": "admin", "password": "admin123"})
    assert r.status_code == 302 and r.headers["Location"].endswith("/account/password")
    assert c.get("/dashboard").status_code == 200
    assert c.get("/api/charts").status_code == 200


def test_login_page_rejects_open_redirect(c):
    r = c.post("/login", data={"username": "admin", "password": "admin123",
                               "next": "http://evil.example.com/"})
    assert "evil.example.com" not in r.headers["Location"]
    c.post("/logout")
    r = c.post("/login", data={"username": "admin", "password": "admin123", "next": "//evil.example.com"})
    assert "evil.example.com" not in r.headers["Location"]


def test_logout(c):
    c.post("/login", data={"username": "admin", "password": "admin123"})
    assert c.get("/dashboard").status_code == 200
    c.post("/logout")
    assert c.get("/dashboard").status_code == 302


def test_change_password_flow(c):
    c.post("/login", data={"username": "admin", "password": "admin123"})
    r = c.post("/account/password", data={"old_password": "bad", "new_password": "orchard2026",
                                          "confirm_password": "orchard2026"})
    assert "原密码不正确" in r.get_data(as_text=True)
    r = c.post("/account/password", data={"old_password": "admin123", "new_password": "123",
                                          "confirm_password": "123"}, follow_redirects=True)
    assert "至少" in r.get_data(as_text=True)
    r = c.post("/account/password", data={"old_password": "admin123", "new_password": "orchard2026",
                                          "confirm_password": "orchard2026"}, follow_redirects=True)
    assert "密码已修改" in r.get_data(as_text=True)
    c.post("/logout")
    assert "用户名或密码错误" in c.post("/login", data={"username": "admin", "password": "admin123"}) \
        .get_data(as_text=True)
    assert c.post("/login", data={"username": "admin", "password": "orchard2026"}).status_code == 302


def test_disabled_user_cannot_login(c, auth_app):
    with auth_app.app_context():
        u = User.query.filter_by(username="admin").one()
        u.is_active = False
        db.session.commit()
    r = c.post("/login", data={"username": "admin", "password": "admin123"})
    assert "用户名或密码错误" in r.get_data(as_text=True)
