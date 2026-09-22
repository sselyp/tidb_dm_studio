import { Tag } from "antd";
import type { TaskState } from "../api/types";

const STATE_META: Record<
  TaskState,
  { color: string; label: string }
> = {
  new: { color: "default", label: "New" },
  running: { color: "green", label: "Running" },
  paused: { color: "orange", label: "Paused" },
  stopped: { color: "default", label: "Stopped" },
  finished: { color: "blue", label: "Finished" },
  failed: { color: "red", label: "Failed" },
};

export default function StateTag({ state }: { state?: TaskState }) {
  if (!state) {
    return <Tag>Unknown</Tag>;
  }
  const meta = STATE_META[state] ?? { color: "default", label: state };
  return <Tag color={meta.color}>{meta.label}</Tag>;
}
