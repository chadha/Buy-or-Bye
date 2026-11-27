"""idealo sign-in: expired tokens are refreshed before a call, failures become SourceError.

idealo answers an expired access token with 403 (not 401), so the MCP SDK never refreshes
on its own; FileTokenStorage refreshes ahead of expiry. No test touches the network.
"""

import json
import time
from contextlib import asynccontextmanager
from urllib.parse import parse_qs

import httpx
import pytest

pytest.importorskip("mcp", reason="needs the idealo extra: pip install -e '.[idealo]'")

from app import idealo_auth, sources  # noqa: E402
from app.idealo_auth import FileTokenStorage
from app.sources import IdealoMCPSource, SourceError

CLIENT = {
    "client_id": "cid-1",
    "redirect_uris": ["http://localhost:6274/callback"],
    "issuer": "https://idp.example",
}
OLD = {
    "access_token": "old-at",
    "token_type": "Bearer",
    "expires_in": 3600,
    "refresh_token": "rt-1",
    "scope": "api.full-access",
}


def store(tmp_path, *, saved_at, tokens=OLD, client=CLIENT):
    path = tmp_path / "idealo_oauth.json"
    data = {"tokens": tokens, "client": client}
    if saved_at is not None:
        data["saved_at"] = saved_at
    path.write_text(json.dumps(data))
    return path


def idp(calls, *, token_status=200, token_body=None):
    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        if request.url.path == "/.well-known/oauth-authorization-server":
            return httpx.Response(
                200,
                json={
                    "issuer": "https://idp.example",
                    "token_endpoint": "https://idp.example/oauth2/token",
                },
            )
        if request.url.path == "/oauth2/token":
            body = token_body or {
                "access_token": "new-at",
                "token_type": "Bearer",
                "expires_in": 3600,
            }
            return httpx.Response(token_status, json=body)
        return httpx.Response(404)

    return httpx.MockTransport(handler)


async def test_fresh_token_is_returned_without_network(tmp_path):
    calls: list[httpx.Request] = []
    s = FileTokenStorage(store(tmp_path, saved_at=time.time()), transport=idp(calls))
    assert (await s.get_tokens()).access_token == "old-at"
    assert calls == []


async def test_expired_token_is_refreshed_at_the_published_token_endpoint(tmp_path):
    calls: list[httpx.Request] = []
    path = store(tmp_path, saved_at=time.time() - 4000)
    s = FileTokenStorage(path, transport=idp(calls))
    tokens = await s.get_tokens()
    assert tokens.access_token == "new-at"
    # refresh_token and scope are kept when the server does not rotate them (RFC 6749 §6)
    assert (tokens.refresh_token, tokens.scope) == ("rt-1", "api.full-access")
    post = calls[-1]
    assert str(post.url) == "https://idp.example/oauth2/token"
    form = parse_qs(post.content.decode())
    assert form["grant_type"] == ["refresh_token"]
    assert form["refresh_token"] == ["rt-1"]
    assert form["client_id"] == ["cid-1"]
    saved = json.loads(path.read_text())
    assert saved["tokens"]["access_token"] == "new-at"
    assert saved["saved_at"] > time.time() - 5


async def test_token_about_to_expire_is_refreshed(tmp_path):
    calls: list[httpx.Request] = []
    s = FileTokenStorage(store(tmp_path, saved_at=time.time() - 3570), transport=idp(calls))
    assert (await s.get_tokens()).access_token == "new-at"


async def test_unknown_save_time_uses_the_file_age(tmp_path):
    import os

    calls: list[httpx.Request] = []
    path = store(tmp_path, saved_at=None)
    old = time.time() - 4000
    os.utime(path, (old, old))
    s = FileTokenStorage(path, transport=idp(calls))
    assert (await s.get_tokens()).access_token == "new-at"


async def test_failed_refresh_keeps_the_old_token(tmp_path):
    calls: list[httpx.Request] = []
    path = store(tmp_path, saved_at=time.time() - 4000)
    s = FileTokenStorage(
        path, transport=idp(calls, token_status=400, token_body={"error": "invalid_grant"})
    )
    assert (await s.get_tokens()).access_token == "old-at"
    assert json.loads(path.read_text())["tokens"]["access_token"] == "old-at"


async def test_set_tokens_records_the_save_time(tmp_path):
    from mcp.shared.auth import OAuthToken

    path = tmp_path / "t.json"
    s = FileTokenStorage(path)
    await s.set_tokens(OAuthToken(access_token="a", token_type="Bearer", expires_in=60))
    assert abs(json.loads(path.read_text())["saved_at"] - time.time()) < 5


async def test_any_idealo_failure_becomes_source_error_with_login_hint(monkeypatch):
    @asynccontextmanager
    async def failing(transport, url):
        raise ExceptionGroup("unhandled errors in a TaskGroup", [RuntimeError("HTTP 403")])
        yield  # pragma: no cover

    monkeypatch.setattr(idealo_auth, "open_transport", failing)
    with pytest.raises(SourceError, match="idealo-login"):
        await IdealoMCPSource().find("sony wh-1000xm5")


async def test_source_error_from_a_tool_passes_through(monkeypatch):
    @asynccontextmanager
    async def failing(transport, url):
        raise SourceError("idealo tool search_products returned an error: bad query")
        yield  # pragma: no cover

    monkeypatch.setattr(idealo_auth, "open_transport", failing)
    with pytest.raises(SourceError, match="bad query"):
        await sources.IdealoMCPSource().find("x y")
