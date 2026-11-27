"""Daily idealo call budget (BOB-URL-001 decision D3).

Every idealo tool call is counted per UTC day in a small JSON file and refused BEFORE it is
made when it would break the policy:

* Hard limit: at most `daily_limit` calls per day (default and maximum 500, the Trial quota).
* Reserve: identity calls (`get_product_details`) are refused once fewer than
  `price_check_reserve` calls are left, so price checks keep working.

Attempts are counted, not only successes: idealo may count a call that failed on our side.
A multi-call check (search + history + offers) is admitted all or nothing. The file survives
restarts; an asyncio lock keeps concurrent requests in one process from overshooting.
The day boundary is UTC midnight (idealo does not document its reset time).
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any, Literal

from .sources import SourceError

log = logging.getLogger("buy_or_bye.idealo_usage")

HARD_MAX_PER_DAY = 500
DEFAULT_PRICE_CHECK_RESERVE = 150


def default_usage_file() -> Path:
    """IDEALO_USAGE_FILE, read when a tracker is created (so tests can redirect it)."""
    return Path(
        os.environ.get("IDEALO_USAGE_FILE") or Path.home() / ".buyorbye" / "idealo_usage.json"
    )


Purpose = Literal["price_check", "identity"]


class QuotaExceeded(SourceError):
    """The call was refused locally; nothing was sent to idealo."""


def _int(env: Mapping[str, str], key: str, default: int) -> int:
    raw = env.get(key)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError:
        log.warning("%s=%r is not a whole number; using %s", key, raw, default)
        return default


@dataclass(frozen=True)
class UsagePolicy:
    daily_limit: int = HARD_MAX_PER_DAY
    price_check_reserve: int = DEFAULT_PRICE_CHECK_RESERVE

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> UsagePolicy:
        env = os.environ if env is None else env
        limit = min(max(_int(env, "IDEALO_DAILY_LIMIT", HARD_MAX_PER_DAY), 0), HARD_MAX_PER_DAY)
        reserve = _int(env, "IDEALO_PRICE_CHECK_RESERVE", DEFAULT_PRICE_CHECK_RESERVE)
        return cls(daily_limit=limit, price_check_reserve=min(max(reserve, 0), limit))


def _utc_today() -> date:
    return datetime.now(UTC).date()


class UsageTracker:
    def __init__(
        self,
        path: Path | None = None,
        policy: UsagePolicy | None = None,
        today: Callable[[], date] = _utc_today,
    ) -> None:
        self.path = path or default_usage_file()
        self.policy = policy or UsagePolicy.from_env()
        self._today = today
        self._lock = asyncio.Lock()

    def _load(self) -> dict[str, Any]:
        day = self._today().isoformat()
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            data = {}
        if not isinstance(data, dict) or data.get("day") != day:
            return {"day": day, "total": 0, "by_tool": {}}
        raw_tools = data.get("by_tool")
        by_tool: dict[str, int] = {
            str(k): v
            for k, v in (raw_tools.items() if isinstance(raw_tools, dict) else [])
            if isinstance(v, int) and v >= 0
        }
        total = data.get("total")
        if not isinstance(total, int) or total < 0:
            total = sum(by_tool.values())
        return {"day": day, "total": total, "by_tool": by_tool}

    def _save(self, data: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data), encoding="utf-8")
        os.replace(tmp, self.path)

    async def acquire(self, tools: list[str], purpose: Purpose = "price_check") -> None:
        """Admit all of `tools` as calls today, or refuse all of them with QuotaExceeded."""
        async with self._lock:
            data = self._load()
            used, wanted = data["total"], len(tools)
            limit, reserve = self.policy.daily_limit, self.policy.price_check_reserve
            if used + wanted > limit:
                raise QuotaExceeded(
                    f"idealo daily limit reached: {used} of {limit} calls used today (UTC). "
                    "Try again tomorrow."
                )
            if purpose == "identity" and used + wanted > limit - reserve:
                raise QuotaExceeded(
                    f"product details skipped: the last {reserve} idealo calls today are "
                    "reserved for price checks."
                )
            for tool in tools:
                data["by_tool"][tool] = data["by_tool"].get(tool, 0) + 1
            data["total"] = used + wanted
            self._save(data)

    def snapshot(self) -> dict[str, Any]:
        data = self._load()
        return {
            **data,
            "limit": self.policy.daily_limit,
            "price_check_reserve": self.policy.price_check_reserve,
            "remaining": max(self.policy.daily_limit - data["total"], 0),
        }
