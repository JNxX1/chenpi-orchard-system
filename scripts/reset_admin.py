"""重置管理员密码。

用法：
    python scripts/reset_admin.py                     # 交互输入新密码（推荐）
    python scripts/reset_admin.py --password 新密码    # 直接指定（会记录在命令历史里，慎用）
    python scripts/reset_admin.py --user admin --create  # 用户不存在时创建
"""
import argparse
import getpass
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import create_app  # noqa: E402
from app.extensions import db  # noqa: E402
from app.models import User  # noqa: E402
from app.services import security  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description="重置系统用户密码")
    parser.add_argument("--user", default="admin")
    parser.add_argument("--password")
    parser.add_argument("--create", action="store_true", help="用户不存在时创建")
    args = parser.parse_args()

    password = args.password
    if not password:
        password = getpass.getpass("新密码（至少 6 位）：")
        if password != getpass.getpass("再次输入："):
            print("两次输入不一致")
            return 1
    if len(password) < security.PASSWORD_MIN_LEN:
        print(f"密码至少 {security.PASSWORD_MIN_LEN} 位")
        return 1

    app = create_app()
    with app.app_context():
        user = User.query.filter_by(username=args.user).first()
        if user is None:
            if not args.create:
                print(f"用户 {args.user} 不存在；如需创建请加 --create")
                return 1
            user = User(username=args.user, display_name=args.user, role="管理员")
            db.session.add(user)
        user.password_hash = security.hash_password(password)
        user.must_change_password = False
        user.is_active = True
        db.session.commit()
        print(f"已重置用户 {user.username} 的密码。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
