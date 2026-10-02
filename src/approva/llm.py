"""Structured Anthropic calls with stub and replayable offline modes."""

from __future__ import annotations

import copy
import hashlib
import json
import threading
import time
from pathlib import Path

import anthropic
from pydantic import BaseModel, ValidationError

from approva import config


class ServiceUnavailable(RuntimeError):
    """Raised when the configured language model service cannot be reached."""


class CacheMiss(RuntimeError):
    """Raised when offline mode has no response for a structured-call key."""


class LLMStructuredError(RuntimeError):
    """Raised when the model fails to return valid forced-tool output."""


_CACHE_LOCK = threading.RLock()
_CACHE_DATA: dict[str, dict] = {}


def cache_key(system: str, user: str, schema: type[BaseModel], tool_name: str, model: str) -> str:
    """Return the deterministic cache key for a structured model call."""
    payload = f"{model}|{tool_name}|{system}|{user}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def inline_json_schema(schema: dict) -> dict:
    """Inline local JSON Schema references and remove the `$defs` section."""
    root = copy.deepcopy(schema)

    def resolve(value: object, trail: tuple[str, ...] = ()) -> object:
        if isinstance(value, list):
            return [resolve(item, trail) for item in value]
        if not isinstance(value, dict):
            return value
        reference = value.get("$ref")
        if reference:
            if not reference.startswith("#/"):
                raise ValueError(f"Unsupported external schema reference: {reference}")
            if reference in trail:
                raise ValueError(f"Recursive schema reference is not supported: {reference}")
            target: object = root
            for part in reference[2:].split("/"):
                target = target[part.replace("~1", "/").replace("~0", "~")]
            expanded = resolve(copy.deepcopy(target), (*trail, reference))
            siblings = {key: val for key, val in value.items() if key != "$ref"}
            if siblings and isinstance(expanded, dict):
                expanded.update(resolve(siblings, trail))
            return expanded
        return {key: resolve(val, trail) for key, val in value.items() if key != "$defs"}

    return resolve(root)


def _cache_file(path: str | Path | None) -> Path:
    """Return the requested or default cache file path."""
    return Path(path) if path else config.data_path("fixtures", "llm_cache.json")


def _cache_load(path: Path) -> dict[str, dict]:
    """Load a cache file on first use for each path."""
    with _CACHE_LOCK:
        key = str(path.resolve())
        if key not in _CACHE_DATA:
            if path.exists():
                with path.open(encoding="utf-8") as cache_file:
                    _CACHE_DATA[key] = json.load(cache_file)
            else:
                _CACHE_DATA[key] = {}
        return _CACHE_DATA[key]


def _cache_put(path: Path, key: str, value: dict) -> None:
    """Atomically persist one model response to the cache."""
    with _CACHE_LOCK:
        cache = _cache_load(path)
        cache[key] = value
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(path.suffix + ".tmp")
        with temporary.open("w", encoding="utf-8") as cache_file:
            json.dump(cache, cache_file, ensure_ascii=False, sort_keys=True, indent=2)
        temporary.replace(path)


def _is_service_error(error: Exception) -> bool:
    """Return whether an Anthropic exception represents a transient outage."""
    return isinstance(error, (
        anthropic.APIConnectionError, anthropic.APITimeoutError, anthropic.RateLimitError,
    )) or (isinstance(error, anthropic.APIStatusError) and error.status_code >= 500)


def call_structured(
    *,
    system: str,
    user: str,
    schema: type[BaseModel],
    tool_name: str,
    model: str,
    max_tokens: int = 2000,
    cache_path: str | Path | None = None,
    client=None,
) -> tuple[BaseModel, dict]:
    """Call a forced-tool model or a configured deterministic cache mode."""
    key = cache_key(system, user, schema, tool_name, model)
    mode = config.llm_mode()
    cache_path = _cache_file(cache_path)
    cache = _cache_load(cache_path)
    if mode == "stub":
        from approva.stub_fixtures import get_stub_response

        return get_stub_response(schema, user), {
            "latency_ms": 0, "tokens_in": 0, "tokens_out": 0, "cached": False,
        }
    if mode in ("offline", "replay") and key in cache:
        return schema.model_validate(cache[key]), {
            "latency_ms": 0, "tokens_in": 0, "tokens_out": 0, "cached": True,
        }
    if mode == "offline":
        raise CacheMiss(key)
    if mode not in ("live", "replay"):
        raise ValueError(f"Unsupported LLM_MODE: {mode}")

    sdk = client or anthropic.Anthropic(timeout=30)
    tool = {
        "name": tool_name,
        "description": f"Return the {tool_name} result.",
        "input_schema": inline_json_schema(schema.model_json_schema()),
    }
    messages = [{"role": "user", "content": user}]
    started = time.perf_counter()
    last_validation: ValidationError | None = None
    for attempt in range(2):
        try:
            response = sdk.messages.create(
                model=model, max_tokens=max_tokens, system=system, tools=[tool],
                tool_choice={"type": "tool", "name": tool_name}, messages=messages,
            )
        except Exception as error:
            if _is_service_error(error):
                if attempt == 1:
                    raise ServiceUnavailable(str(error)) from error
                continue
            raise
        block = next((part for part in response.content if part.type == "tool_use"), None)
        if block is None:
            raise LLMStructuredError(f"No tool result returned for {tool_name}")
        try:
            parsed = schema.model_validate(block.input)
            _cache_put(cache_path, key, block.input)
            elapsed = int((time.perf_counter() - started) * 1000)
            return parsed, {
                "latency_ms": elapsed,
                "tokens_in": response.usage.input_tokens,
                "tokens_out": response.usage.output_tokens,
                "cached": False,
            }
        except ValidationError as error:
            last_validation = error
            messages.extend([
                {"role": "assistant", "content": response.content},
                {"role": "user", "content": [{
                    "type": "tool_result", "tool_use_id": block.id, "is_error": True,
                    "content": f"Validation failed: {error}. Call the tool again with corrected input.",
                }]},
            ])
    raise LLMStructuredError(f"Invalid structured output for {tool_name}: {last_validation}")