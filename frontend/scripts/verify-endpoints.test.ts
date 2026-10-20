import fs from "node:fs";

import { describe, expect, it } from "vitest";
import { parse as parseYaml } from "yaml";

/**
 * Frontend <-> contract path completeness. Guards against the API client calling
 * a path that the frozen `api/openapi.yaml` does not define (the failure mode the
 * backend/P1 gap makes easy to miss until joint-integration). Only path-level:
 * method/status semantics are pinned by the contract gate on the API side.
 */
const endpointsUrl = new URL("../src/api/endpoints.ts", import.meta.url);
const specUrl = new URL("../../api/openapi.yaml", import.meta.url);

const normalize = (p: string) => p.split("?")[0].replace(/\$\{[^}]*\}/g, "{p}");

const calledPaths = [
  ...fs
    .readFileSync(endpointsUrl, "utf8")
    .matchAll(/["'`](\/[^"'`\s]+)/g),
].map((m) => normalize(m[1]));

const spec = parseYaml(fs.readFileSync(specUrl, "utf8")) as {
  paths: Record<string, unknown>;
};
const contractPaths = new Set(
  Object.keys(spec.paths).map((p) => normalize(p.replace(/\{[^}]+\}/g, "{p}"))),
);

/**
 * Explicit pin (review seq=87): a contract endpoint that is intentionally not
 * consumed by the frontend must be listed here, so adding an unconsumed endpoint
 * (e.g. /metrics) fails loudly and points at this file instead of looking like a
 * client regression. The file also documents *why* a path is unconsumed.
 */
const allowlistUrl = new URL("./unconsumed-paths.json", import.meta.url);
const unconsumedAllowlist = new Set<string>(
  (JSON.parse(fs.readFileSync(allowlistUrl, "utf8")) as { paths: string[] }).paths,
);

describe("frontend API client covers only contract paths", () => {
  it("extracts a non-trivial number of called paths", () => {
    expect(new Set(calledPaths).size).toBeGreaterThanOrEqual(16);
  });

  it("every called path exists in api/openapi.yaml", () => {
    const unknown = [...new Set(calledPaths)].filter(
      (p) => !contractPaths.has(p),
    );
    expect(unknown).toEqual([]);
  });

  it("unconsumed contract paths exactly match the pinned allowlist", () => {
    const unused = [...contractPaths].filter((p) => !calledPaths.includes(p));
    expect(new Set(unused)).toEqual(unconsumedAllowlist);
  });

  it("every allowlist entry is a real, currently-unconsumed contract path", () => {
    for (const p of unconsumedAllowlist) {
      expect(contractPaths.has(p)).toBe(true);
      expect(calledPaths).not.toContain(p);
    }
  });
});
