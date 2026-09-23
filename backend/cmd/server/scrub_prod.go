//go:build !canary

package main

// canaryScrubOverride returns nil in production builds. DM_SCRUB is deliberately
// ignored here so no environment variable can disable the D16 credential zero-echo
// redline in a real deployment. The negative control lives behind `-tags canary`.
func canaryScrubOverride() *bool { return nil }
