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
# Architect-pinned platform state machine (non-symmetric paused/stopped, see x-dm-compat).
# seq=32: keep `new` (do NOT introduce `pending`); `failed` kept with a unique derivation.
PLATFORM_STATES = ["new", "running", "paused", "stopped", "finished", "failed"]
DM_NATIVE_STAGES = ["Stopped", "Running", "Finished"]
# (platformState, native, required condition tokens) from architect seq=32 derivation table.
STATE_DERIVATION = [
    ("new", None, ["从未下发"]),
    ("running", "Running", []),
    ("finished", "Finished", []),
    ("failed", "Stopped", ["lastOp", "lastError"]),
    ("paused", "Stopped", ["lastOp", "pause"]),
    ("stopped", "Stopped", ["lastOp", "stop", "默认"]),
]


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
    """Pinned registry: required field/precheck codes must exist by name.

    Guards against a 'consistent delete' (dropping a code from BOTH
    x-field-error-codes AND FieldError.errorCode.enum) silently passing the
    equality-only check_field_codes_registered. Requirement set is versioned in
    contract_manifest.json so it cannot be softened without editing the manifest.
    """
    problems = 0
    manifest = _load_manifest()
    reg = set(doc.get("x-field-error-codes", []))
    enum = set(
        (doc["components"]["schemas"]["FieldError"]["properties"]["errorCode"].get("enum")) or []
    )
    required_field = manifest.get("requiredFieldCodes") or []
    if not required_field:
        problems += fail("manifest.requiredFieldCodes missing/empty (pinned field-code registry)")
    for code in required_field:
        if code not in reg:
            problems += fail(f"required field code {code} missing from x-field-error-codes")
        if code not in enum:
            problems += fail(f"required field code {code} missing from FieldError.errorCode.enum")
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
    """TaskSummary.state and TaskStatusData.state must share the pinned state enum."""
    problems = 0
    summary = doc["components"]["schemas"]["TaskSummary"]["properties"].get("state", {})
    status = doc["components"]["schemas"]["TaskStatusData"]["properties"].get("state", {})
    if set(summary.get("enum") or []) != set(PLATFORM_STATES):
        problems += fail(f"TaskSummary.state enum must be exactly {PLATFORM_STATES}")
    if summary.get("enum") != status.get("enum"):
        problems += fail("TaskSummary.state enum != TaskStatusData.state enum")
    if "pending" in (summary.get("enum") or []):
        problems += fail("state enum must not introduce 'pending' (architect seq=32 keeps 'new')")
    for need in ("new", "finished", "failed"):
        if need not in (status.get("enum") or []):
            problems += fail(f"state enum must include '{need}'")
    if "status" in doc["components"]["schemas"]["TaskSummary"]["properties"]:
        problems += fail("TaskSummary must not expose a separate 'status' field")
    # native passthrough for cross-checking against DM TaskStage
    for sch in ("TaskStatusData", "TaskSummary"):
        ns = doc["components"]["schemas"][sch]["properties"].get("nativeState", {})
        if not ns:
            problems += fail(f"{sch}.nativeState missing (DM TaskStage passthrough)")
        elif ns.get("enum") != DM_NATIVE_STAGES:
            problems += fail(f"{sch}.nativeState enum must be {DM_NATIVE_STAGES}")
    return problems


