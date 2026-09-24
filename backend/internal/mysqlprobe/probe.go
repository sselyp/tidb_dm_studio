// Package mysqlprobe performs a controlled, credential-safe connectivity and
// authentication probe against a MySQL/TiDB endpoint using only the standard
// library. It powers the platform's inbound diagnostic POST /datasources/test
// (D12-b): the caller decides policy (SSRF allow-list) and always learns
// reachable/authenticated, never the password.
package mysqlprobe

import (
	"context"
	"crypto/rand"
	"crypto/rsa"
	"crypto/sha1"
	"crypto/sha256"
	"crypto/x509"
	"encoding/binary"
	"encoding/pem"
	"errors"
	"io"
	"net"
	"strconv"
	"strings"
	"time"
)

const probeTimeout = 5 * time.Second

// Result is a credential-free summary of one probe attempt.
type Result struct {
	Reachable     bool
	Authenticated bool
	ServerVersion string
	LatencyMs     int
	// Err is a safe, password-free reason string ("" on success).
	Err string
}

// Probe dials host:port, completes a MySQL handshake with user/password and
// reports reachability, authentication and the server version banner. It never
// returns or logs the supplied password.
func Probe(ctx context.Context, host string, port int, user, password string) Result {
	var res Result
	start := time.Now()

	d := net.Dialer{Timeout: probeTimeout}
	conn, err := d.DialContext(ctx, "tcp", net.JoinHostPort(host, strconv.Itoa(port)))
	if err != nil {
		res.Err = "target unreachable: " + netErrReason(err)
		return res
	}
	defer conn.Close()
	res.Reachable = true

	if dl, ok := ctx.Deadline(); ok {
		_ = conn.SetDeadline(dl)
	} else {
		_ = conn.SetDeadline(time.Now().Add(probeTimeout))
	}

	version, ok, reason := handshake(conn, user, password)
	res.ServerVersion = version
	res.Authenticated = ok
	res.Err = reason
	res.LatencyMs = int(time.Since(start).Milliseconds())
	return res
}

func netErrReason(err error) string {
	var ne net.Error
	if errors.As(err, &ne) && ne.Timeout() {
		return "timeout"
	}
	return "connect failed"
}

// ---- wire helpers -----------------------------------------------------------

func readPacket(r io.Reader) (payload []byte, seq uint8, err error) {
	hdr := make([]byte, 4)
	if _, err = io.ReadFull(r, hdr); err != nil {
		return nil, 0, err
	}
	n := int(hdr[0]) | int(hdr[1])<<8 | int(hdr[2])<<16
	seq = hdr[3]
	if n == 0 {
		return []byte{}, seq, nil
	}
	if n > 1<<24-1 {
		return nil, seq, errors.New("packet too large")
	}
	payload = make([]byte, n)
	if _, err = io.ReadFull(r, payload); err != nil {
		return nil, seq, err
	}
	return payload, seq, nil
}

func writePacket(w io.Writer, seq uint8, payload []byte) error {
	hdr := []byte{byte(len(payload)), byte(len(payload) >> 8), byte(len(payload) >> 16), seq}
	if _, err := w.Write(hdr); err != nil {
		return err
	}
	_, err := w.Write(payload)
	return err
}

type greeting struct {
	serverVersion string
	scramble      []byte
	plugin        string
	caps          uint32
}

func parseGreeting(pkt []byte) (greeting, error) {
	var g greeting
	if len(pkt) < 1+1+4+8+1+2+1+2+2 {
		return g, errors.New("short greeting")
	}
	if pkt[0] != 10 {
		return g, errors.New("unsupported protocol version")
	}
	i := 1
	end := indexNUL(pkt[i:])
	if end < 0 {
		return g, errors.New("bad greeting")
	}
	g.serverVersion = string(pkt[i : i+end])
	i += end + 1
	if i+4 > len(pkt) {
		return g, errors.New("bad greeting")
	}
	i += 4 // connection id
	scr1 := pkt[i : i+8]
	i += 8
	i++ // filler
	capsLower := binary.LittleEndian.Uint16(pkt[i:])
	i += 2
	i++    // charset
	i += 2 // status flags
	capsUpper := binary.LittleEndian.Uint16(pkt[i:])
	i += 2
	g.caps = uint32(capsLower) | uint32(capsUpper)<<16

	authLen := 0
	if g.caps&clientPluginAuth != 0 {
		if i >= len(pkt) {
			return g, errors.New("bad greeting")
		}
		authLen = int(pkt[i])
	}
	i++ // auth plugin data length (or filler)
	i += 10

	if g.caps&clientSecureConnection != 0 {
		n := authLen - 8
		if n < 13 {
			n = 13
		}
		if i+n > len(pkt) {
			n = len(pkt) - i
		}
		if n < 0 {
			n = 0
		}
		part2 := pkt[i : i+n]
		i += n
		g.scramble = append(append([]byte{}, scr1...), part2...)
		if len(g.scramble) > 0 && g.scramble[len(g.scramble)-1] == 0 {
			g.scramble = g.scramble[:len(g.scramble)-1]
		}
	} else {
		g.scramble = append([]byte{}, scr1...)
	}

	if g.caps&clientPluginAuth != 0 && i < len(pkt) {
		if e := indexNUL(pkt[i:]); e > 0 {
			g.plugin = string(pkt[i : i+e])
		}
	}
	if g.plugin == "" {
		g.plugin = "mysql_native_password"
	}
	return g, nil
}

