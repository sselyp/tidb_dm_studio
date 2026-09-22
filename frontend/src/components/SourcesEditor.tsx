import { Button, Card, Collapse, Empty, Input, Select, Space } from "antd";
import type { SourceInstance } from "../api/types";
import JsonField from "./JsonField";

interface Props {
  value: SourceInstance[];
  datasourceOptions: Array<{ id: string; label: string }>;
  onChange: (value: SourceInstance[]) => void;
  disabled?: boolean;
}

export default function SourcesEditor({
  value,
  datasourceOptions,
  onChange,
  disabled,
}: Props) {
  const update = (index: number, patch: Partial<SourceInstance>) => {
    const next = value.map((item, i) => (i === index ? { ...item, ...patch } : item));
    onChange(next);
  };

  const add = () => {
    onChange([...value, { sourceRef: "" }]);
  };

  const remove = (index: number) => {
    onChange(value.filter((_, i) => i !== index));
  };

  return (
    <Space direction="vertical" size={12} style={{ width: "100%" }}>
      {value.length === 0 && (
        <Empty description="尚未添加数据源；多库合并请依次加入多个 MySQL 源" />
      )}

      {value.map((source, index) => (
        <Card
          key={index}
          size="small"
          title={`源 ${index + 1}`}
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
          <Space direction="vertical" size={12} style={{ width: "100%" }}>
            <div>
              <div style={{ marginBottom: 4 }}>数据源</div>
              <Select
                style={{ width: "100%" }}
                value={source.sourceRef || undefined}
                disabled={disabled}
                placeholder="选择数据源"
                options={datasourceOptions.map((o) => ({
                  value: o.id,
                  label: o.label,
                }))}
                onChange={(v) => update(index, { sourceRef: v })}
              />
            </div>

            <div>
              <div style={{ marginBottom: 4 }}>meta-snapshot（可选）</div>
              <Input
                value={source.metaSnapshot ?? ""}
                disabled={disabled}
                placeholder="SQL 文件 / 已导入库"
                onChange={(e) =>
                  update(index, { metaSnapshot: e.target.value || null })
                }
              />
            </div>

            <Collapse
              ghost
              items={[
                {
                  key: "advanced",
                  label: "高级（路由 / 过滤 / 位点）",
                  children: (
                    <Space
                      direction="vertical"
                      size={12}
                      style={{ width: "100%" }}
                    >
                      <div>
                        <div style={{ marginBottom: 4 }}>routeRules</div>
                        <JsonField
                          value={source.routeRules}
                          disabled={disabled}
                          aria-label="routeRules"
                          onChange={(v) =>
                            update(index, {
                              routeRules: v as SourceInstance["routeRules"],
                            })
                          }
                        />
                      </div>
                      <div>
                        <div style={{ marginBottom: 4 }}>blockAllowList</div>
                        <JsonField
                          value={source.blockAllowList}
                          disabled={disabled}
                          aria-label="blockAllowList"
                          onChange={(v) =>
                            update(index, {
                              blockAllowList:
                                v as SourceInstance["blockAllowList"],
                            })
                          }
                        />
                      </div>
                      <div>
                        <div style={{ marginBottom: 4 }}>filters</div>
                        <JsonField
                          value={source.filters}
                          disabled={disabled}
                          aria-label="filters"
                          onChange={(v) =>
                            update(index, {
                              filters: v as SourceInstance["filters"],
                            })
                          }
                        />
                      </div>
                      <div>
                        <div style={{ marginBottom: 4 }}>binlogPosition</div>
                        <JsonField
                          value={source.binlogPosition}
                          disabled={disabled}
                          aria-label="binlogPosition"
                          onChange={(v) =>
                            update(index, {
                              binlogPosition:
                                v as SourceInstance["binlogPosition"],
                            })
                          }
                        />
                      </div>
                    </Space>
                  ),
                },
              ]}
            />
          </Space>
        </Card>
      ))}

      <Button block disabled={disabled} onClick={add}>
        + 添加数据源
      </Button>
    </Space>
  );
}
