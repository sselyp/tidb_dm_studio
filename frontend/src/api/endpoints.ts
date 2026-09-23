import { newIdempotencyKey, request, requestText } from "./http";
import type {
  ConnectivityResult,
  DataSource,
  DataSourceWrite,
  DesiredState,
  LogPageData,
  MeData,
  Page,
  PasswordChangeRequest,
  SchemaData,
  StateData,
  Task,
  TaskStatusData,
  TaskSummary,
  TaskUpdateWrite,
  TaskWrite,
  ValidationData,
} from "./types";

/* ------------------------------- auth ---------------------------------- */

export function login(username: string, password: string) {
  return request<MeData>("/login", {
    method: "POST",
    body: { username, password },
  });
}

export function logout() {
  return request<void>("/logout", { method: "POST" });
}

export function getMe() {
  return request<MeData>("/me");
}

export function changePassword(oldPassword: string, newPassword: string) {
  const body: PasswordChangeRequest = { oldPassword, newPassword };
  return request<void>("/password", { method: "POST", body });
}

/* ---------------------------- datasources ------------------------------ */

export function listDataSources(page = 1, pageSize = 20) {
  return request<Page<DataSource>>(
    `/datasources?page=${page}&pageSize=${pageSize}`,
  );
}

export function getDataSource(id: string) {
  return request<DataSource>(`/datasources/${encodeURIComponent(id)}`);
}

export function createDataSource(body: DataSourceWrite) {
  return request<DataSource>("/datasources", {
    method: "POST",
    body,
    idempotencyKey: newIdempotencyKey(),
  });
}

export function updateDataSource(
  id: string,
  body: DataSourceWrite,
  etag?: string,
) {
  return request<DataSource>(`/datasources/${encodeURIComponent(id)}`, {
    method: "PUT",
    body,
    ifMatch: etag,
  });
}

export function deleteDataSource(id: string) {
  return request<void>(`/datasources/${encodeURIComponent(id)}`, {
    method: "DELETE",
  });
}

export function testDataSource(body: DataSourceWrite) {
  return request<ConnectivityResult>("/datasources/test", {
    method: "POST",
    body,
  });
}

/* ------------------------------- tasks --------------------------------- */

export function listTasks(page = 1, pageSize = 20) {
  return request<Page<TaskSummary>>(`/tasks?page=${page}&pageSize=${pageSize}`);
}

export function getTaskSchema(mode: string) {
  return request<SchemaData>(`/task-schema?mode=${encodeURIComponent(mode)}`);
}

export function validateTask(body: TaskWrite) {
  return request<ValidationData>("/task-validate", { method: "POST", body });
}

export function precheckTask(body: TaskWrite, level: "schema" | "connectivity") {
  return request<ValidationData>(
    `/task-precheck?level=${level}`,
    { method: "POST", body },
  );
}

export function createTask(body: TaskWrite) {
  return request<Task>("/tasks", {
    method: "POST",
    body,
    idempotencyKey: newIdempotencyKey(),
  });
}

export function getTask(name: string) {
  return request<Task>(`/tasks/${encodeURIComponent(name)}`);
}

export function updateTask(
  name: string,
  body: TaskUpdateWrite,
  etag: string,
) {
  return request<Task>(`/tasks/${encodeURIComponent(name)}`, {
    method: "PUT",
    body,
    ifMatch: etag,
  });
}

export function deleteTask(name: string) {
  return request<void>(`/tasks/${encodeURIComponent(name)}`, {
    method: "DELETE",
  });
}

export function putTaskState(name: string, desiredState: DesiredState) {
  return request<StateData>(`/tasks/${encodeURIComponent(name)}/state`, {
    method: "PUT",
    body: { desiredState },
    idempotencyKey: newIdempotencyKey(),
  });
}

export function getTaskStatus(name: string) {
  return request<TaskStatusData>(`/tasks/${encodeURIComponent(name)}/status`);
}

export function getTaskLogs(name: string, offset = 0, limit = 200) {
  return request<LogPageData>(
    `/tasks/${encodeURIComponent(name)}/logs?offset=${offset}&limit=${limit}`,
  );
}

export function exportTaskYaml(name: string) {
  return requestText(`/tasks/${encodeURIComponent(name)}/yaml`);
}