def check_dm_compat(doc):
    """Calibration against the pinned DM control plane (v7.1.6) must be declared."""
    problems = 0
    c = doc.get("x-dm-compat") or {}
    if str(c.get("dmVersion")) != "7.1.6":
        problems += fail("x-dm-compat.dmVersion must be 7.1.6")
    cp = c.get("controlPlane") or {}
    if cp.get("basePath") != "/api/v1":
        problems += fail("x-dm-compat.controlPlane.basePath must be /api/v1 (DM v7.1)")
    if not cp.get("errorEnvelope"):
        problems += fail("x-dm-compat.controlPlane.errorEnvelope must document DM native {error_msg,error_code}")
    mapping = (c.get("taskStageMapping") or {}).get("dmEnum") or []
    for st in ("Stopped", "Running", "Finished"):
        if st not in mapping:
            problems += fail(f"x-dm-compat.taskStageMapping.dmEnum missing {st}")
    tsm = c.get("taskStageMapping") or {}
    if set(tsm.get("platformState") or []) != set(PLATFORM_STATES):
        problems += fail(f"x-dm-compat.taskStageMapping.platformState must be {PLATFORM_STATES}")
    downlink = tsm.get("downlink") or {}
    if downlink.get("paused") != "pause-task" or downlink.get("stopped") != "stop-task":
        problems += fail("x-dm-compat.downlink must map paused→pause-task, stopped→stop-task")
    if downlink.get("running") != "start-task":
        problems += fail("x-dm-compat.downlink must map running→start-task")
    uplink = tsm.get("uplink") or {}
    for k, v in (("Running", "running"), ("Finished", "finished"), ("Stopped", "by-last-op-and-error")):
        if uplink.get(k) != v:
            problems += fail(f"x-dm-compat.uplink.{k} must be '{v}'")
    # architect seq=32: pinned derivation table (native + lastOp + lastError), human intent first.
    deriv = {d.get("platformState"): d for d in (tsm.get("derivation") or [])}
    if set(deriv) != set(PLATFORM_STATES):
        problems += fail(f"x-dm-compat.derivation states must be exactly {PLATFORM_STATES}")
    for state, native, tokens in STATE_DERIVATION:
        row = deriv.get(state)
        if not row:
            continue
        if native and row.get("native") != native:
            problems += fail(f"x-dm-compat.derivation[{state}].native must be {native}")
        cond = str(row.get("condition") or "")
        for tok in tokens:
            if tok not in cond:
                problems += fail(f"x-dm-compat.derivation[{state}].condition must mention '{tok}'")
    if not tsm.get("intentPriority"):
        problems += fail("x-dm-compat.taskStageMapping.intentPriority must state human-intent priority")
    persist = str(tsm.get("lastOpPersistence") or "")
    if "持久化" not in persist or "非内存" not in persist:
        problems += fail("x-dm-compat.taskStageMapping.lastOpPersistence must require persisted (non-memory) lastOp")
    notes = tsm.get("notes") or ""
    if "last-op" not in notes and "最近一次下发意图" not in notes:
        problems += fail("x-dm-compat.taskStageMapping.notes must document paused/stopped last-op disambiguation")
    precheck = c.get("precheck") or {}
    if precheck.get("restEndpoint") is not None:
        problems += fail("x-dm-compat.precheck.restEndpoint must be null (no DM REST precheck in v7.1.6)")
    if not precheck.get("mechanism"):
        problems += fail("x-dm-compat.precheck.mechanism must document the dmctl-aligned mechanism")
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


def check_source_instance_shapes(doc):
    """SourceInstance must mirror the frozen per-source design (rule-name refs, not inline objects).

    Guards drift: routeRules / filters are string[] references to /routes[*].name and
    /filters[*].name, and blockAllowList is BlockAllowList[] — never free-form object[] / object.
    """
    problems = 0
    schemas = doc["components"]["schemas"]
    src = schemas.get("SourceInstance")
    if not src:
        return fail("SourceInstance schema missing")
    props = src.get("properties") or {}
    if props.get("sourceRef", {}).get("type") != "string":
        problems += fail("SourceInstance.sourceRef must be a string")
    for f in ("routeRules", "filters"):
        p = props.get(f) or {}
        if p.get("type") != "array" or (p.get("items") or {}).get("type") != "string":
            problems += fail(f"SourceInstance.{f} must be array<string> (rule-name reference)")
    bal = props.get("blockAllowList") or {}
    ref = (bal.get("items") or {}).get("$ref", "")
    if bal.get("type") != "array" or not ref.endswith("/BlockAllowList"):
        problems += fail("SourceInstance.blockAllowList must be array<$ref BlockAllowList>")
    block = schemas.get("BlockAllowList") or {}
    if sorted(block.get("required") or []) != ["schemaPattern", "tablePattern"]:
        problems += fail("BlockAllowList.required must be [schemaPattern, tablePattern]")
    observed = {
        "routeRules": _array_shape(props.get("routeRules")),
        "filters": _array_shape(props.get("filters")),
        "blockAllowList": _array_shape(bal),
    }
    pinned = _load_manifest().get("schemaShapes")
    if not isinstance(pinned, dict) or not pinned:
        problems += fail("manifest.schemaShapes must pin SourceInstance composite shapes")
    elif pinned != observed:
        problems += fail(f"SourceInstance shapes {observed} != manifest.schemaShapes {pinned}")
    return problems


