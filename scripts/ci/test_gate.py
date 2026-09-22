#!/usr/bin/env python3
"""Gate self-test (negative/mutation tests) for check_contract.py.

Each entry mutates a *contract binding* that CI is supposed to protect.
If check_contract.py still exits 0, that binding is unguarded -> gate hole.
Proposed by DS-测试; owner of the CI fix: DS-后端开发.

Usage: python scripts/ci/test_gate.py api/openapi.yaml
Exit non-zero if any must_fail mutation is NOT caught, or a benign edit IS flagged.
"""
import copy
import os
import shutil
import subprocess
import sys
import tempfile
import yaml

HERE = os.path.dirname(os.path.abspath(__file__))
CHECKER = os.path.join(HERE, "check_contract.py")


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
    d["x-field-error-codes"] = [c for c in d["x-field-error-codes"] if c != code]
    enum = d["components"]["schemas"]["FieldError"]["properties"]["errorCode"]["enum"]
    enum[:] = [c for c in enum if c != code]


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

# D16 redline: read models must not echo credentials; request credentials stay writeOnly.
MUTATIONS += [
    ("Task response exposes password (D16 regression)", lambda d: d["components"]["schemas"]["Task"]["properties"].__setitem__("password", {"type": "string"}), True),
    ("DataSource response exposes target_config.password (D16)", lambda d: d["components"]["schemas"]["DataSource"]["properties"].__setitem__("targetConfig", {"type": "object", "properties": {"password": {"type": "string"}}}), True),
    ("x-credential-handling redline removed", lambda d: d.pop("x-credential-handling", None), True),
    ("DataSourceWrite.password loses writeOnly (echoable input)", lambda d: d["components"]["schemas"]["DataSourceWrite"]["properties"]["password"].pop("writeOnly", None), True),
]


def main():
    spec = sys.argv[1] if len(sys.argv) > 1 else "api/openapi.yaml"
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
        caught = r.returncode != 0
        if must_fail and not caught:
            holes.append(name)
            print(f"  HOLE          {name}")
        elif not must_fail and caught:
            fps.append(name)
            print(f"  FALSE-POSITIVE {name}")
        else:
            print(f"  OK            {name}")
    shutil.rmtree(tmpdir, ignore_errors=True)
    print(
        f"\n{len(MUTATIONS)} mutations: {len(holes)} hole(s) [checker missed], "
        f"{len(unapplied)} unapplied [binding absent in spec], {len(fps)} false positive(s)"
    )
    return 1 if (holes or fps or unapplied) else 0


if __name__ == "__main__":
    sys.exit(main())
