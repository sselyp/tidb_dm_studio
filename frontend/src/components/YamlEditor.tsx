import { Input, Segmented, Space } from "antd";
import { useMemo, useState } from "react";
import { stringify as toYaml } from "yaml";
import type { TaskConfig } from "../api/types";

interface Props {
  config: TaskConfig;
  rawYaml?: string;
  onRawYamlChange: (value: string) => void;
}

type Mode = "form" | "yaml";

/**
 * Dual view: the form (config) is authoritative in "form" mode; the generated
 * YAML is a live preview. Editing the YAML switches to "yaml" mode and the raw
 * text is what gets submitted (server-side validation is authoritative).
 */
export default function YamlEditor({ config, rawYaml, onRawYamlChange }: Props) {
  const [mode, setMode] = useState<Mode>("form");

  const generated = useMemo(() => {
    try {
      return toYaml(config, { lineWidth: 0 });
    } catch {
      return "";
    }
  }, [config]);

  return (
    <Space direction="vertical" size={12} style={{ width: "100%" }}>
      <Segmented<Mode>
        value={mode}
        options={[
          { label: "表单预览", value: "form" },
          { label: "编辑 YAML", value: "yaml" },
        ]}
        onChange={setMode}
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
