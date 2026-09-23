#!/usr/bin/env python3
"""Gate self-test (negative/mutation tests) for check_contract.py.

Each entry mutates a *contract binding* that CI is supposed to protect.
If check_contract.py still exits 0, that binding is unguarded -> gate hole.
Proposed by DS-测试; owner of the CI fix: DS-后端开发.

Usage: python scripts/ci/test_gate.py api/openapi.yaml
Exit non-zero if any must_fail mutation is NOT caught, or a benign edit IS flagged.
"""
import copy
import json
import os
import shutil
import subprocess
import sys
import tempfile
import yaml

HERE = os.path.dirname(os.path.abspath(__file__))
CHECKER = os.path.join(HERE, "check_contract.py")
MANIFEST = os.path.join(HERE, "contract_manifest.json")


def load(path):
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def del_resp(d, path, method, status):
    d["paths"][path][method]["responses"].pop(str(status), None)


def del_header(d, resp, header):
    (d["components"]["responses"][resp].get("headers") or {}).pop(header, None)


def add_422(d, path):
    d["paths"][path]["post"]["responses"]["422"] = {"$ref": "#/components/responses/Error"}


def misalign_error_code(d):
    d["x-error-codes"][0]["code"] = 59901


def require_field_pop(d, schema, field):
    """Remove one required entry; a missing binding raises => counts as a hole."""
    d["components"]["schemas"][schema]["required"].remove(field)


def drop_precheck_code(d, name):
    d["x-precheck-codes"] = [c for c in d["x-precheck-codes"] if c.get("code") != name]


def reintroduce_retired_502(d):
    d.setdefault("x-error-codes", []).append(
        {"http": 502, "code": 50202, "name": "E_SOURCE_UNREACHABLE"}
    )


def policy_reject_as_200(d):
    r = d["paths"]["/datasources/test"]["post"]["responses"]
    r["200"] = r.pop("422")


def consistency_delete_field_code(d, code):
    """Delete a field code from registry AND enum together (self-consistent bad state)."""
    reg = d["x-field-error-codes"]
    enum = d["components"]["schemas"]["FieldError"]["properties"]["errorCode"]["enum"]
    assert code in reg and code in enum, f"{code} absent from registry/enum (would be a silent no-op)"
    d["x-field-error-codes"] = [c for c in reg if c != code]
    enum[:] = [c for c in enum if c != code]


def platform_state(d):
    return d["x-dm-compat"]["taskStageMapping"]["platformState"]


def derivation(d):
    return d["x-dm-compat"]["taskStageMapping"]["derivation"]


def failed_row(d):
    return next(r for r in derivation(d) if r.get("platformState") == "failed")


def state_enum(d):
    return d["components"]["schemas"]["TaskSummary"]["properties"]["state"]["enum"]


def status_enum(d):
    return d["components"]["schemas"]["TaskStatusData"]["properties"]["state"]["enum"]


