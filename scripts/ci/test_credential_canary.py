#!/usr/bin/env python3
"""Live credential-canary gate (architect seq=85 §10.2 ②).

Writes a unique canary password through our own write path
(``config.targetDatabase.password``) and asserts the canary never appears in:

  * read models   GET /tasks, /tasks/{name}, /tasks/{name}/status, /tasks/{name}/yaml
  * error bodies  401 / 404 / 422 envelopes
  * server logs   (optional, via DM_LOG_FILES)

Runs only when DM_BASE_URL is set; otherwise prints SKIP and exits 0 so contract-only
CI stays green. ``--selfcheck`` exercises the scanner offline (no service needed).

Usage:
  python scripts/ci/test_credential_canary.py --selfcheck
  $env:DM_BASE_URL="http://<dm-proxy-host>:8080/api"; $env:DM_SESSION_COOKIE="dm_session=...";
  $env:DM_CSRF_TOKEN="..."; $env:DM_TASK_NAME="canary-sec";
  $env:DM_LOG_FILES="C:\\logs\\app.log";
  python scripts/ci/test_credential_canary.py

Exit non-zero on any leak (or a write that did not apply), 0 otherwise.
"""
import argparse
import json
import os
import ssl
import sys
import urllib.error
import urllib.request
import uuid

CANARY_PREFIX = "CANARYPW_"
READ_PATHS = ["/tasks", "/tasks/{name}", "/tasks/{name}/status", "/tasks/{name}/yaml"]


def new_canary():
    return CANARY_PREFIX + uuid.uuid4().hex


def scan(text, canary):
    return [canary] if (text and canary in text) else []


def _request(url, method="GET", body=None, headers=None, timeout=15):
    hdrs = dict(headers or {})
    data = None
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        hdrs.setdefault("Content-Type", "application/json")
    req = urllib.request.Request(url, data=data, method=method, headers=hdrs)
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=ctx) as r:
            return r.status, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")
    except Exception as e:  # transport/connect failures are reported, not swallowed
        return 0, f"<transport error: {e}>"


def _check(label, text, canary, failures):
    if scan(text, canary):
        failures.append(f"LEAK {label}")
    return failures


def selfcheck():
    canary = new_canary()
    assert canary.startswith(CANARY_PREFIX), "prefix"
    assert new_canary() != canary, "uniqueness"
    assert scan(canary, canary) == [canary], "detects exact match"
    assert scan(f'{{"password":"{canary}"}}', canary) == [canary], "detects embedded match"
    assert scan("clean payload", canary) == [], "no false positive"
    assert scan("", canary) == [] and scan(None, canary) == [], "empty/null safe"
    print("selfcheck ok: scanner detects embedded canary and ignores clean input")
    return 0


def run(base, headers, task, canary, failures):
    target = {
        "host": os.environ.get("DM_TARGET_HOST", "127.0.0.1"),
        "port": int(os.environ.get("DM_TARGET_PORT", "4000")),
        "user": os.environ.get("DM_TARGET_USER", "root"),
        "password": canary,
    }
    body = {
        "name": task,
        "config": {
            "taskMode": "all",
            "sources": [{"sourceRef": os.environ.get("DM_SOURCE_REF", "mysql-single")}],
            "targetDatabase": target,
        },
    }
    status, text = _request(f"{base}/tasks/{task}", "PUT", body, headers)
    if status not in (200, 201):
        status, text = _request(f"{base}/tasks", "POST", body, headers)
    if status not in (200, 201):
        failures.append(f"write did not apply: HTTP {status} {text[:200]}")
        return failures

    for path in READ_PATHS:
        st, payload = _request(f"{base}{path.replace('{name}', task)}", "GET", None, headers)
        _check(f"read {path} (HTTP {st})", payload, canary, failures)

    err_endpoints = [
        ("GET", f"{base}/tasks/__no_such_task__", None, {}),
        ("POST", f"{base}/tasks", {"name": task, "config": {}}, headers),
        ("GET", f"{base}/tasks", None, {}),
    ]
    for method, url, payload, hdrs in err_endpoints:
        st, text = _request(url, method, payload, hdrs)
        _check(f"error body (HTTP {st})", text, canary, failures)

    for path in [p.strip() for p in os.environ.get("DM_LOG_FILES", "").split(",") if p.strip()]:
        try:
            with open(path, encoding="utf-8", errors="replace") as fh:
                _check(f"log {path}", fh.read(), canary, failures)
        except OSError as e:
            failures.append(f"cannot read log {path}: {e}")
    return failures


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--selfcheck", action="store_true")
    ap.add_argument(
        "--expect-leak",
        action="store_true",
        help="reverse control: assert the canary IS detected (scrub disabled); "
        "exit 0 only if a leak is found, 1 if the scanner silently passes",
    )
    args = ap.parse_args()
    if args.selfcheck:
        return selfcheck()

    base = os.environ.get("DM_BASE_URL", "").rstrip("/")
    if not base:
        print("SKIP: DM_BASE_URL not set (contract-only CI); canary not executed")
        return 0

    task = os.environ.get("DM_TASK_NAME", "canary-sec")
    canary = new_canary()
    headers = {}
    if os.environ.get("DM_SESSION_COOKIE"):
        headers["Cookie"] = os.environ["DM_SESSION_COOKIE"]
    if os.environ.get("DM_CSRF_TOKEN"):
        headers["X-CSRF-Token"] = os.environ["DM_CSRF_TOKEN"]

    failures = run(base, headers, task, canary, [])
    leaks = [f for f in failures if f.startswith("LEAK")]
    if args.expect_leak:
        if leaks:
            print(f"OK: reverse control detected {len(leaks)} leak channel(s) (scrub disabled)")
            return 0
        if failures:
            print("FAIL: reverse control could not validate (no leak, and the run itself errored):")
            for f in failures:
                print(f"  - {f}")
            return 1
        print("FAIL: reverse control found NO leak with scrub disabled (silent blind spot)")
        return 1
    if failures:
        print(f"FAIL: credential canary leaked ({len(failures)}):")
        for f in failures:
            print(f"  - {f}")
        return 1
    print(f"OK: canary {canary} absent from reads, error bodies, and logs")
    return 0


if __name__ == "__main__":
    sys.exit(main())
