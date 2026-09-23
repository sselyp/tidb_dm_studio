import { Input, Segmented, Space } from "antd";
import type { YamlMode } from "./yamlMode";

interface Props {
  mode: YamlMode;
  generated: string;
  rawYaml?: string;
  onModeChange: (mode: YamlMode) => void;
  onRawYamlChange: (value: string) => void;
}

/**
 * Dual view: the form (config) is authoritative in "form" mode; the generated
 * YAML is a live preview. Editing the YAML switches to "yaml" mode and the raw
 * text is what gets submitted (server-side validation is authoritative).
 *
 * `mode` is owned by the wizard (not local state) so that the submitted body
 * always follows the view the user is looking at.
 */
export default function YamlEditor({
  mode,
  generated,
  rawYaml,
  onModeChange,
  onRawYamlChange,
}: Props) {
  return (
    <Space direction="vertical" size={12} style={{ width: "100%" }}>
      <Segmented<YamlMode>
        value={mode}
        options={[
          { label: "表单预览", value: "form" },
          { label: "编辑 YAML", value: "yaml" },
        ]}
        onChange={onModeChange}
      />
      {mode === "form" ? (
        <Input.TextArea
          value={generated}
          readOnly
          autoSize={{ minRows: 16, maxRows: 32 }}
          style={{ fontFamily: "monospace" }}
        />
      ) : (
        <Input.TextArea
          value={rawYaml ?? generated}
          autoSize={{ minRows: 16, maxRows: 32 }}
          style={{ fontFamily: "monospace" }}
          onChange={(e) => onRawYamlChange(e.target.value)}
        />
      )}
    </Space>
  );
}
