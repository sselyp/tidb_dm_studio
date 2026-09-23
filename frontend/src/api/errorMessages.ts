import { ErrorCodes, type ErrorCodeName } from "./errorCodes";
import type { FieldError, FieldErrorCode } from "./types";

/**
 * UI mapping for field-level and precheck error codes. The set of codes is
 * authoritative in api/openapi.yaml (generated into errorCodes.ts); this only
 * supplies human-facing labels. Unknown codes fall through to the raw code.
 */
const FIELD_ERROR_LABELS: Record<FieldErrorCode, string> = {
  E_FIELD_REQUIRED: "必填项缺失",
  E_PARAM_RANGE: "取值超出范围",
  E_PARAM_ENUM: "取值不在枚举内",
  E_PARAM_REGEX: "格式不匹配",
  E_PARAM_DEPENDENCY: "依赖字段不满足",
  E_FIELD_EXISTENCE: "引用的对象不存在",
  E_FIELD_DUPLICATE: "名称重复（需唯一）",
  PRECHECK_TABLE_CONFLICT: "多源映射到同一目标表",
  PRECHECK_PK_CONFLICT: "多源写入同一表且主键/唯一键冲突",
  PRECHECK_ROUTE_OVERLAP: "源间 route-rules 目标范围相互覆盖",
  PRECHECK_TASK_NAME_DUP: "目标表名映射后同名",
  PRECHECK_CHARSET_TZ_MISMATCH: "上游字符集/时区不一致",
  E_SOURCE_UNREACHABLE: "上游数据源不可达",
  E_TARGET_AUTH_FAILED: "目标库鉴权失败",
};

export function fieldErrorLabel(code: FieldErrorCode): string {
  return FIELD_ERROR_LABELS[code] ?? code;
}

/**
 * Friendly label for a `FieldError.fieldPath`. `/name` is the write-side pointer
 * bound to top-level `TaskWrite.name`; it is deliberately absent from jsonSchema
 * (D11 / monorepo ruling), so it gets a name here instead of an opaque path.
 */
const FIELD_PATH_LABELS: Record<string, string> = {
  "/name": "任务名",
};

export function fieldPathLabel(path: string | undefined): string {
  if (!path) {
    return "/";
  }
  return FIELD_PATH_LABELS[path] ?? path;
}

const ENVELOPE_MESSAGES: Partial<Record<ErrorCodeName, string>> = {
  E_UNAUTHENTICATED: "登录已失效，请重新登录",
  E_INVALID_CREDENTIALS: "用户名或密码错误",
  E_FORBIDDEN: "没有权限执行该操作",
  E_PASSWORD_CHANGE_REQUIRED: "需要先修改初始密码",
  E_CSRF_FAILED: "安全令牌校验失败，请重试",
  E_PRECONDITION_FAILED: "数据已被他人修改，请刷新后重试",
  E_PRECONDITION_REQUIRED: "缺少并发校验信息，请刷新后重试",
  E_RATE_LIMITED: "操作过于频繁，请稍后再试",
  E_ACCOUNT_LOCKED: "账号已临时锁定，请稍后再试",
  E_DM_UNAVAILABLE: "DM 控制面不可用",
};

export function envelopeMessage(code: number, fallback: string): string {
  const name = (Object.keys(ErrorCodes) as ErrorCodeName[]).find(
    (key) => ErrorCodes[key].code === code,
  );
  if (name && ENVELOPE_MESSAGES[name]) {
    return ENVELOPE_MESSAGES[name] as string;
  }
  return fallback;
}

export function groupErrors(errors: FieldError[]) {
  const bySeverity = {
    error: [] as FieldError[],
    warning: [] as FieldError[],
    info: [] as FieldError[],
  };
  for (const err of errors) {
    if (err.severity === "warning") {
      bySeverity.warning.push(err);
    } else if (err.severity === "info") {
      bySeverity.info.push(err);
    } else {
      bySeverity.error.push(err);
    }
  }
  return bySeverity;
}
