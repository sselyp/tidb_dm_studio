import { Button, Card, Collapse, Empty, Space } from "antd";
import type { UiField } from "../api/types";
import {
  deref,
  evalVisibleWhen,
  inferredWidget,
  type JsonSchemaNode,
} from "./schemaUtils";
import WidgetControl from "./WidgetControl";

interface Props {
  pointer: string;
  node: JsonSchemaNode;
  root?: JsonSchemaNode;
  ui?: Record<string, UiField>;
  value: unknown[];
  onChange: (value: unknown[]) => void;
  disabled?: boolean;
  /** Whole form value, for row-level visibleWhen evaluation. */
  formValue?: unknown;
  /** Dynamic options per property, e.g. { sourceRef: datasourceOptions }. */
  dynamicOptions?: Record<string, Array<{ value: string; label: string }>>;
}

export default function ArrayTableField({
  pointer,
  node,
  root,
  ui,
  value,
  onChange,
  disabled,
  formValue,
  dynamicOptions,
}: Props) {
  const itemNode = deref(root, node.items);
  const itemProps = itemNode?.properties ?? {};
  const propNames = Object.keys(itemProps);
  const itemTitlePointer = ui?.[pointer]?.itemTitle;

  const update = (index: number, prop: string, propValue: unknown) => {
    onChange(
      value.map((row, i) =>
        i === index ? { ...(row as object), [prop]: propValue } : row,
      ),
    );
  };

  const remove = (index: number) => {
    onChange(value.filter((_, i) => i !== index));
  };

  const add = () => {
    const blank: Record<string, unknown> = {};
    for (const prop of propNames) {
      const schema = deref(root, itemProps[prop]);
      if (schema?.default !== undefined) {
        blank[prop] = schema.default;
      }
    }
    onChange([...value, blank]);
  };

  const renderRowField = (row: unknown, index: number, prop: string) => {
    const propNode = deref(root, itemProps[prop]);
    if (!propNode) {
      return null;
    }
    const uiField = ui?.[`${pointer}/*/${prop}`];
    const widget = inferredWidget(propNode, uiField);
    return (
      <div key={prop}>
        <div style={{ fontSize: 13, color: "#646a73", marginBottom: 4 }}>
          {prop}
          {propNode.description ? `（${propNode.description}）` : ""}
        </div>
        <WidgetControl
          widget={widget}
          node={propNode}
          ui={uiField}
          value={(row as Record<string, unknown>)[prop]}
          disabled={disabled}
          dynamicOptions={dynamicOptions?.[prop]}
          onChange={(v) => update(index, prop, v)}
        />
      </div>
    );
  };

  return (
    <Space direction="vertical" size={12} style={{ width: "100%" }}>
      {value.length === 0 && <Empty description="暂无条目" />}
      {value.map((row, index) => {
        const rowObj = row as Record<string, unknown>;
        const title =
          itemTitlePointer && rowObj[itemTitlePointer] != null
            ? String(rowObj[itemTitlePointer])
            : `#${index + 1}`;
        const normalProps = propNames.filter(
          (p) => !ui?.[`${pointer}/*/${p}`]?.advanced,
        );
        const advancedProps = propNames.filter(
          (p) => ui?.[`${pointer}/*/${p}`]?.advanced,
        );
        const visibleProps = (props: string[]) =>
          props.filter((p) =>
            evalVisibleWhen(ui?.[`${pointer}/*/${p}`]?.visibleWhen, formValue),
          );
        return (
          <Card
            key={index}
            size="small"
            title={title}
            extra={
              <Button
                danger
                size="small"
                disabled={disabled}
                onClick={() => remove(index)}
              >
                移除
              </Button>
            }
          >
            <Space direction="vertical" size={10} style={{ width: "100%" }}>
              {visibleProps(normalProps).map((p) => renderRowField(row, index, p))}
              {advancedProps.length > 0 && (
                <Collapse
                  ghost
                  items={[
                    {
                      key: "advanced",
                      label: "高级",
                      children: (
                        <Space
                          direction="vertical"
                          size={10}
                          style={{ width: "100%" }}
                        >
                          {visibleProps(advancedProps).map((p) =>
                            renderRowField(row, index, p),
                          )}
                        </Space>
                      ),
                    },
                  ]}
                />
              )}
            </Space>
          </Card>
        );
      })}
      <Button block disabled={disabled} onClick={add}>
        + 添加
      </Button>
    </Space>
  );
}
