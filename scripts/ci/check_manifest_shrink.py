#!/usr/bin/env python3
"""Anti-shrink guard: the contract manifest must match the real implementation.

Asserts:
  - scripts/ci/check_contract.py's defined `check_*` function set == manifest.checkFunctions
  - scripts/ci/test_gate.py's mutation names (and count) == manifest.mutations{.count,.names}

Any rename/drop => exit 1, so a shrinking gate cannot pass CI silently.
Proposed by DS-测试 (seq=66); wired into CI by architect.
"""
import importlib.util
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
MANIFEST = os.path.join(HERE, "contract_manifest.mutations.json")


def load_module(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def main():
    problems = 0
    with open(MANIFEST, encoding="utf-8") as f:
        man = json.load(f)

    cc = load_module(os.path.join(HERE, "check_contract.py"), "check_contract")
    tg = load_module(os.path.join(HERE, "test_gate.py"), "test_gate")

    impl = {f for f in dir(cc) if f.startswith("check_") and callable(getattr(cc, f))}
    want = set(man["checkFunctions"])
    missing = sorted(want - impl)
    extra = sorted(impl - want)
    if missing:
        print(f"FAIL: checker functions missing vs manifest: {missing}")
        problems += 1
    if extra:
        print(f"FAIL: checker functions not in manifest: {extra}")
        problems += 1

    names = [m[0] for m in tg.MUTATIONS]
    want_count = man["mutations"]["count"]
    want_names = man["mutations"]["names"]
    if len(names) != want_count:
        print(f"FAIL: test_gate mutation count {len(names)} != manifest {want_count}")
        problems += 1
    missing_n = sorted(set(want_names) - set(names))
    extra_n = sorted(set(names) - set(want_names))
    if missing_n:
        print(f"FAIL: mutations missing vs manifest: {missing_n}")
        problems += 1
    if extra_n:
        print(f"FAIL: mutations not in manifest: {extra_n}")
        problems += 1

    if problems:
        print(f"anti-shrink: {problems} problem(s)")
        return 1
    print(f"anti-shrink OK: {len(impl)} checker fns, {len(names)} mutations")
    return 0


if __name__ == "__main__":
    sys.exit(main())
