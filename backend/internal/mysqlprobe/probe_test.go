package mysqlprobe

import (
	"context"
	"crypto/rand"
	"crypto/rsa"
	"crypto/x509"
	"encoding/pem"
	"net"
	"testing"
)

func testScramble() []byte {
	return []byte("0123456789abcdefghij") // 20 bytes
}

func greetingBytes(plugin string, scramble []byte) []byte {
	p := []byte{10}
	p = append(p, []byte("5.7.25-TiDB-v7.1.9")...)
	p = append(p, 0)
	p = append(p, 1, 0, 0, 0) // connection id
	p = append(p, scramble[:8]...)
	p = append(p, 0)          // filler
	p = append(p, 0xff, 0xff) // caps lower
	p = append(p, 45)         // charset
	p = append(p, 2, 0)       // status
	p = append(p, 0xff, 0xff) // caps upper
	p = append(p, 21)         // auth plugin data len
	p = append(p, make([]byte, 10)...)
	p = append(p, scramble[8:20]...)
	p = append(p, 0) // part-2 NUL terminator
	p = append(p, plugin...)
	p = append(p, 0)
	return p
}

func srvWrite(c net.Conn, seq byte, payload []byte) {
	_ = writePacket(c, seq, payload)
}

func srvRead(c net.Conn) ([]byte, byte) {
	p, s, err := readPacket(c)
	if err != nil {
		return nil, 0
	}
	return p, s
}

func TestParseGreeting(t *testing.T) {
	g, err := parseGreeting(greetingBytes("caching_sha2_password", testScramble()))
	if err != nil {
		t.Fatalf("parse: %v", err)
	}
	if g.serverVersion != "5.7.25-TiDB-v7.1.9" {
		t.Errorf("version = %q", g.serverVersion)
	}
	if g.plugin != "caching_sha2_password" {
		t.Errorf("plugin = %q", g.plugin)
	}
	if len(g.scramble) != 20 {
		t.Errorf("scramble len = %d want 20", len(g.scramble))
	}
}

func TestScrambleLengths(t *testing.T) {
	if got := len(nativeScramble("pw", testScramble())); got != 20 {
		t.Errorf("native len = %d", got)
	}
	if got := len(cachingSHA2Scramble("pw", testScramble())); got != 32 {
		t.Errorf("caching_sha2 len = %d", got)
	}
	if got, _ := authResponse("mysql_native_password", testScramble(), ""); got != nil {
		t.Errorf("empty password must yield nil auth response")
	}
	if _, err := authResponse("weird_plugin", testScramble(), "pw"); err == nil {
		t.Errorf("unknown plugin must error")
	}
}

// fakeServer accepts one connection and runs script(conn).
func fakeServer(t *testing.T, script func(net.Conn)) (host string, port int) {
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
		script(c)
	}()
	addr := ln.Addr().(*net.TCPAddr)
	return "127.0.0.1", addr.Port
}

func TestProbeNativeOK(t *testing.T) {
	host, port := fakeServer(t, func(c net.Conn) {
		srvWrite(c, 0, greetingBytes("mysql_native_password", testScramble()))
		srvRead(c) // handshake response
		srvWrite(c, 2, []byte{0x00, 0x00, 0x00, 0x02, 0x00, 0x00, 0x00})
	})
	res := Probe(context.Background(), host, port, "dm_verify", "hunter2")
	if !res.Reachable || !res.Authenticated {
		t.Fatalf("res = %+v", res)
	}
	if res.ServerVersion != "5.7.25-TiDB-v7.1.9" {
		t.Errorf("version = %q", res.ServerVersion)
	}
}

func TestProbeAuthError(t *testing.T) {
	host, port := fakeServer(t, func(c net.Conn) {
		srvWrite(c, 0, greetingBytes("mysql_native_password", testScramble()))
		srvRead(c)
		errPkt := append([]byte{0xff, 0x15, 0x04, '#'}, []byte("28000Access denied")...)
		srvWrite(c, 2, errPkt)
	})
	res := Probe(context.Background(), host, port, "dm_verify", "wrong")
	if !res.Reachable || res.Authenticated {
		t.Fatalf("res = %+v", res)
	}
	if res.Err == "" {
		t.Errorf("expected a safe error reason")
	}
}

func TestProbeCachingSHA2FastPath(t *testing.T) {
	host, port := fakeServer(t, func(c net.Conn) {
		srvWrite(c, 0, greetingBytes("caching_sha2_password", testScramble()))
		srvRead(c)
		srvWrite(c, 2, []byte{0x01, 0x03}) // fast auth success
		srvWrite(c, 3, []byte{0x00, 0x00, 0x00, 0x02, 0x00, 0x00, 0x00})
	})
	res := Probe(context.Background(), host, port, "dm_verify", "hunter2")
	if !res.Authenticated {
		t.Fatalf("res = %+v", res)
	}
}

func TestProbeCachingSHA2FullAuth(t *testing.T) {
	key, err := rsa.GenerateKey(rand.Reader, 2048)
	if err != nil {
		t.Fatalf("rsa: %v", err)
	}
	der, err := x509.MarshalPKIXPublicKey(&key.PublicKey)
	if err != nil {
		t.Fatalf("marshal: %v", err)
	}
	pemKey := pem.EncodeToMemory(&pem.Block{Type: "PUBLIC KEY", Bytes: der})

	host, port := fakeServer(t, func(c net.Conn) {
		srvWrite(c, 0, greetingBytes("caching_sha2_password", testScramble()))
		srvRead(c)                         // handshake response
		srvWrite(c, 2, []byte{0x01, 0x04}) // full auth required
		req, _ := srvRead(c)               // public key request (0x02)
		if len(req) != 1 || req[0] != 0x02 {
			t.Errorf("expected public key request, got %v", req)
		}
		srvWrite(c, 4, append([]byte{0x01}, pemKey...))
		srvRead(c) // encrypted password
		srvWrite(c, 6, []byte{0x00, 0x00, 0x00, 0x02, 0x00, 0x00, 0x00})
	})
	res := Probe(context.Background(), host, port, "dm_verify", "hunter2")
	if !res.Authenticated {
		t.Fatalf("res = %+v", res)
	}
}

func TestProbeUnreachable(t *testing.T) {
	ln, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		t.Fatalf("listen: %v", err)
	}
	port := ln.Addr().(*net.TCPAddr).Port
	_ = ln.Close() // free the port so the dial is refused
	res := Probe(context.Background(), "127.0.0.1", port, "u", "p")
	if res.Reachable {
		t.Fatalf("expected unreachable, got %+v", res)
	}
	if res.Err == "" {
		t.Errorf("expected a reason")
	}
}
