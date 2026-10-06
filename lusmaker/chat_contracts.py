"""JSON-schema’s voor de chatadapter; netwerk- en opslagvrij."""

STOP_SCHEMA = {
    "type": "object", "additionalProperties": False, "required": ["soort", "rond_km"],
    "properties": {
        "soort": {"type": "string", "enum": ["cafe", "water", "bakker", "toilet", "fietsenmaker"]},
        "rond_km": {"type": "number", "minimum": 0},
    },
}

PLAN_ROUTE_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["start"],
    "properties": {
        "stop_onderweg": STOP_SCHEMA,
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
        "activiteit": {
            "type": "string",
            "enum": [
                "wandelen", "trail", "wegloop", "stadsfiets", "toerfiets",
                "koersfiets", "gravel", "mtb", "fietsen",
            ],
            "description": "Kies de activiteit die bij de vraag past; 'fietsen' is de oude naam van toerfiets.",
        },
        "geen_opvulling": {"type": "boolean"},
        "heuvels": {
            "type": ["string", "null"], "enum": ["zoek", "ok", "vlak", None],
            "description": "Alleen invullen als de gebruiker heuvels uitdrukkelijk zoekt (zoek), onverschillig is (ok) of vlak wil (vlak).",
        },
        "ondergrond": {
            "type": ["string", "null"], "enum": ["verhard", "ok", "onverhard", None],
            "description": "Alleen invullen als de gebruiker de ondergrond noemt.",
        },
    },
}

ADJUST_ROUTE_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["draft_id"],
    "properties": {
        "startplaats": {"type": "string", "enum": ["0", "1", "2", "3"]},
        "draft_id": {"type": "string", "minLength": 1, "maxLength": 64},
        "voeg_klimmen_toe": {"type": "array", "items": {"type": "string"}, "maxItems": 12},
        "verwijder_klimmen": {"type": "array", "items": {"type": "string"}, "maxItems": 12},
        "vermijd_plaatsen": {"type": "array", "items": {"type": "string"}, "maxItems": 12},
        "niet_meer_vermijden": {"type": "array", "items": {"type": "string"}, "maxItems": 12},
        "sta_plaatsen_toe": {
            "type": "array", "items": {"type": "string"}, "maxItems": 12,
            "description": "Plaatsen of passages waar de gebruiker uitdrukkelijk mee akkoord is.",
        },
        "profiel_naam": {"type": "string", "minLength": 1, "maxLength": 64},
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



def validate_arguments(value, schema, path='arguments'):
    """Valideer het gedeelde beperkte toolschema vóór enige side effect."""
    import math
    kind = schema.get('type')
    kinds = kind if isinstance(kind, list) else [kind]
    types = {'object': isinstance(value, dict), 'array': isinstance(value, list),
             'string': isinstance(value, str), 'boolean': isinstance(value, bool),
             'null': value is None, 'number': isinstance(value, (int,float)) and not isinstance(value,bool) and math.isfinite(value),
             'integer': isinstance(value,int) and not isinstance(value,bool)}
    if kind and not any(types.get(k,False) for k in kinds):
        raise ValueError(f'{path}: ongeldig type')
    if 'enum' in schema and value not in schema['enum']:
        raise ValueError(f'{path}: kies een toegestane waarde')
    if isinstance(value, dict):
        properties = schema.get('properties',{})
        if schema.get('additionalProperties') is False and set(value)-set(properties):
            raise ValueError(f'{path}: onbekende velden {", ".join(sorted(set(value)-set(properties)))}')
        if set(schema.get('required',[]))-set(value):
            raise ValueError(f'{path}: verplichte velden ontbreken')
        for key, child in value.items():
            if key in properties: validate_arguments(child,properties[key],f'{path}.{key}')
    elif isinstance(value, list):
        if len(value)>schema.get('maxItems',1000): raise ValueError(f'{path}: te veel waarden')
        for item in value: validate_arguments(item,schema.get('items',{}),path)
    elif isinstance(value,str):
        if not schema.get('minLength',0)<=len(value)<=schema.get('maxLength',10000): raise ValueError(f'{path}: ongeldige tekstlengte')
    elif isinstance(value,(float,int)) and not isinstance(value,bool):
        if value<schema.get('minimum',-float('inf')) or value>schema.get('maximum',float('inf')) or value<=schema.get('exclusiveMinimum',-float('inf')):
            raise ValueError(f'{path}: getal buiten bereik')

REROUTE_SCHEMA = {"type":"object", "required":["draft_id","lat","lon"], "additionalProperties":False,
    "properties":{"draft_id":{"type":"string","minLength":1,"maxLength":64},
        "lat":{"type":"number","minimum":-90,"maximum":90},"lon":{"type":"number","minimum":-180,"maximum":180},
        "rest_km":{"type":["string","number"]},"expected_revision":{"type":"integer","minimum":0},
        "closure":{"type":"object","required":["lat","lon"],"additionalProperties":False,
                   "properties":{"lat":{"type":"number"},"lon":{"type":"number"}}}}}
