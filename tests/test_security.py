"""
单元测试：src/core/security.py
- 密码哈希/验证
- JWT token 生成/解码/过期校验
不依赖数据库或外部服务
"""
import time
from datetime import timedelta

import pytest
from jose import JWTError

from src.core.security import (
    ACCESS_TOKEN_EXPIRE_MINUTES,
    ALGORITHM,
    REFRESH_TOKEN_EXPIRE_DAYS,
    _create_token,
    create_access_token,
    create_refresh_token,
    decode_access_token,
    hash_password,
    verify_password,
)


# ── 密码哈希 ──────────────────────────────────────────────────────────
@pytest.mark.unit
class TestPasswordHashing:
    def test_hash_is_not_plaintext(self):
        hashed = hash_password("MyPass123")
        assert hashed != "MyPass123"

    def test_verify_correct_password(self):
        hashed = hash_password("MyPass123")
        assert verify_password("MyPass123", hashed) is True

    def test_verify_wrong_password(self):
        hashed = hash_password("MyPass123")
        assert verify_password("WrongPass", hashed) is False

    def test_same_password_different_hash(self):
        """bcrypt 每次生成不同 salt，哈希值不同"""
        h1 = hash_password("MyPass123")
        h2 = hash_password("MyPass123")
        assert h1 != h2

    def test_empty_password_hashes(self):
        hashed = hash_password("")
        assert verify_password("", hashed) is True


# ── JWT access token ──────────────────────────────────────────────────
@pytest.mark.unit
class TestAccessToken:
    def test_create_and_decode(self):
        token = create_access_token("member-1", "family-1", "admin")
        payload = decode_access_token(token)
        assert payload["sub"] == "member-1"
        assert payload["fid"] == "family-1"
        assert payload["role"] == "admin"
        assert payload["type"] == "access"

    def test_decode_invalid_signature(self):
        token = create_access_token("m1", "f1", "adult")
        tampered = token[:-4] + "xxxx"
        with pytest.raises(JWTError):
            decode_access_token(tampered)

    def test_decode_expired_token(self):
        expired = _create_token(
            {"sub": "m1", "fid": "f1", "role": "adult", "type": "access"},
            timedelta(seconds=-1),  # 已过期
        )
        with pytest.raises(JWTError):
            decode_access_token(expired)

    def test_refresh_token_rejected_as_access(self):
        """refresh token 不能当 access token 使用"""
        refresh = create_refresh_token("m1")
        with pytest.raises(JWTError):
            decode_access_token(refresh)

    def test_different_members_get_different_tokens(self):
        t1 = create_access_token("m1", "f1", "admin")
        t2 = create_access_token("m2", "f1", "adult")
        assert t1 != t2


# ── JWT refresh token ─────────────────────────────────────────────────
@pytest.mark.unit
class TestRefreshToken:
    def test_refresh_token_contains_correct_sub(self):
        from jose import jwt
        from src.core.config import settings

        token = create_refresh_token("member-99")
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[ALGORITHM])
        assert payload["sub"] == "member-99"
        assert payload["type"] == "refresh"
