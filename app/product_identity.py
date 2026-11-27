"""BOB-URL-001 M1: validate a product URL and extract what it says about the product.

* `normalize_product_url` validates and canonicalises the URL before any network access
  (scheme, credentials, port, host, length; tracking parameters and fragment removed).
* `identity_from_url` reads only clear patterns from the URL: a model number with variant
  in the path (XC2011_01 -> XC2011/01) and the market (ccTLD or locale path segment).
* `identity_from_html` reads only structured data: schema.org JSON-LD Product and product
  meta tags. Free page text is ignored (untrusted and ambiguous).
* Every value is a `FieldValue` with its source and status. In M1 nothing is verified yet:
  verification against idealo comes in M4. Unknown fields stay None, never guessed.

Network access stays in `app/shop_page.py` (`fetch_page`: robots.txt, public hosts only,
redirect, size and time limits).
"""

from __future__ import annotations

import ipaddress
import logging
import re
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any, Literal
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from pydantic import BaseModel, Field

from .shop_page import PageFetchError, fetch_page, json_ld_products, meta_map

log = logging.getLogger("buy_or_bye.product_identity")

MAX_URL_LENGTH = 2048
MAX_FIELD_LENGTH = 200
Source = Literal["json_ld", "meta", "url_path", "url_host", "idealo"]
Status = Literal["unverified", "verified", "contradicted"]
Fetcher = Callable[[str], Awaitable[str]]

# Click and campaign trackers: they never identify a product.
_TRACKING_KEYS = {
    "gclid",
    "fbclid",
    "msclkid",
    "dclid",
    "yclid",
    "igshid",
    "mc_cid",
    "mc_eid",
    "_ga",
    "_gl",
    "srsltid",
    "wbraid",
    "gbraid",
}
# Two-letter TLDs that are used generically, not as a market.
_GENERIC_CC_TLDS = {"io", "co", "ai", "me", "tv", "fm", "ly", "to", "gg", "cc", "ws", "app"}


