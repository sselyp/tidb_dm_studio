#!/usr/bin/env python3
"""Contract CI checks for the TiDB DM OpenAPI spec (reviewer gate assertions).

Usage: python check_contract.py <openapi.yaml>
Exits non-zero on any violation.
"""
import json
import os
import re
import sys
import yaml

RESERVED_NAME_SEGMENTS = {"schema", "validate", "precheck", "state", "status", "logs", "yaml"}
NAME_PATTERN = r"^[a-zA-Z0-9_-]{1,64}$"


def fail(msg):
    print(f"FAIL: {msg}")
    return 1


def check_error_code_prefix(doc):
    problems = 0
    for c in doc.get("x-error-codes", []):
        code = str(c["code"])
        if code[:3] != str(c["http"]):
            problems += fail(f"code {code} ({c['name']}) prefix != http {c['http']}")
    return problems


def check_no_top_level_errors(doc):
    problems = 0
    envelope = doc["components"]["schemas"]["Envelope"]
    keys = set(envelope["properties"].keys())
    if keys != {"code", "data", "message"}:
        problems += fail(f"Envelope keys must be exactly code/data/message, got {sorted(keys)}")
    # Only envelope-shaped schemas (allOf includes Envelope) may not expose top-level 'errors'.
    for name, sch in doc["components"]["schemas"].items():
        branches = sch.get("allOf", []) or []
        is_envelope = any(b.get("$ref", "").endswith("/Envelope") for b in branches)
        if is_envelope and "errors" in (sch.get("properties") or {}):
            problems += fail(f"envelope schema {name} exposes top-level 'errors'")
        for branch in branches:
            if is_envelope and "errors" in (branch.get("properties") or {}):
                problems += fail(f"envelope schema {name} allOf branch exposes top-level 'errors'")
    return problems


def _precheck_codes(doc):
    out = []
    for item in doc.get("x-precheck-codes", []):
        out.append(item["code"] if isinstance(item, dict) else item)
    return out


def check_field_codes_registered(doc):
    """G2 gate: FieldError.errorCode must carry an enum matching the registries."""
    problems = 0
    registry = set(doc.get("x-field-error-codes", []))
    precheck = set(_precheck_codes(doc))
    if not registry:
        problems += fail("x-field-error-codes registry is empty")
    if not precheck:
        problems += fail("x-precheck-codes registry is empty")
    code_prop = doc["components"]["schemas"]["FieldError"]["properties"]["errorCode"]
    enum = code_prop.get("enum")
    if not enum:
        return problems + fail("FieldError.errorCode.enum missing (G2 gate)")
    expected = registry | precheck
    if set(enum) != expected:
        problems += fail(
            "FieldError.errorCode.enum != registries; "
            f"missing={sorted(expected - set(enum))} extra={sorted(set(enum) - expected)}"
        )
    return problems


def check_required_field_codes(doc):
    """G2 gate (pinned by name): codes frozen by the architecture must be present
    in x-field-error-codes, so a consistent deletion (registry + enum together)
    cannot silently drop a code."""
    required = _load_manifest().get("requiredFieldCodes") or []
    if not required:
        return 0
    registry = set(doc.get("x-field-error-codes", []))
    problems = 0
    for code in required:
        if code not in registry:
            problems += fail(f"required field code {code} missing from x-field-error-codes")
    return problems


def check_etag_exposed(doc):
    problems = 0
    for resp_name in ("DataSourceItem", "TaskItem"):
        headers = doc["components"]["responses"][resp_name].get("headers", {})
        if "ETag" not in headers:
            problems += fail(f"response {resp_name} missing ETag header")
    for name in ("Task", "DataSource"):
        props = doc["components"]["schemas"][name].get("properties", {})
        if "etag" in props:
            problems += fail(f"schema {name} must not embed 'etag' in body")
    return problems


def iter_responses(doc):
    for path, item in doc["paths"].items():
        for method, op in item.items():
            if method in {"parameters", "get", "put", "post", "delete", "patch"} and isinstance(op, dict):
                for status in op.get("responses", {}):
                    yield path, method, str(status)


def check_http_codes_used(doc):
    used = {s for _, _, s in iter_responses(doc)}
    problems = 0
    for c in doc.get("x-error-codes", []):
        if str(c["http"]) not in used:
            problems += fail(f"HTTP {c['http']} ({c['name']}) declared but never used by any operation")
    return problems