def _array_shape(p):
    p = p or {}
    items = p.get("items") or {}
    ref = items.get("$ref", "")
    items_desc = ref.rsplit("/", 1)[-1] if ref else items.get("type", "?")
    return f"{p.get('type', '?')}<{items_desc}>"


FROZEN_EXAMPLE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "docs",
    "architecture",
    "form-schema.example.json",
)


def _load_frozen_example():
    with open(FROZEN_EXAMPLE, encoding="utf-8") as fh:
        return json.load(fh)


def check_frozen_example_parity(doc):
    """docs/architecture/form-schema.example.json must not drift from the frozen spec surface.

    The example is the frontend renderer's ground truth (schema-driven forms), so the
    TaskConfig subtree must match api/openapi.yaml exactly — otherwise the renderer silently
    renders a shape the backend rejects (or vice-versa). Closes the blind spot flagged by
    review: `TargetDatabase` and `TaskConfig.required` (taskMode) were previously unasserted,
    and the example `version` could lag `info.version`.
    """
    problems = 0
    if not os.path.exists(FROZEN_EXAMPLE):
        return fail("frozen example docs/architecture/form-schema.example.json missing")
    ex = _load_frozen_example()
    schemas = doc["components"]["schemas"]
    js = ex.get("jsonSchema") or {}

    if str(ex.get("version")) != str(doc["info"]["version"]):
        problems += fail(
            f"example.version {ex.get('version')} != info.version {doc['info']['version']}"
        )

    ex_req = set(js.get("required") or [])
    spec_req = set(schemas["TaskConfig"].get("required") or [])
    if ex_req != spec_req:
        problems += fail(
            f"example jsonSchema.required {sorted(ex_req)} != TaskConfig.required {sorted(spec_req)}"
        )

    ex_td = (js.get("properties") or {}).get("targetDatabase") or {}
    spec_td = schemas.get("TargetDatabase") or {}
    if set(ex_td.get("required") or []) != set(spec_td.get("required") or []):
        problems += fail(
            f"example targetDatabase.required {sorted(set(ex_td.get('required') or []))} "
            f"!= TargetDatabase.required {sorted(set(spec_td.get('required') or []))}"
        )
    ex_props = set((ex_td.get("properties") or {}).keys())
    spec_props = set((spec_td.get("properties") or {}).keys())
    if ex_props != spec_props:
        problems += fail(
            f"example targetDatabase properties {sorted(ex_props)} != TargetDatabase {sorted(spec_props)}"
        )
    if ex_td.get("additionalProperties") != spec_td.get("additionalProperties"):
        problems += fail(
            f"example targetDatabase.additionalProperties {ex_td.get('additionalProperties')} "
            f"!= spec {spec_td.get('additionalProperties')} (both ends must match)"
        )
    for side, td in (("example", ex_td), ("spec", spec_td)):
        if "security" not in (td.get("properties") or {}):
            problems += fail(f"{side} targetDatabase must expose security (DM task.yaml target-database key)")
    return problems


ALLOWED_ACTIONS = ["start", "pause", "resume", "stop", "delete"]


def check_allowed_actions(doc):
    """D15: actions are server-authoritative, a stable AllowedAction enum on state + status.

    Guards against `allowedActions` drifting back to a free `string[]`, which would let the
    frontend re-derive actions from `state` (two state machines → drift at failed/stopped/paused).
    """
    problems = 0
    schemas = doc["components"]["schemas"]
    action = schemas.get("AllowedAction")
    if not action:
        return fail("AllowedAction schema missing (D15 server-authoritative action enum)")
    if action.get("enum") != ALLOWED_ACTIONS:
        problems += fail(
            f"AllowedAction.enum must be exactly {ALLOWED_ACTIONS}, got {action.get('enum')}"
        )
    for name in ("StateData", "TaskStatusData"):
        sch = schemas.get(name)
        if not sch:
            problems += fail(f"{name} missing")
            continue
        prop = (sch.get("properties") or {}).get("allowedActions")
        if not prop:
            problems += fail(f"{name}.allowedActions missing (D15: server returns the action set)")
            continue
        if prop.get("items", {}).get("$ref", "") != "#/components/schemas/AllowedAction":
            problems += fail(
                f"{name}.allowedActions.items must be $ref AllowedAction (stable enum, not free string)"
            )
        if "allowedActions" not in (sch.get("required") or []):
            problems += fail(f"{name}.allowedActions must be required")
    return problems


