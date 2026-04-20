"""OpenAI/OpenRouter function-calling schema for every tool in tools.py."""

from .tools import (
    business_lookup,
    ccld_facility_lookup,
    complaints_311_lookup,
    evictions_lookup,
    housing_inspections_lookup,
    parcel_lookup,
    permits_lookup,
    physical_impossibility_check,
    resolve_block_lot,
)

TOOL_IMPL = {
    "ccld_facility_lookup": ccld_facility_lookup,
    "resolve_block_lot": resolve_block_lot,
    "parcel_lookup": parcel_lookup,
    "permits_lookup": permits_lookup,
    "business_lookup": business_lookup,
    "housing_inspections_lookup": housing_inspections_lookup,
    "complaints_311_lookup": complaints_311_lookup,
    "evictions_lookup": evictions_lookup,
    "physical_impossibility_check": physical_impossibility_check,
}

TOOL_DEFS = [
    {
        "type": "function",
        "function": {
            "name": "ccld_facility_lookup",
            "description": (
                "Query the California CCLD roster (ArcGIS) for licensed child care "
                "facilities in San Francisco. Filter by name fragment, address prefix, "
                "or minimum capacity. Returns NAME, RES_STREET_ADDR, CAPACITY, STATUS."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Fragment of facility name"},
                    "street_address": {"type": "string", "description": "Address prefix, e.g. '1984 GREAT'"},
                    "capacity_min": {"type": "integer", "description": "Minimum licensed capacity"},
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
                "Compute whether a licensed capacity fits the building. CA Title 22 requires "
                "35 sqft indoor activity space per child. Pass the CCLD capacity and parcel "
                "property_area; returns verdict 'possible' or 'physically_impossible'."
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
]
