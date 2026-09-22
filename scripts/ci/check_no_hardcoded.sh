#!/usr/bin/env bash
# PR gate: fail on hardcoded addresses / credentials outside docs & examples.
# Allowlist: docs/**, **/*.md, *.example.*, .env.example, testdata/, api/openapi.yaml,
#            dev-only build/proxy config (vite/vitest config), and this script itself.
set -euo pipefail

EXCLUDES=(
  -g '!**/.git/**'
  -g '!**/*.md'
  -g '!**/*.example.*'
  -g '!**/.env.example'
  -g '!**/testdata/**'
  -g '!**/docs/**'
  -g '!**/vite.config.*'
  -g '!**/vitest.config.*'
  -g '!**/api/openapi.yaml'
  -g '!**/scripts/ci/check_no_hardcoded.sh'
)

fail=0
# 1) private IPs / localhost literals in source
if rg -n --hidden "${EXCLUDES[@]}" \
  -e '\b(10|172|192)\.(?:[0-9]{1,3}\.){2}[0-9]{1,3}\b' \
  -e '\blocalhost\b' ; then
  echo "FAIL: hardcoded host/IP found in source"; fail=1
fi
# 2) obvious secret assignments
if rg -n --hidden "${EXCLUDES[@]}" \
  -e '(?i)(password|passwd|secret|token|api[_-]?key)\s*[:=]\s*["'"'"'][^"'"'"']{3,}' ; then
  echo "FAIL: hardcoded credential-like literal found"; fail=1
fi
exit "$fail"
