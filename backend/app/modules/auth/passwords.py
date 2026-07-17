"""集中处理密码哈希，业务代码不直接依赖具体 Argon2 实现。"""

from pwdlib import PasswordHash
from pwdlib.exceptions import UnknownHashError

_password_hash = PasswordHash.recommended()


def hash_password(password: str) -> str:
    return _password_hash.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return _password_hash.verify(password, password_hash)
    except (UnknownHashError, ValueError):
        # 数据库里的哈希若损坏，也只按“登录失败”处理，不向外泄漏内部细节。
        return False
