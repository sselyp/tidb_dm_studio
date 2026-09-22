#!/usr/bin/env bash
# PR gate: fail on hardcoded addresses / credentials outside docs & examples.
# Allowlist: .env.example, docs/**, **/*.md, api/openapi.yaml (server placeholder), tests fixtures.
set -euo pipefail

fail=0
# 1) private IPs / localhost literals in source
if rg -n --hidden \
  -g '!**/.git/**' -g '!**/*.md' -g '!**/.env.example' -g '!**/testdata/**' \
  -e '\b(10|172|192)\.(?:[0-9]{1,3}\.){2}[0-9]{1,3}\b' \
  -e '\blocalhost\b' ; then
  echo "FAIL: hardcoded host/IP found in source"; fail=1
fi
# 2) obvious secret assignments
if rg -n --hidden \
  -g '!**/.git/**' -g '!**/*.md' -g '!**/.env.example' -g '!**/testdata/**' \
  -e '(?i)(password|passwd|secret|token|api[_-]?key)\s*[:=]\s*["'"'"'][^"'"'"']{3,}' ; then
  echo "FAIL: hardcoded credential-like literal found"; fail=1
fi
exit "$fail"
