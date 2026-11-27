"""BOB-URL-001 M4: resolve a URL identity to one idealo product and verify its fields.

Matching (strict, explainable, no guessing):
* With a model number: an idealo product name must contain that exact model (and variant).
  Same model without a variant -> medium confidence; another variant or model -> rejected.
  A page-stated brand must appear in the idealo name.
* Without a model: the page's product name must match idealo's name closely -> low
  confidence, reported as "uncertain" and never used as a firm identity.
* Single-shop listings (SINGLE_OFFER) are not products and are rejected.
* Two different products matching equally well -> "ambiguous"; none is picked.

Field status: "verified" needs two independent sources agreeing (e.g. URL slug and idealo
name); one source alone is "unverified"; disagreement is "contradicted". Values come only
from what a source states. idealo gives no series/family field, so family stays unknown.

All idealo access goes through the source (`search`, `product_details`), which applies the
daily budget (decision D3); product details are requested only when `details_needed`.
"""

from __future__ import annotations

import re
from typing import Literal, Protocol

from pydantic import BaseModel, Field

from .product_identity import (
    FieldValue,
    ProductIdentity,
    UrlIdentityReport,
    details_needed,
)
from .sources import ProductDetails, SearchHit, SourceError

Status = Literal["matched", "uncertain", "ambiguous", "not_found", "unavailable"]
Confidence = Literal["high", "medium", "low"]
Kind = Literal["exact", "base_only", "name"]
_RANK: dict[str, int] = {"exact": 3, "base_only": 2, "name": 1}
_CONFIDENCE: dict[str, Confidence] = {"exact": "high", "base_only": "medium", "name": "low"}
MIN_NAME_SIMILARITY = 0.8


class IdentitySource(Protocol):
    name: str
    country: str

    async def search(self, query: str, purpose: Literal["identity"] = ...) -> list[SearchHit]: ...

    async def product_details(
        self, product_ref: str, url: str | None, item_type: str | None = ...
    ) -> ProductDetails: ...


class IdealoMatch(BaseModel):
    canonical_id: str | None
    product_ref: str
    name: str
    url: str | None
    item_type: str | None


class Rejected(BaseModel):
    name: str
    reason: str


class Resolution(BaseModel):
    schema_version: Literal["1"] = "1"
    status: Status
    confidence: Confidence | None = None
    reasons: list[str] = Field(default_factory=list)
    match: IdealoMatch | None = None
    rejected: list[Rejected] = Field(default_factory=list)
    identity: ProductIdentity
    details: ProductDetails | None = None
    unknown: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    identification: UrlIdentityReport


