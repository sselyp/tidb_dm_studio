package main

import "testing"

func TestTargetSchemaB(t *testing.T) {
	cases := map[string]string{
		"single":  "shop",
		"shards":  "shop_merged",
		"sharded": "shop_merged",
		"SINGLE":  "shop",
	}
	for in, want := range cases {
		got, ok := targetSchemaB(in)
		if !ok || got != want {
			t.Errorf("targetSchemaB(%q) = %q,%v want %q,true", in, got, ok, want)
		}
	}
	if _, ok := targetSchemaB("unknown"); ok {
		t.Errorf("unknown topology must not map")
	}
}

func TestTopologyForSources(t *testing.T) {
	if got := topologyForSources(1); got != "single" {
		t.Errorf("1 source = %q", got)
	}
	if got := topologyForSources(3); got != "shards" {
		t.Errorf("3 sources = %q", got)
	}
}

func TestBindTargetSchema(t *testing.T) {
	single := map[string]any{
		"config": map[string]any{"sources": []any{map[string]any{"sourceRef": "a"}}},
	}
	bindTargetSchema(single)
	if got := single["config"].(map[string]any)["targetSchema"]; got != "shop" {
		t.Errorf("single source targetSchema = %v", got)
	}

	sharded := map[string]any{
		"config": map[string]any{"sources": []any{map[string]any{}, map[string]any{}}},
	}
	bindTargetSchema(sharded)
	if got := sharded["config"].(map[string]any)["targetSchema"]; got != "shop_merged" {
		t.Errorf("sharded targetSchema = %v", got)
	}

	explicit := map[string]any{
		"config": map[string]any{
			"targetSchema": "custom",
			"sources":      []any{map[string]any{}},
		},
	}
	bindTargetSchema(explicit)
	if got := explicit["config"].(map[string]any)["targetSchema"]; got != "custom" {
		t.Errorf("explicit targetSchema must be preserved, got %v", got)
	}

	bindTargetSchema(map[string]any{"rawYaml": "name: x"}) // must not panic
}
