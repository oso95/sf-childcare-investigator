from __future__ import annotations

import os
import re
import urllib.parse
from typing import Any

import httpx

from .hermai import HermaiError, sfgov_query, _DEFAULT_TIMEOUT

CCL_FACILITIES_URL = (
    "https://services.arcgis.com/XLPEppdz2H9dOiqp/arcgis/rest/services/"
    "CDSS_CCL_Facilities/FeatureServer/0/query"
)

# CCR Title 22 §101230(c): 35 sqft indoor activity space per child — centers only.
SF_TITLE_22_INDOOR_SQFT_PER_CHILD = 35
# CCR Title 22 §101230(c): 75 sqft of outdoor activity space per child — centers only.
SF_TITLE_22_OUTDOOR_SQFT_PER_CHILD = 75

# CCLD TYPE codes to which the sqft-per-child rule applies.
# 830 = Infant Care Center, 840 = Child Care Center, 850 = Preschool, 860 = School Age Center.
# Family Child Care Homes (TYPE 200/202/204) are regulated by capacity tier, NOT sqft,
# so they must be excluded from the indoor/outdoor impossibility check.
CENTER_TYPES = {830, 840, 850, 860}
FCCH_TYPES = {200, 202, 204}
TYPE_LABELS = {
    830: "Infant Care Center",
    840: "Child Care Center",
    850: "Preschool",
    860: "School Age Center",
    200: "Family Child Care Home (small)",
    202: "Family Child Care Home (large)",
    204: "Family Child Care Home",
}


def _soql_escape(value: str) -> str:
    return value.replace("'", "''")


_STREET_PREFIX = {"N", "S", "E", "W", "NORTH", "SOUTH", "EAST", "WEST"}
_STREET_SUFFIXES = {
    "ST", "STREET", "AVE", "AVENUE", "BLVD", "BOULEVARD", "HWY", "HIGHWAY",
    "RD", "ROAD", "LN", "LANE", "DR", "DRIVE", "CT", "COURT", "PL", "PLACE",
    "TER", "TERRACE", "WAY", "PKWY", "PARKWAY", "CIR", "CIRCLE",
}


def _parse_street(address: str) -> tuple[str, str]:
    """
    Best-effort: pull (street_number, street_name_token) out of messy CCL address
    strings. Examples handled:
      '1984 GREAT HIGHWAY'                 → ('1984', 'GREAT')
      '3960 (AKA3950) SACRAMENTO S'        → ('3960', 'SACRAMENTO')
      '207 SKYLINE BLVD. 1-5 12 14'        → ('207', 'SKYLINE')
      '1775 - 44TH AVENUE'                 → ('1775', '44TH')
      '680 18TH AVENUE'                    → ('680', '18TH')
      '680 N VAN NESS AVE'                 → ('680', 'VAN')  (skips directional)
    Falls back to the first all-alpha-ish token after the number.
    """
    addr = re.sub(r"\([^)]*\)", " ", address).strip()  # strip parens like (AKA3950)
    m = re.match(r"\s*(\d+)\s*-?\s*(.+)", addr)
    if not m:
        raise ValueError(f"cannot parse street number from {address!r}")
    number = m.group(1)
    rest = m.group(2).upper()
    tokens = [t.strip(".,") for t in rest.split() if t.strip(".,")]
    for tok in tokens:
        if tok in _STREET_PREFIX:
            continue
        if tok in _STREET_SUFFIXES:
            continue
        if not re.match(r"^[A-Z0-9]+$", tok):
            continue
        return number, tok
    raise ValueError(f"cannot extract street name from {address!r}")