ACTION_TARGET_STATE = {
    "start": "running",
    "resume": "running",
    "pause": "paused",
    "stop": "stopped",
    "delete": None,
}


def check_state_taxonomy(doc):
    """Reviewer ④: writable desiredState and the action vocabulary stay inside platformState.

    Prevents a stale/extra value drifting back outside the six-state taxonomy:
    - `StateRequest.desiredState` must be the downlink-settable subset of platformState
      (and equal the pinned `downlink` key set, so `new`/`finished`/`failed` are never writable);
    - every `AllowedAction` must be a known action whose resulting platform state (if any)
      is within platformState.
    """
    problems = 0
    schemas = doc["components"]["schemas"]
    tsm = ((doc.get("x-dm-compat") or {}).get("taskStageMapping") or {})
    downlink = set(tsm.get("downlink") or {})
    req = schemas.get("StateRequest") or {}
    desired = (req.get("properties") or {}).get("desiredState") or {}
    dset = set(desired.get("enum") or [])
    if not dset:
        problems += fail("StateRequest.desiredState must be a non-empty enum")
    elif not dset <= set(PLATFORM_STATES):
        problems += fail(
            f"StateRequest.desiredState {sorted(dset)} must be within platformState {PLATFORM_STATES}"
        )
    if downlink and dset != downlink:
        problems += fail(
            f"StateRequest.desiredState {sorted(dset)} must equal downlink-settable {sorted(downlink)}"
        )
    action = schemas.get("AllowedAction") or {}
    for a in action.get("enum") or []:
        if a not in ACTION_TARGET_STATE:
            problems += fail(
                f"AllowedAction '{a}' has no taxonomy binding (known: {sorted(ACTION_TARGET_STATE)})"
            )
            continue
        target = ACTION_TARGET_STATE[a]
        if target is not None and target not in PLATFORM_STATES:
            problems += fail(f"AllowedAction '{a}' targets '{target}' outside platformState")
    pinned_map = _load_manifest().get("actionTargetState")
    if not isinstance(pinned_map, dict) or not pinned_map:
        problems += fail("manifest.actionTargetState must pin the action->target-state map")
    elif pinned_map != ACTION_TARGET_STATE:
        problems += fail(
            f"ACTION_TARGET_STATE {ACTION_TARGET_STATE} != manifest.actionTargetState {pinned_map}"
        )
    return problems


SENSITIVE_KEY_TOKENS = ("password", "passwd", "target_config")


def _is_credential_key(key):
    """True only for credential *values*, not policy flags like mustChangePassword."""
    k = key.lower()
    if "target_config" in k:
        return True
    if "password" in k or "passwd" in k:
        return "must" not in k
    return False
def _resolve_component(ref, container, components):
    """Resolve a `#/components/<container>/<name>` ref, else None."""
    if not (isinstance(ref, str) and ref.startswith("#/components/")):
        return None
    parts = ref.rsplit("/", 2)
    if len(parts) != 3 or parts[1] != container:
        return None
    return (components.get(container) or {}).get(parts[2])


def _operation_media_schemas(doc, section):
    """Every media-type schema declared by any operation's responses/requestBody.

    Derived from the spec (DS-代码审核 seq: no hand-maintained model whitelist), so a
    newly added response/request model is scanned automatically — closing the
    "new model with a credential slips past the whitelist" gap.
    """
    components = doc.get("components") or {}
    container = "requestBodies" if section == "requestBody" else "responses"
    for path_item in (doc.get("paths") or {}).values():
        if not isinstance(path_item, dict):
            continue
        for op in path_item.values():
            if not isinstance(op, dict):
                continue
            if section == "requestBody":
                bodies = [op.get("requestBody")]
            else:
                bodies = list((op.get("responses") or {}).values())
            for body in bodies:
                if not isinstance(body, dict):
                    continue
                node = _resolve_component(body.get("$ref"), container, components) or body
                for media in (node.get("content") or {}).values():
                    if isinstance(media, dict) and isinstance(media.get("schema"), dict):
                        yield media["schema"]