# name, mutate, must_fail
MUTATIONS = [
    ("drop 428 from PUT /tasks/{name}", lambda d: del_resp(d, "/tasks/{name}", "put", 428), True),
    ("drop 428 from PUT /datasources/{id}", lambda d: del_resp(d, "/datasources/{id}", "put", 428), True),
    ("drop 412 from PUT /tasks/{name}", lambda d: del_resp(d, "/tasks/{name}", "put", 412), True),
    ("drop 412 from PUT /datasources/{id}", lambda d: del_resp(d, "/datasources/{id}", "put", 412), True),
    ("drop ETag header from PreconditionFailed (412)", lambda d: del_header(d, "PreconditionFailed", "ETag"), True),
    ("drop ETag header from TaskItem", lambda d: del_header(d, "TaskItem", "ETag"), True),
    ("drop ETag header from DataSourceItem", lambda d: del_header(d, "DataSourceItem", "ETag"), True),
    ("drop 409 from DELETE /datasources/{id} (E_DS_REFERENCED)", lambda d: del_resp(d, "/datasources/{id}", "delete", 409), True),
    ("drop 409 from DELETE /tasks/{name} (state conflict)", lambda d: del_resp(d, "/tasks/{name}", "delete", 409), True),
    ("drop 502 from PUT /tasks/{name}/state (DM down)", lambda d: del_resp(d, "/tasks/{name}/state", "put", 502), True),
    ("drop 404 from GET /tasks/{name}", lambda d: del_resp(d, "/tasks/{name}", "get", 404), True),
    ("drop 400 from PUT /tasks/{name}", lambda d: del_resp(d, "/tasks/{name}", "put", 400), True),
    ("drop 403 from POST /logout (CSRF)", lambda d: del_resp(d, "/logout", "post", 403), True),
    ("delete whole UpdateTask op", lambda d: d["paths"]["/tasks/{name}"].pop("put", None), True),
    ("delete whole DeleteTask op", lambda d: d["paths"]["/tasks/{name}"].pop("delete", None), True),
    ("TaskConfig.sources.minItems -> 0", lambda d: d["components"]["schemas"]["TaskConfig"]["properties"]["sources"].__setitem__("minItems", 0), True),
    ("drop TaskWrite.oneOf", lambda d: d["components"]["schemas"]["TaskWrite"].pop("oneOf", None), True),
    ("loosen NamePath pattern", lambda d: d["components"]["parameters"]["NamePath"]["schema"].__setitem__("pattern", "^.*$"), True),
    ("re-introduce literal /tasks/schema", lambda d: d["paths"].__setitem__("/tasks/schema", {"get": {"responses": {"200": {"description": "x"}}}}), True),
    ("FieldError.errorCode.enum loses one entry", lambda d: d["components"]["schemas"]["FieldError"]["properties"]["errorCode"]["enum"].pop(), True),
    ("info.description version text != info.version", lambda d: d["info"].__setitem__("description", "后端接口契约 v0.8\n"), True),
    ("Idempotency-Key required:true on idempotent PUT", lambda d: d["components"]["parameters"]["IdempotencyKey"].__setitem__("required", True), True),
    # D12-b (diagnostic endpoints single-track 200; write-side 422 only)
    ("re-add 422 to /task-validate (diagnostic must stay 200-only)", lambda d: add_422(d, "/task-validate"), True),
    ("re-add 422 to /task-precheck (diagnostic must stay 200-only)", lambda d: add_422(d, "/task-precheck"), True),
    # D12-b exception: /datasources/test keeps 422 for policy/SSRF reject, never 200.
    ("drop 422 from /datasources/test (policy/SSRF reject must stay 422)", lambda d: del_resp(d, "/datasources/test", "post", 422), True),
    ("policy reject (E_TARGET_NOT_ALLOWED) downgraded to 200", policy_reject_as_200, True),
    ("drop required 'valid' from ValidationData", lambda d: require_field_pop(d, "ValidationData", "valid"), True),
    ("drop required 'errors' from ValidationData (want [] when valid)", lambda d: require_field_pop(d, "ValidationData", "errors"), True),
    ("drop required 'valid' from ConnectivityResult", lambda d: require_field_pop(d, "ConnectivityResult", "valid"), True),
    ("drop required 'errors' from ConnectivityResult (want [] when valid)", lambda d: require_field_pop(d, "ConnectivityResult", "errors"), True),
    ("retired 50202 re-introduced into x-error-codes", reintroduce_retired_502, True),
    ("drop E_SOURCE_UNREACHABLE from x-precheck-codes", lambda d: drop_precheck_code(d, "E_SOURCE_UNREACHABLE"), True),
    ("drop E_TARGET_AUTH_FAILED from x-precheck-codes", lambda d: drop_precheck_code(d, "E_TARGET_AUTH_FAILED"), True),
    ("x-error-codes code prefix != http", misalign_error_code, True),
    ("/task-precheck description reintroduces upstream-502 wording", lambda d: d["paths"]["/task-precheck"]["post"].__setitem__("description", "level=connectivity 触达上游，失败回 502。"), True),
    # D14 (v0.9.2): six-state enum + `failed` state derivation must be pinned.
    ("platformState re-introduces 'pending' (D14 forbids)", lambda d: platform_state(d).append("pending"), True),
    ("platformState drops 'failed'", lambda d: platform_state(d).remove("failed"), True),
    ("derivation drops 'failed' row", lambda d: derivation(d).__setitem__(slice(None), [r for r in derivation(d) if r.get("platformState") != "failed"]), True),
    ("derivation 'failed' loses lastOp guard", lambda d: failed_row(d).__setitem__("condition", "native=Stopped & lastError!=null"), True),
    ("intentPriority removed (human-intent priority lost)", lambda d: d["x-dm-compat"]["taskStageMapping"].pop("intentPriority", None), True),
    ("lastOpPersistence removed (lastOp not persisted)", lambda d: d["x-dm-compat"]["taskStageMapping"].pop("lastOpPersistence", None), True),
    ("state enum (both) re-introduces 'pending'", lambda d: (state_enum(d).append("pending"), status_enum(d).append("pending")), True),
    ("state enum (both) drops 'failed'", lambda d: (state_enum(d).remove("failed"), status_enum(d).remove("failed")), True),
    ("dmEnum drops 'Finished' (control: check_dm_compat guards)", lambda d: d["x-dm-compat"]["taskStageMapping"]["dmEnum"].remove("Finished"), True),
    # benign control: must NOT be flagged
    ("benign: reword a response description", lambda d: d["components"]["responses"]["Error"].__setitem__("description", "统一错误包"), False),
]

