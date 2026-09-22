import { ErrorCodes, type ErrorCodeName } from "./errorCodes";
import type { Envelope, FieldError } from "./types";

const CSRF_COOKIE = "dm_csrf";
const STATE_CHANGING = new Set(["POST", "PUT", "PATCH", "DELETE"]);

/** Normalized API error carrying the stable envelope code and field errors. */
export class ApiError extends Error {
  readonly http: number;
  readonly code: number;
  readonly errors: FieldError[];
  readonly retryAfter?: number;

  constructor(
    http: number,
    code: number,
    message: string,
    errors: FieldError[] = [],
    retryAfter?: number,
  ) {
    super(message);
    this.name = "ApiError";
    this.http = http;
    this.code = code;
    this.errors = errors;
    this.retryAfter = retryAfter;
  }

  is(name: ErrorCodeName): boolean {
    return this.code === ErrorCodes[name].code;
  }
}

function readCookie(name: string): string | undefined {
  const escaped = name.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  const match = document.cookie.match(new RegExp(`(?:^|; )${escaped}=([^;]*)`));
  return match ? decodeURIComponent(match[1]) : undefined;
}

export interface RequestOptions {
  method?: string;
  body?: unknown;
  idempotencyKey?: string;
  ifMatch?: string;
  signal?: AbortSignal;
}

export interface RequestResult<T> {
  data: T;
  /** ETag from the response, to feed back as If-Match on updates. */
  etag?: string;
}

export function newIdempotencyKey(): string {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) {
    return crypto.randomUUID();
  }
  return `${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

export async function request<T>(
  path: string,
  opts: RequestOptions = {},
): Promise<RequestResult<T>> {
  const method = (opts.method ?? "GET").toUpperCase();
  const headers: Record<string, string> = { Accept: "application/json" };
  if (opts.body !== undefined) {
    headers["Content-Type"] = "application/json";
  }
  if (STATE_CHANGING.has(method) && path !== "/login") {
    const csrf = readCookie(CSRF_COOKIE);
    if (csrf) {
      headers["X-CSRF-Token"] = csrf;
    }
  }
  if (opts.idempotencyKey) {
    headers["Idempotency-Key"] = opts.idempotencyKey;
  }
  if (opts.ifMatch) {
    headers["If-Match"] = opts.ifMatch;
  }

  const res = await fetch(`/api${path}`, {
    method,
    headers,
    credentials: "include",
    body: opts.body !== undefined ? JSON.stringify(opts.body) : undefined,
    signal: opts.signal,
  });

  const etag = res.headers.get("ETag") ?? undefined;

  if (res.status === 204) {
    return { data: undefined as T, etag };
  }

  const text = await res.text();
  let payload: unknown;
  if (text) {
    try {
      payload = JSON.parse(text);
    } catch {
      payload = undefined;
    }
  }

  if (!res.ok) {
    const env = payload as Partial<Envelope<{ errors?: FieldError[] }>> | undefined;
    const code = typeof env?.code === "number" ? env.code : res.status * 100;
    const errors =
      (env?.data as { errors?: FieldError[] } | null | undefined)?.errors ?? [];
    const retryAfterHeader = res.headers.get("Retry-After");
    throw new ApiError(
      res.status,
      code,
      env?.message || res.statusText,
      errors,
      retryAfterHeader ? Number(retryAfterHeader) : undefined,
    );
  }

  const env = payload as Envelope<T>;
  return { data: env.data, etag };
}

/** Fetch a plain-text resource (e.g. exported task.yaml). */
export async function requestText(
  path: string,
  opts: RequestOptions = {},
): Promise<string> {
  const method = (opts.method ?? "GET").toUpperCase();
  const headers: Record<string, string> = { Accept: "text/yaml, text/plain" };
  if (STATE_CHANGING.has(method)) {
    const csrf = readCookie(CSRF_COOKIE);
    if (csrf) {
      headers["X-CSRF-Token"] = csrf;
    }
  }
  const res = await fetch(`/api${path}`, {
    method,
    headers,
    credentials: "include",
    signal: opts.signal,
  });
  if (!res.ok) {
    throw new ApiError(res.status, res.status * 100, res.statusText);
  }
  return res.text();
}
