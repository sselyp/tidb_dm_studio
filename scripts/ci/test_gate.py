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