# G2 (main d99a2e4): manifest-pinned required field codes; consistent deletion must FAIL.
for _code in (
    "E_FIELD_REQUIRED",
    "E_PARAM_RANGE",
    "E_PARAM_ENUM",
    "E_PARAM_REGEX",
    "E_PARAM_DEPENDENCY",
    "E_FIELD_DUPLICATE",
    "E_FIELD_EXISTENCE",
):
    MUTATIONS.append(
        (
            f"consistent-delete {_code} (registry+enum)",
            lambda d, c=_code: consistency_delete_field_code(d, c),
            True,
        )
    )

# allowedActions must stay a server-authoritative stable enum (D15).
MUTATIONS += [
    ("StateData.allowedActions back to free string[]", lambda d: d["components"]["schemas"]["StateData"]["properties"]["allowedActions"].__setitem__("items", {"type": "string"}), True),
    ("drop allowedActions from TaskStatusData (status has no action source)", lambda d: d["components"]["schemas"]["TaskStatusData"]["properties"].pop("allowedActions", None), True),
    ("AllowedAction enum loses 'resume'", lambda d: d["components"]["schemas"]["AllowedAction"]["enum"].remove("resume"), True),
    ("AllowedAction enum gains bogus 'restart'", lambda d: d["components"]["schemas"]["AllowedAction"]["enum"].append("restart"), True),
]

# desiredState / action vocabulary must stay inside the six-state platformState taxonomy (reviewer ④).
MUTATIONS += [
    ("StateRequest.desiredState gains stale 'pending' (outside platformState)", lambda d: d["components"]["schemas"]["StateRequest"]["properties"]["desiredState"]["enum"].append("pending"), True),
    ("StateRequest.desiredState drops 'paused' (downlink-settable subset shrunk)", lambda d: d["components"]["schemas"]["StateRequest"]["properties"]["desiredState"]["enum"].remove("paused"), True),
    ("StateRequest.desiredState becomes writable 'finished' (not a downlink target)", lambda d: d["components"]["schemas"]["StateRequest"]["properties"]["desiredState"]["enum"].append("finished"), True),
]

# SourceInstance must stay the frozen per-source shape (rule-name refs, not inline objects).
MUTATIONS += [
    ("SourceInstance.routeRules back to object[]", lambda d: d["components"]["schemas"]["SourceInstance"]["properties"]["routeRules"].__setitem__("items", {"type": "object"}), True),
    ("SourceInstance.filters back to object[]", lambda d: d["components"]["schemas"]["SourceInstance"]["properties"]["filters"].__setitem__("items", {"type": "object"}), True),
    ("SourceInstance.blockAllowList back to free object", lambda d: d["components"]["schemas"]["SourceInstance"]["properties"].__setitem__("blockAllowList", {"type": "object"}), True),
    ("BlockAllowList loses tablePattern requirement", lambda d: d["components"]["schemas"]["BlockAllowList"]["required"].remove("tablePattern"), True),
]

# D16 redline: read models must not echo credentials; request credentials stay writeOnly.
MUTATIONS += [
    ("Task response exposes password (D16 regression)", lambda d: d["components"]["schemas"]["Task"]["properties"].__setitem__("password", {"type": "string"}), True),
    ("DataSource response exposes target_config.password (D16)", lambda d: d["components"]["schemas"]["DataSource"]["properties"].__setitem__("targetConfig", {"type": "object", "properties": {"password": {"type": "string"}}}), True),
    ("x-credential-handling redline removed", lambda d: d.pop("x-credential-handling", None), True),
    ("DataSourceWrite.password loses writeOnly (echoable input)", lambda d: d["components"]["schemas"]["DataSourceWrite"]["properties"]["password"].pop("writeOnly", None), True),
]

