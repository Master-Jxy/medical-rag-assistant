"""Controlled web snapshot fetcher with SSRF-oriented validation."""

from __future__ import annotations

import asyncio
import hashlib
import ipaddress
import socket
from html import escape
from dataclasses import dataclass
from datetime import datetime, timezone
from time import monotonic
from typing import Protocol
from urllib.parse import urljoin, urlsplit, urlunsplit

import httpx

from app.core.config import Settings
from app.modules.knowledge.web_snapshot import (
    WebSnapshotDisabledError,
    WebSnapshotError,
    WebSnapshotFetchPort,
    WebSnapshotResult,
    WebSnapshotTimeoutError,
    WebSnapshotTooLargeError,
)

MAX_URL_LENGTH = 2048
ALLOWED_SCHEMES = {"http", "https"}
DEFAULT_PORTS = {"http": 80, "https": 443}
REDIRECT_STATUSES = {301, 302, 303, 307, 308}
ACCEPTED_MIME_TYPES = {"text/html", "text/plain"}


@dataclass(frozen=True, slots=True)
class ValidatedUrl:
    url: str
    scheme: str
    host: str
    port: int


@dataclass(frozen=True, slots=True)
class SnapshotHttpResponse:
    status_code: int
    headers: dict[str, str]
    body: bytes


class DnsResolverPort(Protocol):
    async def resolve(self, host: str, port: int) -> tuple[str, ...]: ...


class SnapshotHttpClientPort(Protocol):
    async def fetch_once(
        self,
        url: str,
        *,
        max_bytes: int,
        connect_timeout: float,
        read_timeout: float,
    ) -> SnapshotHttpResponse: ...


class SocketDnsResolver:
    async def resolve(self, host: str, port: int) -> tuple[str, ...]:
        def _resolve() -> tuple[str, ...]:
            records = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
            return tuple(sorted({record[4][0] for record in records}))

        try:
            return await asyncio.to_thread(_resolve)
        except OSError as exc:
            raise WebSnapshotError("无法解析网页主机") from exc


class HttpxSnapshotHttpClient:
    async def fetch_once(
        self,
        url: str,
        *,
        max_bytes: int,
        connect_timeout: float,
        read_timeout: float,
    ) -> SnapshotHttpResponse:
        timeout = httpx.Timeout(
            connect=connect_timeout,
            read=read_timeout,
            write=connect_timeout,
            pool=connect_timeout,
        )
        headers = {
            "Accept": "text/html,text/plain;q=0.9",
            "User-Agent": "medical-rag-assistant-web-snapshot/1.0",
        }
        try:
            async with httpx.AsyncClient(
                follow_redirects=False,
                timeout=timeout,
                headers=headers,
            ) as client:
                async with client.stream("GET", url) as response:
                    if response.status_code in REDIRECT_STATUSES:
                        return SnapshotHttpResponse(
                            response.status_code,
                            dict(response.headers),
                            b"",
                        )
                    body = bytearray()
                    async for chunk in response.aiter_bytes():
                        body.extend(chunk)
                        if len(body) > max_bytes:
                            raise WebSnapshotTooLargeError()
                    return SnapshotHttpResponse(
                        response.status_code,
                        dict(response.headers),
                        bytes(body),
                    )
        except WebSnapshotError:
            raise
        except httpx.TimeoutException as exc:
            raise WebSnapshotTimeoutError() from exc
        except httpx.HTTPError as exc:
            raise WebSnapshotError() from exc


class SafeWebSnapshotFetcher(WebSnapshotFetchPort):
    def __init__(
        self,
        *,
        resolver: DnsResolverPort,
        http_client: SnapshotHttpClientPort,
        enabled: bool,
        allowed_hosts: tuple[str, ...],
        max_bytes: int,
        max_redirects: int,
        connect_timeout_seconds: float,
        read_timeout_seconds: float,
        total_timeout_seconds: float,
        require_allowlist: bool,
    ) -> None:
        self.resolver = resolver
        self.http_client = http_client
        self.enabled = enabled
        self.allowed_hosts = tuple(
            normalize_host(host) for host in allowed_hosts if host.strip()
        )
        self.max_bytes = max_bytes
        self.max_redirects = max_redirects
        self.connect_timeout_seconds = connect_timeout_seconds
        self.read_timeout_seconds = read_timeout_seconds
        self.total_timeout_seconds = total_timeout_seconds
        self.require_allowlist = require_allowlist

    async def fetch(self, url: str) -> WebSnapshotResult:
        if not self.enabled:
            raise WebSnapshotDisabledError()
        started = monotonic()
        original = validate_url(url)
        current = original
        redirects = 0

        while True:
            self._check_deadline(started)
            await self._validate_network_target(current)
            response = await self.http_client.fetch_once(
                current.url,
                max_bytes=self.max_bytes,
                connect_timeout=self.connect_timeout_seconds,
                read_timeout=self.read_timeout_seconds,
            )
            self._check_deadline(started)
            if response.status_code in REDIRECT_STATUSES:
                redirects += 1
                if redirects > self.max_redirects:
                    raise WebSnapshotError("网页重定向次数超过限制")
                location = response.headers.get("location")
                if not location:
                    raise WebSnapshotError("网页重定向缺少目标地址")
                current = validate_url(urljoin(current.url, location))
                continue
            return build_snapshot_result(
                original.url,
                current.url,
                response,
                max_bytes=self.max_bytes,
            )

    async def _validate_network_target(self, item: ValidatedUrl) -> None:
        if self.require_allowlist and item.host not in self.allowed_hosts:
            raise WebSnapshotError("网页主机不在允许列表中")
        addresses = await self.resolver.resolve(item.host, item.port)
        if not addresses:
            raise WebSnapshotError("无法解析网页主机")
        for address in addresses:
            if is_blocked_ip(address):
                raise WebSnapshotError("网页地址不允许访问")

    def _check_deadline(self, started: float) -> None:
        if monotonic() - started > self.total_timeout_seconds:
            raise WebSnapshotTimeoutError()


