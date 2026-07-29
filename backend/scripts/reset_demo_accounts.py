"""预检并受控清理演示账号；必须从backend目录以模块方式运行。"""

import argparse
import json

from sqlalchemy.orm import Session

from app.db.session import get_engine
from app.maintenance.demo_accounts import (
    DEMO_ACCOUNT_CONFIRM_PHRASE,
    DemoAccountMaintenanceService,
    cleanup_plan_as_dict,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--owner-email", required=True, help="必须保留的真实超级管理员邮箱")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--preflight", action="store_true", help="只读输出精确计划")
    mode.add_argument(
        "--confirm",
        metavar="PHRASE",
        help=f"执行时必须精确传入 {DEMO_ACCOUNT_CONFIRM_PHRASE}",
    )
    parser.add_argument(
        "--plan-fingerprint",
        help="执行时必须传入本次预检输出的fingerprint",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    with Session(get_engine()) as session:
        service = DemoAccountMaintenanceService(session)
        if args.preflight:
            plan = service.preflight(args.owner_email)
        else:
            if not args.plan_fingerprint:
                raise SystemExit("--confirm 同时要求 --plan-fingerprint")
            plan = service.execute(
                args.owner_email,
                expected_fingerprint=args.plan_fingerprint,
                confirmation=args.confirm,
            )
    print(json.dumps(cleanup_plan_as_dict(plan), ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
