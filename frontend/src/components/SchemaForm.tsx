import { Form, Input, InputNumber, Select, Switch } from "antd";

/**
 * Schema-driven form renderer.
 *
 * Consumes the payload of `GET /task-schema` (`data.jsonSchema` + `data.formLayout`).
 * The exact field-level shape is still being finalised in P0; this renderer
 * implements the following documented assumption and is isolated here so it can
 * be adapted without touching pages:
 *
 *   jsonSchema: { properties: { <name>: { type, enum?, default?, description?,
 *                                       "x-ui"?: { label?, help?, widget?, options?, placeholder? } } } }
 *   formLayout: { groups: [ { key, title, fields: [<name>...] } ] }
 *
 * Only scalar widgets are handled here; the multi-source array is rendered by a
 * dedicated editor (see SourcesEditor). Unknown widgets fall back to text.
 */
export interface UiHints {
  label?: string;
  help?: string;
  widget?: "input" | "textarea" | "number" | "select" | "switch" | "json";
  options?: Array<{ value: string | number | boolean; label?: string }>;
  placeholder?: string;
}

export interface JsonSchemaNode {
  type?: string;
  title?: string;
  description?: string;
  default?: unknown;
  enum?: Array<string | number>;
  properties?: Record<string, JsonSchemaNode>;
  items?: JsonSchemaNode;
  "x-ui"?: UiHints;
}

export interface FormLayoutGroup {
  key: string;
  title: string;
  fields: string[];
}

export interface FormLayout {
  groups?: FormLayoutGroup[];
}

interface Props {
  schema?: Record<string, unknown>;
  layout?: Record<string, unknown>;
  value: Record<string, unknown>;
  onChange: (name: string, value: unknown) => void;
  disabled?: boolean;
}

function resolveOptions(
  node: JsonSchemaNode,
  ui?: UiHints,
): Array<{ value: string | number | boolean; label: string }> {
  if (ui?.options && ui.options.length > 0) {
    return ui.options.map((o) => ({
      value: o.value,
      label: o.label ?? String(o.value),
    }));
  }
  return (node.enum ?? []).map((v) => ({ value: v, label: String(v) }));
}

function FieldControl({
  name,
  node,
  value,
  onChange,
  disabled,
}: {
  name: string;
  node: JsonSchemaNode;
  value: unknown;
  onChange: (name: string, value: unknown) => void;
  disabled?: boolean;
}) {
  const ui = node["x-ui"];
  const widget =
    ui?.widget ??
    (node.enum
      ? "select"
      : node.type === "boolean"
        ? "switch"
        : node.type === "number" || node.type === "integer"
          ? "number"
          : "input");

  switch (widget) {
    case "switch":
      return (
        <Switch
          checked={Boolean(value)}
          disabled={disabled}
          onChange={(checked) => onChange(name, checked)}
        />
      );
    case "number":
      return (
        <InputNumber
          style={{ width: "100%" }}
          value={value as number | undefined}
          disabled={disabled}
          placeholder={ui?.placeholder}
          onChange={(v) => onChange(name, v ?? undefined)}
        />
      );
    case "select":
      return (
        <Select
          style={{ width: "100%" }}
          value={value as string | undefined}
          disabled={disabled}
          placeholder={ui?.placeholder}
          options={resolveOptions(node, ui)}
          onChange={(v) => onChange(name, v)}
        />
      );
    case "textarea":
    case "json":
      return (
        <Input.TextArea
          value={value as string | undefined}
          disabled={disabled}
          placeholder={ui?.placeholder}
          autoSize={{ minRows: 3, maxRows: 8 }}
          onChange={(e) => onChange(name, e.target.value)}
        />
      );
    default:
      return (
        <Input
          value={value as string | undefined}
          disabled={disabled}
          placeholder={ui?.placeholder}
          onChange={(e) => onChange(name, e.target.value)}
        />
      );
  }
}

export default function SchemaForm({
  schema,
  layout,
  value,
  onChange,
  disabled,
}: Props) {
  const root = schema as JsonSchemaNode | undefined;
  const properties = root?.properties ?? {};
  const groups = (layout as FormLayout | undefined)?.groups;

  const fieldNames = groups
    ? groups.flatMap((g) => g.fields)
    : Object.keys(properties);

  const renderField = (name: string) => {
    const node = properties[name];
    if (!node) {
      return null;
    }
    const ui = node["x-ui"];
    const label = ui?.label ?? node.title ?? name;
    return (
      <Form.Item
        key={name}
        label={label}
        help={ui?.help ?? node.description}
        style={{ marginBottom: 18 }}
      >
        <FieldControl
          name={name}
          node={node}
          value={value[name]}
          onChange={onChange}
          disabled={disabled}
        />
      </Form.Item>
    );
  };

  if (groups && groups.length > 0) {
    return (
      <>
        {groups.map((group) => (
          <div key={group.key} style={{ marginBottom: 24 }}>
            <div style={{ fontWeight: 600, marginBottom: 12 }}>{group.title}</div>
            {group.fields.map(renderField)}
          </div>
        ))}
      </>
    );
  }

  return <>{fieldNames.map(renderField)}</>;
}
