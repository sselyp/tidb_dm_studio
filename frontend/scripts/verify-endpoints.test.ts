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

  it("contract paths the client does not call are limited to /healthz", () => {
    const unused = [...contractPaths].filter((p) => !calledPaths.includes(p));
    expect(unused).toEqual(["/healthz"]);
  });
});
