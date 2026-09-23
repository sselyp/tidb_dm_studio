import {
  Input,
  InputNumber,
  Radio,
  Select,
  Switch,
} from "antd";
import type { UiField } from "../api/types";
import { type JsonSchemaNode } from "./schemaUtils";
import JsonField from "./JsonField";

interface Props {
  widget: string;
  node: JsonSchemaNode;
  ui?: UiField;
  value: unknown;
  onChange: (value: unknown) => void;
  disabled?: boolean;
  dynamicOptions?: Array<{ value: string; label: string }>;
}

function resolveOptions(
  node: JsonSchemaNode,
  ui?: UiField,
  dynamicOptions?: Array<{ value: string; label: string }>,
): Array<{ value: string | number; label: string }> {
  if (ui?.options && ui.options.length > 0) {
    return ui.options.map((o) => ({
      value: o.value as string | number,
      label: o.label,
    }));
  }
  if (dynamicOptions && dynamicOptions.length > 0) {
    return dynamicOptions;
  }
  return (node.enum ?? []).map((v) => ({ value: v, label: String(v) }));
}

export default function WidgetControl({
  widget,
  node,
  ui,
  value,
  onChange,
  disabled,
  dynamicOptions,
}: Props) {
  switch (widget) {
    case "password":
      return (
        <Input.Password
          value={value as string | undefined}
          disabled={disabled}
          placeholder={ui?.placeholder}
          autoComplete="new-password"
          onChange={(e) => onChange(e.target.value)}
        />
      );
    case "textarea":
    case "code-yaml":
      return (
        <Input.TextArea
          value={value as string | undefined}
          disabled={disabled}
          placeholder={ui?.placeholder}
          autoSize={{ minRows: 4, maxRows: 12 }}
          style={widget === "code-yaml" ? { fontFamily: "monospace" } : undefined}
          onChange={(e) => onChange(e.target.value)}
        />
      );
    case "number":
      return (
        <InputNumber
          style={{ width: "100%" }}
          value={value as number | undefined}
          disabled={disabled}
          min={node.minimum}
          max={node.maximum}
          placeholder={ui?.placeholder}
          addonAfter={ui?.unit}
          onChange={(v) => onChange(v ?? undefined)}
        />
      );
    case "switch":
      return (
        <Switch
          checked={Boolean(value)}
          disabled={disabled}
          onChange={(checked) => onChange(checked)}
        />
      );
    case "select":
      return (
        <Select
          style={{ width: "100%" }}
          value={value as string | undefined}
          disabled={disabled}
          placeholder={ui?.placeholder}
          options={resolveOptions(node, ui, dynamicOptions)}
          onChange={(v) => onChange(v)}
        />
      );
    case "radio":
      return (
        <Radio.Group
          value={value}
          disabled={disabled}
          options={resolveOptions(node, ui)}
          onChange={(e) => onChange(e.target.value)}
        />
      );
    case "multi-select":
      return (
        <Select
          mode="multiple"
          style={{ width: "100%" }}
          value={(value as string[]) ?? []}
          disabled={disabled}
          placeholder={ui?.placeholder}
          options={resolveOptions(node, ui, dynamicOptions)}
          onChange={(v) => onChange(v)}
        />
      );
    case "tag-list":
      return (
        <Select
          mode="tags"
          style={{ width: "100%" }}
          value={(value as string[]) ?? []}
          disabled={disabled}
          placeholder={ui?.placeholder}
          onChange={(v) => onChange(v)}
        />
      );
    case "key-value":
    case "array-table":
    case "object-form":
      // object-form is rendered structurally by SchemaForm; this is a fallback
      // for nested rows where no dedicated renderer is dispatched.
      return <JsonField value={value} disabled={disabled} onChange={onChange} />;
    default:
      return (
        <Input
          value={value as string | undefined}
          disabled={disabled}
          placeholder={ui?.placeholder}
          onChange={(e) => onChange(e.target.value)}
        />
      );
  }
}
