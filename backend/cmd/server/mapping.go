package main

import "strings"

// targetSchemaB is the frozen POC target-schema mapping (option B, zero grant
// change): single-source tasks land in `shop`, sharded tasks merge into
// `shop_merged`. Unknown topologies are unmapped (ok=false).
func targetSchemaB(topology string) (string, bool) {
	switch strings.ToLower(strings.TrimSpace(topology)) {
	case "single":
		return "shop", true
	case "shards", "sharded", "merge", "merged":
		return "shop_merged", true
	}
	return "", false
}

// topologyForSources derives the mapping-B topology from a task's source count.
func topologyForSources(n int) string {
	if n <= 1 {
		return "single"
	}
	return "shards"
}

// bindTargetSchema materializes mapping B onto a task config. It derives the
// topology from the source count and only fills `config.targetSchema` when the
// client did not set one; the write side keeps its explicit value.
func bindTargetSchema(body map[string]any) {
	cfg, ok := body["config"].(map[string]any)
	if !ok {
		return
	}
	if _, exists := cfg["targetSchema"]; exists {
		return
	}
	srcs, ok := cfg["sources"].([]any)
	if !ok {
		return
	}
	if name, ok := targetSchemaB(topologyForSources(len(srcs))); ok {
		cfg["targetSchema"] = name
	}
}
