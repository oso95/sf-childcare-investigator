"""OpenAI/OpenRouter function-calling schema for every tool in tools.py."""

from .tools import (
    business_lookup,
    ccld_facility_lookup,
    complaints_311_lookup,
    evictions_lookup,
    housing_inspections_lookup,
    outdoor_space_check,
    parcel_lookup,
    permits_change_of_use_check,
    permits_lookup,
    physical_impossibility_check,
    resolve_block_lot,
    risk_scorecard,
    satellite_image,
    street_view_image,
)

TOOL_IMPL = {
    "ccld_facility_lookup": ccld_facility_lookup,
    "resolve_block_lot": resolve_block_lot,
    "parcel_lookup": parcel_lookup,
    "permits_lookup": permits_lookup,
    "permits_change_of_use_check": permits_change_of_use_check,
    "business_lookup": business_lookup,
    "housing_inspections_lookup": housing_inspections_lookup,
    "complaints_311_lookup": complaints_311_lookup,
    "evictions_lookup": evictions_lookup,
    "physical_impossibility_check": physical_impossibility_check,
    "outdoor_space_check": outdoor_space_check,
    "street_view_image": street_view_image,
    "satellite_image": satellite_image,
    "risk_scorecard": risk_scorecard,
}

TOOL_DEFS = [
    {
        "type": "function",
        "function": {
            "name": "ccld_facility_lookup",
            "description": (
                "Query the California CCLD roster (ArcGIS) for licensed child care "
                "facilities in San Francisco. By default restricts to *centers* (TYPE "
                "830/840/850/860) because Family Child Care Homes (FCCH) are NOT "
                "regulated by the 35-sqft-per-child rule and must not be scored with "
                "Title 22 indoor/outdoor checks. Pass centers_only=false only for "
                "research."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Fragment of facility name"},
                    "street_address": {"type": "string", "description": "Address prefix, e.g. '1984 GREAT'"},
                    "capacity_min": {"type": "integer", "description": "Minimum licensed capacity"},
                    "centers_only": {"type": "boolean", "default": True,
                                     "description": "Restrict to center TYPEs; set False only for FCCH research"},
                    "limit": {"type": "integer", "default": 25},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "resolve_block_lot",
            "description": (
                "Resolve a San Francisco street address to Assessor block+lot by looking up "
                "DBI permits at that address. Required as a first step before parcel_lookup "
                "because the parcel dataset's property_location field is non-matchable."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "street_number": {"type": "string", "description": "e.g. '1984'"},
                    "street_name_token": {"type": "string", "description": "First token of street, UPPER. e.g. 'GREAT'"},
                },
                "required": ["street_number", "street_name_token"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "parcel_lookup",
            "description": (
                "SF Assessor secured property tax roll for a parcel. Returns year_property_built, "
                "property_area (BUILDING sqft), lot_area, number_of_stories/units, use_definition, "
                "zoning_code. This is the source for the physical-impossibility check."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "block": {"type": "string"},
                    "lot": {"type": "string"},
                    "closed_roll_year": {"type": "string", "default": "2016"},
                },
                "required": ["block", "lot"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "permits_lookup",
            "description": "All DBI building permits at an address. Reveals use changes (e.g. church → daycare).",
            "parameters": {
                "type": "object",
                "properties": {
                    "street_number": {"type": "string"},
                    "street_name_token": {"type": "string"},
                    "limit": {"type": "integer", "default": 25},
                },
                "required": ["street_number", "street_name_token"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "business_lookup",
            "description": "SF registered business locations at an address prefix.",
            "parameters": {
                "type": "object",
                "properties": {
                    "address_prefix": {"type": "string", "description": "e.g. '1984 GREAT HIGHWAY'"},
                    "limit": {"type": "integer", "default": 20},
                },
                "required": ["address_prefix"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "housing_inspections_lookup",
            "description": "DBI housing code complaints + NOVs at an address.",
            "parameters": {
                "type": "object",
                "properties": {
                    "street_number": {"type": "string"},
                    "street_name_token": {"type": "string"},
                    "limit": {"type": "integer", "default": 25},
                },
                "required": ["street_number", "street_name_token"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "complaints_311_lookup",
            "description": "SF 311 service requests at an address prefix.",
            "parameters": {
                "type": "object",
                "properties": {
                    "address_prefix": {"type": "string"},
                    "limit": {"type": "integer", "default": 25},
                },
                "required": ["address_prefix"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "evictions_lookup",
            "description": "SF eviction notices filed at an address prefix.",
            "parameters": {
                "type": "object",
                "properties": {
                    "address_prefix": {"type": "string"},
                    "limit": {"type": "integer", "default": 25},
                },
                "required": ["address_prefix"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "physical_impossibility_check",
            "description": (
                "CCR Title 22 §101230(c) indoor check: 35 sqft indoor activity space per "
                "child (exclusive of kitchen/storage/laundry/bathrooms/halls). Applies to "
                "centers only — do NOT run on FCCH (TYPE 200/202/204). Returns verdict: "
                "impossible/implausible/possible/could_not_verify."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "capacity": {"type": "integer"},
                    "building_sqft": {"type": "number"},
                    "sqft_per_child": {"type": "number", "default": 35},
                },
                "required": ["capacity", "building_sqft"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "outdoor_space_check",
            "description": (
                "CCR Title 22 §101230(c) outdoor check: 75 sqft outdoor activity space per "
                "child. Uses `lot_area - building_area` as a conservative proxy. Centers "
                "only. Use as a compound signal; don't flag on this alone."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "capacity": {"type": "integer"},
                    "lot_sqft": {"type": "number"},
                    "building_sqft": {"type": "number"},
                    "sqft_per_child": {"type": "number", "default": 75},
                },
                "required": ["capacity", "lot_sqft", "building_sqft"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "permits_change_of_use_check",
            "description": (
                "Scan the permits list from permits_lookup and return whether any DBI "
                "permit converts the property to child care / school / preschool use. "
                "A missing change-of-use permit at a residential-zoned facility is a "
                "strong signal."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "permits": {"type": "array", "items": {"type": "object"}},
                },
                "required": ["permits"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "street_view_image",
            "description": (
                "Build a Google Street View URL for an SF address. Also hits the free "
                "metadata endpoint to confirm imagery exists. Return value includes an "
                "image_url (for human review) and a street_view_link (public Google Maps). "
                "API-only agents cannot view the image; surface the URLs in the report."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "address": {"type": "string"},
                    "heading": {"type": "integer", "description": "Compass heading 0-360"},
                    "pitch": {"type": "integer", "default": 0},
                    "fov": {"type": "integer", "default": 80},
                },
                "required": ["address"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "satellite_image",
            "description": (
                "Google Maps Static Satellite URL for the address. Good for roof-footprint "
                "vs parcel-area sanity checks. Returns URL only — image is for human review."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "address": {"type": "string"},
                    "zoom": {"type": "integer", "default": 19},
                },
                "required": ["address"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "risk_scorecard",
            "description": (
                "Compound 6-signal risk scorecard for a single facility. Summarises the "
                "investigation into HIGH / MEDIUM / LOW / EXCLUDED. Call after gathering "
                "all the underlying data. Signals: S1 type_is_center, S2 indoor_fails, "
                "S3 outdoor_fails, S4 no_change_of_use_permit, S5 active_code_problem, "
                "S6 residential_parcel. HIGH requires 5+ signals fired AND not EXCLUDED. "
                "Returns a tweet_draft + a CCLD complaint URL. Human review is required "
                "before publication."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "facility_name": {"type": "string"},
                    "address": {"type": "string"},
                    "capacity": {"type": "integer"},
                    "facility_type": {"type": "integer",
                                      "description": "CCLD TYPE code (830/840/850/860 = center; 200/202/204 = FCCH)"},
                    "indoor_verdict": {"type": "string",
                                       "enum": ["impossible", "implausible", "possible", "could_not_verify"]},
                    "outdoor_verdict": {"type": "string",
                                        "enum": ["outdoor_insufficient", "outdoor_sufficient", "could_not_verify"]},
                    "change_of_use_found": {"type": "boolean"},
                    "has_open_nov_or_311": {"type": "boolean"},
                    "parcel_use_definition": {"type": "string"},
                    "parcel_is_condo": {"type": "boolean", "default": False},
                    "parcel_is_exempt": {"type": "boolean", "default": False,
                                         "description": "True when parcel building_sqft=0 (common for tax-exempt YMCA/SFUSD/religious)"},
                },
                "required": ["facility_name", "address", "capacity",
                             "indoor_verdict", "outdoor_verdict",
                             "change_of_use_found", "has_open_nov_or_311"],
            },
        },
    },
]
