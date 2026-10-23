"""接口契约校验（jsonschema）。"""
import jsonschema

SCHEMA = {"type": "object", "properties": {"ok": {"type": "boolean"}}}


def validate(obj) -> None:
    jsonschema.validate(obj, SCHEMA)