# D16 $ref blind spot (DS-测试 probe): a credential nested behind Task.config ($ref TaskConfig)
# or Task.sources ($ref SourceInstance) must still be caught -> _credential_hits dereferences $ref.
MUTATIONS += [
    ("TaskConfig.password (direct; $ref'd from Task.config)", lambda d: d["components"]["schemas"]["TaskConfig"]["properties"].__setitem__("password", {"type": "string"}), True),
    ("TaskConfig.targetDatabase.password (nested; our own path)", lambda d: d["components"]["schemas"]["TaskConfig"]["properties"].__setitem__("targetDatabase", {"type": "object", "properties": {"password": {"type": "string"}}}), True),
    ("SourceInstance.password (direct; $ref'd from Task.sources)", lambda d: d["components"]["schemas"]["SourceInstance"]["properties"].__setitem__("password", {"type": "string"}), True),
]

# AC-SEC (architect seq=85): own-path target credential input-only + D11 UI channel + freeze.
MUTATIONS += [
    ("TaskConfig.targetDatabase.password loses writeOnly (own-path echo)", lambda d: d["components"]["schemas"]["TargetDatabase"]["properties"]["password"].pop("writeOnly", None), True),
    ("TaskConfig.targetDatabase removed (own-path input channel gone)", lambda d: d["components"]["schemas"]["TaskConfig"]["properties"].pop("targetDatabase", None), True),
    ("ownPathCredentialFields drops the target password pin", lambda d: d["x-credential-handling"].__setitem__("ownPathCredentialFields", []), True),
    ("SchemaData.jsonSchema gains an x-ui-* hint (D11 UI leak)", lambda d: d["components"]["schemas"]["SchemaData"]["properties"]["jsonSchema"].__setitem__("x-ui-widget", "select"), True),
    ("SchemaData loses formLayout (D11 UI channel removed)", lambda d: d["components"]["schemas"]["SchemaData"]["properties"].pop("formLayout", None), True),
    ("SchemaData.version stops tracking info.version", lambda d: d["components"]["schemas"]["SchemaData"]["properties"]["version"].__setitem__("description", "契约版本。"), True),
    ("x-freeze.version drifts from info.version", lambda d: d["x-freeze"].__setitem__("version", "0.0.0"), True),
]

# Frozen example parity (review seq=94): the spec TaskConfig subtree must not drift from
# docs/architecture/form-schema.example.json (the renderer's ground truth). Each must FAIL
# AND land on the specific example-parity assertion (see EXPECT_SUBSTR below).
MUTATIONS += [
    ("TaskConfig.required drops taskMode (example requires it)", lambda d: d["components"]["schemas"]["TaskConfig"]["required"].remove("taskMode"), True),
    ("TargetDatabase.required dropped (example requires host/port/user)", lambda d: d["components"]["schemas"]["TargetDatabase"].pop("required"), True),
    ("TargetDatabase.additionalProperties flips vs example", lambda d: d["components"]["schemas"]["TargetDatabase"].__setitem__("additionalProperties", False), True),
    ("TargetDatabase.security dropped (example keeps it)", lambda d: d["components"]["schemas"]["TargetDatabase"]["properties"].pop("security"), True),
]

# The frozen example *document* is itself the parity target. check_contract resolves it from
# its own __file__-relative root, so these run against a mirrored root (checker+manifest+spec
# copies) — the mutation acts on a copy, never the repo file, and stays deterministic.
EXAMPLE_MUTATIONS = [
    ("example.version drifts from info.version (frozen doc ground truth)", lambda ex: ex.__setitem__("version", "0.0.0")),
]

# Constraint (review seq=94 / architect seq=102): a mutation must trip the *intended*
# assertion, not merely any non-zero exit. For these parity mutations we assert the
# checker's stdout carries the matching FAIL line.
EXPECT_SUBSTR = {
    "TaskConfig.required drops taskMode (example requires it)": "TaskConfig.required must be [taskMode, sources]",
    "TargetDatabase.required dropped (example requires host/port/user)": "TargetDatabase.required must be [host, port, user]",
    "TargetDatabase.additionalProperties flips vs example": "TargetDatabase.additionalProperties must be true",
    "TargetDatabase.security dropped (example keeps it)": "TargetDatabase.properties must be [host,port,user,password,security,session]",
    "example.version drifts from info.version (frozen doc ground truth)": "form-schema.example.json version",
}


def assert_gate_manifest():
    """The manifest pins the mutation set so it cannot silently shrink.

    Deleting (or renaming) a mutation without updating contract_manifest.json fails here,
    before the gate runs, instead of quietly reducing coverage.
    """
    with open(MANIFEST, encoding="utf-8") as f:
        pinned = json.load(f).get("mutations") or {}
    names = [name for name, _, _ in MUTATIONS] + [name for name, _ in EXAMPLE_MUTATIONS]
    total = len(MUTATIONS) + len(EXAMPLE_MUTATIONS)
    if pinned.get("count") != total:
        return f"manifest.mutations.count {pinned.get('count')} != actual {total}"
    if list(pinned.get("names") or []) != names:
        return (
            "manifest.mutations.names != actual MUTATIONS list "
            "(mutation set changed without updating contract_manifest.json)"
        )
    return None