func indexNUL(b []byte) int {
	for i, c := range b {
		if c == 0 {
			return i
		}
	}
	return -1
}

const (
	clientLongPassword     = 1 << 0
	clientProtocol41       = 1 << 9
	clientTransactions     = 1 << 13
	clientSecureConnection = 1 << 15
	clientPluginAuth       = 1 << 19
)

func buildHandshakeResponse(g greeting, user, password string) ([]byte, string, error) {
	caps := uint32(clientLongPassword | clientProtocol41 | clientTransactions | clientSecureConnection | clientPluginAuth)
	plugin := g.plugin
	ar, err := authResponse(plugin, g.scramble, password)
	if err != nil {
		return nil, plugin, err
	}
	buf := make([]byte, 0, 64+len(user)+len(ar)+len(plugin))
	buf = appendLE32(buf, caps)
	buf = appendLE32(buf, 1<<24-1) // max packet size
	buf = append(buf, 45)          // utf8mb4_general_ci
	buf = append(buf, make([]byte, 23)...)
	buf = append(buf, user...)
	buf = append(buf, 0)
	buf = append(buf, byte(len(ar)))
	buf = append(buf, ar...)
	buf = append(buf, plugin...)
	buf = append(buf, 0)
	return buf, plugin, nil
}

func appendLE32(b []byte, v uint32) []byte {
	return append(b, byte(v), byte(v>>8), byte(v>>16), byte(v>>24))
}

func authResponse(plugin string, scramble []byte, password string) ([]byte, error) {
	if password == "" {
		return nil, nil
	}
	switch plugin {
	case "mysql_native_password", "":
		return nativeScramble(password, scramble), nil
	case "caching_sha2_password":
		return cachingSHA2Scramble(password, scramble), nil
	case "sha256_password":
		// Initial sha256_password reply is empty; the server then hands over its
		// public key via AuthMoreData and we encrypt (handled in the loop).
		return nil, nil
	default:
		return nil, errors.New("unsupported auth plugin")
	}
}

func nativeScramble(password string, scramble []byte) []byte {
	h1 := sha1.Sum([]byte(password))
	h2 := sha1.Sum(h1[:])
	h := sha1.New()
	h.Write(scramble)
	h.Write(h2[:])
	mask := h.Sum(nil)
	out := make([]byte, len(h1))
	for i := range h1 {
		out[i] = h1[i] ^ mask[i]
	}
	return out
}

func cachingSHA2Scramble(password string, scramble []byte) []byte {
	h1 := sha256.Sum256([]byte(password))
	h2 := sha256.Sum256(h1[:])
	h := sha256.New()
	h.Write(h2[:])
	h.Write(scramble)
	mask := h.Sum(nil)
	out := make([]byte, len(h1))
	for i := range h1 {
		out[i] = h1[i] ^ mask[i]
	}
	return out
}

