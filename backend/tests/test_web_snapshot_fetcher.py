"""Stage 24.2b controlled web snapshot fetching security tests."""

import asyncio

import pytest

from app.infrastructure.web_snapshot_fetcher import (
    SafeWebSnapshotFetcher,
    SnapshotHttpResponse,
    validate_url,
)
from app.modules.knowledge.web_snapshot import (
    WebSnapshotDisabledError,
    WebSnapshotError,
    WebSnapshotTimeoutError,
    WebSnapshotTooLargeError,
)


class FakeResolver:
    def __init__(self, records: dict[str, tuple[str, ...]]) -> None:
        self.records = records
        self.calls: list[tuple[str, int]] = []

    async def resolve(self, host: str, port: int) -> tuple[str, ...]:
        self.calls.append((host, port))
        return self.records.get(host, ())


class FakeHttpClient:
    def __init__(self, responses: list[SnapshotHttpResponse | Exception]) -> None:
        self.responses = responses
        self.urls: list[str] = []

    async def fetch_once(self, url: str, **_kwargs) -> SnapshotHttpResponse:
        self.urls.append(url)
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


def make_fetcher(
    *,
    records: dict[str, tuple[str, ...]] | None = None,
    responses: list[SnapshotHttpResponse | Exception] | None = None,
    allowed_hosts: tuple[str, ...] = ("example.com", "www.example.com"),
    enabled: bool = True,
) -> SafeWebSnapshotFetcher:
    return SafeWebSnapshotFetcher(
        resolver=FakeResolver(records or {"example.com": ("93.184.216.34",)}),
        http_client=FakeHttpClient(
            responses
            or [
                SnapshotHttpResponse(
                    200,
                    {"content-type": "text/html; charset=utf-8"},
                    b"<html><body>ok</body></html>",
                )
            ]
        ),
        enabled=enabled,
        allowed_hosts=allowed_hosts,
        max_bytes=1024,
        max_redirects=3,
        connect_timeout_seconds=1,
        read_timeout_seconds=1,
        total_timeout_seconds=5,
        require_allowlist=True,
    )


def test_fetcher_success_normalizes_url_and_hashes_content() -> None:
    fetcher = make_fetcher()

    result = asyncio.run(fetcher.fetch("HTTPS://Example.COM/path?q=1#ignored"))

    assert result.original_url == "https://example.com/path?q=1"
    assert result.final_url == "https://example.com/path?q=1"
    assert result.mime_type == "text/html"
    assert result.content_sha256


def test_fetcher_wraps_plain_text_as_html_snapshot() -> None:
    fetcher = make_fetcher(
        responses=[
            SnapshotHttpResponse(
                200,
                {"content-type": "text/plain; charset=utf-8"},
                "纯文本 <资料>".encode(),
            )
        ]
    )

    result = asyncio.run(fetcher.fetch("https://example.com/plain"))

    assert result.mime_type == "text/html"
    assert b"&lt;" in result.content
    assert result.content.startswith(b"<!doctype html>")


def test_fetcher_revalidates_redirect_and_rejects_private_target() -> None:
    fetcher = make_fetcher(
        records={
            "example.com": ("93.184.216.34",),
            "private.example.com": ("10.0.0.5",),
        },
        responses=[
            SnapshotHttpResponse(302, {"location": "https://private.example.com/"}, b"")
        ],
        allowed_hosts=("example.com", "private.example.com"),
    )

    with pytest.raises(WebSnapshotError, match="不允许访问"):
        asyncio.run(fetcher.fetch("https://example.com/"))


def test_fetcher_limits_redirect_count() -> None:
    fetcher = make_fetcher(
        records={"example.com": ("93.184.216.34",)},
        responses=[
            SnapshotHttpResponse(302, {"location": "/a"}, b""),
            SnapshotHttpResponse(302, {"location": "/b"}, b""),
            SnapshotHttpResponse(302, {"location": "/c"}, b""),
            SnapshotHttpResponse(302, {"location": "/d"}, b""),
        ],
    )

    with pytest.raises(WebSnapshotError, match="重定向次数"):
        asyncio.run(fetcher.fetch("https://example.com/"))


def test_fetcher_rejects_ssrf_hosts_and_dns_results() -> None:
    for url in [
        "http://localhost/",
        "http://127.0.0.1/",
        "http://[::1]/",
        "http://2130706433/",
        "http://127.1/",
        "http://0x7f000001/",
        "http://example.com:22/",
        "ftp://example.com/",
        "https://user:pass@example.com/",
    ]:
        with pytest.raises(WebSnapshotError):
            validate_url(url)

    fetcher = make_fetcher(records={"example.com": ("93.184.216.34", "192.168.1.8")})
    with pytest.raises(WebSnapshotError, match="不允许访问"):
        asyncio.run(fetcher.fetch("https://example.com/"))


def test_fetcher_rejects_bad_mime_download_empty_timeout_and_oversize() -> None:
    cases = [
        (
            SnapshotHttpResponse(200, {"content-type": "application/pdf"}, b"pdf"),
            WebSnapshotError,
        ),
        (SnapshotHttpResponse(200, {}, b"<html></html>"), WebSnapshotError),
        (
            SnapshotHttpResponse(
                200,
                {"content-type": "text/html", "content-disposition": "attachment"},
                b"<html></html>",
            ),
            WebSnapshotError,
        ),
        (SnapshotHttpResponse(200, {"content-type": "text/plain"}, b""), WebSnapshotError),
        (SnapshotHttpResponse(200, {"content-type": "text/plain"}, b"x" * 1025), WebSnapshotTooLargeError),
        (WebSnapshotTimeoutError(), WebSnapshotTimeoutError),
    ]
    for response, expected_error in cases:
        fetcher = make_fetcher(responses=[response])
        with pytest.raises(expected_error):
            asyncio.run(fetcher.fetch("https://example.com/"))


def test_fetcher_defaults_closed_and_allowlist_gate_documents_rebinding_risk() -> None:
    with pytest.raises(WebSnapshotDisabledError):
        asyncio.run(make_fetcher(enabled=False).fetch("https://example.com/"))

    fetcher = make_fetcher(allowed_hosts=("trusted.example",))
    with pytest.raises(WebSnapshotError, match="允许列表"):
        asyncio.run(fetcher.fetch("https://example.com/"))
