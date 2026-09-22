// Types mirroring api/openapi.yaml (v0.9.0). Keep in sync with the contract.

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
  | "EXISTENCE";

export type FieldErrorCode =
  | "E_FIELD_REQUIRED"
  | "E_PARAM_RANGE"
  | "E_PARAM_ENUM"
  | "E_PARAM_REGEX"
  | "E_PARAM_DEPENDENCY"
  | "E_FIELD_EXISTENCE"
  | "PRECHECK_TABLE_CONFLICT"
  | "PRECHECK_PK_CONFLICT"
  | "PRECHECK_ROUTE_OVERLAP"
  | "PRECHECK_TASK_NAME_DUP"
  | "PRECHECK_CHARSET_TZ_MISMATCH";

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
  latencyMs?: number;
  serverVersion?: string;
  errors?: FieldError[];
}

export interface SourceInstance {
  sourceRef: string;
  routeRules?: Array<Record<string, unknown>>;
  blockAllowList?: Record<string, unknown>;
  filters?: Array<Record<string, unknown>>;
  binlogPosition?: Record<string, unknown> | null;
  metaSnapshot?: string | null;
}

export type TaskMode = "all" | "full" | "incremental";

export interface TaskConfig {
  taskMode?: TaskMode;
  sources: SourceInstance[];
  [key: string]: unknown;
}

export interface Task {
  name: string;
  rawYaml?: string;
  config?: TaskConfig;
  /** Top-level projection of config.sources (same schema). */
  sources: SourceInstance[];
}

export type TaskState = "new" | "running" | "paused" | "stopped";

export interface TaskSummary {
  name: string;
  state: TaskState;
  stage?: string;
  lag?: number;
  sourceCount?: number;
}

export interface TaskStatusData {
  state: TaskState;
  stage?: string;
  /** 0..1. */
  progress?: number;
  lag?: number;
  lastError?: string | null;
  updatedAt?: string;
}

export type DesiredState = "running" | "paused" | "stopped";

export interface StateRequest {
  desiredState: DesiredState;
}

export interface StateData {
  currentState?: string;
  applied?: boolean;
  allowedActions?: string[];
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
