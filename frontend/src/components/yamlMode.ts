import type { TaskConfig, TaskWrite } from "../api/types";

export type YamlMode = "form" | "yaml";

/**
 * The submitted body must follow the view the user is looking at: "yaml" mode
 * submits the raw text, "form" mode submits the structured config. A YAML mode
 * that has no raw text yet falls back to the config so the body stays a valid
 * `TaskWrite` instead of carrying a stale/undefined `rawYaml`.
 */
export function buildTaskWrite(
  name: string,
  mode: YamlMode,
  rawYaml: string | undefined,
  config: TaskConfig,
): TaskWrite {
  if (mode === "yaml" && rawYaml !== undefined) return { name, rawYaml };
  return { name, config };
}

/**
 * Raw-text state for a mode switch: entering YAML mode seeds from the generated
 * preview when nothing was edited yet; leaving it discards stale edits, so the
 * screen and the submitted body can never diverge.
 */
export function rawYamlForMode(
  mode: YamlMode,
  rawYaml: string | undefined,
  generated: string,
): string | undefined {
  return mode === "yaml" ? (rawYaml ?? generated) : undefined;
}
