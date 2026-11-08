"""The module runner page is JavaScript and the API is Python, so only these tests keep them in step.

They read the page's own tables (modules, input fields, limits, routes) and compare them with the real
request models, the module list, the replacement defaults and the health markers. When one side changes,
a test here fails and names the field or module that drifted.
"""

from __future__ import annotations

import inspect
import re
from pathlib import Path
from typing import Any, get_args

import pytest
from fastapi.testclient import TestClient

import stockscanner.pip.api as pip_api
from stockscanner.pip.api import HoldingInputs, create_app
from stockscanner.pip.decision_engine import DecisionEngine


ROOT = Path(__file__).resolve().parents[2]


def read(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


CORE = read("pip-modules-core.js")
PAGE = read("pip-modules.js")
SHARED = read("pip-shared.js")
SCHEMA = HoldingInputs.model_json_schema()

# The only requests the page may make: all reads, and one module run that saves nothing.
PAGE_ROUTES = {
    ("GET", "/healthz"),
    ("GET", "/api/pip/portfolios"),
    ("GET", "/api/pip/portfolios/{}/positions"),
    ("POST", "/api/pip/portfolios/{}/modules/{}"),
}


def frozen_table(source: str, name: str) -> list[str]:
    """The lines of `export const NAME = Object.freeze([ ... ]);`, one table entry per line."""
    start = source.index(f"export const {name} = Object.freeze([")
    end = source.index("\n]);", start)
    lines = source[start:end].splitlines()[1:]
    assert lines, f"{name} is empty"
    return lines


def parse_modules() -> list[str]:
    ids = []
    for line in frozen_table(CORE, "PIP_MODULES"):
        found = re.match(r'\s*\{ id: "([a-z_]+)", label: "[^"]+", needs: "[^"]+" \},?\s*$', line)
        assert found, f"cannot read this module line: {line!r}"
        ids.append(found[1])
    return ids


def parse_fields() -> list[dict[str, Any]]:
    fields = []
    for line in frozen_table(CORE, "PIP_MODULE_FIELDS"):
        found = re.match(r"\s*\{ path: \[(?P<path>[^\]]+)\], (?P<rest>.*) \},?\s*$", line)
        assert found, f"cannot read this field line: {line!r}"
        path = re.findall(r'"([a-z_]+)"', found["path"])
        rest = re.sub(r'\b(?:label|help|placeholder): "[^"]*",?\s*', "", found["rest"])
        field: dict[str, Any] = {"path": path, "key": ".".join(path), "positive": "positive: true" in rest}
        for name in ("type", "scope", "group", "value"):
            match = re.search(rf'\b{name}: "([^"]*)"', rest)
            field[name] = match[1] if match else None
        for name in ("min", "max"):
            match = re.search(rf"\b{name}: (-?\d+(?:\.\d+)?)", rest)
            field[name] = float(match[1]) if match else None
        fields.append(field)
    return fields


def js_constant(name: str) -> int:
    found = re.search(rf"export const {name} = (\d+);", CORE)
    assert found, f"{name} is not defined in pip-modules-core.js"
    return int(found[1])


def resolve(node: dict[str, Any]) -> dict[str, Any]:
    """Follow `$ref` and unwrap `X | None` so constraints can be read off the real type."""
    while True:
        if "$ref" in node:
            node = SCHEMA["$defs"][node["$ref"].rsplit("/", 1)[-1]]
            continue
        options = [option for option in node.get("anyOf", []) if option.get("type") != "null"]
        if len(options) == 1:
            outer = {key: value for key, value in node.items() if key != "anyOf"}
            node = {**options[0], **outer}
            continue
        return node


def api_property(path: list[str]) -> dict[str, Any]:
    node = SCHEMA
    for step in path:
        properties = resolve(node)["properties"]
        assert step in properties, f"the API has no request field {'.'.join(path)}"
        node = properties[step]
    return resolve(node)


def page_lower(field: dict[str, Any]) -> tuple[float, bool] | None:
    if field["positive"]:
        return 0.0, True
    return (field["min"], False) if field["min"] is not None else None


def page_upper(field: dict[str, Any]) -> tuple[float, bool] | None:
    return (field["max"], False) if field["max"] is not None else None


def api_lower(prop: dict[str, Any]) -> tuple[float, bool] | None:
    if "exclusiveMinimum" in prop:
        return float(prop["exclusiveMinimum"]), True
    return (float(prop["minimum"]), False) if "minimum" in prop else None


def api_upper(prop: dict[str, Any]) -> tuple[float, bool] | None:
    if "exclusiveMaximum" in prop:
        return float(prop["exclusiveMaximum"]), True
    return (float(prop["maximum"]), False) if "maximum" in prop else None


def page_is_inside(page: tuple[float, bool] | None, api: tuple[float, bool] | None, *, lower: bool) -> bool:
    """True when every value the page lets through is also within the API's limit."""
    if api is None:
        return True
    if page is None:
        return False
    (page_value, page_exclusive), (api_value, api_exclusive) = page, api
    if page_value != api_value:
        return page_value > api_value if lower else page_value < api_value
    return page_exclusive or not api_exclusive


def body_with(field: dict[str, Any], value: Any) -> dict[str, Any]:
    body: dict[str, Any] = {"symbol": "AAA"}
    node = body
    for step in field["path"][:-1]:
        node = node.setdefault(step, {})
    node[field["path"][-1]] = value
    return body


def edge_values(field: dict[str, Any]) -> list[Any]:
    if field["type"] == "date":
        return ["2026-01-02"]
    if field["type"] == "candidates":
        return [[{"symbol": "AAA", "score": 0.0}, {"symbol": "BBB", "score": 100.0}]]
    values = [value for value in (field["min"], field["max"]) if value is not None]
    if field["positive"]:
        values.append(0.01)
    return values or [-1.5, 0.0, 2.5]


def page_paths() -> set[str]:
    literals = re.findall(r'["`](/(?:healthz|api/pip)[^"`]*)["`]', PAGE)
    return {re.sub(r"\$\{[^}]*\}", "{}", literal) for literal in literals}


def build_app():
    def no_database(url, key):
        raise AssertionError("these checks must not reach the database")

    return create_app(
        client_factory=no_database,
        environ={"SUPABASE_URL": "https://project.example.test", "SUPABASE_PUBLISHABLE_KEY": "public-test-key"},
    )


FIELDS = parse_fields()
FIELD_IDS = [field["key"] for field in FIELDS]


def test_the_page_tables_were_read():
    assert len(parse_modules()) == len(set(parse_modules()))
    assert len(FIELDS) == len(set(FIELD_IDS))
    assert FIELDS and parse_modules()


def test_the_pages_modules_are_the_apis_modules_in_the_same_order():
    assert parse_modules() == list(get_args(pip_api.ModuleName))


@pytest.mark.parametrize("field", FIELDS, ids=FIELD_IDS)
def test_each_page_field_exists_in_the_api_with_the_same_kind_of_value(field):
    prop = api_property(field["path"])
    if field["type"] == "number":
        assert prop["type"] == "number"
    elif field["type"] == "date":
        assert (prop["type"], prop.get("format")) == ("string", "date")
    elif field["type"] == "candidates":
        assert prop["type"] == "array"
        assert set(resolve(prop["items"])["properties"]) == {"symbol", "score"}
    else:
        pytest.fail(f"{field['key']} has the unknown type {field['type']!r}")


@pytest.mark.parametrize("field", FIELDS, ids=FIELD_IDS)
def test_the_page_never_lets_through_a_value_the_api_would_reject(field):
    if field["type"] != "number":
        pytest.skip("only numbers have limits")
    prop = api_property(field["path"])
    assert page_is_inside(page_lower(field), api_lower(prop), lower=True), f"{field['key']} lower limit"
    assert page_is_inside(page_upper(field), api_upper(prop), lower=False), f"{field['key']} upper limit"


@pytest.mark.parametrize("field", FIELDS, ids=FIELD_IDS)
def test_values_at_the_pages_limits_pass_the_real_request_model(field):
    for value in edge_values(field):
        HoldingInputs.model_validate(body_with(field, value))


def test_every_prefilled_value_is_the_apis_default():
    prefilled = [field for field in FIELDS if field["value"] is not None]
    assert prefilled, "the page no longer prefills anything; check the required-return default"
    for field in prefilled:
        assert float(field["value"]) == api_property(field["path"])["default"], field["key"]


def test_the_candidate_and_replacement_limits_match_the_api():
    assert js_constant("MAX_MODULE_CANDIDATES") == api_property(["peer_scores"])["maxItems"]
    default = inspect.signature(DecisionEngine.analyze_position).parameters["replacement_limit"].default
    assert js_constant("REPLACEMENT_LIMIT") == default


def test_the_symbol_pattern_is_the_apis_symbol_pattern():
    found = re.search(r"export const PIP_SYMBOL_PATTERN = /(.+)/;", SHARED)
    assert found and found[1] == pip_api.SYMBOL_PATTERN.pattern


def test_the_page_calls_only_the_read_routes_and_the_api_has_all_of_them():
    assert page_paths() == {path for _, path in PAGE_ROUTES}
    routes = {
        (method, re.sub(r"\{[^}]*\}", "{}", route.path))
        for route in build_app().routes
        for method in getattr(route, "methods", None) or ()
    }
    assert PAGE_ROUTES <= routes


def test_the_health_markers_the_page_requires_are_advertised():
    markers = sorted(re.findall(r"health\.(\w+) !== 1", PAGE))
    assert markers == ["module_runner", "positions_list"]
    health = TestClient(build_app()).get("/healthz").json()
    assert health["service"] == "pip"
    for marker in markers:
        assert health[marker] == 1


def test_the_page_is_gated_linked_and_published():
    page = read("pip-modules.html")
    assert 'src="/StockScanner/auth.js"' in page
    assert "data-stockscanner-pip-api" in page
    assert '["Portfolio intelligence", "PIP module runner", "pip-modules.html"]' in read("auth.js")
    assert "/StockScanner/pip-modules.html" in read("portfolio-intelligence.html")

    workflow = read(".github/workflows/scan.yml")
    imported = {
        name
        for script in ("pip-modules.js", "pip-modules-core.js", "pip-dashboard.js", "pip-shared.js")
        for name in re.findall(r'from "\./([\w.-]+\.js)"', read(script))
    }
    for name in sorted({"pip-modules.html", "pip-modules.js", *imported}):
        assert f'- "{name}"' in workflow, f"{name} is missing from the scan.yml push paths"
