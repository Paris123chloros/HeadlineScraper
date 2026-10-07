"""Strict public JSON decoding; duplicate keys and non-finite numbers are rejected."""

import json

from motorsport_research.championships.common import OfficialDataError


def decode(content: bytes | str):
    def pairs(values):
        result = {}
        for key, value in values:
            if key in result:
                raise OfficialDataError("Duplicate JSON field")
            result[key] = value
        return result

    def constant(value):
        raise OfficialDataError("Non-finite JSON number")

    try:
        return json.loads(content, object_pairs_hook=pairs, parse_constant=constant)
    except (json.JSONDecodeError, RecursionError, UnicodeError) as error:
        raise OfficialDataError("Malformed or excessively nested JSON archive") from error


def fields(values: dict) -> dict[str, str | None]:
    return {key: None if value is None else str(value) for key, value in values.items()}


def quote(values: dict) -> str:
    return json.dumps(values, ensure_ascii=False, sort_keys=True, allow_nan=False)
