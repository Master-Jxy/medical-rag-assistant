"""显式确认后把已有账号初始化为超级管理员，不创建账号或接收密码。"""

import argparse

from sqlalchemy.orm import Session

from app.db.session import get_engine
from app.modules.auth.maintenance import SuperAdminInitializationService


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("email", help="已注册邮箱")
    parser.add_argument("--operator", required=True, help="执行本次维护的操作者标识")
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
        result = SuperAdminInitializationService(session).initialize(
            args.email,
            operator=args.operator,
        )

    outcome = "initialized" if result.changed else "unchanged"
    print(
        f"super_admin_{outcome} "
        f"email={result.user.email} operator={result.operator}"
    )


if __name__ == "__main__":
    main()
