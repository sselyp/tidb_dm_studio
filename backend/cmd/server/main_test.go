package main

import (
	"reflect"
	"testing"
)

func TestPlatformState(t *testing.T) {
	cases := []struct {
		native, lastOp string
		lastErr        any
		want           string
	}{
		{"Running", "", nil, "running"},
		{"Finished", "", nil, "finished"},
		{"Stopped", "", nil, "stopped"},
		{"Stopped", "stop", nil, "stopped"},
		{"Stopped", "pause", nil, "paused"},
		{"Stopped", "", "boom", "failed"},
		{"Stopped", "pause", "boom", "paused"},
		{"Stopped", "stop", "boom", "stopped"},
		{"Stopped", "", "", "stopped"},
		{"", "", nil, "new"},
	}
	for _, c := range cases {
		if got := platformState(c.native, c.lastOp, c.lastErr); got != c.want {
			t.Errorf("platformState(%q,%q,%v)=%q want %q", c.native, c.lastOp, c.lastErr, got, c.want)
		}
	}
}

func TestAllowedActions(t *testing.T) {
	cases := map[string][]string{
		"new":      {"start", "delete"},
		"running":  {"pause", "stop"},
		"paused":   {"resume", "stop", "delete"},
		"stopped":  {"start", "delete"},
		"finished": {"delete"},
		"failed":   {"start", "delete"},
		"bogus":    {},
	}
	for state, want := range cases {
		if got := allowedActions(state); !reflect.DeepEqual(got, want) {
			t.Errorf("allowedActions(%q)=%v want %v", state, got, want)
		}
	}
}

func TestPickStage(t *testing.T) {
	if got := pickStage("", "Stopped"); got != "Stopped" {
		t.Fatalf("got %q", got)
	}
	if got := pickStage("Stopped", "Running"); got != "Running" {
		t.Fatalf("got %q", got)
	}
	if got := pickStage("Running", "Stopped"); got != "Running" {
		t.Fatalf("got %q", got)
	}
}

func TestScrubDropsCredentials(t *testing.T) {
	v := map[string]any{
		"name": "t",
		"config": map[string]any{
			"targetDatabase":     map[string]any{"host": "h", "password": "CANARYPW_x"},
			"mustChangePassword": true,
			"sources":            []any{map[string]any{"sourceRef": "s", "password": "CANARYPW_y"}},
		},
	}
	scrub(v)
	cfg := v["config"].(map[string]any)
	td := cfg["targetDatabase"].(map[string]any)
	if _, ok := td["password"]; ok {
		t.Fatalf("targetDatabase.password survived scrub")
	}
	if td["host"] != "h" {
		t.Fatalf("non-credential field was dropped")
	}
	if cfg["mustChangePassword"] != true {
		t.Fatalf("policy flag mustChangePassword must survive")
	}
	src := cfg["sources"].([]any)[0].(map[string]any)
	if _, ok := src["password"]; ok {
		t.Fatalf("source password survived scrub")
	}
}

func TestHasCredKey(t *testing.T) {
	// F2 name coverage: every alternate credential name from the contract must be
	// flagged so a DM-passthrough or self-built config cannot echo it.
	for _, k := range []string{
		"password", "passwd", "target_config", "oldPassword",
		"authToken", "secret", "privateKey", "dsn", "cert",
		"accessKey", "clientSecret", "apikey", "api_key", "access_key", "credential",
	} {
		if !hasCredKey(k) {
			t.Errorf("hasCredKey(%q) should be true", k)
		}
	}
	// Policy/config/metadata fields about a credential must not false-positive.
	for _, k := range []string{
		"mustChangePassword", "username", "host", "serverVersion",
		"passwordPolicy", "passwordMinLength", "tokenTtl", "csrfToken",
		"certPath", "secretName",
	} {
		if hasCredKey(k) {
			t.Errorf("hasCredKey(%q) should be false", k)
		}
	}
}

func TestScrubOnByDefault(t *testing.T) {
	if !scrubEnabled {
		t.Fatalf("credential stripping must be on in the default (production) build")
	}
}