def _cred_tails(own_paths):
    """Registered own-path fields -> their property-key tail (drop the model head).

    A registered field like `TaskConfig.targetDatabase.password` is the property chain
    `targetDatabase.password` inside its model; the credential walk yields the same chain
    (head = read model). Comparing tails keeps `$ref` aliases (Task.config -> TaskConfig)
    transparent without weakening the "unregistered => FAIL" rule.
    """
    tails = []
    for p in own_paths or []:
        toks = [t for t in str(p).split(".") if t]
        tails.append(toks[1:] if len(toks) > 1 else toks)
    return tails


def _cred_chain_registered(chain, tails):
    ct = chain[1:] if len(chain) > 1 else chain
    for rt in tails:
        if rt and len(ct) >= len(rt) and ct[-len(rt):] == rt:
            return True
    return False


def _credential_hits(node, chain, schemas, seen=None, own_tails=()):
    """Walk a response model, dereferencing local `$ref`s so a credential hidden behind
    Task.config ($ref TaskConfig) / Task.sources ($ref SourceInstance) is still caught.

    A `writeOnly: true` field is skipped ONLY when its property chain matches an own-path
    field registered in x-credential-handling.ownPathCredentialFields. OpenAPI `writeOnly`
    is a serialization convention and does NOT remove the field from a response schema, so
    an unregistered (or otherwise uncovered) response credential is a FAIL, not a silent
    skip (DS-代码审核 seq=16).
    """
    if seen is None:
        seen = set()
    if not isinstance(node, dict):
        return []
    ref = node.get("$ref")
    if isinstance(ref, str) and ref.startswith("#/components/schemas/"):
        name = ref.rsplit("/", 1)[-1]
        if name in seen:
            return []
        target = schemas.get(name)
        if isinstance(target, dict):
            return _credential_hits(target, chain, schemas, seen | {name}, own_tails)
        return []
    hits = []
    props = node.get("properties")
    if isinstance(props, dict):
        for pname, pschema in props.items():
            child = chain + [str(pname)]
            if _is_credential_key(pname):
                target = pschema
                if isinstance(pschema, dict) and isinstance(pschema.get("$ref"), str) and pschema["$ref"].startswith("#/components/schemas/"):
                    target = schemas.get(pschema["$ref"].rsplit("/", 1)[-1], pschema)
                allowed = (
                    isinstance(target, dict)
                    and target.get("writeOnly") is True
                    and _cred_chain_registered(child, own_tails)
                )
                if not allowed:
                    hits.append(".".join(child))
            hits.extend(_credential_hits(pschema, child, schemas, seen, own_tails))
    for key in ("items", "additionalProperties", "not"):
        sub = node.get(key)
        if isinstance(sub, dict):
            hits.extend(_credential_hits(sub, chain, schemas, seen, own_tails))
    for key in ("allOf", "anyOf", "oneOf", "prefixItems"):
        sub = node.get(key)
        if isinstance(sub, list):
            for item in sub:
                hits.extend(_credential_hits(item, chain, schemas, seen, own_tails))
    return hits




def check_no_credential_echo(doc):
    """D16 redline: no read/response schema may expose an upstream credential.

    DM v7.1.6 GET /api/v1/tasks returns `target_config.password` in clear; the proxy must
    strip it. This asserts the *contract* side never models a password on a response schema,
    and that every request-side password field is writeOnly (input-only channel).
    """
    problems = 0
    schemas = doc["components"]["schemas"]
    ch = doc.get("x-credential-handling") or {}
    if str(ch.get("redline")) != "D16":
        problems += fail("x-credential-handling.redline must be D16")
    never = ch.get("neverInResponses") or []
    for tok in ("password", "passwd"):
        if tok not in never:
            problems += fail(f"x-credential-handling.neverInResponses must include '{tok}'")
    if not ch.get("stripFromUpstreamResponses"):
        problems += fail("x-credential-handling.stripFromUpstreamResponses must list DM passthrough fields")
    # Response side: scan every response-reachable media schema (structurally derived),
    # skipping only credentials registered in ownPathCredentialFields (whose runtime
    # no-echo guarantee is pinned by the canary via check_own_path_canary_coverage).
    own_tails = _cred_tails(ch.get("ownPathCredentialFields"))
    for schema in _operation_media_schemas(doc, "responses"):
        for hit in _credential_hits(schema, ["<response>"], schemas, None, own_tails):
            problems += fail(f"response schema {hit} exposes a credential (D16 no-echo)")
    # Request side: every request-reachable credential must be writeOnly AND registered
    # in writeOnlyRequestFields (input-only channel, never echoed back).
    req_tails = _cred_tails(ch.get("writeOnlyRequestFields"))
    for schema in _operation_media_schemas(doc, "requestBody"):
        for hit in _credential_hits(schema, ["<request>"], schemas, None, req_tails):
            problems += fail(f"request schema {hit} must be a writeOnly, registered credential (D16 input-only)")
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
        return fail(f"info.description must state a version token like v{version}")
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
    for need in ("PRECHECK_SOURCE_UNREACHABLE", "PRECHECK_TARGET_AUTH_FAILED"):
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