def check_static_routes(doc):
    problems = 0
    for path in doc["paths"]:
        parts = path.strip("/").split("/")
        for i, seg in enumerate(parts):
            if seg == "{name}" and i + 1 < len(parts):
                # {name} must be terminal-ish; literal children allowed only as sub-resources
                continue
            if seg == "tasks" and i + 1 < len(parts) and parts[i + 1] != "{name}":
                problems += fail(f"literal segment under /tasks/ collides with {{name}}: {path}")
    # reserved words must not be valid task names under the pattern used for {name}
    pat = doc["components"]["parameters"]["NamePath"]["schema"]["pattern"]
    if pat != NAME_PATTERN:
        problems += fail(f"NamePath pattern {pat!r} != expected {NAME_PATTERN!r}")
    reserved_hits = [r for r in RESERVED_NAME_SEGMENTS if re.fullmatch(NAME_PATTERN, r)]
    if not reserved_hits:
        return fail("reserved-name guard is vacuous (no reserved word matches pattern)")
    return problems


def check_oneof_write(doc):
    problems = 0
    tw = doc["components"]["schemas"]["TaskWrite"]
    if "oneOf" not in tw:
        problems += fail("TaskWrite must use oneOf (config XOR rawYaml)")
    return problems


def check_namepath_responses(doc):
    """Every operation under a {name} path must declare 404 and 400 (reserved/charset rejection)."""
    problems = 0
    methods = {"get", "put", "post", "delete", "patch"}
    for path, item in doc["paths"].items():
        if "/{name}" not in path:
            continue
        for method, op in item.items():
            if method not in methods or not isinstance(op, dict):
                continue
            codes = {str(c) for c in op.get("responses", {})}
            if "404" not in codes:
                problems += fail(f"{method.upper()} {path} missing 404")
            if "400" not in codes:
                problems += fail(f"{method.upper()} {path} missing 400 (reserved/charset name rejection)")
    return problems


def _has_param(op, ref_suffix):
    for p in op.get("parameters", []) or []:
        if p.get("$ref", "").endswith(ref_suffix):
            return True
    return False


def check_csrf(doc):
    """state-changing ops (except /login) must enforce CSRF: X-CSRF-Token + 403 + 40303 registered."""
    problems = 0
    scheme = doc["components"]["securitySchemes"].get("cookieAuth", {})
    if scheme.get("name") != "dm_session":
        problems += fail("cookieAuth.name must be dm_session")
    names = {c["name"] for c in doc.get("x-error-codes", [])}
    if "E_CSRF_FAILED" not in names:
        problems += fail("E_CSRF_FAILED not registered in x-error-codes")
    for path, item in doc["paths"].items():
        for method, op in item.items():
            if method not in {"post", "put", "delete", "patch"} or not isinstance(op, dict):
                continue
            if path == "/login":
                continue
            if not _has_param(op, "/parameters/CsrfToken"):
                problems += fail(f"{method.upper()} {path} missing X-CSRF-Token parameter")
            if "403" not in {str(c) for c in op.get("responses", {})}:
                problems += fail(f"{method.upper()} {path} missing 403 (CSRF/enumeration)")
    return problems


def check_me_endpoint(doc):
    problems = 0
    me = doc["paths"].get("/me", {}).get("get")
    if not me:
        return fail("GET /me is required (route guard / mustChangePassword)")
    if "401" not in {str(c) for c in me.get("responses", {})}:
        problems += fail("GET /me must declare 401")
    me_data = doc["components"]["schemas"]["MeData"]
    for bad in ("password", "passwordHash", "oldPassword", "newPassword"):
        if bad in (me_data.get("properties") or {}):
            problems += fail(f"MeData must not contain '{bad}'")
    if set(me_data.get("required", [])) != {"username", "mustChangePassword"}:
        problems += fail("MeData required must be [username, mustChangePassword]")
    return problems


def check_login_lock(doc):
    problems = 0
    names = {c["name"] for c in doc.get("x-error-codes", [])}
    if "E_INVALID_CREDENTIALS" not in names:
        problems += fail("E_INVALID_CREDENTIALS not registered")
    if "E_ACCOUNT_LOCKED" not in names:
        problems += fail("E_ACCOUNT_LOCKED (42902) not registered")
    if any(str(c["http"]) == "423" for c in doc.get("x-error-codes", [])):
        problems += fail("must not use HTTP 423 (WebDAV semantics)")
    # 429 responses must be TooManyRequests with Retry-After
    tmr = doc["components"]["responses"].get("TooManyRequests", {})
    if "Retry-After" not in (tmr.get("headers") or {}):
        problems += fail("TooManyRequests response missing Retry-After header")
    for path in ("/login", "/password"):
        op = doc["paths"].get(path, {}).get("post", {})
        ref = (op.get("responses", {}).get("429") or {}).get("$ref", "")
        if not ref.endswith("/TooManyRequests"):
            problems += fail(f"POST {path} 429 must reference TooManyRequests (Retry-After)")
    return problems


