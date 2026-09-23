// Types mirroring api/openapi.yaml (v0.9.4). Keep in sync with the contract.

import { FieldErrorCodes, PrecheckCodes } from "./errorCodes";

export interface Envelope<T> {
  code: number;
  data: T;
  message: string;
}

export type Severity = "error" | "warning" | "info";

export type RuleCode =
  | "REQUIRED"
  | "RANGE"
  | "ENUM"
  | "REGEX"
  | "DEPENDENCY"
  | "EXISTENCE"
  | "UNIQUE";

/** Derived from the generated registries (do not hand-maintain). */
export type FieldErrorCode =
  | (typeof FieldErrorCodes)[number]
  | (typeof PrecheckCodes)[number];

export interface FieldError {
  fieldPath: string;
  ruleCode?: RuleCode;
  errorCode: FieldErrorCode;
  message: string;
  severity: Severity;
}

export interface RiskSummary {
  error?: number;
  warning?: number;
}

export interface MeData {
  username: string;
  mustChangePassword: boolean;
  roles?: string[];
}

export interface LoginRequest {
  username: string;
  password: string;
}

export interface PasswordChangeRequest {
  oldPassword: string;
  newPassword: string;
}

export type DataSourceType = "mysql" | "tidb";

export interface DataSource {
  id: string;
  name: string;
  type: DataSourceType;
  host: string;
  port: number;
  username: string;
  version?: string;
  createdAt?: string;
  updatedAt?: string;
}

export interface DataSourceWrite {
  name: string;
  type: DataSourceType;
  host: string;
  port: number;
  username: string;
  password?: string;
  tls?: Record<string, unknown>;
}

export interface ConnectivityResult {
  reachable?: boolean;
  authenticated?: boolean;
  /** = reachable && authenticated (required as of v0.9.1). */
  valid?: boolean;
  latencyMs?: number;
  serverVersion?: string;
  errors?: FieldError[];
}

/** Frozen example `#/$defs/BlockAllowList` (task-config-schema.md §4.3 / form-schema.example.json). */
export interface BlockAllowList {
  schemaPattern: string;
  tablePattern: string;
}

/** Frozen example `#/$defs/BinlogPosition`; also the shape of the per-source metaSnapshot property. */
export interface BinlogPosition {
  binlogName?: string;
  binlogPos?: number;
  binlogGtid?: string;
}

export interface SourceInstance {
  sourceRef: string;
  /** Object-form (BinlogPosition), NOT a string (openapi aligned to the example in v0.9.4). */
  metaSnapshot?: BinlogPosition | null;
  /** Flat binlog point; replaces the old `binlogPosition` stray object (v0.9.4). */
  binlogName?: string | null;
  binlogPos?: number | null;
  binlogGtid?: string | null;
  /** Names referencing `/routes[*].name` on the task config (D11 §4.3). */
  routeRules?: string[];
  /** Frozen example = `array<BlockAllowList>` (NOT an object; openapi 0.9.3 was wrong, fixed in 0.9.4). */
  blockAllowList?: BlockAllowList[];
  /** Names referencing `/filters[*].name` on the task config (D11 §4.3). */
  filters?: string[];
}

export type TaskMode = "all" | "full" | "incremental";

/** Frozen `TargetDatabase` (openapi v0.9.5, D16 own-path). `password` is a write-only channel. */
export interface TargetDatabase {
  host: string;
  port: number;
  user: string;
  /** writeOnly (D16): may appear in writes, but read models / yaml export / logs must never echo it. */
  password?: string;
  session?: Record<string, string>;
}

export interface TaskConfig {
  taskMode?: TaskMode;
  sources: SourceInstance[];
  /** Downstream TiDB target; `password` write-only (D16 own-path, v0.9.5). */
  targetDatabase?: TargetDatabase;
  [key: string]: unknown;
}

export interface Task {
  name: string;
  rawYaml?: string;
  config?: TaskConfig;
  /** Top-level projection of config.sources (same schema). */
  sources: SourceInstance[];
}

/** Platform state (v0.9.2). Unique derivation from native + lastOp + lastError. */
export type TaskState =
  | "new"
  | "running"
  | "paused"
  | "stopped"
  | "finished"
  | "failed";

/** DM native TaskStage, passed through verbatim (capitalized). */
export type NativeState = "Stopped" | "Running" | "Finished";

export interface TaskSummary {
  name: string;
  state: TaskState;
  stage?: string;
  nativeState?: NativeState;
  lag?: number;
  sourceCount?: number;
  /**
   * Server-authoritative action set (D15) when the list endpoint provides it.
   * Optional: today only the status/state endpoints return it, so the list
   * falls back to `resolveAllowedActions`' state mapping until then.
   */
  allowedActions?: TaskAction[];
}

export interface TaskStatusData {
  state: TaskState;
  stage?: string;
  nativeState?: NativeState;
  /** 0..1. */
  progress?: number;
  lag?: number;
  lastError?: string | null;
  updatedAt?: string;
  /** Server-authoritative action set (v0.9.2+); UI must not re-derive it. */
  allowedActions?: TaskAction[];
}

export type DesiredState = "running" | "paused" | "stopped";

/**
 * Server-authoritative action set (reviewer ruling: buttons follow this, never a
 * frontend state→action derivation). Enum pinned by the backend.
 */
export type TaskAction = "start" | "pause" | "resume" | "stop" | "delete";

export interface StateRequest {
  desiredState: DesiredState;
}

export interface StateData {
  currentState?: string;
  applied?: boolean;
  allowedActions?: TaskAction[];
}

export interface ValidationData {
  valid: boolean;
  errors?: FieldError[];
  riskSummary?: RiskSummary;
}

export interface SchemaData {
  version?: string;
  mode?: string;
  jsonSchema?: Record<string, unknown>;
  formLayout?: FormLayout;
}

/** A UI hint, keyed by JSON Pointer in formLayout.ui. */
export interface UiField {
  widget?: string;
  help?: string;
  placeholder?: string;
  options?: Array<{ label: string; value: unknown }>;
  visibleWhen?: VisibleWhen;
  advanced?: boolean;
  unit?: string;
  order?: number;
  itemTitle?: string;
}

export type VisibleWhen =
  | { field: string; in: unknown[] }
  | { all: VisibleWhen[] }
  | { any: VisibleWhen[] };

export interface FormGroup {
  key: string;
  title: string;
  fields: string[];
}

export interface FormStep {
  key: string;
  title: string;
  description?: string;
  groups: FormGroup[];
}

export interface FormLayout {
  steps?: FormStep[];
  ui?: Record<string, UiField>;
}


export interface LogPageData {
  items: string[];
  total?: number;
  offset?: number;
  limit?: number;
}

export interface Page<T> {
  items: T[];
  total: number;
  page?: number;
  pageSize?: number;
}

export type TaskWrite =
  | { name: string; config: TaskConfig }
  | { name: string; rawYaml: string };

export type TaskUpdateWrite =
  | { name?: string; config: TaskConfig }
  | { name?: string; rawYaml: string };
