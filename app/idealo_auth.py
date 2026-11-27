"""OAuth sign-in for the idealo MCP server (Trial tier is self-serve via OAuth).

First use opens a browser for the idealo login and catches the redirect on a local port.
Tokens are cached in ~/.buyorbye/idealo_oauth.json. FileTokenStorage refreshes them shortly
before they expire: idealo answers an expired access token with 403 (not 401), and the MCP
SDK treats a token loaded from disk as never expiring, so the SDK alone never refreshes it.
Run `make idealo-login` once before the demo so the app never waits on a browser.
"""

from __future__ import annotations

import asyncio
import inspect
import json
import logging
import os
import time
import webbrowser
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from threading import Thread
from typing import Any
from urllib.parse import parse_qs, urljoin, urlparse

import httpx
from pydantic import AnyUrl

log = logging.getLogger("buy_or_bye.idealo_auth")
REFRESH_MARGIN_S = 60  # refresh this long before the access token expires

CALLBACK_PORT = int(os.environ.get("IDEALO_CALLBACK_PORT", "6274"))
REDIRECT_URI = f"http://localhost:{CALLBACK_PORT}/callback"
STORE = Path(os.environ.get("IDEALO_TOKEN_FILE", Path.home() / ".buyorbye" / "idealo_oauth.json"))


