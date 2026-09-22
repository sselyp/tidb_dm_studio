import type { DesiredState, TaskAction, TaskState } from "../api/types";

export interface ActionMeta {
  label: string;
  /** Present for actions that map onto PUT /tasks/{name}/state. */
  desiredState?: DesiredState;
  primary?: boolean;
}

export const ACTION_META: Record<TaskAction, ActionMeta> = {
  start: { label: "启动", desiredState: "running", primary: true },
  resume: { label: "恢复", desiredState: "running", primary: true },
  pause: { label: "暂停", desiredState: "paused" },
  stop: { label: "停止", desiredState: "stopped" },
  delete: { label: "删除" },
};

/**
 * Compatibility fallback only. The server owns `allowedActions`; this mirrors
 * the state machine just so the UI still works against older backends. Every
 * call site goes through `resolveAllowedActions`, which prefers the server set.
 */
export function compatActions(state: TaskState | undefined): TaskAction[] {
  switch (state) {
    case "new":
    case "stopped":
    case "failed":
      return ["start"];
    case "running":
      return ["pause", "stop"];
    case "paused":
      return ["resume", "stop"];
    case "finished":
    default:
      return [];
  }
}

export function resolveAllowedActions(
  serverActions: TaskAction[] | undefined,
  state: TaskState | undefined,
): { actions: TaskAction[]; compat: boolean } {
  if (serverActions) {
    return { actions: serverActions, compat: false };
  }
  return { actions: compatActions(state), compat: true };
}