def ccld_facility_lookup(
    *,
    name: str | None = None,
    street_address: str | None = None,
    capacity_min: int | None = None,
    centers_only: bool = True,
    limit: int = 25,
) -> dict[str, Any]:
    """
    Query CDSS CCL Facilities ArcGIS, restricted to SF child care.

    `centers_only=True` (default) drops Family Child Care Homes (FCCH) because
    they are regulated by head-count tiers, NOT by the 35-sqft-per-child rule,
    so they must not be scored with the Title 22 indoor/outdoor checks.
    """
    clauses = ["COUNTY='San Francisco'", "PROGRAM_TYPE='CHILD CARE'"]
    if centers_only:
        type_list = ",".join(str(t) for t in sorted(CENTER_TYPES))
        clauses.append(f"TYPE IN ({type_list})")
    if name:
        clauses.append(f"UPPER(NAME) LIKE '%{_soql_escape(name.upper())}%'")
    if street_address:
        clauses.append(f"UPPER(RES_STREET_ADDR) LIKE '{_soql_escape(street_address.upper())}%'")
    if capacity_min is not None:
        clauses.append(f"CAPACITY>={int(capacity_min)}")

    params = {
        "where": " AND ".join(clauses),
        "outFields": "NAME,RES_STREET_ADDR,RES_CITY,RES_ZIP_CODE,CAPACITY,"
                     "PROGRAM_TYPE,STATUS,CLIENT_SERVED,FAC_NBR,TYPE",
        "returnGeometry": "false",
        "f": "json",
        "resultRecordCount": str(limit),
    }
    resp = httpx.get(CCL_FACILITIES_URL, params=params, timeout=_DEFAULT_TIMEOUT)
    if resp.status_code != 200:
        raise HermaiError(f"CCL ArcGIS {resp.status_code}: {resp.text[:200]}")
    features = resp.json().get("features", [])
    enriched = []
    for feat in features:
        a = feat["attributes"]
        a["TYPE_LABEL"] = TYPE_LABELS.get(a.get("TYPE"), f"TYPE {a.get('TYPE')}")
        a["IS_CENTER"] = a.get("TYPE") in CENTER_TYPES
        enriched.append(a)
    return {
        "count": len(enriched),
        "centers_only": centers_only,
        "facilities": enriched,
    }


def resolve_block_lot(street_number: str, street_name_token: str) -> dict[str, Any]:
    """Use DBI permits as the address → block/lot join table (canonical recipe)."""
    where = (
        f"street_number='{_soql_escape(street_number)}' AND "
        f"upper(street_name)='{_soql_escape(street_name_token.upper())}'"
    )
    rows = sfgov_query(
        "i98e-djp9", where,
        select="block,lot,street_number,street_name,street_suffix",
        limit=5,
    )
    if not rows:
        return {"resolved": False, "block": None, "lot": None, "candidates": []}
    seen: list[tuple[str, str]] = []
    uniq: list[dict[str, Any]] = []
    for r in rows:
        key = (r.get("block", ""), r.get("lot", ""))
        if key in seen:
            continue
        seen.append(key)
        uniq.append(r)
    top = uniq[0]
    return {
        "resolved": True,
        "block": top.get("block"),
        "lot": top.get("lot"),
        "candidates": uniq,
    }


def parcel_lookup(block: str, lot: str, closed_roll_year: str = "2016") -> dict[str, Any]:
    """SF Assessor secured property tax roll parcel — the physical-impossibility source."""
    where = (
        f"block='{_soql_escape(block)}' AND "
        f"lot='{_soql_escape(lot)}' AND "
        f"closed_roll_year='{_soql_escape(closed_roll_year)}'"
    )
    rows = sfgov_query("wv5m-vpq2", where, limit=3)
    if not rows:
        return {"found": False}
    r = rows[0]
    keep = [
        "property_location", "block", "lot", "year_property_built",
        "property_area", "lot_area", "number_of_stories", "number_of_units",
        "number_of_bedrooms", "number_of_bathrooms", "number_of_rooms",
        "use_code", "use_definition", "property_class_code",
        "property_class_code_definition", "zoning_code", "construction_type",
        "analysis_neighborhood", "supervisor_district",
    ]
    return {"found": True, **{k: r.get(k) for k in keep}}


