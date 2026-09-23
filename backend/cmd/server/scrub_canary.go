//go:build canary

package main

import "os"

// canaryScrubOverride is compiled in ONLY with `-tags canary` (test/negative control).
// It lets DM_SCRUB=off disable stripping so the AC-SEC canary gate can prove it really
// detects a leak (reverse control must exit 1). Never ship a binary built this way.
func canaryScrubOverride() *bool {
	if os.Getenv("DM_SCRUB") == "off" {
		v := false
		return &v
	}
	return nil
}
