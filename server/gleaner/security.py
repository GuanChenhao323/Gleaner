"""口令哈希（argon2）、会话令牌（HMAC-SHA256）、凭据加密（AES-GCM）。

密钥只来自环境变量：
- GLEANER_SECRET：签发令牌用（网关、业务、推送、Broker 共享，用于本地验证令牌）
- GLEANER_DATA_KEY：32 字节十六进制，加密保存的 Cookie / 授权码
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import time
from typing import Any

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

_ph = PasswordHasher(time_cost=2, memory_cost=19456, parallelism=1)

_DEV_SECRET = "dev-only-secret-change-me"


def secret() -> bytes:
    return os.environ.get("GLEANER_SECRET", _DEV_SECRET).encode()


def hash_password(pw: str) -> str:
    return _ph.hash(pw)


def verify_password(hashed: str, pw: str) -> bool:
    try:
        return _ph.verify(hashed, pw)
    except (VerificationError, InvalidHashError):
        return False


def _b64(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def _unb64(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def sign_token(
    claims: dict[str, Any], ttl: float = 30 * 24 * 3600, key: bytes | None = None
) -> str:
    """紧凑令牌 ``payload.signature``，payload 为 JSON（含 exp）。"""
    body = dict(claims)
    body["exp"] = int(time.time() + ttl)
    raw = _b64(json.dumps(body, separators=(",", ":")).encode())
    sig = hmac.new(key or secret(), raw.encode(), hashlib.sha256).digest()
    return f"{raw}.{_b64(sig)}"


def verify_token(token: str, key: bytes | None = None) -> dict[str, Any] | None:
    try:
        raw, sig = token.split(".", 1)
        expect = hmac.new(key or secret(), raw.encode(), hashlib.sha256).digest()
        if not hmac.compare_digest(expect, _unb64(sig)):
            return None
        claims = json.loads(_unb64(raw))
    except (ValueError, TypeError):
        return None
    if not isinstance(claims, dict) or claims.get("exp", 0) < time.time():
        return None
    return claims


def mqtt_password(uid: int, token_version: int) -> str:
    """MQTT 登录口令：由用户 ID 派生，客户端登录后从 /api/me 获取。"""
    return _b64(
        hmac.new(secret(), f"mqtt:{uid}:{token_version}".encode(), hashlib.sha256).digest()[:18]
    )


def _data_key() -> bytes:
    hexkey = os.environ.get("GLEANER_DATA_KEY")
    if hexkey:
        return bytes.fromhex(hexkey)
    return hashlib.sha256(secret() + b"data-key").digest()


def encrypt(data: dict[str, Any] | bytes, aad: bytes = b"") -> bytes:
    """AES-256-GCM：12 字节随机 nonce || 密文 || 16 字节 tag。aad 绑定用户与来源，防止密文挪用。"""
    plain = data if isinstance(data, bytes) else json.dumps(data).encode()
    nonce = os.urandom(12)
    return nonce + AESGCM(_data_key()).encrypt(nonce, plain, aad)


def decrypt(blob: bytes, aad: bytes = b"") -> dict[str, Any]:
    plain = AESGCM(_data_key()).decrypt(bytes(blob[:12]), bytes(blob[12:]), aad)
    return json.loads(plain)
