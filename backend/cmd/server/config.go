package main

import (
	"net"
	"os"
	"strings"
)

// targetEnv is the effective downstream TiDB target credential set. Values are
// read from an out-of-repo env file (the POC hand-off channel) with the process
// environment as fallback. It is never logged and never echoed in a response.
type targetEnv struct {
	Host     string
	Port     string
	User     string
	Password string
}

func targetEnvFile() string {
	return env("DM_TARGET_ENV_FILE", "/data/dm-mysql/tidb-target.env")
}

// loadTargetEnv resolves TIDB_TARGET_* with precedence: external file first
// (chmod 600, not in the repo), then process environment as a fallback. An
// absent/unreadable file is not an error; the caller still fails closed on an
// empty host.
func loadTargetEnv() targetEnv {
	vals := map[string]string{}
	if b, err := os.ReadFile(targetEnvFile()); err == nil {
		for _, line := range strings.Split(string(b), "\n") {
			line = strings.TrimSpace(line)
			if line == "" || strings.HasPrefix(line, "#") {
				continue
			}
			k, v, ok := strings.Cut(line, "=")
			if !ok {
				continue
			}
			k = strings.TrimSpace(k)
			v = strings.TrimSpace(v)
			v = strings.Trim(v, `"'`)
			if k != "" {
				vals[k] = v
			}
		}
	}
	get := func(key string) string {
		if v, ok := vals[key]; ok && v != "" {
			return v
		}
		return os.Getenv(key)
	}
	return targetEnv{
		Host:     get("TIDB_TARGET_HOST"),
		Port:     get("TIDB_TARGET_PORT"),
		User:     get("TIDB_TARGET_USER"),
		Password: get("TIDB_TARGET_PASSWORD"),
	}
}

// ssrfPolicy is a deny-by-default egress allow-list for /datasources/test. Hosts
// are supplied by deployment configuration (DM_SSRF_ALLOWED_HOSTS / _CIDRS), so
// no operational address is hardcoded in the source tree.
type ssrfPolicy struct {
	hosts map[string]bool
	nets  []*net.IPNet
}

func loadSSRFPolicy() ssrfPolicy {
	p := ssrfPolicy{hosts: map[string]bool{}}
	for _, h := range strings.Split(os.Getenv("DM_SSRF_ALLOWED_HOSTS"), ",") {
		if h = strings.ToLower(strings.TrimSpace(h)); h != "" {
			p.hosts[h] = true
		}
	}
	for _, c := range strings.Split(os.Getenv("DM_SSRF_ALLOWED_CIDRS"), ",") {
		c = strings.TrimSpace(c)
		if c == "" {
			continue
		}
		if _, n, err := net.ParseCIDR(c); err == nil {
			p.nets = append(p.nets, n)
		}
	}
	return p
}

// allows reports whether a probe to host may be attempted. Exact host match or
// every resolved address inside an allowed CIDR is required; unresolvable hosts
// and partial CIDR matches fail closed (DNS-rebinding safe).
func (p ssrfPolicy) allows(host string) bool {
	h := strings.ToLower(strings.TrimSpace(host))
	if h == "" {
		return false
	}
	if p.hosts[h] {
		return true
	}
	if ip := net.ParseIP(h); ip != nil {
		return p.inAnyNet(ip)
	}
	ips, err := net.LookupIP(h)
	if err != nil || len(ips) == 0 {
		return false
	}
	for _, ip := range ips {
		if !p.inAnyNet(ip) {
			return false
		}
	}
	return true
}

func (p ssrfPolicy) inAnyNet(ip net.IP) bool {
	for _, n := range p.nets {
		if n.Contains(ip) {
			return true
		}
	}
	return false
}
