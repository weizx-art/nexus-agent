import base64
import binascii
import hashlib
import re
import secrets
import uuid
from datetime import datetime, timedelta
from hashlib import sha3_256
from typing import Any

import jwt

from core.config import settings

# ---- 密码 ----
PASSWORD_PATTERN = r"^(?=.*[a-zA-Z])(?=.*\d).{8,16}$"
# OWASP 2023 推荐: 至少 600000 轮
PBKDF2_ITERATIONS = 600000


def validate_password_strength(password: str) -> None:
    """校验密码强度，不合法抛 ValueError"""
    if re.match(PASSWORD_PATTERN, password) is None:
        raise ValueError("密码至少包含一个字母、一个数字，且长度为 8-16 位")


def hash_password(password: str, salt: bytes) -> bytes:
    """密码 + 盐 做 pbkdf2_hmac 哈希"""
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, PBKDF2_ITERATIONS)
    return binascii.hexlify(dk)


def compare_password(password: str, password_hashed_base64: str, salt_base64: str) -> bool:
    """校验密码是否匹配"""
    return hash_password(password, base64.b64decode(salt_base64)) == base64.b64decode(
        password_hashed_base64
    )


def generate_password_salt_and_hash(password: str) -> tuple[str, str]:
    """生成随机盐并返回 (base64_salt, base64_password_hashed)"""
    salt = secrets.token_bytes(16)
    password_hashed = hash_password(password, salt)
    return base64.b64encode(salt).decode(), base64.b64encode(password_hashed).decode()


# ---- JWT ----
def create_access_token(account_id: Any) -> tuple[str, int]:
    """签发 JWT，返回 (token, expire_at_ts)"""
    expire_at = int((datetime.now() + timedelta(days=settings.JWT_EXPIRE_DAYS)).timestamp())
    payload = {
        "sub": str(account_id),
        "iss": "nexus-agent",
        "exp": expire_at,
        "jti": str(uuid.uuid4()),  # 唯一 JWT ID，防止重放
        "iat": int(datetime.now().timestamp()),  # 签发时间
    }
    token = jwt.encode(payload, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)
    return token, expire_at


def decode_access_token(token: str) -> dict:
    """解析 JWT，失败抛异常"""
    return jwt.decode(token, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])


_TEXT_HASH_SALT = "nexus-agent:v1"


def generate_text_hash(text: str) -> str:
    """计算文本内容的 SHA3-256 哈希值，用于检测内容是否变更"""
    return sha3_256(f"{_TEXT_HASH_SALT}:{text}".encode()).hexdigest()