def check_own_path_credential(doc):
    """AC-SEC①: own-path target credential is input-only; never echoed on read.

    TaskConfig is shared by the write models AND the read model Task.config. If its
    targetDatabase.password were not writeOnly:true, a write would be echoed back by
    GET /tasks/{name} and /tasks/{name}/yaml. DM v7.1.6 GET /api/v1/tasks returns
    target_config.password in clear, so the proxy owns this on both sides.
    """
    problems = 0
    schemas = doc["components"]["schemas"]
    td = (schemas.get("TaskConfig", {}).get("properties") or {}).get("targetDatabase")
    if not isinstance(td, dict):
        return fail("TaskConfig.targetDatabase missing (own-path target DB input channel)")
    if not td.get("$ref", "").endswith("/TargetDatabase"):
        problems += fail("TaskConfig.targetDatabase must $ref TargetDatabase")
    tdb = schemas.get("TargetDatabase")
    if not isinstance(tdb, dict):
        return problems + fail("TargetDatabase schema missing")
    pw = (tdb.get("properties") or {}).get("password")
    if not isinstance(pw, dict):
        return problems + fail("TargetDatabase.password missing (must exist as a writeOnly input channel)")
    if pw.get("writeOnly") is not True:
        problems += fail("TargetDatabase.password must set writeOnly:true (D16 own-path no-echo)")
    ch = doc.get("x-credential-handling") or {}
    if "TaskConfig.targetDatabase.password" not in (ch.get("ownPathCredentialFields") or []):
        problems += fail("x-credential-handling.ownPathCredentialFields must pin TaskConfig.targetDatabase.password")
    if "TaskConfig.targetDatabase.password" not in (ch.get("writeOnlyRequestFields") or []):
        problems += fail("x-credential-handling.writeOnlyRequestFields must include TaskConfig.targetDatabase.password")
    if schemas.get("Task", {}).get("properties", {}).get("config", {}).get("$ref", "") != "#/components/schemas/TaskConfig":
        problems += fail("Task.config must $ref TaskConfig (single read/write model, so writeOnly is load-bearing)")
    return problems


def check_own_path_canary_coverage(doc):
    """Every own-path credential that is allowed to skip the D16 no-echo scan MUST be
    covered by the AC-SEC canary (DS-代码审核 seq=16 / DS-测试 seq=17).

    `writeOnly` alone does not prove "never echoed": the field is still reachable from a
    response schema, so the guarantee moves to the runtime canary. If a future own-path
    credential is registered without canary coverage, skipping it would be a silent blind
    spot -> FAIL here.
    """
    ch = doc.get("x-credential-handling") or {}
    own = ch.get("ownPathCredentialFields") or []
    covered = ch.get("canaryCoveredFields") or []
    problems = 0
    if not own:
        problems += fail("x-credential-handling.ownPathCredentialFields must list the own-path credential(s)")
    for f in own:
        if f not in covered:
            problems += fail(f"own-path credential {f} has no canary coverage (add it to x-credential-handling.canaryCoveredFields)")
    for f in covered:
        if f not in own:
            problems += fail(f"canaryCoveredFields lists {f} which is not an ownPathCredentialField (stale coverage)")
    return problems