def main():
    spec = sys.argv[1] if len(sys.argv) > 1 else "api/openapi.yaml"
    err = assert_gate_manifest()
    if err:
        print(f"  GATE CONFIG ERROR: {err}")
        return 2
    base = load(spec)
    tmpdir = tempfile.mkdtemp(prefix="gate_selftest_")
    holes, fps, unapplied = [], [], []
    for name, mutate, must_fail in MUTATIONS:
        d = copy.deepcopy(base)
        try:
            mutate(d)
        except Exception as e:  # binding absent => gate cannot protect it yet
            if must_fail:
                unapplied.append(name)
                print(f"  UNAPPLIED     {name} (binding absent: {e})")
            else:
                print(f"  SKIP          {name} (cannot apply: {e})")
            continue
        p = os.path.join(tmpdir, "_m.yaml")
        with open(p, "w", encoding="utf-8") as f:
            yaml.safe_dump(d, f, allow_unicode=True, sort_keys=False)
        r = subprocess.run([sys.executable, CHECKER, p], capture_output=True, text=True)
        out = r.stdout + r.stderr
        caught = r.returncode != 0
        exp = EXPECT_SUBSTR.get(name)
        hit = exp is None or exp in out
        if must_fail and (not caught or not hit):
            holes.append(name)
            if caught and not hit:
                print(f"  HOLE          {name} (wrong assertion: expected {exp!r})")
            else:
                print(f"  HOLE          {name}")
        elif not must_fail and caught:
            fps.append(name)
            print(f"  FALSE-POSITIVE {name}")
        else:
            print(f"  OK            {name}")

    # Frozen-doc parity mutations: check_contract resolves the example from its own
    # __file__-relative root, so run the checker from a mirrored copy of that root.
    example_src = os.path.join(
        os.path.dirname(os.path.dirname(HERE)), "docs", "architecture", "form-schema.example.json"
    )
    with open(example_src, encoding="utf-8") as f:
        ex_base = json.load(f)
    mirror = os.path.join(tmpdir, "mirror")
    os.makedirs(os.path.join(mirror, "scripts", "ci"), exist_ok=True)
    os.makedirs(os.path.join(mirror, "api"), exist_ok=True)
    os.makedirs(os.path.join(mirror, "docs", "architecture"), exist_ok=True)
    m_checker = os.path.join(mirror, "scripts", "ci", "check_contract.py")
    m_spec = os.path.join(mirror, "api", "openapi.yaml")
    m_example = os.path.join(mirror, "docs", "architecture", "form-schema.example.json")
    shutil.copyfile(CHECKER, m_checker)
    shutil.copyfile(MANIFEST, os.path.join(mirror, "scripts", "ci", "contract_manifest.json"))
    with open(m_spec, "w", encoding="utf-8") as f:
        yaml.safe_dump(base, f, allow_unicode=True, sort_keys=False)
    for name, ex_mutate in EXAMPLE_MUTATIONS:
        ex = copy.deepcopy(ex_base)
        try:
            ex_mutate(ex)
        except Exception as e:
            unapplied.append(name)
            print(f"  UNAPPLIED     {name} (binding absent: {e})")
            continue
        with open(m_example, "w", encoding="utf-8") as f:
            json.dump(ex, f, ensure_ascii=False, indent=2)
        r = subprocess.run([sys.executable, m_checker, m_spec], capture_output=True, text=True)
        out = r.stdout + r.stderr
        caught = r.returncode != 0
        exp = EXPECT_SUBSTR.get(name)
        hit = exp is None or exp in out
        if not caught or not hit:
            holes.append(name)
            if caught and not hit:
                print(f"  HOLE          {name} (wrong assertion: expected {exp!r})")
            else:
                print(f"  HOLE          {name}")
        else:
            print(f"  OK            {name}")

    shutil.rmtree(tmpdir, ignore_errors=True)
    total = len(MUTATIONS) + len(EXAMPLE_MUTATIONS)
    print(
        f"\n{total} mutations: {len(holes)} hole(s) [checker missed], "
        f"{len(unapplied)} unapplied [binding absent in spec], {len(fps)} false positive(s)"
    )
    return 1 if (holes or fps or unapplied) else 0


if __name__ == "__main__":
    sys.exit(main())