def permits_lookup(street_number: str, street_name_token: str, limit: int = 25) -> dict[str, Any]:
    where = (
        f"street_number='{_soql_escape(street_number)}' AND "
        f"upper(street_name)='{_soql_escape(street_name_token.upper())}'"
    )
    rows = sfgov_query(
        "i98e-djp9", where,
        select="permit_number,status,permit_type_definition,description,"
               "filed_date,issued_date,completed_date,estimated_cost,revised_cost,"
               "existing_use,proposed_use,block,lot",
        order="filed_date DESC",
        limit=limit,
    )
    return {"count": len(rows), "permits": rows}


def business_lookup(address_prefix: str, limit: int = 20) -> dict[str, Any]:
    where = f"upper(full_business_address) like '{_soql_escape(address_prefix.upper())}%'"
    rows = sfgov_query(
        "g8m3-pdis", where,
        select="dba_name,ownership_name,full_business_address,business_zip,"
               "dba_start_date,dba_end_date,location_start_date,location_end_date,"
               "naic_code,naic_code_description,certificate_number",
        order="dba_start_date DESC",
        limit=limit,
    )
    return {"count": len(rows), "businesses": rows}


def housing_inspections_lookup(street_number: str, street_name_token: str, limit: int = 25) -> dict[str, Any]:
    where = (
        f"street_number='{_soql_escape(street_number)}' AND "
        f"upper(street_name)='{_soql_escape(street_name_token.upper())}'"
    )
    rows = sfgov_query(
        "nbtm-fbw5", where,
        select="complaint_number,date_filed,status,item,"
               "nov_category_description,nov_item_description,"
               "receiving_division,assigned_division",
        order="date_filed DESC",
        limit=limit,
    )
    return {"count": len(rows), "inspections": rows}


def complaints_311_lookup(address_prefix: str, limit: int = 25) -> dict[str, Any]:
    where = f"upper(address) like '{_soql_escape(address_prefix.upper())}%'"
    rows = sfgov_query(
        "vw6y-z8j6", where,
        order="requested_datetime DESC",
        limit=limit,
    )
    keep = [
        "service_request_id", "requested_datetime", "closed_date",
        "status_description", "service_name", "service_subtype",
        "service_details", "address",
    ]
    trimmed = [{k: r.get(k) for k in keep if k in r} for r in rows]
    return {"count": len(trimmed), "complaints": trimmed}


def evictions_lookup(address_prefix: str, limit: int = 25) -> dict[str, Any]:
    where = f"upper(address) like '{_soql_escape(address_prefix.upper())}%'"
    rows = sfgov_query(
        "5cei-gny5", where,
        order="file_date DESC",
        limit=limit,
    )
    keep = [
        "eviction_id", "address", "file_date", "non_payment", "breach",
        "nuisance", "illegal_use", "failure_to_sign_renewal", "access_denial",
        "unapproved_subtenant", "owner_move_in", "demolition", "capital_improvement",
        "substantial_rehab", "ellis_act_withdrawal",
    ]
    trimmed = [{k: r.get(k) for k in keep if k in r} for r in rows]
    return {"count": len(trimmed), "evictions": trimmed}