def check_precheck_codes(doc):
    if not doc.get("x-precheck-codes"):
        return fail("x-precheck-codes registry is empty")
    for item in doc["x-precheck-codes"]:
        if not isinstance(item, dict) or "code" not in item or "rule" not in item:
            return fail("each x-precheck-codes entry needs {code, rule}")
    return 0


def check_config_storage(doc):
    storage = doc.get("x-config-storage") or {}
    if storage.get("mode") not in {"materialized", "sparse"}:
        return fail("x-config-storage.mode must be materialized or sparse (documented decision)")
    return 0


def check_state_enum_consistent(doc):
    """TaskSummary.state and TaskStatusData.state must share the same stable enum."""
    problems = 0
    summary = doc["components"]["schemas"]["TaskSummary"]["properties"].get("state", {})
    status = doc["components"]["schemas"]["TaskStatusData"]["properties"].get("state", {})
    if not summary.get("enum"):
        problems += fail("TaskSummary.state must declare an enum (list view)")
    if summary.get("enum") != status.get("enum"):
        problems += fail("TaskSummary.state enum != TaskStatusData.state enum")
    if "status" in doc["components"]["schemas"]["TaskSummary"]["properties"]:
        problems += fail("TaskSummary must not expose a separate 'status' field")
    return problems


def check_task_config_isomorphic(doc):
    """Write TaskConfig and read Task.sources must use the same SourceInstance schema."""
    problems = 0
    schemas = doc["components"]["schemas"]
    cfg = schemas["TaskConfig"]
    cfg_sources = cfg["properties"]["sources"]
    if cfg_sources.get("minItems") != 1:
        problems += fail("TaskConfig.sources.minItems must be 1")
    ref = cfg_sources["items"].get("$ref", "")
    if not ref.endswith("/SourceInstance"):
        problems += fail("TaskConfig.sources.items must be SourceInstance")
    read_sources = schemas["Task"]["properties"]["sources"]
    if read_sources["items"].get("$ref", "") != ref:
        problems += fail("Task.sources.items must match TaskConfig.sources.items")
    if read_sources.get("readOnly") is not True:
        problems += fail("Task.sources must be readOnly (derived projection, not independently writable)")
    for w in ("TaskConfigWrite", "TaskConfigUpdate"):
        if schemas[w]["properties"]["config"].get("$ref", "") != "#/components/schemas/TaskConfig":
            problems += fail(f"{w}.config must be TaskConfig")
        if "sources" in (schemas[w].get("properties") or {}):
            problems += fail(f"{w} must not expose top-level 'sources' (write via config.sources)")
    return problems


# Required operations / per-operation statuses live in the versioned manifest
# scripts/ci/contract_manifest.json (consumed by check_manifest), so adding a new
# legitimate endpoint never gets false-killed by a completeness check.


def _codes(op):
    return {str(c) for c in op.get("responses", {})}


def _find_param(op, name):
    for p in op.get("parameters", []) or []:
        if p.get("$ref"):
            continue
        if p.get("name") == name:
            return p
    return None


