import ipaddress
import socket
from urllib.parse import urlsplit

from app.core.config import settings


def validate_outbound_http_url(url: str) -> None:
    """Reject unsafe execution targets before opening a network connection."""
    try:
        parsed = urlsplit(url)
    except ValueError as exc:
        raise ValueError("请求 URL 无效") from exc
    if parsed.scheme.lower() not in {"http", "https"}:
        raise ValueError("仅允许执行 HTTP 或 HTTPS 请求")
    if not parsed.hostname:
        raise ValueError("请求 URL 缺少主机名")

    hostname = parsed.hostname.rstrip(".").lower()
    allowed_hosts = {item.rstrip(".").lower() for item in settings.EXECUTION_OUTBOUND_ALLOWED_HOSTS}
    if hostname in allowed_hosts or settings.EXECUTION_OUTBOUND_ALLOW_PRIVATE_NETWORKS:
        return

    try:
        addresses = {
            item[4][0]
            for item in socket.getaddrinfo(hostname, parsed.port, type=socket.SOCK_STREAM)
        }
    except OSError as exc:
        raise ValueError(f"请求主机无法解析: {hostname}") from exc
    for address in addresses:
        ip = ipaddress.ip_address(address)
        if (
            ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_multicast
            or ip.is_reserved
            or ip.is_unspecified
        ):
            raise ValueError(
                f"请求目标 {hostname} 解析到受保护网络地址；如确需访问，请加入 EXECUTION_OUTBOUND_ALLOWED_HOSTS"
            )
