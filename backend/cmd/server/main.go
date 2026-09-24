// Minimal AC-SEC-capable proxy bootstrap for the TiDB DM visualization platform.
//
// Scope: enough surface for the credential canary (AC-SEC-01..04) to run against
// a live dm-master: read /api/tasks*, write a task config, and never echo a
// credential (own-path or DM passthrough). P1 adds the controlled egress
// diagnostic POST /api/datasources/test (see datasource.go). The remaining P1
// surface (auth/CSRF/state machine/full validation) is still pending.
//
// Env:
//   DM_WEB_LISTEN       listen address            (default 0.0.0.0:8080)
//   DM_MASTER_ADDRS     dm-master base URL        (default http://127.0.0.1:8261;
//                       AC-SEC sets DM_MASTER_ADDRS=http://<dm-host>:8261)
//   DM_UPSTREAM_PREFIX  dm-master API prefix      (default /api/v1)
//   DM_SCRUB            negative control only; ignored by default, honored ONLY in
//                       `go build -tags canary` builds (see scrub_canary.go)
package main

import (
	"encoding/json"
	"io"
	"log"
	"net/http"
	"os"
	"strings"
	"sync"
	"time"
)

var (
	listenAddr = env("DM_WEB_LISTEN", "0.0.0.0:8080")
	upstream   = env("DM_MASTER_ADDRS", "http://127.0.0.1:8261")
	upPrefix   = env("DM_UPSTREAM_PREFIX", "/api/v1")
	client     = &http.Client{Timeout: 10 * time.Second}

	// Credential stripping is always on. DM_SCRUB=off is honored ONLY in canary
	// builds (`go build -tags canary`), never in a production binary, so the D16
	// zero-echo redline cannot be disabled by a leaked environment variable.
	scrubEnabled = true

	mu    sync.RWMutex
	store = map[string]map[string]any{}
)

func init() {
	if o := canaryScrubOverride(); o != nil {
		scrubEnabled = *o
	}
}

func env(k, def string) string {
	if v := os.Getenv(k); v != "" {
		return v
	}
	return def
}

// Credential-key rule, kept byte-for-byte with the contract's single source of
// truth `scripts/ci/check_contract.py::_is_credential_key` (SENSITIVE_KEY_TOKENS /
// NON_SECRET_MARKERS). D16 zero-echo must agree between the spec gate and the
// runtime scrub, or the write side would let an F2 name (secret/token/apikey/etc.)
// through. Keep these two lists in lockstep with the checker.
var sensitiveKeyTokens = []string{
	"password", "passwd", "secret", "token", "credential", "target_config",
	"api_key", "apikey", "access_key", "accesskey", "private_key", "privatekey",
	"client_secret", "dsn", "cert",
}

var nonSecretMarkers = []string{
	"policy", "minlength", "min_length", "maxlength", "max_length", "length",
	"ttl", "expire", "expiry", "timeout", "duration", "interval",
	"algorithm", "regex", "pattern", "format", "enabled", "count",
	"must", "required", "path", "file", "files", "dir", "name", "type",
	"url", "uri", "endpoint", "version", "issuer", "audience", "csrf",
}

// hasCredKey reports whether a JSON key holds a credential *value* (not a
// policy/config field about one). Mirrors the contract's `_is_credential_key`.
func hasCredKey(k string) bool {
	lk := strings.ToLower(k)
	if !containsAny(lk, sensitiveKeyTokens) {
		return false
	}
	if containsAny(lk, nonSecretMarkers) {
		return false
	}
	return true
}

func containsAny(s string, subs []string) bool {
	for _, sub := range subs {
		if strings.Contains(s, sub) {
			return true
		}
	}
	return false
}

// scrub drops every credential value in place; values are deleted, never masked
// in place, so no fragment of the secret can survive.
func scrub(v any) any {
	switch t := v.(type) {
	case map[string]any:
		for k, val := range t {
			if hasCredKey(k) {
				delete(t, k)
				continue
			}
			t[k] = scrub(val)
		}
		return t
	case []any:
		for i, val := range t {
			t[i] = scrub(val)
		}
		return t
	default:
		return v
	}
}

func writeJSON(w http.ResponseWriter, status int, v any) {
	w.Header().Set("Content-Type", "application/json; charset=utf-8")
	w.WriteHeader(status)
	_ = json.NewEncoder(w).Encode(v)
}

func fail(w http.ResponseWriter, status, code int, name string) {
	writeJSON(w, status, map[string]any{
		"code":    code,
		"data":    map[string]any{"errors": []any{}},
		"message": name,
	})
}

func ok(w http.ResponseWriter, status int, data any) {
	writeJSON(w, status, map[string]any{"code": 0, "data": data, "message": "ok"})
}

func fetch(path string) (int, []byte, error) {
	req, err := http.NewRequest(http.MethodGet, upstream+upPrefix+path, nil)
	if err != nil {
		return 0, nil, err
	}
	resp, err := client.Do(req)
	if err != nil {
		return 0, nil, err
	}
	defer resp.Body.Close()
	b, _ := io.ReadAll(resp.Body)
	return resp.StatusCode, b, nil
}

func sanitized(body []byte) any {
	var v any
	if err := json.Unmarshal(body, &v); err != nil {
		return nil
	}
	if scrubEnabled {
		return scrub(v)
	}
	return v
}

func nameFromPath(rest string) (name, sub string) {
	parts := strings.Split(strings.Trim(rest, "/"), "/")
	if len(parts) < 2 {
		return "", ""
	}
	name = parts[1]
	if len(parts) > 2 {
		sub = parts[2]
	}
	return
}

