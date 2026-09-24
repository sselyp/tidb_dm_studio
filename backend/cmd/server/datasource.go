package main

import (
	"context"
	"encoding/json"
	"io"
	"net/http"
	"strconv"
	"strings"
	"time"

	"github.com/sselyp/tidb_dm_studio/backend/internal/mysqlprobe"
)

// fieldError mirrors the contract's FieldError (D11/D12). errorCode lives in
// either the E_* or the PRECHECK_* namespace.
type fieldError struct {
	FieldPath string `json:"fieldPath"`
	RuleCode  string `json:"ruleCode,omitempty"`
	ErrorCode string `json:"errorCode"`
	Message   string `json:"message"`
	Severity  string `json:"severity"`
}

// connectivity is the /datasources/test payload (ConnectivityResult). It is
// built from scratch on every response, so it can never echo an inbound
// credential (D16): `security` and the password input channel are absent.
type connectivity struct {
	Valid         bool         `json:"valid"`
	Reachable     bool         `json:"reachable"`
	Authenticated bool         `json:"authenticated"`
	LatencyMs     int          `json:"latencyMs,omitempty"`
	ServerVersion string       `json:"serverVersion,omitempty"`
	Errors        []fieldError `json:"errors"`
}

// handleDataSourceTest implements the controlled egress diagnostic (D12-b).
// Policy/SSRF refusal → 422 E_TARGET_NOT_ALLOWED and never 200; an attempt that
// actually ran reports 200 + data.valid (reachability is authoritative). A body
// that is not a JSON object → 400.
func handleDataSourceTest(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost {
		fail(w, http.StatusNotFound, 40401, "E_NOT_FOUND")
		return
	}
	raw, _ := io.ReadAll(io.LimitReader(r.Body, 1<<20))
	var body map[string]any
	if err := json.Unmarshal(raw, &body); err != nil || body == nil {
		fail(w, http.StatusBadRequest, 40001, "E_BAD_REQUEST")
		return
	}

	// Body value wins; the out-of-repo target env (then process env) is the
	// fallback so an operator can probe the POC target without a datasource row.
	te := loadTargetEnv()
	host := strField(body, "host", te.Host)
	user := strField(body, "username", te.User)
	pass := strField(body, "password", te.Password)
	port := intField(body, "port", atoiSafe(te.Port))

	if host == "" || port == 0 {
		ok(w, http.StatusOK, connectivity{
			Valid: false,
			Errors: []fieldError{{
				FieldPath: "/host",
				RuleCode:  "REQUIRED",
				ErrorCode: "E_FIELD_REQUIRED",
				Message:   "target host/port is not configured",
				Severity:  "error",
			}},
		})
		return
	}

	if !loadSSRFPolicy().allows(host) {
		// Fail closed: an unlisted host is a refusal, never a 200 diagnostic.
		fail(w, http.StatusUnprocessableEntity, 42202, "E_TARGET_NOT_ALLOWED")
		return
	}

	ctx, cancel := context.WithTimeout(r.Context(), 6*time.Second)
	defer cancel()
	res := mysqlprobe.Probe(ctx, host, port, user, pass)

	out := connectivity{
		Valid:         res.Reachable && res.Authenticated,
		Reachable:     res.Reachable,
		Authenticated: res.Authenticated,
		LatencyMs:     res.LatencyMs,
		ServerVersion: res.ServerVersion,
		Errors:        []fieldError{},
	}
	switch {
	case !res.Reachable:
		out.Errors = append(out.Errors, fieldError{
			FieldPath: "/host",
			RuleCode:  "EXISTENCE",
			ErrorCode: "PRECHECK_SOURCE_UNREACHABLE",
			Message:   "target unreachable",
			Severity:  "error",
		})
	case !res.Authenticated:
		out.Errors = append(out.Errors, fieldError{
			FieldPath: "/username",
			RuleCode:  "EXISTENCE",
			ErrorCode: "PRECHECK_TARGET_AUTH_FAILED",
			Message:   "target authentication failed",
			Severity:  "error",
		})
	}
	ok(w, http.StatusOK, out)
}

func strField(m map[string]any, key, fallback string) string {
	if v, ok := m[key].(string); ok && strings.TrimSpace(v) != "" {
		return strings.TrimSpace(v)
	}
	return fallback
}

func intField(m map[string]any, key string, fallback int) int {
	switch v := m[key].(type) {
	case float64:
		return int(v)
	case json.Number:
		if n, err := v.Int64(); err == nil {
			return int(n)
		}
	case int:
		return v
	case string:
		if n, err := strconv.Atoi(strings.TrimSpace(v)); err == nil {
			return n
		}
	}
	return fallback
}

func atoiSafe(s string) int {
	n, err := strconv.Atoi(strings.TrimSpace(s))
	if err != nil {
		return 0
	}
	return n
}