class UrlValidationError(ValueError):
    """The input is not a URL Buy or Bye will read. `code` is stable for API clients."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class ProductUrl(BaseModel):
    url: str  # canonical form, the only form used for fetching
    host: str
    shop: str  # host without "www."
    path: str


class FieldValue(BaseModel):
    value: str
    source: Source
    status: Status = "unverified"
    raw: str | None = None  # the text as found, when the value was normalised


class ProductIdentity(BaseModel):
    name: FieldValue | None = None
    brand: FieldValue | None = None
    model: FieldValue | None = None
    mpn: FieldValue | None = None
    gtin: FieldValue | None = None
    category: FieldValue | None = None
    family: FieldValue | None = None  # product line/series: from idealo in M3/M4
    currency: FieldValue | None = None
    market: FieldValue | None = None


class PageRead(BaseModel):
    fetched: bool
    structured_data: bool = False
    retrieved_at: datetime | None = None  # UTC
    reason: str | None = None  # why the page was not read


class UrlIdentityReport(BaseModel):
    schema_version: Literal["1"] = "1"
    input: ProductUrl
    identity: ProductIdentity
    page: PageRead
    warnings: list[str] = Field(default_factory=list)


# --- URL validation ------------------------------------------------------------------------------


def _not_public(host: str) -> bool:
    try:
        ip = ipaddress.ip_address(host.strip("[]"))
    except ValueError:
        if "." not in host or host == "localhost":
            return True
        return host.endswith((".localhost", ".local", ".internal", ".lan", ".home.arpa"))
    return not ip.is_global


def normalize_product_url(raw: str) -> ProductUrl:
    text = (raw or "").strip()
    if not text:
        raise UrlValidationError("empty", "Paste a product link.")
    if len(text) > MAX_URL_LENGTH:
        raise UrlValidationError(
            "too_long", f"The link is longer than {MAX_URL_LENGTH} characters."
        )
    parts = urlsplit(text)
    if parts.scheme.lower() not in ("http", "https"):
        raise UrlValidationError("not_http", "Only http and https product links can be read.")
    if parts.username or parts.password:
        raise UrlValidationError("credentials", "Links with a user name or password are not read.")
    try:
        port = parts.port
    except ValueError as exc:
        raise UrlValidationError("port", "The link has an invalid port.") from exc
    if port not in (None, 80, 443):
        raise UrlValidationError("port", "Only links on the default web ports are read.")
    if not parts.hostname:
        raise UrlValidationError("no_host", "The link has no shop address.")
    try:
        host = parts.hostname.encode("idna").decode("ascii").lower()
    except UnicodeError as exc:
        raise UrlValidationError("no_host", "The shop address is not valid.") from exc
    if _not_public(host):
        raise UrlValidationError("not_public_host", "Only links to public shop websites are read.")
    query = [
        (k, v)
        for k, v in parse_qsl(parts.query, keep_blank_values=True)
        if not k.lower().startswith("utm_") and k.lower() not in _TRACKING_KEYS
    ]
    netloc = f"[{host}]" if ":" in host else host
    path = parts.path or "/"
    url = urlunsplit((parts.scheme.lower(), netloc, path, urlencode(query, doseq=True), ""))
    return ProductUrl(url=url, host=host, shop=host.removeprefix("www."), path=path)


# --- Identity from the URL -----------------------------------------------------------------------

# A model number with a two-digit variant, as shops put it in slugs: XC2011_01, HD9285-90.
_MODEL_VARIANT = re.compile(
    r"(?<![a-z0-9])([a-z]{1,5}\d{3,6}[a-z]{0,2})[_-](\d{2})(?![a-z0-9])", re.I
)
# A model number on its own as one slug token: KT3000, XC2011.
_MODEL_ALONE = re.compile(r"(?<![a-z0-9])([a-z]{1,5}\d{3,6}[a-z]{0,2})(?![a-z0-9_])", re.I)
_LOCALE = re.compile(r"^([a-z]{2})[-_]([a-z]{2})$", re.I)
_CC = re.compile(r"^[a-z]{2}$", re.I)


def _model_from_path(path: str) -> FieldValue | None:
    tail = path.rstrip("/").rsplit("/", 1)[-1]
    tail = re.sub(r"\.(html?|php|aspx?)$", "", tail, flags=re.I)
    with_variant = {
        (m.group(0), f"{m.group(1)}/{m.group(2)}".upper()) for m in _MODEL_VARIANT.finditer(tail)
    }
    if len(with_variant) == 1:
        raw, value = with_variant.pop()
        return FieldValue(value=value, source="url_path", raw=raw)
    if with_variant:  # several candidates: ambiguous, leave unknown
        return None
    alone = {m.group(1).upper() for m in _MODEL_ALONE.finditer(tail)}
    if len(alone) == 1:
        value = alone.pop()
        return FieldValue(value=value, source="url_path", raw=value)
    return None


def _market(u: ProductUrl) -> FieldValue | None:
    tld = u.host.rsplit(".", 1)[-1]
    if _CC.match(tld) and tld not in _GENERIC_CC_TLDS:
        code = "GB" if tld == "uk" else tld.upper()
        return FieldValue(value=code, source="url_host", raw=tld)
    segments = [s for s in u.path.split("/") if s][:3]
    for s in segments:
        m = _LOCALE.match(s)
        if m:
            return FieldValue(value=m.group(2).upper(), source="url_path", raw=s)
    codes = [s for s in segments[:2] if _CC.match(s)]
    if len(codes) == 2 and codes[0].lower() == codes[1].lower():  # /de/de/: country and language
        return FieldValue(value=codes[0].upper(), source="url_path", raw="/".join(codes))
    return None  # a lone /de/ may be a language, not a market: not guessed


def identity_from_url(u: ProductUrl) -> ProductIdentity:
    return ProductIdentity(model=_model_from_path(u.path), market=_market(u))


# --- Identity from page structured data ----------------------------------------------------------


def _clean(value: Any) -> str | None:
    if isinstance(value, dict):
        value = value.get("name")
    if isinstance(value, list):
        value = next((v for v in value if isinstance(v, (str, dict))), None)
        return _clean(value)
    if not isinstance(value, (str, int)) or isinstance(value, bool):
        return None
    text = re.sub(r"\s+", " ", str(value)).strip()
    return text[:MAX_FIELD_LENGTH] or None


def valid_gtin(code: str) -> bool:
    """GS1 check digit for GTIN-8/12/13/14."""
    if not code.isdigit() or len(code) not in (8, 12, 13, 14):
        return False
    digits = [int(c) for c in code]
    body, check = digits[:-1], digits[-1]
    total = sum(d * (3 if i % 2 == 0 else 1) for i, d in enumerate(reversed(body)))
    return (10 - total % 10) % 10 == check


def _field(value: Any, source: Source) -> FieldValue | None:
    text = _clean(value)
    return FieldValue(value=text, source=source) if text else None


def identity_from_html(html: str) -> tuple[ProductIdentity, list[str]]:
    """Identity from JSON-LD Product (preferred) and product meta tags. Text is never read."""
    ident = ProductIdentity()
    warnings: list[str] = []
    gtin_raw: list[tuple[str, Source]] = []

    for node in json_ld_products(html):
        ident.name = ident.name or _field(node.get("name"), "json_ld")
        ident.brand = ident.brand or _field(
            node.get("brand") or node.get("manufacturer"), "json_ld"
        )
        ident.mpn = ident.mpn or _field(node.get("mpn"), "json_ld")
        ident.model = ident.model or _field(node.get("model"), "json_ld")
        ident.category = ident.category or _field(node.get("category"), "json_ld")
        for key in ("gtin13", "gtin", "gtin14", "gtin12", "gtin8", "ean"):
            if (text := _clean(node.get(key))) is not None:
                gtin_raw.append((text, "json_ld"))
        if ident.currency is None:
            offers = node.get("offers")
            for offer in offers if isinstance(offers, list) else [offers]:
                cur = _clean(offer.get("priceCurrency")) if isinstance(offer, dict) else None
                if cur and re.fullmatch(r"[A-Za-z]{3}", cur):
                    ident.currency = FieldValue(value=cur.upper(), source="json_ld")
                    break

    meta = meta_map(html)
    ident.name = ident.name or _field(meta.get("og:title"), "meta")
    ident.brand = ident.brand or _field(
        meta.get("product:brand") or meta.get("og:brand") or meta.get("brand"), "meta"
    )
    ident.mpn = ident.mpn or _field(meta.get("mpn") or meta.get("product:mpn"), "meta")
    for key in ("gtin13", "gtin", "product:ean", "product:gtin", "product:upc"):
        if (text := _clean(meta.get(key))) is not None:
            gtin_raw.append((text, "meta"))
    if ident.currency is None:
        cur = _clean(meta.get("product:price:currency") or meta.get("pricecurrency"))
        if cur and re.fullmatch(r"[A-Za-z]{3}", cur):
            ident.currency = FieldValue(value=cur.upper(), source="meta")

    for text, source in gtin_raw:
        digits = re.sub(r"\D", "", text)
        if valid_gtin(digits):
            ident.gtin = FieldValue(
                value=digits, source=source, raw=text if text != digits else None
            )
            break
        warnings.append(f"The page's GTIN {text!r} has an invalid check digit; it was ignored.")

    if ident.model is None and ident.mpn is not None:
        ident.model = ident.mpn.model_copy()
    return ident, warnings


# --- Full identification -------------------------------------------------------------------------


def _same_model(a: str, b: str) -> bool:
    return re.sub(r"[^A-Z0-9]", "", a.upper()) == re.sub(r"[^A-Z0-9]", "", b.upper())


async def identify_product_url(
    raw: str, *, fetch: Fetcher | None = None, offline: bool = False
) -> UrlIdentityReport:
    """Validate the URL, read the page's structured data (unless offline) and merge.

    Raises UrlValidationError for unusable input. Never raises for page problems: the
    report then says why the page was not read and keeps what the URL gave.
    """
    u = normalize_product_url(raw)
    from_url = identity_from_url(u)
    warnings: list[str] = []
    page = PageRead(fetched=False)
    from_page = ProductIdentity()

    if offline:
        page.reason = "demo mode is offline: the page was not read"
    else:
        try:
            html = await (fetch or fetch_page)(u.url)
            page = PageRead(fetched=True, retrieved_at=datetime.now(UTC))
            from_page, page_warnings = identity_from_html(html)
            warnings.extend(page_warnings)
            page.structured_data = any(
                getattr(from_page, f) is not None for f in ProductIdentity.model_fields
            )
        except PageFetchError as exc:
            page = PageRead(fetched=False, reason=str(exc))
        except Exception:  # noqa: BLE001 - identification must degrade, not fail
            log.exception("product page could not be read for %s", u.shop)
            page = PageRead(fetched=False, reason="the page could not be read")

    if page.fetched and not page.structured_data:
        warnings.append(
            "The page has no structured product data (it may load it with JavaScript); "
            "the identity comes from the URL only."
        )
    if (
        from_page.model
        and from_url.model
        and not _same_model(from_page.model.value, from_url.model.value)
    ):
        warnings.append(
            f"The URL suggests model {from_url.model.value} but the page says "
            f"{from_page.model.value}; the page's value is used."
        )

    merged = ProductIdentity(
        **{f: getattr(from_page, f) or getattr(from_url, f) for f in ProductIdentity.model_fields}
    )
    return UrlIdentityReport(input=u, identity=merged, page=page, warnings=warnings)