func handleTasks(w http.ResponseWriter, r *http.Request, rest string) {
	name, sub := nameFromPath(rest)

	switch {
	case r.Method == http.MethodGet && name == "":
		st, body, err := fetch("/tasks")
		if err != nil {
			fail(w, http.StatusBadGateway, 50201, "E_DM_UNAVAILABLE")
			return
		}
		writeJSON(w, st, sanitized(body))
	case r.Method == http.MethodGet && name != "" && sub == "":
		if v := stored(name); v != nil {
			ok(w, http.StatusOK, v)
			return
		}
		st, body, err := fetch("/tasks/" + name)
		if err != nil {
			fail(w, http.StatusBadGateway, 50201, "E_DM_UNAVAILABLE")
			return
		}
		writeJSON(w, st, sanitized(body))
	case r.Method == http.MethodGet && sub == "status":
		_, body, err := fetch("/tasks/" + name + "/status")
		if err != nil {
			fail(w, http.StatusBadGateway, 50201, "E_DM_UNAVAILABLE")
			return
		}
		ok(w, http.StatusOK, statusData(body))
	case r.Method == http.MethodGet && sub == "yaml":
		if v := stored(name); v != nil {
			w.Header().Set("Content-Type", "text/yaml; charset=utf-8")
			w.WriteHeader(http.StatusOK)
			enc := json.NewEncoder(w)
			enc.SetIndent("", "  ")
			_ = enc.Encode(v)
			return
		}
		fail(w, http.StatusNotFound, 40401, "E_NOT_FOUND")
	case r.Method == http.MethodPut || r.Method == http.MethodPost:
		body, _ := io.ReadAll(io.LimitReader(r.Body, 1<<20))
		var v map[string]any
		if err := json.Unmarshal(body, &v); err != nil {
			fail(w, http.StatusUnprocessableEntity, 42201, "E_VALIDATION_FAILED")
			return
		}
		if scrubEnabled {
			scrub(v)
		}
		if n, _ := v["name"].(string); n != "" {
			name = n
		}
		if name == "" {
			fail(w, http.StatusUnprocessableEntity, 42201, "E_VALIDATION_FAILED")
			return
		}
		bindTargetSchema(v)
		mu.Lock()
		store[name] = v
		mu.Unlock()
		status := http.StatusOK
		if r.Method == http.MethodPost && sub == "" && strings.HasSuffix(rest, "/tasks") {
			status = http.StatusCreated
		}
		ok(w, status, v)
	default:
		fail(w, http.StatusNotFound, 40401, "E_NOT_FOUND")
	}
}

func stored(name string) map[string]any {
	mu.RLock()
	defer mu.RUnlock()
	return store[name]
}

// platformState derives the platform state from DM's native TaskStage + lastOp +
// lastError (x-dm-compat.taskStageMapping.derivation, architect seq=32):
// human intent first, then lastError; unclassifiable Stopped defaults to stopped.
func platformState(native, lastOp string, lastErr any) string {
	switch native {
	case "Running":
		return "running"
	case "Finished":
		return "finished"
	case "Stopped":
		if lastOp == "pause" {
			return "paused"
		}
		if lastOp != "stop" && lastErr != nil && lastErr != "" {
			return "failed"
		}
		return "stopped"
	default:
		return "new" // 平台已建、DM 无该任务
	}
}

// allowedActions is the server-authoritative action set (D15); the frontend must
// not re-derive it from state.
func allowedActions(state string) []string {
	switch state {
	case "new", "stopped", "failed":
		return []string{"start", "delete"}
	case "running":
		return []string{"pause", "stop"}
	case "paused":
		return []string{"resume", "stop", "delete"}
	case "finished":
		return []string{"delete"} // 正常完成，仅日志/导出
	}
	return []string{}
}

func pickStage(cur, next string) string {
	rank := map[string]int{"": 0, "Stopped": 1, "Finished": 2, "Running": 3}
	if rank[next] > rank[cur] {
		return next
	}
	return cur
}

func statusData(body []byte) map[string]any {
	var env struct {
		Data []map[string]any `json:"data"`
	}
	_ = json.Unmarshal(body, &env)
	stage := ""
	var lag, lastErr any
	for _, row := range env.Data {
		s, _ := row["stage"].(string)
		stage = pickStage(stage, s)
		if ss, ok := row["sync_status"].(map[string]any); ok {
			if v, ok := ss["seconds_behind_master"]; ok {
				lag = v
			}
		}
		if e, ok := row["last_error"]; ok && e != nil && e != "" {
			lastErr = e
		}
	}
	state := platformState(stage, "", lastErr)
	return map[string]any{
		"state":          state,
		"stage":          stage,
		"nativeState":    stage,
		"allowedActions": allowedActions(state),
		"lag":            lag,
		"lastError":      lastErr,
		"updatedAt":      time.Now().UTC().Format(time.RFC3339),
	}
}

func handler(w http.ResponseWriter, r *http.Request) {
	log.Printf("%s %s", r.Method, r.URL.Path) // path only; never the body
	p := r.URL.Path
	if p == "/api/healthz" || p == "/healthz" {
		writeJSON(w, http.StatusOK, map[string]any{"status": "ok"})
		return
	}
	if p == "/api/tasks" || strings.HasPrefix(p, "/api/tasks/") {
		handleTasks(w, r, strings.TrimPrefix(p, "/api"))
		return
	}
	if p == "/api/datasources/test" {
		handleDataSourceTest(w, r)
		return
	}
	fail(w, http.StatusNotFound, 40401, "E_NOT_FOUND")
}

func main() {
	log.Printf("dm-web proxy listening on %s -> %s%s", listenAddr, upstream, upPrefix)
	if err := http.ListenAndServe(listenAddr, http.HandlerFunc(handler)); err != nil {
		log.Fatal(err)
	}
}
