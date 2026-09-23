# TiDB DM OpenAPI v7.1.6 — 能力矩阵（后端代理面）

> 来源：对 `dm-master` 实测 `GET http://10.168.2.241:8261/api/v1/dm.json`（二进制 **v7.1.6**）。
> 采集：agent 侧本机直连（非 502）。规模：**31 paths / 60 schemas**。
> ⚠️ 文档自报 `info.version = 6.0.0`，与二进制 7.1.6 不符 → **版本探测勿读 `dm.json`/`/cluster/info`**，以 dmctl/二进制为准（`x-dm-compat: v7.1.6`）。

## 1. 端点清单（实测）

### 集群 / 健康
| Method | Path | 说明 |
|---|---|---|
| GET | `/api/v1/cluster/info` | 集群 id（不含版本） |
| PUT | `/api/v1/cluster/info` | 更新集群信息 |
| GET | `/api/v1/cluster/masters` | master 列表（leader/alive） |
| DELETE | `/api/v1/cluster/masters/{master-name}` | 下线 master |
| GET | `/api/v1/cluster/workers` | worker 列表（bound/free） |
| DELETE | `/api/v1/cluster/workers/{worker-name}` | 下线 worker |

### 数据源（Sources）
| Method | Path | 说明 |
|---|---|---|
| GET | `/api/v1/sources` | 列表（`password` 掩码 `******`） |
| POST | `/api/v1/sources` | 新建并启用 |
| GET/PUT/DELETE | `/api/v1/sources/{source-name}` | 详情/更新/删除 |
| POST | `.../{source-name}/enable` \| `/disable` | 启停 source |
| POST | `.../{source-name}/relay/enable` \| `/disable` \| `/purge` | relay log |
| POST | `.../{source-name}/transfer` | 迁移到空闲 worker |
| GET | `.../{source-name}/status` | source 状态 |
| GET | `.../{source-name}/schemas` | 库列表 |
| GET | `.../{source-name}/schemas/{schema-name}` | 表列表 |

### 任务（Tasks）
| Method | Path | 说明 |
|---|---|---|
| GET | `/api/v1/tasks` | 列表（⚠️ 见 §4 明文口令） |
| POST | `/api/v1/tasks` | 创建 |
| GET/PUT/DELETE | `/api/v1/tasks/{task-name}` | 详情/更新/删除（⚠️ 明文口令） |
| GET | `.../{task-name}/status` | 状态（每 source 一条 SubTaskStatus） |
| POST | `.../{task-name}/start` | 启动 |
| POST | `.../{task-name}/stop` | 停止 |
| POST | `/api/v1/tasks/converters` | Task ⇄ 配置文件互转 |
| GET/POST/PUT/DELETE | `/api/v1/tasks/templates[...]` | 任务模板 CRUD/import |
| GET | `.../{task-name}/sources/{source-name}/migrate_targets` | route 预览 |
| GET | `.../{task-name}/sources/{source-name}/schemas[/{schema}]` | 任务级库表浏览 |
| GET/PUT/DELETE | `.../schemas/{schema}/{table}` | 任务级表结构 |

### 文档
| GET | `/api/v1/dm.json`（spec JSON）| `/api/v1/docs`（Swagger UI HTML，内嵌 `url: /api/v1/dm.json`） |

## 2. 与后端契约的映射

**可用（可直连代理）**
- tasks / sources CRUD；source enable/disable/relay/transfer。
- `GET /tasks/{name}/status`：`data: SubTaskStatus[]`，每项含 `source_name`、`stage`、`dump_status`、`load_status`、`sync_status`、`error_msg`、`worker_name`、`unit`。
- 库表浏览：source/task 级 `schemas`、表结构与 `migrate_targets`（route-rules 预览）。
- `/cluster/masters|workers`：健康探针。

**缺口（须后端兜底，对应架构 P0 §7）**
| 契约能力 | DM OpenAPI | 兜底 |
|---|---|---|
| `PUT /tasks/{name}/state` 的 `paused` | **无 pause/resume**，仅 start/stop；`TaskStage ∈ {Stopped,Running,Finished}` **无 Paused** | dmctl `pause-task`/`resume-task`；`desiredState:paused` 由后端状态机产生，不从 TaskStage 反推 |
| `POST /task-precheck`（check-task） | **无独立端点**；`OperateTaskResponse.check_result` 仅 start/stop 附一段 | dmctl `check-task` |
| `GET /tasks/{name}/logs` | **无日志端点** | 后端自实现（读 worker 日志） |
| `GET /tasks/{name}/yaml` | **无 YAML 导出**；`/tasks/converters` 仅 Task⇄config 文件 | 后端基于落库 config 自渲染并脱敏 |

## 3. 关键请求/响应形状

- `StartTaskRequest { remove_meta, safe_mode_time_duration, source_name_list, start_time }`
- `StopTaskRequest { source_name_list, timeout_duration }`
- `Task { name, task_mode(all|full|incremental), shard_mode(pessimistic|optimistic), on_duplicate(replace|error|ignore), ignore_checking_items[], meta_schema, source_config, target_config, table_migrate_rule[], binlog_filter_rule, enhance_online_schema_change, strict_optimistic_shard_mode, status_list }`
- `TaskSourceConfig { source_conf: [{source_name, binlog_name, binlog_pos, binlog_gtid}], full_migrate_conf {export_threads, import_threads, data_dir, consistency}, incr_migrate_conf {repl_threads, repl_batch} }`
- `TaskTargetDataBase { host, port, user, password, security }` ← **含口令**
- `ConverterTaskRequest/Response { task, task_config_file }`

## 4. ⚠️ 安全：task 明文口令（阻断级）

实测（值始终未回显）：
- `GET /api/v1/tasks` → `/data[i]/target_config/password` = **PLAINTEXT**
- `GET /api/v1/tasks/{name}` → `/target_config/password` = **PLAINTEXT**
- 对照 `GET /api/v1/sources` → `/data[i]/password` = `******`（masked）
- 干净：`/tasks/{name}/status`、`/cluster/masters|workers` 无 password 键。

**结论**：DM **对 task 不脱敏、对 source 脱敏**。后端代理必须对 task 响应**白名单化**（递归剔除/掩码 `(?i)password|passwd|pwd|secret|token`），`/tasks/{name}/yaml` 自渲染脱敏，禁止暴露 `/tasks/converters` 及任何原生 passthrough。

## 5. 监控字段映射

| 我们的状态字段 | DM 来源 |
|---|---|
| `stage` | `SubTaskStatus.stage`（Stopped/Running/Finished；**无 Paused**）——DM OpenAPI schema **无 `enum`**（纯 string），故 `dmEnum` 为**运行时/mdctl 断言项**，非 schema 保证（D17 不得写成"schema 已保证"） |
| `lag` | `SubTaskStatus.sync_status.seconds_behind_master` |
| `progress` | dump：`completed_tables/total_tables`；load：`finished_bytes/total_bytes`；sync：`synced` |
| 分片 DDL 冲突 | `sync_status.unresolved_groups[]`（`ShardingGroup{target, ddl_list, synced, unsynced}`）→ PRECHECK |
| 错误 | `SubTaskStatus.error_msg` |

## 6. 可达性与复现

- dm-master `10.168.2.241:8261`：agent 侧本机可达（本轮实测 200）。
- TiDB `10.168.2.241:4000`：对外统一地址（agent 侧可达）；宿主内 `192.168.2.241` 对 dev/proxy 不可达，不得写入文档/配置。
- 复现：`GET /api/v1/dm.json` 取 spec；`GET /api/v1/tasks`、`/tasks/{name}` 核对 §4 路径。