def physical_impossibility_check(capacity: int, building_sqft: float,
                                 sqft_per_child: float = SF_TITLE_22_INDOOR_SQFT_PER_CHILD) -> dict[str, Any]:
    """
    CA Title 22 requires 35 sqft of indoor activity space per child.

    Verdicts:
      - `could_not_verify`  building_sqft is 0 or missing. Assessor reports 0 for many
                            tax-exempt parcels (YMCAs, religious orgs, city-owned rec
                            centers, SFUSD schools). Do NOT conclude impossibility — the
                            building exists, the assessor just didn't record its size.
      - `impossible`        building_sqft < required_sqft (hard ceiling — can't fit even
                            if 100% of the building were activity space).
      - `implausible`       required_sqft > 70% of building_sqft (once you subtract
                            kitchens, bathrooms, office, circulation, capacity won't fit
                            in practice).
      - `possible`          required_sqft <= 70% of building_sqft.
    """
    required_sqft = capacity * sqft_per_child
    if not building_sqft or building_sqft <= 0:
        return {
            "capacity": capacity,
            "required_sqft": required_sqft,
            "building_sqft": building_sqft,
            "verdict": "could_not_verify",
            "note": (
                "Assessor reports building_sqft=0 (common for tax-exempt parcels: "
                "nonprofits, religious orgs, city-owned property, SFUSD). The building "
                "exists — the dataset just doesn't record its size. Look at "
                "permits_lookup to recover footprint from permit filings if available."
            ),
        }
    practical_cap_sqft = building_sqft * 0.70
    if building_sqft < required_sqft:
        verdict = "impossible"
    elif required_sqft > practical_cap_sqft:
        verdict = "implausible"
    else:
        verdict = "possible"
    deficit_sqft = max(required_sqft - building_sqft, 0)
    return {
        "capacity": capacity,
        "sqft_per_child": sqft_per_child,
        "required_sqft": required_sqft,
        "building_sqft": building_sqft,
        "practical_cap_sqft": practical_cap_sqft,
        "deficit_sqft": deficit_sqft,
        "ratio_required_to_building": round(required_sqft / building_sqft, 3),
        "verdict": verdict,
        "rule": (
            f"CCR Title 22 §101230(c): {sqft_per_child} sqft of indoor activity space per child "
            f"(exclusive of kitchen, storage, laundry, bathrooms, halls). "
            f"`impossible` = required > total building sqft. "
            f"`implausible` = required > 70% of building sqft (rest is non-activity space)."
        ),
    }


def outdoor_space_check(capacity: int, lot_sqft: float, building_sqft: float,
                        sqft_per_child: float = SF_TITLE_22_OUTDOOR_SQFT_PER_CHILD) -> dict[str, Any]:
    """
    CCR Title 22 §101230(c): 75 sqft of outdoor activity space per child — centers only.
    Approximated by `lot - building` (the remaining lot area after the footprint).

    Real outdoor activity space must be on-site and accessible; this is a best-effort
    proxy. Don't flag on this alone; use it as a compound signal.
    """
    if not lot_sqft or lot_sqft <= 0:
        return {"verdict": "could_not_verify", "note": "lot_area missing or 0 (often tax-exempt parcels)"}
    approx_outdoor = max(lot_sqft - (building_sqft or 0), 0)
    required = capacity * sqft_per_child
    if approx_outdoor < required:
        verdict = "outdoor_insufficient"
    else:
        verdict = "outdoor_sufficient"
    return {
        "capacity": capacity,
        "sqft_per_child": sqft_per_child,
        "required_outdoor_sqft": required,
        "lot_sqft": lot_sqft,
        "building_sqft": building_sqft,
        "approx_outdoor_sqft": approx_outdoor,
        "ratio_required_to_approx": round(required / approx_outdoor, 3) if approx_outdoor else None,
        "verdict": verdict,
        "rule": (
            f"CCR Title 22 §101230(c): {sqft_per_child} sqft outdoor activity space per child. "
            f"Using `lot_area - building_area` as a conservative proxy. Real outdoor space "
            f"must be on-site and accessible."
        ),
    }


def permits_change_of_use_check(permits: list[dict[str, Any]]) -> dict[str, Any]:
    """
    Given a list of permit rows (from permits_lookup), look for a change-of-use from
    residential/retail into school/daycare/child-care. Returns:
      - change_of_use_found: bool
      - matching_permits: the ones whose existing_use or proposed_use contains a daycare-y word
    A missing change-of-use permit at a residentially-zoned facility is a strong signal.
    """
    if not permits:
        return {"change_of_use_found": False, "matching_permits": [], "total_permits": 0}
    daycare_markers = ("school", "child care", "childcare", "day care", "daycare", "preschool", "nursery")
    residential_markers = ("dwelling", "residential", "1 family", "2 family", "sfr", "single family", "apartment")
    matches = []
    for p in permits:
        proposed = (p.get("proposed_use") or "").lower()
        existing = (p.get("existing_use") or "").lower()
        desc = (p.get("description") or "").lower()
        has_daycare_proposed = any(m in proposed for m in daycare_markers) or any(m in desc for m in daycare_markers)
        has_residential_existing = any(m in existing for m in residential_markers)
        if has_daycare_proposed:
            matches.append({
                "permit_number": p.get("permit_number"),
                "status": p.get("status"),
                "filed_date": p.get("filed_date"),
                "existing_use": p.get("existing_use"),
                "proposed_use": p.get("proposed_use"),
                "description": (p.get("description") or "")[:200],
                "existing_was_residential": has_residential_existing,
            })
    return {
        "change_of_use_found": len(matches) > 0,
        "total_permits": len(permits),
        "matching_permits": matches,
    }


