import fs from "node:fs";

import { describe, expect, it } from "vitest";

import {
  deref,
  inferredWidget,
  lintTopLevelCoverage,
  resolveSchemaNode,
  type JsonSchemaNode,
} from "../src/components/schemaUtils";
import { buildTaskWrite, rawYamlForMode } from "../src/components/yamlMode";
import { compatActions, resolveAllowedActions } from "../src/components/taskActions";
import type { FormLayout, TaskConfig, UiField } from "../src/api/types";

/**
 * Renderer contract regression, run against the committed P0 example so it is
 * reproducible in CI (no out-of-repo fixture). Guards the D11 render rules:
 * `jsonSchema` + `formLayout.steps/ui`, §4.3 option channels, name ownership,
 * YAML-mode submit body and the D15 allowedActions single source.
 */
const fixtureUrl = new URL(
  "../../docs/architecture/form-schema.example.json",
  import.meta.url,
);
const doc = JSON.parse(fs.readFileSync(fixtureUrl, "utf8")) as {
  jsonSchema: JsonSchemaNode;
  formLayout: FormLayout;
};
const root = doc.jsonSchema;
const ui = doc.formLayout.ui as Record<string, UiField> | undefined;

const layoutOf = (fields: string[], uiKeys: string[] = []) => ({
  steps: [{ key: "s", title: "s", groups: [{ key: "g", title: "g", fields }] }],
  ui: Object.fromEntries(uiKeys.map((k) => [k, {}])) as Record<string, UiField>,
});

describe("schema shape (frozen D11 P0 example)", () => {
  it("top-level required excludes name", () => {
    expect(root.required).toEqual(["taskMode", "sources"]);
  });

  it("/name absent from jsonSchema (SchemaForm special-cases it)", () => {
    expect(resolveSchemaNode(root, "/name")).toBeUndefined();
  });

  it("sourceRef is a string", () => {
    expect(resolveSchemaNode(root, "/sources/*/sourceRef")?.type).toBe("string");
  });

  it("source filters is string[]", () => {
    expect([
      resolveSchemaNode(root, "/sources/*/filters")?.type,
      resolveSchemaNode(root, "/sources/*/filters")?.items?.type,
    ]).toEqual(["array", "string"]);
  });

  it("source routeRules is string[]", () => {
    expect([
      resolveSchemaNode(root, "/sources/*/routeRules")?.type,
      resolveSchemaNode(root, "/sources/*/routeRules")?.items?.type,
    ]).toEqual(["array", "string"]);
  });

  it("mydumpers item properties", () => {
    expect(
      Object.keys(
        deref(root, resolveSchemaNode(root, "/mydumpers")?.items)?.properties ?? {},
      ),
    ).toEqual(["global", "threads", "chunkFilesize"]);
  });

  it("syncers item properties", () => {
    expect(
      Object.keys(
        deref(root, resolveSchemaNode(root, "/syncers")?.items)?.properties ?? {},
      ),
    ).toEqual(["global", "workerCount", "batch", "queueSize"]);
  });

  it("RouteRule requires name", () => {
    expect(deref(root, resolveSchemaNode(root, "/routes")?.items)?.required).toEqual([
      "name",
      "schemaPattern",
      "tablePattern",
    ]);
  });
});

describe("widget inference", () => {
  it("targetDatabase -> object-form", () => {
    expect(
      inferredWidget(resolveSchemaNode(root, "/targetDatabase")!, ui?.["/targetDatabase"]),
    ).toBe("object-form");
  });

  it("targetDatabase/session -> key-value (inferred)", () => {
    expect(
      inferredWidget(resolveSchemaNode(root, "/targetDatabase/session")!, undefined),
    ).toBe("key-value");
  });

  it("metaSnapshot -> key-value (ui)", () => {
    expect(
      inferredWidget(
        resolveSchemaNode(root, "/sources/*/metaSnapshot")!,
        ui?.["/sources/*/metaSnapshot"],
      ),
    ).toBe("key-value");
  });

  it("targetDatabase/port -> number", () => {
    expect(
      inferredWidget(resolveSchemaNode(root, "/targetDatabase/port")!, undefined),
    ).toBe("number");
  });

  it("targetDatabase/host -> input", () => {
    expect(
      inferredWidget(resolveSchemaNode(root, "/targetDatabase/host")!, undefined),
    ).toBe("input");
  });

  it("ui-less array<string> -> array-table (ui NOT required to render)", () => {
    expect(inferredWidget({ type: "array", items: { type: "string" } }, undefined)).toBe(
      "array-table",
    );
  });

  it("ui-less enum (<=4) -> radio", () => {
    expect(inferredWidget({ enum: ["a", "b"] }, undefined)).toBe("radio");
  });

  it("ignoreCheckItems is array<string>", () => {
    expect([
      resolveSchemaNode(root, "/ignoreCheckItems")?.type,
      resolveSchemaNode(root, "/ignoreCheckItems")?.items?.type,
    ]).toEqual(["array", "string"]);
  });

  it("ignoreCheckItems widget is multi-select", () => {
    expect(
      inferredWidget(resolveSchemaNode(root, "/ignoreCheckItems")!, ui?.["/ignoreCheckItems"]),
    ).toBe("multi-select");
  });

  it("ignoreCheckItems infers array-table without ui", () => {
    expect(inferredWidget(resolveSchemaNode(root, "/ignoreCheckItems")!, undefined)).toBe(
      "array-table",
    );
  });
});

