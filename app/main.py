"""HTTP API and the mobile-first page."""

from __future__ import annotations

import logging
import re
from datetime import date, timedelta
from importlib import resources

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import HTMLResponse

from .extract import Extracted, parse_photo, parse_text
from .models import Deal, Verdict
from .shop_page import prices_for_link
from .sources import PriceSource, SourceError, make_source
from .verdict import decide

log = logging.getLogger("buy_or_bye")
app = FastAPI(title="Buy or Bye", version="0.1.0")
source: PriceSource = make_source()
MAX_PHOTO_BYTES = 6 * 1024 * 1024
PHOTO = File(...)


def _today_for(history_last: date | None, src: str) -> date:
    # Demo data is a fixed snapshot: judge it as of the day after its last price.
    if src == "demo" and history_last is not None:
        return history_last + timedelta(days=1)
    return date.today()


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"ok": "true", "source": source.name}


@app.get("/", response_class=HTMLResponse)
async def index() -> str:
    return resources.files("app").joinpath("static/index.html").read_text(encoding="utf-8")


@app.post("/api/extract/text")
async def extract_text(body: dict[str, str]) -> Extracted:
    text = body.get("text", "")[:2000].strip()
    # Live mode only: demo mode stays fully offline.
    if source.name != "demo" and re.match(r"https?://", text):
        return await prices_for_link(text, source)
    return parse_text(text)


@app.post("/api/extract/photo")
async def extract_photo(photo: UploadFile = PHOTO) -> Extracted:
    data = await photo.read(MAX_PHOTO_BYTES + 1)
    if len(data) > MAX_PHOTO_BYTES:
        raise HTTPException(413, "Photo too large (max 6 MB).")
    if not (photo.content_type or "").startswith("image/"):
        raise HTTPException(415, "Please upload an image.")
    try:
        return await parse_photo(data, photo.content_type or "image/jpeg")
    except Exception:  # noqa: BLE001 - surfaced to the user as "type it instead"
        log.exception("photo extraction failed")
        return Extracted(note="We couldn't read the photo. Please type the details.")


@app.post("/api/check")
async def check(deal: Deal) -> Verdict:
    try:
        product = await source.find(deal.product)
    except SourceError as exc:
        raise HTTPException(503, str(exc)) from exc
    last = product.history[-1].day if product and product.history else None
    return decide(deal, product, _today_for(last, source.name))
