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


_BLOB_MAGIC = b"GK"  # 新格式：b"GK" || 密钥编号(1 字节) || nonce(12) || 密文+tag


def _hex_key(raw: str) -> bytes:
    key = bytes.fromhex(raw.strip())
    if len(key) != 32:
        raise ValueError("GLEANER_DATA_KEY 必须是 32 字节（64 个十六进制字符）")
    return key


def _derived_key() -> bytes:
    # 旧行为：没配 GLEANER_DATA_KEY 时由令牌密钥派生（换令牌密钥会让所有凭据无法解密，所以只作兜底）
    return hashlib.sha256(secret() + b"data-key").digest()


def _data_key() -> bytes:
    hexkey = os.environ.get("GLEANER_DATA_KEY")
    return _hex_key(hexkey) if hexkey else _derived_key()


def _all_keys() -> list[bytes]:
    """解密时依次尝试：当前密钥、GLEANER_DATA_KEY_OLD 里的旧密钥（逗号分隔，轮换密钥时用）、派生密钥。"""
    keys = [_data_key()]
    for raw in os.environ.get("GLEANER_DATA_KEY_OLD", "").split(","):
        if raw.strip():
            keys.append(_hex_key(raw))
    keys.append(_derived_key())
    out: list[bytes] = []
    for k in keys:
        if k not in out:
            out.append(k)
    return out


def _key_id(key: bytes) -> int:
    return hashlib.sha256(b"key-id:" + key).digest()[0]


def encrypt(data: dict[str, Any] | bytes, aad: bytes = b"") -> bytes:
    """AES-256-GCM。aad 绑定用户与来源，防止密文挪用；带密钥编号，便于轮换密钥。"""
    plain = data if isinstance(data, bytes) else json.dumps(data).encode()
    key = _data_key()
    nonce = os.urandom(12)
    return _BLOB_MAGIC + bytes([_key_id(key)]) + nonce + AESGCM(key).encrypt(nonce, plain, aad)


def decrypt(blob: bytes, aad: bytes = b"") -> dict[str, Any]:
    from cryptography.exceptions import InvalidTag

    blob = bytes(blob)
    if blob[:2] == _BLOB_MAGIC and len(blob) > 3 + 12:
        kid, nonce, ct = blob[2], blob[3:15], blob[15:]
        candidates = [k for k in _all_keys() if _key_id(k) == kid]
    else:  # 旧格式：nonce || 密文
        nonce, ct = blob[:12], blob[12:]
        candidates = _all_keys()
    for key in candidates:
        try:
            return json.loads(AESGCM(key).decrypt(nonce, ct, aad))
        except InvalidTag:
            continue
    raise InvalidTag(
        "没有可用的数据密钥能解密这条凭据（GLEANER_DATA_KEY 是否被更换？旧密钥请放进 GLEANER_DATA_KEY_OLD）"
    )


def check_secrets() -> list[str]:
    """启动检查：返回配置问题；``GLEANER_STRICT_SECRETS=1`` 时由调用方拒绝启动（生产环境建议打开）。"""
    problems = []
    if os.environ.get("GLEANER_SECRET", _DEV_SECRET) == _DEV_SECRET:
        problems.append("GLEANER_SECRET 未设置，正在使用公开的开发密钥（任何人都能伪造登录令牌）")
    if not os.environ.get("GLEANER_DATA_KEY"):
        problems.append(
            "GLEANER_DATA_KEY 未设置，凭据加密密钥由 GLEANER_SECRET 派生（更换令牌密钥会导致凭据无法解密）"
        )
    else:
        try:
            _data_key()
        except ValueError as e:
            problems.append(str(e))
    return problems
