import type { UiField, VisibleWhen } from "../api/types";

export interface JsonSchemaNode {
  type?: string;
  title?: string;
  description?: string;
  default?: unknown;
  enum?: Array<string | number>;
  minimum?: number;
  maximum?: number;
  properties?: Record<string, JsonSchemaNode>;
  required?: string[];
  items?: JsonSchemaNode;
  $ref?: string;
}

/** Follow `$ref` (e.g. "#/$defs/SourceInstance") within the root schema. */
export function deref(
  root: JsonSchemaNode | undefined,
  node: JsonSchemaNode | undefined,
): JsonSchemaNode | undefined {
  let current = node;
  let guard = 0;
  while (current?.$ref && guard < 50) {
    guard += 1;
    const path = current.$ref.replace(/^#\//, "").split("/");
    let target: unknown = root;
    for (const part of path) {
      target = (target as Record<string, unknown> | undefined)?.[part];
    }
    current = target as JsonSchemaNode | undefined;
  }
  return current;
}

/** Resolve a JSON Schema node for a Pointer, where `*` means array items. */
export function resolveSchemaNode(
  root: JsonSchemaNode | undefined,
  pointer: string,
): JsonSchemaNode | undefined {
  if (!root) {
    return undefined;
  }
  let node: JsonSchemaNode | undefined = root;
  for (const part of pointer.split("/").filter(Boolean)) {
    node = deref(root, node);
    if (!node) {
      return undefined;
    }
    if (part === "*") {
      node = node.items;
    } else {
      node = node.properties?.[part] ?? node.items?.properties?.[part];
    }
  }
  return deref(root, node);
}

export function getByPointer(value: unknown, pointer: string): unknown {
  let current: unknown = value;
  for (const part of pointer.split("/").filter(Boolean)) {
    if (current == null || typeof current !== "object") {
      return undefined;
    }
    current = (current as Record<string, unknown>)[part];
  }
  return current;
}

export function setByPointer<T>(obj: T, pointer: string, next: unknown): T {
  const parts = pointer.split("/").filter(Boolean);
  if (parts.length === 0) {
    return next as T;
  }
  const clone: unknown = Array.isArray(obj) ? [...obj] : { ...(obj as object) };
  let cursor = clone as Record<string, unknown>;
  for (let i = 0; i < parts.length - 1; i += 1) {
    const key = parts[i];
    const child = cursor[key];
    const childClone: unknown = Array.isArray(child)
      ? [...child]
      : child && typeof child === "object"
        ? { ...(child as object) }
        : {};
    cursor[key] = childClone;
    cursor = childClone as Record<string, unknown>;
  }
  cursor[parts[parts.length - 1]] = next;
  return clone as T;
}

/** visibleWhen evaluation; on any evaluation failure default to showing. */
export function evalVisibleWhen(
  when: VisibleWhen | undefined,
  value: unknown,
): boolean {
  if (!when) {
    return true;
  }
  if ("all" in when) {
    return when.all.every((w) => evalVisibleWhen(w, value));
  }
  if ("any" in when) {
    return when.any.some((w) => evalVisibleWhen(w, value));
  }
  const current = getByPointer(value, when.field);
  if (current === undefined || current === null) {
    return true;
  }
  return when.in.includes(current as never);
}

export function inferredWidget(
  node: JsonSchemaNode,
  ui: UiField | undefined,
): string {
  if (ui?.widget) {
    return ui.widget;
  }
  if (node.enum) {
    return node.enum.length > 4 ? "select" : "radio";
  }
  if (node.type === "boolean") {
    return "switch";
  }
  if (node.type === "integer" || node.type === "number") {
    return "number";
  }
  if (node.type === "array") {
    return "array-table";
  }
  return "input";
}
