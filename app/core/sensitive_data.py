import base64
import hashlib
import hmac
import json
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from cryptography.fernet import Fernet, InvalidToken

from app.core.config import settings


SENSITIVE_KEYS = {
    "authorization",
    "cookie",
    "password",
    "passwd",
    "secret",
    "token",
    "api_key",
    "apikey",
    "access_key",
    "client_secret",
}
SENSITIVE_EXACT_KEYS = {
    "auth",
    "authentication",
    "lingxi_auth",
    "x_auth_token",
}
ENCRYPTED_MARKER = "__encrypted_value__"
SECRET_TEXT_PREFIX = "enc:v1:"


def encrypt_sensitive(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: _encrypt(item) if _is_sensitive_key(key) else encrypt_sensitive(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [encrypt_sensitive(item) for item in value]
    return value


def decrypt_sensitive(value: Any) -> Any:
    if isinstance(value, dict):
        if set(value) == {ENCRYPTED_MARKER}:
            return _decrypt(value[ENCRYPTED_MARKER])
        return {key: decrypt_sensitive(item) for key, item in value.items()}
    if isinstance(value, list):
        return [decrypt_sensitive(item) for item in value]
    return value


def mask_sensitive(value: Any) -> Any:
    if isinstance(value, dict):
        if set(value) == {ENCRYPTED_MARKER}:
            return "***"
        return {
            key: "***" if _is_sensitive_key(key) else mask_sensitive(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [mask_sensitive(item) for item in value]
    return value


def redact_sensitive_data(value: Any, *, key_hint: str | None = None) -> Any:
    """Redact captured/runtime payloads before they are written to storage."""
    if isinstance(value, dict):
        return {
            key: "***" if _is_sensitive_key(key) else redact_sensitive_data(item, key_hint=str(key))
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [redact_sensitive_data(item, key_hint=key_hint) for item in value]
    if isinstance(value, str):
        normalized_hint = (key_hint or "").lower().replace("-", "_")
        if normalized_hint in {"url", "source_url"}:
            return _redact_url_query(value)
        if normalized_hint in {"body", "raw_body", "request_body", "response_body"}:
            try:
                parsed = json.loads(value)
            except (TypeError, ValueError):
                return value
            return json.dumps(redact_sensitive_data(parsed), ensure_ascii=False, separators=(",", ":"))
    return value


def redact_query_string(value: str) -> str:
    """Mask sensitive query values before URLs are written to logs."""
    if not value:
        return ""
    return urlencode([
        (key, "***" if _is_sensitive_key(key) else item)
        for key, item in parse_qsl(value, keep_blank_values=True)
    ])


def request_fingerprint(payload: Any) -> str:
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str).encode()
    return hashlib.sha256(encoded).hexdigest()


def protect_secret_text(value: str) -> str:
    if value.startswith(SECRET_TEXT_PREFIX):
        return value
    token = _encrypt(value)[ENCRYPTED_MARKER]
    return SECRET_TEXT_PREFIX + token


def reveal_secret_text(value: str) -> str:
    if not value.startswith(SECRET_TEXT_PREFIX):
        return value
    return str(_decrypt(value.removeprefix(SECRET_TEXT_PREFIX)))


def verify_webhook_signature(*, timestamp: str, body: bytes, signature: str) -> bool:
    secret = settings.TEST_PLAN_WEBHOOK_SECRET
    if not secret:
        return False
    expected = hmac.new(secret.encode(), timestamp.encode() + b"." + body, hashlib.sha256).hexdigest()
    supplied = signature.removeprefix("sha256=")
    return hmac.compare_digest(expected, supplied)


def _is_sensitive_key(key: object) -> bool:
    normalized = str(key).lower().replace("-", "_")
    return normalized in SENSITIVE_EXACT_KEYS or any(item in normalized for item in SENSITIVE_KEYS)


def _redact_url_query(value: str) -> str:
    try:
        parsed = urlsplit(value)
    except ValueError:
        return value
    if not parsed.query:
        return value
    redacted_query = urlencode([
        (key, "***" if _is_sensitive_key(key) else item)
        for key, item in parse_qsl(parsed.query, keep_blank_values=True)
    ])
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, redacted_query, parsed.fragment))


def _key() -> bytes:
    source = settings.SNAPSHOT_ENCRYPTION_KEY or settings.JWT_SECRET_KEY
    return base64.urlsafe_b64encode(hashlib.sha256(source.encode()).digest())


def _encrypt(value: Any) -> dict[str, str]:
    raw = json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode()
    token = Fernet(_key()).encrypt(raw).decode()
    return {ENCRYPTED_MARKER: token}


def _decrypt(token: str) -> Any:
    try:
        raw = Fernet(_key()).decrypt(token.encode())
    except InvalidToken as exc:
        raise ValueError("Sensitive snapshot integrity check failed") from exc
    return json.loads(raw.decode())
