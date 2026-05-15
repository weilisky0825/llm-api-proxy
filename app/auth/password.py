from __future__ import annotations

import bcrypt


def hash_password(password: str) -> str:
    """哈希密码，返回字符串."""
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, hash_str: str) -> bool:
    """验证密码是否匹配哈希."""
    return bcrypt.checkpw(password.encode("utf-8"), hash_str.encode("utf-8"))