class HttpxWebSnapshotFetchAdapter(SafeWebSnapshotFetcher):
    def __init__(self, settings: Settings) -> None:
        super().__init__(
            resolver=SocketDnsResolver(),
            http_client=HttpxSnapshotHttpClient(),
            enabled=settings.web_snapshot_fetch_enabled,
            allowed_hosts=tuple(settings.web_snapshot_allowed_hosts),
            max_bytes=settings.web_snapshot_max_bytes,
            max_redirects=settings.web_snapshot_max_redirects,
            connect_timeout_seconds=settings.web_snapshot_connect_timeout_seconds,
            read_timeout_seconds=settings.web_snapshot_read_timeout_seconds,
            total_timeout_seconds=settings.web_snapshot_total_timeout_seconds,
            require_allowlist=True,
        )


def validate_url(value: str) -> ValidatedUrl:
    if len(value) > MAX_URL_LENGTH:
        raise WebSnapshotError("网页地址过长")
    try:
        parsed = urlsplit(value.strip())
    except ValueError as exc:
        raise WebSnapshotError("网页地址无效") from exc
    if parsed.scheme.lower() not in ALLOWED_SCHEMES:
        raise WebSnapshotError("网页地址仅支持 http/https")
    if not parsed.hostname:
        raise WebSnapshotError("网页地址缺少主机名")
    if parsed.username or parsed.password:
        raise WebSnapshotError("网页地址不能包含用户信息")
    host = normalize_host(parsed.hostname)
    reject_local_or_ip_like_host(host)
    try:
        port = parsed.port or DEFAULT_PORTS[parsed.scheme.lower()]
    except ValueError as exc:
        raise WebSnapshotError("网页地址端口不允许访问") from exc
    if port != DEFAULT_PORTS[parsed.scheme.lower()]:
        raise WebSnapshotError("网页地址端口不允许访问")
    normalized = urlunsplit(
        (
            parsed.scheme.lower(),
            host if port == DEFAULT_PORTS[parsed.scheme.lower()] else f"{host}:{port}",
            parsed.path or "/",
            parsed.query,
            "",
        )
    )
    return ValidatedUrl(normalized, parsed.scheme.lower(), host, port)


def normalize_host(host: str) -> str:
    cleaned = host.strip().rstrip(".")
    try:
        return cleaned.encode("idna").decode("ascii").lower()
    except UnicodeError as exc:
        raise WebSnapshotError("网页主机名无效") from exc


def reject_local_or_ip_like_host(host: str) -> None:
    if host == "localhost" or host.endswith(".localhost"):
        raise WebSnapshotError("网页地址不允许访问")
    try:
        ipaddress.ip_address(host)
    except ValueError:
        pass
    else:
        raise WebSnapshotError("网页地址不能使用IP地址")
    labels = host.split(".")
    if labels and all(is_numeric_address_label(label) for label in labels):
        raise WebSnapshotError("网页地址不能使用IP地址")


def is_numeric_address_label(label: str) -> bool:
    lower = label.lower()
    return lower.isdigit() or lower.startswith("0x") or lower.startswith("0o")


def is_blocked_ip(value: str) -> bool:
    try:
        address = ipaddress.ip_address(value)
    except ValueError as exc:
        raise WebSnapshotError("DNS解析结果无效") from exc
    return any(
        (
            address.is_loopback,
            address.is_private,
            address.is_link_local,
            address.is_multicast,
            address.is_reserved,
            address.is_unspecified,
        )
    )


def build_snapshot_result(
    original_url: str,
    final_url: str,
    response: SnapshotHttpResponse,
    *,
    max_bytes: int,
) -> WebSnapshotResult:
    if response.status_code != 200:
        raise WebSnapshotError("网页响应状态不允许导入")
    content_disposition = response.headers.get("content-disposition", "")
    if content_disposition.lower().strip().startswith("attachment"):
        raise WebSnapshotError("网页响应是下载内容")
    mime_type = normalize_mime_type(response.headers.get("content-type"))
    if mime_type not in ACCEPTED_MIME_TYPES:
        raise WebSnapshotError("网页响应类型不支持")
    if not response.body:
        raise WebSnapshotError("网页正文为空")
    if len(response.body) > max_bytes:
        raise WebSnapshotTooLargeError()
    if b"\x00" in response.body:
        raise WebSnapshotError("网页正文包含非法内容")
    try:
        response.body.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise WebSnapshotError("网页正文必须使用UTF-8编码") from exc
    content = response.body
    if mime_type == "text/plain":
        text = response.body.decode("utf-8")
        content = (
            "<!doctype html><html><body><p>"
            + escape(text)
            + "</p></body></html>"
        ).encode("utf-8")
        mime_type = "text/html"
    digest = hashlib.sha256(content).hexdigest()
    return WebSnapshotResult(
        original_url=original_url,
        final_url=final_url,
        fetched_at=datetime.now(timezone.utc),
        mime_type=mime_type,
        content_sha256=digest,
        content=content,
    )


def normalize_mime_type(value: str | None) -> str:
    if not value:
        raise WebSnapshotError("网页响应缺少内容类型")
    return value.split(";", 1)[0].strip().lower()
