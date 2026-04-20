from __future__ import annotations

import re
from typing import Any

import httpx

from .hermai import HermaiError, sfgov_query, _DEFAULT_TIMEOUT

CCL_FACILITIES_URL = (
    "https://services.arcgis.com/XLPEppdz2H9dOiqp/arcgis/rest/services/"
    "CDSS_CCL_Facilities/FeatureServer/0/query"
)

SF_TITLE_22_SQFT_PER_CHILD = 35


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
    limit: int = 25,
) -> dict[str, Any]:
    """Query the CDSS CCL Facilities ArcGIS layer restricted to San Francisco child care."""
    clauses = ["COUNTY='San Francisco'", "PROGRAM_TYPE='CHILD CARE'"]
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
    return {
        "count": len(features),
        "facilities": [f["attributes"] for f in features],
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
                                 sqft_per_child: float = SF_TITLE_22_SQFT_PER_CHILD) -> dict[str, Any]:
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
    return {
        "capacity": capacity,
        "sqft_per_child": sqft_per_child,
        "required_sqft": required_sqft,
        "building_sqft": building_sqft,
        "practical_cap_sqft": practical_cap_sqft,
        "ratio_required_to_building": round(required_sqft / building_sqft, 3),
        "verdict": verdict,
        "rule": (
            f"CA Title 22 requires {sqft_per_child} sqft of indoor activity space per child. "
            f"`impossible` = required > total building sqft. "
            f"`implausible` = required > 70% of building sqft (rest is non-activity space)."
        ),
    }
