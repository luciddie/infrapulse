import httpx
import pytest

from app.services import http_checker


def mock_http(monkeypatch, handler):
    original_client = httpx.Client

    def fake_client(*args, **kwargs):
        return original_client(
            *args,
            transport=httpx.MockTransport(handler),
            **kwargs
        )

    monkeypatch.setattr(
        http_checker.httpx,
        "Client",
        fake_client
    )


def test_http_healthy(monkeypatch):
    mock_http(
        monkeypatch,
        lambda request: httpx.Response(200)
    )

    result = http_checker.check_http(
        "http://127.0.0.1/health"
    )

    assert result["status"] == "healthy"
    assert result["status_code"] == 200


def test_http_unhealthy(monkeypatch):
    mock_http(
        monkeypatch,
        lambda request: httpx.Response(503)
    )

    result = http_checker.check_http(
        "http://127.0.0.1/health"
    )

    assert result["status"] == "unhealthy"
    assert result["status_code"] == 503


def test_http_custom_status(monkeypatch):
    mock_http(
        monkeypatch,
        lambda request: httpx.Response(204)
    )

    result = http_checker.check_http(
        "http://127.0.0.1",
        expected_status=204
    )

    assert result["status"] == "healthy"


def test_http_timeout(monkeypatch):
    def handler(request):
        raise httpx.ReadTimeout("Timeout")

    mock_http(monkeypatch, handler)

    result = http_checker.check_http(
        "http://127.0.0.1"
    )

    assert result["status"] == "timeout"


def test_http_unreachable(monkeypatch):
    def handler(request):
        raise httpx.ConnectError(
            "Connection failed"
        )

    mock_http(monkeypatch, handler)

    result = http_checker.check_http(
        "http://127.0.0.1"
    )

    assert result["status"] == "unreachable"


@pytest.mark.parametrize(
    "url",
    [
        "ftp://127.0.0.1",
        "invalid-url",
        "http://user:pass@127.0.0.1"
    ]
)
def test_invalid_url(url):
    with pytest.raises(ValueError):
        http_checker.check_http(url)


def test_invalid_expected_status():
    with pytest.raises(ValueError):
        http_checker.check_http(
            "http://127.0.0.1",
            expected_status=999
        )


def test_invalid_timeout():
    with pytest.raises(ValueError):
        http_checker.check_http(
            "http://127.0.0.1",
            timeout=0
        )