def _load_manifest():
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "contract_manifest.json")
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def check_manifest(doc):
    """Versioned manifest = required operation set + per-operation required statuses/headers.

    Manifest is a *required subset* of the spec: every manifest op must exist and
    declare its statuses, but a newly added (unlisted) operation is NOT flagged —
    otherwise adding a legitimate endpoint would be a false positive. Deleting or
    downgrading a listed op/status still fails.
    """
    problems = 0
    manifest = _load_manifest()
    mver = str(manifest.get("version"))
    if mver != str(doc["info"]["version"]):
        problems += fail(f"manifest.version {mver} != info.version {doc['info']['version']}")
    spec_ops = {}
    for path, item in doc["paths"].items():
        for method, op in item.items():
            if method not in {"get", "put", "post", "delete", "patch"} or not isinstance(op, dict):
                continue
            oid = op.get("operationId")
            if oid:
                spec_ops[oid] = (path, method, op)
    manifest_ids = set()
    for entry in manifest.get("operations", []):
        oid = entry.get("operationId")
        if oid in manifest_ids:
            problems += fail(f"manifest duplicate operationId {oid}")
            continue
        manifest_ids.add(oid)
        if oid not in spec_ops:
            problems += fail(f"required operation {oid} missing from spec")
            continue
        path, method, op = spec_ops[oid]
        if (path, method) != (entry.get("path"), entry.get("method")):
            problems += fail(
                f"manifest {oid} path/method {entry.get('path')}/{entry.get('method')} != spec {path}/{method}"
            )
        have = {int(c) for c in op.get("responses", {})}
        for need in sorted({int(s) for s in entry.get("statuses", [])} - have):
            problems += fail(f"{method.upper()} {path} ({oid}) missing required status {need}")
    for resp, headers in (manifest.get("responseHeaders") or {}).items():
        r = doc["components"]["responses"].get(resp)
        if not isinstance(r, dict):
            problems += fail(f"manifest responseHeaders references missing response {resp}")
            continue
        have = r.get("headers") or {}
        for h in headers:
            if h not in have:
                problems += fail(f"response {resp} missing required header {h}")
    return problems


def check_write_mutex_codes(doc):
    """Server must disambiguate oneOf: both → 42203, neither → 42204, else → 42201."""
    problems = 0
    for name in ("TaskWrite", "TaskUpdateWrite"):
        desc = doc["components"]["schemas"][name].get("description") or ""
        for tok in ("E_PARAM_MUTUALLY_EXCLUSIVE", "E_PARAM_REQUIRED_ONE"):
            if tok not in desc:
                problems += fail(f"{name}.description must state {tok} (server disambiguates oneOf)")
    return problems


def check_ifmatch_binding(doc):
    """Any op referencing IfMatch must declare both 412 and 428 (per-operation binding)."""
    problems = 0
    for path, item in doc["paths"].items():
        for method, op in item.items():
            if method not in {"get", "put", "post", "delete", "patch"} or not isinstance(op, dict):
                continue
            if _has_param(op, "/parameters/IfMatch"):
                codes = _codes(op)
                for need in ("412", "428"):
                    if need not in codes:
                        problems += fail(f"{method.upper()} {path} references IfMatch but missing {need}")
    return problems


def check_precondition_etag(doc):
    """Every 412 response must expose an ETag header (spec §5.2)."""
    problems = 0
    pcf = doc["components"]["responses"].get("PreconditionFailed", {})
    if "ETag" not in (pcf.get("headers") or {}):
        problems += fail("PreconditionFailed response missing ETag header")
    for path, item in doc["paths"].items():
        for method, op in item.items():
            if method not in {"get", "put", "post", "delete", "patch"} or not isinstance(op, dict):
                continue
            resp = (op.get("responses", {}) or {}).get("412")
            if not isinstance(resp, dict):
                continue
            if resp.get("headers", {}).get("ETag"):
                continue
            if resp.get("$ref", "").endswith("/PreconditionFailed") and "ETag" in (pcf.get("headers") or {}):
                continue
            problems += fail(f"{method.upper()} {path} 412 response missing ETag header")
    return problems


def check_version_description(doc):
    """info.description version token must equal info.version (no drift)."""
    version = str(doc["info"]["version"])
    desc = doc["info"].get("description") or ""
    m = re.search(r"v(\d+\.\d+\.\d+)", desc)
    if not m:
        return fail("info.description must state a version token like v0.9.1")
    if m.group(1) != version:
        return fail(f"info.description version v{m.group(1)} != info.version {version}")
    return 0


def _resolve_param(doc, p):
    ref = p.get("$ref", "")
    if ref.startswith("#/components/parameters/"):
        return doc["components"]["parameters"].get(ref.rsplit("/", 1)[-1], {})
    return p


def check_idempotency_optional(doc):
    """Idempotent target-state PUT must expose Idempotency-Key with required:false."""
    op = (doc["paths"].get("/tasks/{name}/state") or {}).get("put")
    if not isinstance(op, dict):
        return fail("PUT /tasks/{name}/state is required")
    p = None
    for cand in op.get("parameters", []) or []:
        rp = _resolve_param(doc, cand)
        if rp.get("name") == "Idempotency-Key":
            p = rp
            break
    if p is None:
        return fail("/tasks/{name}/state must define Idempotency-Key")
    if p.get("required") is not False:
        return fail("/tasks/{name}/state Idempotency-Key must be required:false")
    return 0