def street_view_image(address: str, *, heading: int | None = None,
                      pitch: int = 0, fov: int = 80) -> dict[str, Any]:
    """
    Build a Google Street View Static API URL for an SF address and call the free
    metadata endpoint to confirm imagery exists there. Returns:
      {has_imagery, image_url, metadata_status, pano_id, lat, lng, street_view_link}

    `image_url` is a signed-less Static API URL; if GOOGLE_MAPS_API_KEY is set the
    key is appended so it renders. The metadata check is free and doesn't count
    against image quota.

    Use this as a compound signal only: Street View suggests whether the address
    looks residential vs commercial, but the LLM can't see the image — return the
    URL for human review.
    """
    api_key = os.environ.get("GOOGLE_MAPS_API_KEY", "")
    loc = urllib.parse.quote_plus(f"{address}, San Francisco, CA")

    metadata: dict[str, Any] = {"status": "UNKNOWN"}
    if api_key:
        meta_url = (
            "https://maps.googleapis.com/maps/api/streetview/metadata"
            f"?location={loc}&source=outdoor&key={api_key}"
        )
        try:
            r = httpx.get(meta_url, timeout=_DEFAULT_TIMEOUT)
            if r.status_code == 200:
                metadata = r.json()
        except httpx.HTTPError:
            metadata = {"status": "REQUEST_FAILED"}

    params = {"size": "640x400", "location": f"{address}, San Francisco, CA",
              "fov": str(fov), "pitch": str(pitch), "source": "outdoor"}
    if heading is not None:
        params["heading"] = str(heading)
    if api_key:
        params["key"] = api_key
    image_url = (
        "https://maps.googleapis.com/maps/api/streetview?"
        + urllib.parse.urlencode(params)
    )
    # Human-viewable Street View link (no key required).
    street_view_link = f"https://www.google.com/maps/place/{loc}"

    return {
        "has_imagery": metadata.get("status") == "OK",
        "metadata_status": metadata.get("status"),
        "pano_id": metadata.get("pano_id"),
        "lat": metadata.get("location", {}).get("lat") if isinstance(metadata.get("location"), dict) else None,
        "lng": metadata.get("location", {}).get("lng") if isinstance(metadata.get("location"), dict) else None,
        "image_url": image_url,
        "street_view_link": street_view_link,
        "note": (
            "API-only agents cannot see the image; return the URL for human review. "
            "When key is absent, image_url is still usable if a GOOGLE_MAPS_API_KEY "
            "is appended."
        ),
    }


def satellite_image(address: str, *, zoom: int = 19) -> dict[str, Any]:
    """
    Google Maps Static Satellite URL for the address. Good for roof-footprint
    vs parcel-area sanity checks. Returns {image_url, map_link}.
    """
    api_key = os.environ.get("GOOGLE_MAPS_API_KEY", "")
    loc = f"{address}, San Francisco, CA"
    loc_q = urllib.parse.quote_plus(loc)
    params = {"center": loc, "zoom": str(zoom), "size": "640x480",
              "maptype": "satellite", "scale": "2"}
    if api_key:
        params["key"] = api_key
    image_url = (
        "https://maps.googleapis.com/maps/api/staticmap?"
        + urllib.parse.urlencode(params)
    )
    return {
        "image_url": image_url,
        "map_link": f"https://www.google.com/maps/place/{loc_q}",
        "zoom": zoom,
    }