class FileTokenStorage:
    """Token + client registration cache. Holds secrets: never commit it, never log it."""

    def __init__(
        self,
        path: Path = STORE,
        server_url: str | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.path = path
        self.server_url = server_url
        self.transport = transport  # tests inject a mock; production uses the network

    def _load(self) -> dict[str, Any]:
        try:
            return dict(json.loads(self.path.read_text(encoding="utf-8")))
        except (OSError, ValueError):
            return {}

    def _write(self, data: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(data), encoding="utf-8")
        os.chmod(self.path, 0o600)

    def _save(self, key: str, value: Any) -> None:
        data = self._load()
        data[key] = value.model_dump(mode="json", exclude_none=True)
        if key == "tokens":
            data["saved_at"] = time.time()
        self._write(data)

    def _saved_at(self, data: dict[str, Any]) -> float:
        saved = data.get("saved_at")
        if isinstance(saved, (int, float)):
            return float(saved)
        try:  # files written before saved_at existed: the file age is the token age
            return self.path.stat().st_mtime
        except OSError:
            return 0.0

    async def get_tokens(self) -> Any:
        from mcp.shared.auth import OAuthToken

        data = self._load()
        raw = data.get("tokens")
        if not raw:
            return None
        tokens = OAuthToken.model_validate(raw)
        expires_in = tokens.expires_in
        if expires_in and time.time() >= self._saved_at(data) + expires_in - REFRESH_MARGIN_S:
            fresh = await self._refresh(tokens, data.get("client") or {})
            if fresh is not None:
                await self.set_tokens(fresh)
                return fresh
        return tokens

    async def _refresh(self, tokens: Any, client: dict[str, Any]) -> Any:
        """Standard OAuth refresh (RFC 6749 §6) at the token endpoint idealo publishes."""
        from mcp.shared.auth import OAuthToken

        client_id = client.get("client_id")
        issuer = client.get("issuer") or self.server_url
        if not tokens.refresh_token or not client_id or not issuer:
            return None
        parsed = urlparse(str(issuer))
        origin = f"{parsed.scheme}://{parsed.netloc}"
        form = {
            "grant_type": "refresh_token",
            "refresh_token": tokens.refresh_token,
            "client_id": str(client_id),
        }
        if self.server_url:
            form["resource"] = self.server_url  # RFC 8707, as the SDK sends it
        try:
            async with httpx.AsyncClient(transport=self.transport, timeout=15.0) as http:
                meta = await http.get(urljoin(origin, "/.well-known/oauth-authorization-server"))
                meta.raise_for_status()
                token_url = meta.json()["token_endpoint"]
                resp = await http.post(token_url, data=form)
            if resp.status_code != 200:
                log.warning("idealo token refresh failed: HTTP %s", resp.status_code)
                return None
            fresh = OAuthToken.model_validate(resp.json())
        except (httpx.HTTPError, ValueError, KeyError) as exc:
            log.warning("idealo token refresh failed: %s", type(exc).__name__)
            return None
        # A refresh response may omit refresh_token and scope when they do not change.
        if fresh.refresh_token is None:
            fresh.refresh_token = tokens.refresh_token
        if fresh.scope is None:
            fresh.scope = tokens.scope
        return fresh

    async def set_tokens(self, tokens: Any) -> None:
        self._save("tokens", tokens)

    async def get_client_info(self) -> Any:
        from mcp.shared.auth import OAuthClientInformationFull

        raw = self._load().get("client")
        return OAuthClientInformationFull.model_validate(raw) if raw else None

    async def set_client_info(self, client_info: Any) -> None:
        self._save("client", client_info)


async def _redirect(url: str) -> None:
    print(f"\nSign in to idealo in your browser:\n{url}\n", flush=True)
    webbrowser.open(url)


async def _wait_for_code() -> Any:
    from mcp.shared.auth import AuthorizationCodeResult

    got: dict[str, str] = {}

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802 - stdlib API
            q = parse_qs(urlparse(self.path).query)
            for k in ("code", "state", "iss", "error"):
                if k in q:
                    got[k] = q[k][0]
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(b"<h2>Signed in to idealo. You can close this tab.</h2>")

        def log_message(self, *args: Any) -> None:
            return

    server = HTTPServer(("localhost", CALLBACK_PORT), Handler)
    thread = Thread(target=server.handle_request, daemon=True)
    thread.start()
    for _ in range(600):  # up to 5 minutes
        if "code" in got or "error" in got:
            break
        await asyncio.sleep(0.5)
    server.server_close()
    if "code" not in got:
        raise RuntimeError(f"idealo sign-in failed: {got.get('error', 'timed out')}")
    return AuthorizationCodeResult(code=got["code"], state=got.get("state"), iss=got.get("iss"))


def make_auth(server_url: str) -> Any:
    from mcp.client.auth import OAuthClientProvider
    from mcp.shared.auth import OAuthClientMetadata

    meta = OAuthClientMetadata(
        client_name="Buy or Bye",
        # A real AnyUrl type-checks with and without the mcp extra installed (CI has none).
        redirect_uris=[AnyUrl(REDIRECT_URI)],
        grant_types=["authorization_code", "refresh_token"],
        response_types=["code"],
        token_endpoint_auth_method="none",
    )
    return OAuthClientProvider(
        server_url=server_url,
        client_metadata=meta,
        storage=FileTokenStorage(server_url=server_url),
        redirect_handler=_redirect,
        callback_handler=_wait_for_code,
    )


@asynccontextmanager
async def open_transport(transport: Any, url: str) -> AsyncIterator[Any]:
    """Open the streamable-HTTP client with OAuth, across MCP SDK 1.x and 2.x."""
    auth = make_auth(url)
    client = getattr(transport, "streamable_http_client", None) or getattr(
        transport, "streamablehttp_client", None
    )
    if client is None:  # pragma: no cover
        raise RuntimeError("unsupported mcp SDK version")
    params = inspect.signature(client).parameters
    if "auth" in params:  # SDK 1.x
        async with client(url, auth=auth) as streams:
            yield streams
        return
    import httpx2  # SDK 2.x: pass auth through the HTTP client

    async with (
        httpx2.AsyncClient(auth=auth, timeout=httpx2.Timeout(30.0, read=60.0)) as http,
        client(url, http_client=http) as streams,
    ):
        yield streams


async def _login_and_probe(query: str) -> None:
    from .sources import IdealoMCPSource

    src = IdealoMCPSource()
    product = await src.find(query)
    if product is None:
        print(f"Signed in. No confident idealo match for {query!r}.")
        return
    print(
        f"Signed in. {product.name}: {len(product.history)} days of price history, "
        f"{len(product.offers)} offers. Token cached in {STORE}."
    )


if __name__ == "__main__":  # python -m app.idealo_auth "sony wh-1000xm5"
    import sys

    asyncio.run(_login_and_probe(" ".join(sys.argv[1:]) or "sony wh-1000xm5"))
