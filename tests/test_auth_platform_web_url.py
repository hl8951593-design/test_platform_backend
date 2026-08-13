from datetime import datetime, timezone
from types import SimpleNamespace

from app.schemas.auth import LoginRequest, RefreshTokenRequest
from app.services import user_service as user_service_module
from app.services.user_service import UserService


def _user():
    return SimpleNamespace(
        id=7,
        username="tester",
        avatar=None,
        account="tester",
        phone="13800138000",
        email="tester@example.com",
        is_active=True,
        is_admin=False,
        created_at=datetime.now(timezone.utc),
        password_hash="hashed",
    )


def test_login_and_refresh_publish_the_platform_web_base_url(monkeypatch):
    user = _user()
    service = UserService.__new__(UserService)
    service.repository = SimpleNamespace(
        get_by_account=lambda _account: user,
        get_by_id=lambda _user_id: user,
    )
    monkeypatch.setattr(user_service_module, "verify_password", lambda *_args: True)
    monkeypatch.setattr(user_service_module, "create_access_token", lambda _user_id: "access")
    monkeypatch.setattr(user_service_module, "create_refresh_token", lambda _user_id: "refresh")
    monkeypatch.setattr(user_service_module, "decode_refresh_token", lambda _token: {"sub": "7"})
    monkeypatch.setattr(user_service_module.settings, "PLATFORM_WEB_BASE_URL", "https://testauto.example.com/")

    logged_in = service.login(LoginRequest(account="tester", password="secret1"))
    refreshed = service.refresh_token(RefreshTokenRequest(refresh_token="refresh"))

    assert logged_in.platform_web_url == "https://testauto.example.com"
    assert refreshed.platform_web_url == "https://testauto.example.com"
