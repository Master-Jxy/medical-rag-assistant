"""用户持久化：只负责 MySQL/SQLAlchemy 查询和写入。"""

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.modules.auth.models import User


class UserRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def get_by_email(self, email: str) -> User | None:
        return self.session.scalar(select(User).where(User.email == email))

    def get_by_id(self, user_id: str) -> User | None:
        return self.session.get(User, user_id)

    def list_users(
        self,
        *,
        offset: int,
        limit: int,
        search: str | None = None,
        role: str | None = None,
        is_active: bool | None = None,
    ) -> list[User]:
        statement = select(User)
        if search:
            pattern = f"%{search.lower()}%"
            statement = statement.where(
                or_(
                    func.lower(User.email).like(pattern),
                    func.lower(User.display_name).like(pattern),
                )
            )
        if role is not None:
            statement = statement.where(User.role == role)
        if is_active is not None:
            statement = statement.where(User.is_active.is_(is_active))
        return self.session.scalars(
            statement.order_by(User.created_at.desc(), User.id.desc())
            .offset(offset)
            .limit(limit)
        ).all()

    def count_users(
        self,
        *,
        search: str | None = None,
        role: str | None = None,
        is_active: bool | None = None,
    ) -> int:
        statement = select(func.count()).select_from(User)
        if search:
            pattern = f"%{search.lower()}%"
            statement = statement.where(
                or_(
                    func.lower(User.email).like(pattern),
                    func.lower(User.display_name).like(pattern),
                )
            )
        if role is not None:
            statement = statement.where(User.role == role)
        if is_active is not None:
            statement = statement.where(User.is_active.is_(is_active))
        return self.session.scalar(statement) or 0

    def lock_active_super_admins(self) -> list[User]:
        return self.session.scalars(
            select(User)
            .where(User.role == "super_admin", User.is_active.is_(True))
            .with_for_update()
        ).all()

    def add(self, user: User) -> User:
        self.session.add(user)
        self.session.flush()
        return user

    def set_role(self, user: User, role: str) -> User:
        user.role = role
        self.session.flush()
        return user

    def set_active(self, user: User, is_active: bool) -> User:
        user.is_active = is_active
        self.session.flush()
        return user
