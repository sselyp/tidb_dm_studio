import { Alert, List, Space, Tag, Typography } from "antd";
import { fieldErrorLabel, fieldPathLabel, groupErrors } from "../api/errorMessages";
import type { FieldError, ValidationData } from "../api/types";

function ErrorRow({ item }: { item: FieldError }) {
  const color =
    item.severity === "warning"
      ? "orange"
      : item.severity === "info"
        ? "blue"
        : "red";
  return (
    <List.Item>
      <Space direction="vertical" size={2} style={{ width: "100%" }}>
        <Space size={8} wrap>
          <Tag color={color}>{fieldErrorLabel(item.errorCode)}</Tag>
          <Typography.Text code>{fieldPathLabel(item.fieldPath)}</Typography.Text>
        </Space>
        <Typography.Text type="secondary">{item.message}</Typography.Text>
      </Space>
    </List.Item>
  );
}

/** Renders a validate/precheck result. The authoritative judgement is data.valid. */
export default function ValidationReport({
  result,
}: {
  result: ValidationData;
}) {
  const errors = result.errors ?? [];
  if (result.valid && errors.length === 0) {
    return <Alert type="success" showIcon message="校验通过" />;
  }
  const { error, warning, info } = groupErrors(errors);
  return (
    <Space direction="vertical" size={12} style={{ width: "100%" }}>
      {!result.valid && (
        <Alert
          type="error"
          showIcon
          message={`校验未通过（错误 ${result.riskSummary?.error ?? error.length} / 警告 ${
            result.riskSummary?.warning ?? warning.length
          }）`}
        />
      )}
      {error.length > 0 && (
        <List
          size="small"
          bordered
          header="错误"
          dataSource={error}
          renderItem={(item) => <ErrorRow item={item} />}
        />
      )}
      {warning.length > 0 && (
        <List
          size="small"
          bordered
          header="警告"
          dataSource={warning}
          renderItem={(item) => <ErrorRow item={item} />}
        />
      )}
      {info.length > 0 && (
        <List
          size="small"
          bordered
          header="提示"
          dataSource={info}
          renderItem={(item) => <ErrorRow item={item} />}
        />
      )}
    </Space>
  );
}