func handshake(conn net.Conn, user, password string) (version string, ok bool, reason string) {
	pkt, _, err := readPacket(conn)
	if err != nil {
		return "", false, "no server greeting"
	}
	g, err := parseGreeting(pkt)
	if err != nil {
		return "", false, "bad server greeting"
	}
	resp, plugin, err := buildHandshakeResponse(g, user, password)
	if err != nil {
		return g.serverVersion, false, "unsupported auth plugin"
	}
	if err := writePacket(conn, 1, resp); err != nil {
		return g.serverVersion, false, "handshake write failed"
	}
	scramble := g.scramble

	for i := 0; i < 8; i++ {
		pkt, s, err := readPacket(conn)
		if err != nil {
			return g.serverVersion, false, "handshake aborted"
		}
		if len(pkt) == 0 {
			return g.serverVersion, false, "empty handshake packet"
		}
		switch pkt[0] {
		case 0x00:
			return g.serverVersion, true, ""
		case 0xff:
			return g.serverVersion, false, errMessage(pkt)
		case 0xfe:
			name, data, perr := parseAuthSwitch(pkt)
			if perr != nil {
				return g.serverVersion, false, "bad auth switch"
			}
			plugin = name
			if len(data) > 0 {
				scramble = data
			}
			ar, aerr := authResponse(plugin, scramble, password)
			if aerr != nil {
				return g.serverVersion, false, "unsupported auth plugin"
			}
			if err := writePacket(conn, s+1, ar); err != nil {
				return g.serverVersion, false, "handshake write failed"
			}
		case 0x01:
			if herr := handleAuthMore(conn, s, plugin, scramble, password, pkt); herr != nil {
				return g.serverVersion, false, herr.Error()
			}
		default:
			return g.serverVersion, false, "unexpected handshake packet"
		}
	}
	return g.serverVersion, false, "handshake did not complete"
}

// handleAuthMore processes an AuthMoreData (0x01) packet and drives the follow-up
// exchange (public-key request for full caching_sha2/sha256 auth).
func handleAuthMore(conn net.Conn, seq uint8, plugin string, scramble []byte, password string, pkt []byte) error {
	if plugin == "caching_sha2_password" && len(pkt) == 2 {
		switch pkt[1] {
		case 0x03: // fast auth success; an OK packet follows
			return nil
		case 0x04: // full authentication required
			if err := writePacket(conn, seq+1, []byte{0x02}); err != nil {
				return errors.New("handshake write failed")
			}
			keyPkt, s, err := readPacket(conn)
			if err != nil || len(keyPkt) < 2 || keyPkt[0] != 0x01 {
				return errors.New("missing server public key")
			}
			enc, err := encryptPassword(password, scramble, keyPkt[1:])
			if err != nil {
				return errors.New("public key encryption failed")
			}
			return writePacket(conn, s+1, enc)
		}
	}
	if plugin == "sha256_password" && len(pkt) > 1 {
		enc, err := encryptPassword(password, scramble, pkt[1:])
		if err != nil {
			return errors.New("public key encryption failed")
		}
		return writePacket(conn, seq+1, enc)
	}
	return errors.New("unsupported auth exchange")
}

func parseAuthSwitch(pkt []byte) (string, []byte, error) {
	if len(pkt) < 2 {
		return "", nil, errors.New("short auth switch")
	}
	body := pkt[1:]
	e := indexNUL(body)
	if e < 0 {
		return "", nil, errors.New("bad auth switch")
	}
	name := string(body[:e])
	data := body[e+1:]
	if len(data) > 0 && data[len(data)-1] == 0 {
		data = data[:len(data)-1]
	}
	return name, data, nil
}

func encryptPassword(password string, scramble []byte, pemKey []byte) ([]byte, error) {
	block, _ := pem.Decode(pemKey)
	if block == nil {
		return nil, errors.New("bad public key")
	}
	pub, err := x509.ParsePKIXPublicKey(block.Bytes)
	if err != nil {
		if rsaPub, rerr := x509.ParsePKCS1PublicKey(block.Bytes); rerr == nil {
			pub = rsaPub
		} else {
			return nil, err
		}
	}
	rsaPub, ok := pub.(*rsa.PublicKey)
	if !ok {
		return nil, errors.New("not an RSA key")
	}
	if len(scramble) == 0 {
		return nil, errors.New("empty nonce")
	}
	plain := make([]byte, len(password)+1)
	for i := 0; i < len(password); i++ {
		plain[i] = password[i] ^ scramble[i%len(scramble)]
	}
	plain[len(password)] = 0
	return rsa.EncryptOAEP(sha1.New(), rand.Reader, rsaPub, plain, nil)
}

// errMessage extracts the server message from an ERR packet. MySQL never echoes
// the password in this message.
func errMessage(pkt []byte) string {
	if len(pkt) < 3 {
		return "authentication failed"
	}
	i := 3
	if len(pkt) > 9 && pkt[3] == '#' {
		i = 9
	}
	return strings.TrimSpace(string(pkt[i:]))
}