describe("YAML-mode submit body", () => {
  const cfg = { taskMode: "all", sources: [] } as unknown as TaskConfig;

  it("form mode submits config, never stale rawYaml", () => {
    expect(buildTaskWrite("t", "form", "stale: true", cfg)).toEqual({ name: "t", config: cfg });
  });

  it("yaml mode submits the raw text", () => {
    expect(buildTaskWrite("t", "yaml", "mode: all", cfg)).toEqual({
      name: "t",
      rawYaml: "mode: all",
    });
  });

  it("yaml mode without raw text falls back to config", () => {
    expect(buildTaskWrite("t", "yaml", undefined, cfg)).toEqual({ name: "t", config: cfg });
  });

  it("entering yaml mode seeds from generated preview", () => {
    expect(rawYamlForMode("yaml", undefined, "mode: all")).toBe("mode: all");
  });

  it("entering yaml mode keeps existing edits", () => {
    expect(rawYamlForMode("yaml", "edited: 1", "mode: all")).toBe("edited: 1");
  });

  it("leaving yaml mode discards stale raw text", () => {
    expect(rawYamlForMode("form", "edited: 1", "mode: all")).toBeUndefined();
  });
});

describe("layout coverage lint (step whitelist cannot silently drop fields)", () => {
  it("clean on the real example", () => {
    expect(lintTopLevelCoverage(root, doc.formLayout)).toEqual([]);
  });

  it("flags a schema property absent from every step", () => {
    expect(
      lintTopLevelCoverage(
        {
          properties: {
            taskMode: { type: "string" },
            ignoreCheckItems: { type: "array", items: { type: "string" } },
          },
        },
        layoutOf(["/taskMode"]),
      ),
    ).toEqual(["/ignoreCheckItems"]);
  });

  it("listing the pointer in a step clears the lint", () => {
    expect(
      lintTopLevelCoverage(
        {
          properties: {
            taskMode: { type: "string" },
            ignoreCheckItems: { type: "array", items: { type: "string" } },
          },
        },
        layoutOf(["/taskMode", "/ignoreCheckItems"]),
      ),
    ).toEqual([]);
  });

  it("a ui-only entry also clears the lint", () => {
    expect(
      lintTopLevelCoverage(
        { properties: { ignoreCheckItems: { type: "array" } } },
        layoutOf([], ["/ignoreCheckItems"]),
      ),
    ).toEqual([]);
  });
});

describe("allowedActions single source (D15)", () => {
  it("server allowedActions wins (no state inference)", () => {
    expect(resolveAllowedActions(["stop", "pause"], "running")).toEqual({
      actions: ["stop", "pause"],
      compat: false,
    });
  });

  it("failed is not special-cased when the server decides", () => {
    expect(resolveAllowedActions(["start"], "failed")).toEqual({
      actions: ["start"],
      compat: false,
    });
  });

  it("compat fallback for failed = start+delete", () => {
    expect(resolveAllowedActions(undefined, "failed")).toEqual({
      actions: ["start", "delete"],
      compat: true,
    });
  });

  it("compat fallback matches P0 §10.1 for every state", () => {
    expect({
      new: compatActions("new"),
      stopped: compatActions("stopped"),
      failed: compatActions("failed"),
      running: compatActions("running"),
      paused: compatActions("paused"),
      finished: compatActions("finished"),
    }).toEqual({
      new: ["start", "delete"],
      stopped: ["start", "delete"],
      failed: ["start", "delete"],
      running: ["pause", "stop"],
      paused: ["resume", "stop"],
      finished: ["delete"],
    });
  });
});