def _norm(text: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", text.upper())


def _words(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9]+", text.lower()) if len(w) > 1}


def _model_kind(model: str, name: str) -> tuple[str, str | None]:
    """How an idealo name relates to the model: exact, base_only, variant_mismatch or none."""
    base, _, variant = model.partition("/")
    nb, nv = _norm(base), _norm(variant)
    best, other = "none", None
    for token in name.split():
        t = _norm(token)
        if not nb or not t.startswith(nb):
            continue
        rest = t[len(nb) :]
        if rest == nv:
            return "exact", None
        if rest == "" and nv:
            best = "base_only"
        elif re.fullmatch(r"\d{1,3}", rest) and best == "none":
            best, other = "variant_mismatch", token
    return best, other


def _brand_before_model(name: str, model: str) -> str | None:
    """The single word idealo puts before the model ("Philips XC2011/01" -> "Philips")."""
    tokens = name.split()
    nb = _norm(model.partition("/")[0])
    for i, token in enumerate(tokens):
        if nb and _norm(token).startswith(nb):
            if i == 1 and re.fullmatch(r"[A-Za-zÀ-ÿ][A-Za-zÀ-ÿ&'-]{1,30}", tokens[0]):
                return tokens[0]
            return None
    return None


def _classify(identity: ProductIdentity, hit: SearchHit) -> tuple[Kind | None, str]:
    if hit.item_type == "SINGLE_OFFER":
        return None, "single shop listing, not a product"
    if identity.brand and _norm(identity.brand.value) not in {_norm(w) for w in hit.name.split()}:
        return None, f"brand differs from the page ({identity.brand.value})"
    if identity.model:
        kind, other = _model_kind(identity.model.value, hit.name)
        if kind == "exact":
            return "exact", "same model and variant"
        if kind == "base_only":
            return "base_only", "same model; idealo does not state the variant"
        if kind == "variant_mismatch":
            return None, f"different variant ({other}, not {identity.model.value})"
        return None, f"different model (not {identity.model.value})"
    if identity.name:
        q, h = _words(identity.name.value), _words(hit.name)
        if q and len(q & h) / max(len(q), len(h)) >= MIN_NAME_SIMILARITY:
            return "name", "product name matches (no model number to compare)"
        return None, "product name does not match"
    return None, "nothing to compare"


def _query(identity: ProductIdentity) -> str | None:
    if identity.model:
        return (
            f"{identity.brand.value} {identity.model.value}"
            if identity.brand
            else (identity.model.value)
        )
    return identity.name.value if identity.name else None


def _confirm(field: FieldValue | None, value: str, by: Literal["idealo", "url_host"]) -> None:
    if field is None:
        return
    same = _norm(field.value) == _norm(value)
    field.status = "verified" if same else "contradicted"
    field.corroborated_by = by


def _unknown(identity: ProductIdentity) -> list[str]:
    return [f for f in ProductIdentity.model_fields if getattr(identity, f) is None]


def _unresolved(
    status: Status,
    report: UrlIdentityReport,
    identity: ProductIdentity,
    reasons: list[str],
    rejected: list[Rejected] | None = None,
) -> Resolution:
    return Resolution(
        status=status,
        identity=identity,
        reasons=reasons,
        rejected=rejected or [],
        unknown=_unknown(identity),
        warnings=list(report.warnings),
        identification=report,
    )


async def resolve_identity(report: UrlIdentityReport, source: IdentitySource) -> Resolution:
    identity = report.identity.model_copy(deep=True)

    query = _query(identity)
    if query is None:
        return _unresolved(
            "not_found",
            report,
            identity,
            ["nothing to search for: no model number or product name was found"],
        )
    try:
        hits = await source.search(query, purpose="identity")
    except SourceError as exc:
        return _unresolved("unavailable", report, identity, [str(exc)])

    accepted: list[tuple[Kind, SearchHit]] = []
    rejected: list[Rejected] = []
    for hit in hits:
        hit_kind, why = _classify(identity, hit)
        if hit_kind is None:
            rejected.append(Rejected(name=hit.name, reason=why))
        else:
            accepted.append((hit_kind, hit))

    if not accepted:
        return _unresolved(
            "not_found", report, identity, [f"no idealo product matches {query!r}"], rejected
        )
    top = max(_RANK[k] for k, _ in accepted)
    best = [h for k, h in accepted if _RANK[k] == top]
    distinct = {h.canonical_id or h.product_ref for h in best}
    if len(distinct) > 1:
        return _unresolved(
            "ambiguous",
            report,
            identity,
            [
                f"{len(distinct)} different idealo products match equally well: "
                + "; ".join(h.name for h in best[:5])
            ],
            rejected,
        )

    best_kind: Kind = next(k for k, h in accepted if _RANK[k] == top)
    hit = best[0]
    warnings = list(report.warnings)
    reasons = [f"idealo product {hit.name!r}: {_classify(identity, hit)[1]}"]
    status: Status = "matched" if best_kind in ("exact", "base_only") else "uncertain"

    # --- Verify fields against the match ------------------------------------------------------
    if identity.model and best_kind == "exact":
        _confirm(identity.model, identity.model.value, "idealo")
    elif best_kind == "base_only":
        reasons.append("the variant is not confirmed: idealo lists the model without it")

    if identity.brand:
        _confirm(identity.brand, identity.brand.value, "idealo")  # required to appear above
    elif identity.model and (brand := _brand_before_model(hit.name, identity.model.value)):
        identity.brand = FieldValue(value=brand, source="idealo", raw=hit.name)
        host_labels = {_norm(lbl) for lbl in report.input.host.split(".")}
        if _norm(brand) in host_labels:
            identity.brand.status, identity.brand.corroborated_by = "verified", "url_host"

    if identity.name is None:
        identity.name = FieldValue(value=hit.name, source="idealo")

    market = source.country.upper()
    if identity.market:
        _confirm(identity.market, market, "idealo")
        if identity.market.status == "contradicted":
            status = "uncertain"
            warnings.append(
                f"market: the link is for {identity.market.value}, but idealo was searched "
                f"in the {market} marketplace; prices are not comparable"
            )

    if hit.currency:
        if identity.currency:
            _confirm(identity.currency, hit.currency, "idealo")
        else:
            identity.currency = FieldValue(value=hit.currency, source="idealo")

    details: ProductDetails | None = None
    if status == "matched" and details_needed(identity):
        details = await source.product_details(hit.product_ref, hit.url, hit.item_type)
        if details.product_type:
            identity.category = FieldValue(value=details.product_type, source="idealo")
        if details.status == "unavailable":
            warnings.append(f"product details unavailable: {details.error}")

    unknown = _unknown(identity)
    if "family" in unknown:
        reasons.append("family: no approved source states a product series for this item")

    return Resolution(
        status=status,
        confidence=_CONFIDENCE[best_kind],
        reasons=reasons,
        match=IdealoMatch(
            canonical_id=hit.canonical_id,
            product_ref=hit.product_ref,
            name=hit.name,
            url=hit.url,
            item_type=hit.item_type,
        ),
        rejected=rejected,
        identity=identity,
        details=details,
        unknown=unknown,
        warnings=warnings,
        identification=report,
    )