def check_diagnostic_endpoints(doc):
    """D12-b: /task-validate & /task-precheck stay 200-only; /datasources/test keeps 422 (SSRF reject)."""
    problems = 0
    for path in ("/task-validate", "/task-precheck"):
        op = (doc["paths"].get(path) or {}).get("post")
        if not isinstance(op, dict):
            problems += fail(f"POST {path} is required")
            continue
        if "422" in _codes(op):
            problems += fail(f"{path} is diagnostic and must stay 200-only (no 422)")
    t = (doc["paths"].get("/datasources/test") or {}).get("post")
    if not isinstance(t, dict):
        problems += fail("POST /datasources/test is required")
    elif "422" not in _codes(t):
        problems += fail("/datasources/test must declare 422 (policy/SSRF reject never 200)")
    return problems


def check_diagnostic_required_fields(doc):
    """Diagnostic payloads must always carry valid + errors (errors == [] when valid)."""
    problems = 0
    for schema in ("ValidationData", "ConnectivityResult"):
        req = set(doc["components"]["schemas"][schema].get("required") or [])
        for field in ("valid", "errors"):
            if field not in req:
                problems += fail(f"{schema}.required must include '{field}'")
    return problems


def check_diagnostic_codes(doc):
    """Upstream failures live in the diagnostic registry; retired 50202/50203 must not return."""
    problems = 0
    codes = {c.get("code") for c in doc.get("x-precheck-codes", []) if isinstance(c, dict)}
    for need in ("E_SOURCE_UNREACHABLE", "E_TARGET_AUTH_FAILED"):
        if need not in codes:
            problems += fail(f"x-precheck-codes must register {need}")
    all_codes = codes | {c.get("code") for c in doc.get("x-error-codes", [])}
    for retired in (50202, 50203):
        if retired in all_codes:
            problems += fail(f"retired code {retired} must not be re-introduced")
    return problems


def check_precheck_description(doc):
    """502 wording on /task-precheck must stay scoped to the dm-master control plane."""
    op = (doc["paths"].get("/task-precheck") or {}).get("post")
    if not isinstance(op, dict):
        return fail("POST /task-precheck is required")
    desc = op.get("description") or ""
    if re.search(r"失败回\s*502", desc):
        return fail("/task-precheck must not claim upstream failure returns 502 (control-plane only)")
    if "控制面" not in desc:
        return fail("/task-precheck description must scope 502 to the dm-master control plane")
    return 0


def check_502_scope(doc):
    """O3: 502 is reserved for DM control-plane unavailability only."""
    codes = [c for c in doc.get("x-error-codes", []) if str(c["http"]) == "502"]
    names = {c["name"] for c in codes}
    if names != {"E_DM_UNAVAILABLE"}:
        return fail(f"only E_DM_UNAVAILABLE may be HTTP 502; got {sorted(names)}")
    return 0


def check_healthz_public(doc):
    hz = (doc["paths"].get("/healthz") or {}).get("get")
    if not hz:
        return fail("GET /healthz is required (unauthenticated allowlist)")
    if hz.get("security") != []:
        return fail("GET /healthz must set security: [] (unauthenticated)")
    return 0


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else "api/openapi.yaml"
    with open(path, encoding="utf-8") as fh:
        doc = yaml.safe_load(fh)
    checks = [
        check_error_code_prefix,
        check_no_top_level_errors,
        check_field_codes_registered,
        check_required_field_codes,
        check_etag_exposed,
        check_http_codes_used,
        check_static_routes,
        check_oneof_write,
        check_namepath_responses,
        check_csrf,
        check_me_endpoint,
        check_login_lock,
        check_precheck_codes,
        check_config_storage,
        check_state_enum_consistent,
        check_task_config_isomorphic,
        check_manifest,
        check_write_mutex_codes,
        check_ifmatch_binding,
        check_precondition_etag,
        check_version_description,
        check_idempotency_optional,
        check_diagnostic_endpoints,
        check_diagnostic_required_fields,
        check_diagnostic_codes,
        check_precheck_description,
        check_502_scope,
        check_healthz_public,
    ]
    problems = sum(fn(doc) for fn in checks)
    if problems:
        print(f"{problems} problem(s) found")
        return 1
    print(f"All contract checks passed for {path} ({len(doc['paths'])} paths)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
