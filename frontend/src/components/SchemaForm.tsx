import { Collapse, Form, Typography } from "antd";
import type { FormLayout, UiField } from "../api/types";
import ArrayTableField from "./ArrayTableField";
import ObjectFormField from "./ObjectFormField";
import {
  evalVisibleWhen,
  getByPointer,
  inferredWidget,
  resolveSchemaNode,
  type JsonSchemaNode,
} from "./schemaUtils";
import WidgetControl from "./WidgetControl";

interface Props {
  jsonSchema?: Record<string, unknown>;
  layout?: FormLayout;
  group: { key: string; title: string; fields: string[] };
  value: Record<string, unknown>;
  onChange: (pointer: string, value: unknown) => void;
  disabled?: boolean;
  dynamicOptions?: Record<string, Array<{ value: string; label: string }>>;
}

function fieldLabel(node: JsonSchemaNode, pointer: string): string {
  if (node.title) {
    return node.title;
  }
  const parts = pointer.split("/").filter(Boolean);
  return parts[parts.length - 1] ?? pointer;
}

export default function SchemaForm({
  jsonSchema,
  layout,
  group,
  value,
  onChange,
  disabled,
  dynamicOptions,
}: Props) {
  const root = jsonSchema as JsonSchemaNode | undefined;

  const renderField = (pointer: string) => {
    // `/name` is a special write-side pointer bound to the top-level
    // TaskWrite.name; it is intentionally absent from jsonSchema (D11/monorepo
    // ruling), so fall back to a synthetic string node for it.
    const node =
      resolveSchemaNode(root, pointer) ??
      (pointer === "/name"
        ? ({
            type: "string",
            description:
              "任务名称；唯一性与合法性由服务端校验（提交后以 422 返回该字段错误）",
          } as JsonSchemaNode)
        : undefined);
    if (!node) {
      return null;
    }
    const ui: UiField | undefined = layout?.ui?.[pointer];
    if (!evalVisibleWhen(ui?.visibleWhen, value)) {
      return null;
    }
    const widget = inferredWidget(node, ui);
    const current = getByPointer(value, pointer);
    const help = ui?.help ?? node.description;

    return (
      <Form.Item
        key={pointer}
        label={fieldLabel(node, pointer)}
        help={help}
        style={{ marginBottom: 18 }}
      >
        {widget === "array-table" ? (
          <ArrayTableField
            pointer={pointer}
            node={node}
            root={root}
            ui={layout?.ui}
            value={Array.isArray(current) ? current : []}
            disabled={disabled}
            formValue={value}
            dynamicOptions={dynamicOptions}
            onChange={(v) => onChange(pointer, v)}
          />
        ) : widget === "object-form" ? (
          <ObjectFormField
            pointer={pointer}
            node={node}
            root={root}
            ui={layout?.ui}
            value={(current as Record<string, unknown>) ?? {}}
            formValue={value}
            disabled={disabled}
            dynamicOptions={dynamicOptions}
            onChange={(v) => onChange(pointer, v)}
          />
        ) : (
          <WidgetControl
            widget={widget}
            node={node}
            ui={ui}
            value={current}
            disabled={disabled}
            onChange={(v) => onChange(pointer, v)}
          />
        )}
      </Form.Item>
    );
  };

  const normal = group.fields.filter((p) => !layout?.ui?.[p]?.advanced);
  const advanced = group.fields.filter((p) => layout?.ui?.[p]?.advanced);

  return (
    <div style={{ marginBottom: 24 }}>
      <Typography.Text strong style={{ display: "block", marginBottom: 12 }}>
        {group.title}
      </Typography.Text>
      {normal.map(renderField)}
      {advanced.length > 0 && (
        <Collapse
          ghost
          items={[
            {
              key: "advanced",
              label: "高级",
              children: advanced.map(renderField),
            },
          ]}
        />
      )}
    </div>
  );
}
