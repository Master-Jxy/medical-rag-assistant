"""显式确认后修改现有账号角色；不会创建账号，也不会接收或输出密码。"""

import argparse

from sqlalchemy.orm import Session

from app.db.session import get_engine
from app.modules.auth.maintenance import AdminRoleMaintenanceService


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="设置已有用户的数据库授权角色")
    parser.add_argument("email", help="已注册邮箱")
    parser.add_argument("role", choices=("user", "admin"), help="目标角色")
    parser.add_argument(
        "--confirm",
        action="store_true",
        help="确认执行；未提供时不会修改数据库",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if not args.confirm:
        raise SystemExit("未提供 --confirm，数据库没有发生变化")

    with Session(get_engine()) as session:
        user = AdminRoleMaintenanceService(session).set_role(args.email, args.role)
    print(f"role_updated email={user.email} role={user.role}")


if __name__ == "__main__":
    main()
