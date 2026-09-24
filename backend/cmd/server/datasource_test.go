package main

import (
	"bytes"
	"encoding/json"
	"fmt"
	"io"
	"net"
	"net/http"
	"net/http/httptest"
	"path/filepath"
	"strings"
	"testing"
)

func wireWrite(c net.Conn, seq byte, payload []byte) {
	hdr := []byte{byte(len(payload)), byte(len(payload) >> 8), byte(len(payload) >> 16), seq}
	_, _ = c.Write(append(hdr, payload...))
}

func wireRead(c net.Conn) {
	hdr := make([]byte, 4)
	if _, err := io.ReadFull(c, hdr); err != nil {
		return
	}
	n := int(hdr[0]) | int(hdr[1])<<8 | int(hdr[2])<<16
	if n > 0 {
		_, _ = io.ReadFull(c, make([]byte, n))
	}
}

// startFakeMySQL accepts one handshake and answers OK (native auth).
func startFakeMySQL(t *testing.T) (string, int) {
	t.Helper()
	ln, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		t.Fatalf("listen: %v", err)
	}
	t.Cleanup(func() { _ = ln.Close() })
	go func() {
		c, err := ln.Accept()
		if err != nil {
			return
		}
		defer c.Close()
		scramble := []byte("0123456789abcdefghij")
		p := []byte{10}
		p = append(p, []byte("5.7.25-TiDB-v7.1.9")...)
		p = append(p, 0)
		p = append(p, 1, 0, 0, 0)
		p = append(p, scramble[:8]...)
		p = append(p, 0)
		p = append(p, 0xff, 0xff)
		p = append(p, 45)
		p = append(p, 2, 0)
		p = append(p, 0xff, 0xff)
		p = append(p, 21)
		p = append(p, make([]byte, 10)...)
		p = append(p, scramble[8:]...)
		p = append(p, 0)
		p = append(p, []byte("mysql_native_password")...)
		p = append(p, 0)
		wireWrite(c, 0, p)
		wireRead(c)
		wireWrite(c, 2, []byte{0x00, 0x00, 0x00, 0x02, 0x00, 0x00, 0x00})
	}()
	addr := ln.Addr().(*net.TCPAddr)
	return "127.0.0.1", addr.Port
}

func doTest(t *testing.T, raw string) (int, map[string]any) {
	t.Helper()
	req := httptest.NewRequest(http.MethodPost, "/api/datasources/test", strings.NewReader(raw))
	rec := httptest.NewRecorder()
	handler(rec, req)
	var body map[string]any
	_ = json.Unmarshal(rec.Body.Bytes(), &body)
	return rec.Code, body
}

func TestDataSourceTestBadBody(t *testing.T) {
	t.Setenv("DM_SSRF_ALLOWED_HOSTS", "127.0.0.1")
	if code, _ := doTest(t, "not-json"); code != http.StatusBadRequest {
		t.Errorf("code = %d want 400", code)
	}
	if code, _ := doTest(t, `[1,2,3]`); code != http.StatusBadRequest {
		t.Errorf("array body code = %d want 400", code)
	}
}

func TestDataSourceTestSSRFDenied(t *testing.T) {
	t.Setenv("DM_SSRF_ALLOWED_HOSTS", "127.0.0.1")
	code, body := doTest(t, `{"host":"198.51.100.7","port":4000,"username":"u","password":"p"}`)
	if code != http.StatusUnprocessableEntity {
		t.Fatalf("code = %d want 422", code)
	}
	if body["message"] != "E_TARGET_NOT_ALLOWED" {
		t.Errorf("message = %v", body["message"])
	}
}

func TestDataSourceTestUnreachable(t *testing.T) {
	t.Setenv("DM_SSRF_ALLOWED_HOSTS", "127.0.0.1")
	ln, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		t.Fatalf("listen: %v", err)
	}
	port := ln.Addr().(*net.TCPAddr).Port
	_ = ln.Close()

	code, body := doTest(t, fmt.Sprintf(`{"host":"127.0.0.1","port":%d}`, port))
	if code != http.StatusOK {
		t.Fatalf("code = %d want 200 (diagnostic)", code)
	}
	data, _ := body["data"].(map[string]any)
	if data == nil || data["valid"] != false {
		t.Fatalf("valid should be false, body=%v", body)
	}
	errs, _ := data["errors"].([]any)
	if len(errs) != 1 {
		t.Fatalf("errors = %v", data["errors"])
	}
	first, _ := errs[0].(map[string]any)
	if first["errorCode"] != "PRECHECK_SOURCE_UNREACHABLE" {
		t.Errorf("errorCode = %v", first["errorCode"])
	}
}

func TestDataSourceTestMissingTarget(t *testing.T) {
	t.Setenv("DM_SSRF_ALLOWED_HOSTS", "127.0.0.1")
	t.Setenv("DM_TARGET_ENV_FILE", filepath.Join(t.TempDir(), "absent.env"))
	t.Setenv("TIDB_TARGET_HOST", "")
	t.Setenv("TIDB_TARGET_PORT", "")
	code, body := doTest(t, `{}`)
	if code != http.StatusOK {
		t.Fatalf("code = %d want 200", code)
	}
	data, _ := body["data"].(map[string]any)
	errs, _ := data["errors"].([]any)
	first, _ := errs[0].(map[string]any)
	if first["errorCode"] != "E_FIELD_REQUIRED" {
		t.Errorf("errorCode = %v", first["errorCode"])
	}
}

func TestDataSourceTestOKAndNoEcho(t *testing.T) {
	host, port := startFakeMySQL(t)
	t.Setenv("DM_SSRF_ALLOWED_HOSTS", host)
	pw := "hunter2"
	raw := fmt.Sprintf(`{"host":%q,"port":%d,"username":"dm_verify","password":%q}`, host, port, pw)

	req := httptest.NewRequest(http.MethodPost, "/api/datasources/test", bytes.NewReader([]byte(raw)))
	rec := httptest.NewRecorder()
	handler(rec, req)
	if rec.Code != http.StatusOK {
		t.Fatalf("code = %d body=%s", rec.Code, rec.Body.String())
	}
	if strings.Contains(rec.Body.String(), pw) {
		t.Errorf("response leaked the password")
	}
	var body map[string]any
	_ = json.Unmarshal(rec.Body.Bytes(), &body)
	data, _ := body["data"].(map[string]any)
	if data["valid"] != true || data["reachable"] != true || data["authenticated"] != true {
		t.Fatalf("unexpected data: %v", data)
	}
	if data["serverVersion"] != "5.7.25-TiDB-v7.1.9" {
		t.Errorf("serverVersion = %v", data["serverVersion"])
	}
}
