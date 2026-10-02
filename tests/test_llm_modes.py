import json

import pytest
from pydantic import BaseModel

from approva import llm
from approva.schemas import ParsedRequest, RequestType


def test_stub_returns_validated_fixture(monkeypatch):
    monkeypatch.setenv("LLM_MODE", "stub")
    parsed, meta = llm.call_structured(
        system="intake", user="<employee_request>Need Figma licenses for 5 designers</employee_request>",
        schema=ParsedRequest, tool_name="submit_parsed_request", model="stub",
    )
    assert parsed.request_type == RequestType.SOFTWARE
    assert parsed.unit_cost_inr == 6300
    assert meta["cached"] is False


def test_unknown_stub_request_fails_closed(monkeypatch):
    monkeypatch.setenv("LLM_MODE", "stub")
    with pytest.raises(llm.ServiceUnavailable):
        llm.call_structured(
            system="intake", user="<employee_request>Unknown request</employee_request>",
            schema=ParsedRequest, tool_name="submit_parsed_request", model="stub",
        )


def test_offline_cache_miss(monkeypatch, tmp_path):
    monkeypatch.setenv("LLM_MODE", "offline")
    with pytest.raises(llm.CacheMiss):
        llm.call_structured(
            system="intake", user="new request", schema=ParsedRequest,
            tool_name="submit_parsed_request", model="cached-model", cache_path=tmp_path / "cache.json",
        )


def test_offline_cache_hit_validates_cached_value(monkeypatch, tmp_path):
    monkeypatch.setenv("LLM_MODE", "offline")
    key = llm.cache_key("intake", "cached request", ParsedRequest, "submit_parsed_request", "cached-model")
    path = tmp_path / "cache.json"
    path.write_text(json.dumps({key: {"request_type": "unknown", "summary": "Cached", "confidence": 0.5}}), encoding="utf-8")
    parsed, meta = llm.call_structured(
        system="intake", user="cached request", schema=ParsedRequest,
        tool_name="submit_parsed_request", model="cached-model", cache_path=path,
    )
    assert parsed.summary == "Cached"
    assert meta["cached"] is True


def test_json_schema_references_are_inlined():
    schema = {
        "type": "object",
        "$defs": {"Child": {"type": "string"}, "Parent": {
            "type": "object", "properties": {"name": {"$ref": "#/$defs/Child"}},
        }},
        "properties": {"child": {"$ref": "#/$defs/Parent"}},
    }
    result = llm.inline_json_schema(schema)
    assert "$defs" not in json.dumps(result)
    assert result["properties"]["child"]["properties"]["name"] == {"type": "string"}