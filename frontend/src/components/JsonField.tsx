import { useEffect, useRef, useState } from "react";
import { Input } from "antd";

interface Props {
  value: unknown;
  onChange: (value: unknown) => void;
  disabled?: boolean;
  minRows?: number;
  "aria-label"?: string;
}

function stringify(value: unknown): string {
  if (value === undefined || value === null) {
    return "";
  }
  try {
    return JSON.stringify(value, null, 2);
  } catch {
    return "";
  }
}

/**
 * Textarea bound to a JSON value, kept as raw text while editing so partial
 * input is preserved; parsed value is propagated only when the JSON is valid.
 */
export default function JsonField({
  value,
  onChange,
  disabled,
  minRows = 3,
  "aria-label": ariaLabel,
}: Props) {
  const [text, setText] = useState(() => stringify(value));
  const [invalid, setInvalid] = useState(false);
  const lastEmitted = useRef<string>(stringify(value));

  useEffect(() => {
    const incoming = stringify(value);
    if (incoming !== lastEmitted.current) {
      setText(incoming);
      lastEmitted.current = incoming;
      setInvalid(false);
    }
  }, [value]);

  const handleChange = (next: string) => {
    setText(next);
    if (next.trim() === "") {
      setInvalid(false);
      lastEmitted.current = stringify(undefined);
      onChange(undefined);
      return;
    }
    try {
      const parsed: unknown = JSON.parse(next);
      setInvalid(false);
      lastEmitted.current = stringify(parsed);
      onChange(parsed);
    } catch {
      setInvalid(true);
    }
  };

  return (
    <div>
      <Input.TextArea
        value={text}
        disabled={disabled}
        aria-label={ariaLabel}
        status={invalid ? "error" : undefined}
        autoSize={{ minRows, maxRows: 10 }}
        onChange={(e) => handleChange(e.target.value)}
      />
      {invalid && (
        <div style={{ color: "#f53f3f", fontSize: 12, marginTop: 4 }}>
          JSON 格式错误
        </div>
      )}
    </div>
  );
}
