import { Space, Typography } from "antd";
import type { UiField } from "../api/types";
import { deref, inferredWidget, type JsonSchemaNode } from "./schemaUtils";
import JsonField from "./JsonField";
import WidgetControl from "./WidgetControl";

interface Props {
  pointer: string;
  node: JsonSchemaNode;
  root?: JsonSchemaNode;
  ui?: Record<string, UiField>;
  value: Record<string, unknown>;
  onChange: (value: Record<string, unknown>) => void;
  disabled?: boolean;
  /** Whole form value (reserved for nested visibleWhen). */
  formValue?: unknown;
  dynamicOptions?: Record<string, Array<{ value: string; label: string }>>;
}

/**
 * Renders an object's fixed `properties` as a nested sub-form. `writeOnly` /
 * `password` sub-fields are masked; nested objects recurse; objects without
 * `properties` fall back to a free key-value JSON editor.
 */
export default function ObjectFormField({
  pointer,
  node,
  root,
  ui,
  value,
  onChange,
  disabled,
  dynamicOptions,
}: Props) {
  const props = node.properties ?? {};
  const required = new Set(node.required ?? []);
  const update = (prop: string, next: unknown) =>
    onChange({ ...value, [prop]: next });

  return (
    <Space direction="vertical" size={12} style={{ width: "100%" }}>
      {Object.entries(props).map(([prop, raw]) => {
        const propNode = deref(root, raw) ?? {};
        const propPointer = `${pointer}/${prop}`;
        const uiField = ui?.[propPointer];
        const label = propNode.title ?? prop;
        const nestedObject =
          propNode.type === "object" &&
          propNode.properties !== undefined &&
          Object.keys(propNode.properties).length > 0;

        if (nestedObject) {
          return (
            <div key={prop}>
              <Typography.Text strong style={{ display: "block", marginBottom: 8 }}>
                {label}
              </Typography.Text>
              <ObjectFormField
                pointer={propPointer}
                node={propNode}
                root={root}
                ui={ui}
                value={(value[prop] as Record<string, unknown>) ?? {}}
                onChange={(next) => update(prop, next)}
                disabled={disabled}
                dynamicOptions={dynamicOptions}
              />
            </div>
          );
        }

        const isPassword =
          propNode.writeOnly === true ||
          propNode.format === "password" ||
          uiField?.widget === "password";
        const widget = isPassword ? "password" : inferredWidget(propNode, uiField);
        const sub =
          widget === "key-value" || widget === "array-table" ? (
            <JsonField
              value={value[prop]}
              disabled={disabled}
              onChange={(next) => update(prop, next)}
            />
          ) : (
            <WidgetControl
              widget={widget}
              node={propNode}
              ui={uiField}
              value={value[prop]}
              disabled={disabled}
              dynamicOptions={dynamicOptions?.[prop]}
              onChange={(next) => update(prop, next)}
            />
          );

        return (
          <div key={prop}>
            <div style={{ fontSize: 13, color: "#646a73", marginBottom: 4 }}>
              {label}
              {required.has(prop) ? " *" : ""}
              {propNode.description ? `（${propNode.description}）` : ""}
            </div>
            {sub}
          </div>
        );
      })}
    </Space>
  );
}
