import os
from typing import Any

import httpx

HERMAI_BASE_URL = os.environ.get("HERMAI_BASE_URL", "https://api.hermai.ai")
HERMAI_API_KEY = os.environ.get("HERMAI_API_KEY", "")
HERMAI_INTENT = (
    "investigating San Francisco childcare facilities for physically impossible "
    "licensed capacity given building square footage"
)
SKILL_NAME = "sf-childcare-investigator"
SKILL_VERSION = "0.1.0"

_DEFAULT_TIMEOUT = float(os.environ.get("TOOL_TIMEOUT_SECONDS", "30"))


class HermaiError(RuntimeError):
    pass


def _headers() -> dict[str, str]:
    if not HERMAI_API_KEY:
        raise HermaiError("HERMAI_API_KEY is not set")
    return {
        "Authorization": f"Bearer {HERMAI_API_KEY}",
        "X-Hermai-Intent": HERMAI_INTENT,
        "X-Hermai-Skill-Name": SKILL_NAME,
        "X-Hermai-Skill-Version": SKILL_VERSION,
    }


def sfgov_query(resource_id: str, where: str, *, select: str | None = None,
                order: str | None = None, limit: int = 25) -> list[dict[str, Any]]:
    """
    Call a Socrata resource on data.sfgov.org. The Hermai schema documents which
    resource_id to use for which dataset; this helper bypasses Hermai's package
    endpoint once the caller knows the resource_id and just hits data.sfgov.org
    directly with the documented SoQL filter recipe.
    """
    params: dict[str, Any] = {"$where": where, "$limit": limit}
    if select:
        params["$select"] = select
    if order:
        params["$order"] = order

    url = f"https://data.sfgov.org/resource/{resource_id}.json"
    try:
        resp = httpx.get(url, params=params, timeout=_DEFAULT_TIMEOUT)
    except httpx.HTTPError as e:
        raise HermaiError(f"sfgov request failed: {e}") from e

    if resp.status_code != 200:
        raise HermaiError(f"sfgov {resource_id} → HTTP {resp.status_code}: {resp.text[:200]}")
    data = resp.json()
    if isinstance(data, dict) and "message" in data:
        raise HermaiError(f"sfgov SoQL error: {data['message'][:300]}")
    return data  # type: ignore[no-any-return]


def pull_schema_package(site: str) -> dict[str, Any]:
    """Fetch the full schema package from Hermai for `site` (e.g. 'data.sfgov.org')."""
    url = f"{HERMAI_BASE_URL}/v1/schemas/{site}/package"
    resp = httpx.get(url, headers=_headers(), timeout=_DEFAULT_TIMEOUT)
    if resp.status_code != 200:
        raise HermaiError(f"hermai package fetch failed ({resp.status_code}): {resp.text[:200]}")
    body = resp.json()
    meta = body.get("meta") or {}
    update = meta.get("skill_update")
    if update:
        print(f"[hermai] skill update available: {update}")
    return body.get("data") or body
