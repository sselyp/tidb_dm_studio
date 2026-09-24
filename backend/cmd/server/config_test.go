package main

import (
	"os"
	"path/filepath"
	"testing"
)

func TestLoadTargetEnvFileThenEnvFallback(t *testing.T) {
	dir := t.TempDir()
	path := filepath.Join(dir, "target.env")
	content := "# POC target\nTIDB_TARGET_HOST=203.0.113.9\nTIDB_TARGET_PORT=4000\nTIDB_TARGET_USER=tester\n"
	if err := os.WriteFile(path, []byte(content), 0o600); err != nil {
		t.Fatalf("write env: %v", err)
	}
	t.Setenv("DM_TARGET_ENV_FILE", path)
	t.Setenv("TIDB_TARGET_HOST", "198.51.100.7") // must be shadowed by the file
	t.Setenv("TIDB_TARGET_PASSWORD", "fallback-pw")

	te := loadTargetEnv()
	if te.Host != "203.0.113.9" {
		t.Errorf("host = %q, file should win", te.Host)
	}
	if te.Port != "4000" || te.User != "tester" {
		t.Errorf("file values not loaded: %+v", te)
	}
	if te.Password != "fallback-pw" {
		t.Errorf("password should fall back to process env, got %q", te.Password)
	}
}

func TestLoadTargetEnvMissingFile(t *testing.T) {
	t.Setenv("DM_TARGET_ENV_FILE", filepath.Join(t.TempDir(), "nope.env"))
	t.Setenv("TIDB_TARGET_HOST", "203.0.113.1")
	te := loadTargetEnv()
	if te.Host != "203.0.113.1" {
		t.Errorf("host = %q, env fallback expected", te.Host)
	}
}

func TestSSRFPolicyAllows(t *testing.T) {
	t.Setenv("DM_SSRF_ALLOWED_HOSTS", "db.internal.example, 203.0.113.9")
	t.Setenv("DM_SSRF_ALLOWED_CIDRS", "198.51.100.0/24")
	p := loadSSRFPolicy()

	if !p.allows("db.internal.example") {
		t.Errorf("exact host should be allowed")
	}
	if !p.allows("203.0.113.9") {
		t.Errorf("allow-listed literal IP should be allowed")
	}
	if !p.allows("198.51.100.42") {
		t.Errorf("IP inside allowed CIDR should be allowed")
	}
	if p.allows("203.0.113.250") {
		t.Errorf("unlisted host must be denied (fail closed)")
	}
	if p.allows("") {
		t.Errorf("empty host must be denied")
	}
}

func TestSSRFPolicyDefaultDeny(t *testing.T) {
	t.Setenv("DM_SSRF_ALLOWED_HOSTS", "")
	t.Setenv("DM_SSRF_ALLOWED_CIDRS", "")
	p := loadSSRFPolicy()
	if p.allows("203.0.113.9") {
		t.Errorf("empty allow-list must deny everything")
	}
}