def _find_schema_keys_with_prefix(node, prefix):
    hits = []
    if isinstance(node, dict):
        for k, v in node.items():
            if str(k).startswith(prefix):
                hits.append(k)
            hits.extend(_find_schema_keys_with_prefix(v, prefix))
    elif isinstance(node, list):
        for v in node:
            hits.extend(_find_schema_keys_with_prefix(v, prefix))
    return hits


def check_schema_ui_channel(doc):
    """D11: jsonSchema is pure JSON Schema 2020-12 (no x-ui-*); UI only in formLayout."""
    problems = 0
    sd = doc["components"]["schemas"].get("SchemaData")
    if not isinstance(sd, dict):
        return fail("SchemaData schema missing (GET /task-schema payload)")
    props = sd.get("properties") or {}
    for field in ("version", "jsonSchema", "formLayout"):
        if field not in (sd.get("required") or []):
            problems += fail(f"SchemaData.required must include '{field}'")
    js = props.get("jsonSchema") or {}
    if js.get("type") != "object":
        problems += fail("SchemaData.jsonSchema must be type: object")
    hits = _find_schema_keys_with_prefix(js, "x-ui")
    if hits:
        problems += fail(f"jsonSchema must not embed UI hints: {hits} (D11: UI lives in formLayout)")
    jdesc = js.get("description") or ""
    if "2020-12" not in jdesc or "x-ui-" not in jdesc:
        problems += fail("jsonSchema.description must document pure 2020-12 and the no-x-ui-* rule")
    fl = props.get("formLayout")
    if not isinstance(fl, dict):
        problems += fail("SchemaData.formLayout missing (D11 UI channel)")
    elif "JSON Pointer" not in (fl.get("description") or ""):
        problems += fail("formLayout.description must document the JSON-Pointer-keyed 'ui' channel")
    vdesc = (props.get("version") or {}).get("description") or ""
    if "info.version" not in vdesc:
        problems += fail("SchemaData.version.description must state it follows info.version")
    return problems


def check_freeze(doc):
    """x-freeze marker must not drift from info.version and must scope the frozen surface."""
    fz = doc.get("x-freeze") or {}
    if str(fz.get("version")) != str(doc["info"]["version"]):
        return fail(f"x-freeze.version {fz.get('version')} != info.version {doc['info']['version']}")
    if not fz.get("scope"):
        return fail("x-freeze.scope must state the frozen surface")
    return 0


CHECKS = [
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
    check_state_taxonomy,
    check_dm_compat,
    check_task_config_isomorphic,
    check_source_instance_shapes,
    check_frozen_example_parity,
    check_allowed_actions,
    check_no_credential_echo,
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
    check_own_path_credential,
    check_own_path_canary_coverage,
    check_schema_ui_channel,
    check_freeze,
]


def check_check_functions(doc):
    """Anti-merge-loss guard: contract_manifest.json pins the exact registered check set.

    The mutation gate only protects bindings that have a mutation, so a whole check
    function could vanish in a merge with CI still green. Here every pinned name must be
    a registered check, every registered check must be pinned, and no `check_*` function
    may exist without being wired into CHECKS (write-but-never-run).
    """
    problems = 0
    manifest = _load_manifest()
    pinned = manifest.get("checkFunctions")
    if not isinstance(pinned, list) or not pinned:
        return fail("manifest.checkFunctions must list every registered check function")
    if len(set(pinned)) != len(pinned):
        problems += fail("manifest.checkFunctions has duplicate entries")
    registered = {fn.__name__ for fn in CHECKS}
    for name in pinned:
        if name not in registered:
            problems += fail(f"manifest.checkFunctions lists unregistered check {name}")
    for name in sorted(registered - set(pinned)):
        problems += fail(f"registered check {name} missing from manifest.checkFunctions")
    defined = {n for n, o in globals().items() if n.startswith("check_") and callable(o)}
    for name in sorted(defined - registered - {"check_check_functions"}):
        problems += fail(f"check function {name} is defined but never registered in CHECKS")
    return problems


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else "api/openapi.yaml"
    with open(path, encoding="utf-8") as fh:
        doc = yaml.safe_load(fh)
    problems = sum(fn(doc) for fn in CHECKS)
    problems += check_check_functions(doc)
    if problems:
        print(f"{problems} problem(s) found")
        return 1
    print(f"All contract checks passed for {path} ({len(doc['paths'])} paths)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
