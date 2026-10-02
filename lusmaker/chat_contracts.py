"""JSON-schema’s voor de chatadapter; netwerk- en opslagvrij."""

PLAN_ROUTE_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["start"],
    "properties": {
        "start": {"type": "string", "minLength": 1, "maxLength": 160},
        "rond_plaats": {"type": "string", "minLength": 1, "maxLength": 160},
        "langs_water": {"type": "string", "minLength": 1, "maxLength": 120},
        "target_km": {"type": "number", "exclusiveMinimum": 0},
        "max_km": {"type": "number", "exclusiveMinimum": 0},
        "tolerance_km": {"type": "number", "minimum": 0},
        "doel": {"type": "string", "enum": ["hoogtemeters", "offroad", "kort", "toeren"]},
        "via_klimmen": {"type": "array", "items": {"type": "string"}, "maxItems": 12},
        "vermijd_plaatsen": {"type": "array", "items": {"type": "string"}, "maxItems": 12},
        "kasseien": {"type": ["boolean", "null"]},
        "beton_vermijden": {"type": ["boolean", "null"]},
        "autovrij": {"type": ["boolean", "null"]},
        "strict": {"type": ["boolean", "null"]},
        "naam": {
            "type": "string",
            "minLength": 1,
            "maxLength": 80,
            "description": (
                "Korte natuurlijke titel die de volledige routevraag samenvat, "
                "zoals 'Heuvelrit rond Wetteren · 38 km'."
            ),
        },
        "activiteit": {"type": "string", "enum": ["fietsen", "trail"]},
        "geen_opvulling": {"type": "boolean"},
    },
}

ADJUST_ROUTE_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["draft_id"],
    "properties": {
        "draft_id": {"type": "string", "minLength": 1, "maxLength": 64},
        "voeg_klimmen_toe": {"type": "array", "items": {"type": "string"}, "maxItems": 12},
        "verwijder_klimmen": {"type": "array", "items": {"type": "string"}, "maxItems": 12},
        "vermijd_plaatsen": {"type": "array", "items": {"type": "string"}, "maxItems": 12},
        "niet_meer_vermijden": {"type": "array", "items": {"type": "string"}, "maxItems": 12},
        "target_km": {"type": "number", "exclusiveMinimum": 0},
        "max_km": {"type": "number", "exclusiveMinimum": 0},
        "tolerance_km": {"type": "number", "minimum": 0},
        "doel": {"type": "string", "enum": ["hoogtemeters", "offroad", "kort", "toeren"]},
        "rond_plaats": {"type": "string", "minLength": 1, "maxLength": 160},
        "langs_water": {"type": "string", "minLength": 1, "maxLength": 120},
        "geen_opvulling": {"type": "boolean"},
        "expected_revision": {"type": "integer", "minimum": 0},
    },
}

