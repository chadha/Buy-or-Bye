"""OAuth sign-in for the idealo MCP server (Trial tier is self-serve via OAuth).

First use opens a browser for the idealo login and catches the redirect on a local port.
Tokens are cached in ~/.buyorbye/idealo_oauth.json and refreshed by the MCP SDK.
Run `make idealo-login` once before the demo so the app never waits on a browser.
"""

from __future__ import annotations

import asyncio
import inspect
import json
import os
import webbrowser
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from threading import Thread
from typing import Any
from urllib.parse import parse_qs, urlparse

CALLBACK_PORT = int(os.environ.get("IDEALO_CALLBACK_PORT", "6274"))
REDIRECT_URI = f"http://localhost:{CALLBACK_PORT}/callback"
STORE = Path(os.environ.get("IDEALO_TOKEN_FILE", Path.home() / ".buyorbye" / "idealo_oauth.json"))


class FileTokenStorage:
    """Token + client registration cache. Holds secrets: never commit it, never log it."""

    def __init__(self, path: Path = STORE) -> None:
        self.path = path

    def _load(self) -> dict[str, Any]:
        try:
            return dict(json.loads(self.path.read_text()))
        except (OSError, ValueError):
            return {}

    def _save(self, key: str, value: Any) -> None:
        data = self._load()
        data[key] = value.model_dump(mode="json", exclude_none=True)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(data))
        os.chmod(self.path, 0o600)

    async def get_tokens(self) -> Any:
        from mcp.shared.auth import OAuthToken

        raw = self._load().get("tokens")
        return OAuthToken.model_validate(raw) if raw else None

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
        redirect_uris=[REDIRECT_URI],
        grant_types=["authorization_code", "refresh_token"],
        response_types=["code"],
        token_endpoint_auth_method="none",
    )
    return OAuthClientProvider(
        server_url=server_url,
        client_metadata=meta,
        storage=FileTokenStorage(),
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
