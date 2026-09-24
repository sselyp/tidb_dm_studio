# P0 架构设计 — TiDB DM Studio

> 状态：**评审中（Draft）**。契约细节以 `api/openapi.yaml` 为准；本文记录架构决策与边界。

## 1. 目标

Web 平台，把 MySQL → TiDB 的 DM 迁移**全参数可视化配置**，替代手写 `task.yaml` + `dmctl`。

```
数据源管理 → 任务配置(全参数) → 预检 check-task → 启停/迁移 → 监控与日志
```

## 2. 系统边界

```
┌──────────────┐    /api/*     ┌───────────────┐   dm-master    ┌────────────┐
│  Frontend    │ ────────────▶ │  Backend      │ ─────────────▶ │ dm-master  │
│ React+TS+AntD│ ◀──────────── │ Go 代理+增强层 │ ◀───────────── │ dm-worker* │
└──────────────┘   cookieAuth  └───────────────┘    OpenAPI     └────────────┘
                                      │
                                      ├── Metadata DB（任务/数据源/会话/审计）
                                      └── SecretProvider（默认本地 AES-256-GCM）
```

- **后端做代理 + 增强层**，不重复实现调度；缺失能力再补 `dmctl/pkg` 封装。
- **表单 schema 由后端下发**，前后端不硬编码参数，避免漂移。

## 3. 关键决策（已定稿）

| # | 决策 | 结论 |
|---|---|---|
| D1 | 后端语言 | Go（复用 dm-master OpenAPI） |
| D2 | 前端栈 | React + TS + Vite + Ant Design |
| D3 | 认证 | 需登录；HttpOnly + SameSite=Lax Cookie + 服务端会话（`SessionStore` 默认内存，多实例切 Redis） |
| D4 | CSRF | state-changing 请求双提交头 `X-CSRF-Token` |
| D5 | 口令 | Argon2id（m=64MiB/t=3/p=1，可配）+ 每用户随机盐；初始口令 env 注入 + 首登强制改密 |
| D6 | 密钥 | `SecretProvider` 抽象，默认 AES-256-GCM，主密钥 `DM_WEB_MASTER_KEY`；不进库、不进仓库 |
| D7 | source 语义 | `Task.sources` 为数组、`minItems=1`；单库=1、合并>1，**不按版本变形**；版本差异仅运行时校验 |
| D8 | 合并冲突 | 以稳定 `PRECHECK_*` 码进 `ValidationData` 告警（表名/主键冲突、route-rules 覆盖、同名 task、字符集/时区不一致） |
| D9 | 错误体 | 统一 `data.errors`；码见 §4 |
| D10 | 工程约束 | 不硬编码地址/密钥；配置走 env / 配置文件，仓库只留 `.env.example`；License/依赖合规过评审 |
| D11 | schema shape | **`jsonSchema` 只放标准 JSON Schema（draft 2020-12），属性内不嵌 `x-ui-*`**；UI 提示独立于 `formLayout`，键为 JSON Pointer。理由：`jsonSchema` 需被 `/task-validate` 与通用校验器直接复用，厂商扩展会污染校验语义；UI 关注点与校验关注点分离，可各自演进 |
| D12 | 诊断/失败语义 | **上游源库"检查未通过"≠ HTTP 失败**。`/datasources/test` 与 `/task-precheck?level=connectivity` 一律 **HTTP 200 = 检查已执行**，通过与否看 `data.valid` + `data.errors`；上游不可达/鉴权失败**不**用 5xx。**502 只保留 DM 控制面不可用**（`50201 E_DM_UNAVAILABLE`）；退役 `50202 E_SOURCE_UNREACHABLE`、`50203 E_TARGET_AUTH_FAILED` |
| D13 | 读模型不变量 | `Task.sources` 是落库展开态 `config.sources` 的**只读投影**，二者**长度/顺序/内容恒等**（契约测试断言），不构成两个真相源 |
| D14 | 任务状态枚举 | 唯一真源 = `[new, running, paused, stopped, finished, failed]`。**收回 `pending`**（用 `new`）；保留 `failed` 但**必须按 §9 从 native + 持久化 `lastOp` 唯一推导**，不允许各端自行猜测 |
| D15 | 动作集合真源 | `/tasks/{name}/state` 与 `/tasks/{name}/status` 返回的 **`allowedActions` 是稳定 enum**（`[start, pause, resume, stop, delete]`），是「可执行动作」的唯一真源；前端**不得**按 `state` 自行推导动作（`state` 只定展示）。 |
| D16 | 凭据零回显（红线） | **代理层必须剥离/掩码 DM 原生响应中的一切口令字段**：`target_config.password`、source 口令等。已取证 v7.1.6 `GET /api/v1/tasks` **明文返回 `target_config.password`**（`/api/v1/sources` 则掩码）；后端透传前必须清洗，`/tasks`、`/task/status` 等一律不得出现目标库口令。 |
| D17 | DM 能力缺口兜底 | v7.1.6 OpenAPI **无 pause/resume、无 check-task、无日志、无 YAML 导出**。定死：pause/resume 与 check-task **经 dmctl 实现**（后端封装，非 OpenAPI）；日志与 YAML 导出**后端自实现且必须脱敏**（YAML 由落库 config 渲染，不透传原生）；版本探测**不读 `dm.json`**（自称 6.0.0），以 dmctl/二进制/配置为准；`allowedActions` 按**实际可用能力**下发（dmctl 不可用则不下发 pause/resume，允许降级）。详见 §11。 |

## 4. 错误码

| code | 语义 | HTTP |
|---|---|---|
| 40101 | `E_UNAUTHENTICATED` | 401 |
| 40102 | `E_INVALID_CREDENTIALS` | 401 |
| 40301 | `E_FORBIDDEN` | 403 |
| 40302 | `E_PASSWORD_CHANGE_REQUIRED` | 403 |
| 42206 | `E_WEAK_PASSWORD` | 422 |
| 42901 | `E_RATE_LIMITED` | 429 |

- 除 `POST /api/login`、健康检查外，`/api/**` 未认证一律 401。
- 首登未改密期间，除 `/login` `/logout` `/password` **`/me`** 白名单外一律 40302。`GET /me` 必须在该状态下仍返回 **200**（携带 `mustChangePassword:true`），否则前端守卫无法进入强制改密分支。

### 4.1 CI 门禁退出码契约（`check_contract.py` / `test_gate.py`）

冻结三元组，双方照此写，禁止分叉：

| 退出码 | 语义 |
|---|---|
| `0` | PASS（检查器通过） |
| `1` | CONTRACT_VIOLATION（真实捕获到契约问题） |
| `2` | HARNESS_ERROR（检查器/infra 异常） |

- `check_contract.py` `main()` 必须有顶层 `try/except`：意外异常打印后 `sys.exit(2)`；正常「发现问题」仍 `exit(1)`。
- `test_gate.py`：`caught = (r.returncode == 1)`；`returncode == 2` 或 `not in (0,1)` → 记 **HARNESS ERROR** 并使 gate FAIL（**不得计入 caught**）；先跑 **pristine 正控**（干净未变异树 → 必须 exit 0，否则 HARNESS ERROR）。防 `caught = returncode != 0` 的 fail-open。

## 5. 认证与会话

- 端点：`POST /api/login`、`POST /api/logout`、`POST /api/password`、`GET /api/me`。
- `GET /api/me` 供前端路由守卫获取登录态与 `mustChangePassword`。
- 改密成功吊销该用户**全部会话（含当前）**，需重新登录。
- 登录保护：账号+IP 限频，连续失败递增锁定，落审计。

## 6. 多源合并

- 单任务多源（one task, multi-source），契约 `Task.sources` 数组建模。
- 每个 source 项含 `{ sourceRef, routeRules, blockAllowList, filters, binlogPosition/metaSnapshot }`。
- 合并冲突检测作为 precheck 独立告警，前端按 code 分组标红。

## 7. 待补充

- [x] DM 版本与 dm-master/dm-worker 拓扑：v7.1.6 dm-master OpenAPI（31 paths / 60 schemas），3 worker bound；能力缺口与兜底见 §11 与 `docs/architecture/dm-openapi-v7.1.6-capability.md`
- [~] 全参数 JSON Schema 与字段清单（结构已冻结，见 D11 + `task-config-schema.md`；版本相关字段 `online-ddl`/`validators` 待 DM 版本校准）
- [ ] 页面契约（向导步骤、监控页字段）
- [ ] 依赖清单与 License 合规（@DS-代码审核）

## 8. 里程碑

| 阶段 | 内容 | Owner |
|---|---|---|
| P0 | 架构、参数 schema、接口契约 | 架构师 |
| P1 | 数据源 CRUD、DM OpenAPI 代理、schema/任务/监控接口 | DS-后端开发 |
| P2 | 表单渲染器、任务列表/详情、监控页、YAML 双向编辑 | 前端开发-dm-ds |
| P3 | 前后端联调、端到端跑通 | 后端 + 前端 |
| P4 | 用例设计、功能验收、代码质量 | DS-测试 / DS-代码审核 |

## 9. 任务状态推导（D14）

DM native 只有 `Running` / `Stopped` / `Finished` 三态，平台 `paused`/`stopped`/`failed` 均由 `Stopped` **消歧**而来。消歧输入：

- `lastOp ∈ {start, resume, pause, stop}`：**最近一次平台下发意图，必须持久化**（DB，非内存）；平台重启后仍在。
- `lastError`：DM `Stopped` 携带的错误信息（空表示正常停下）。
- `stage` / `nativeState`：DM 原生值**原样透传**，供人工核对。

| 平台 `state` | DM native | 判定条件 |
|---|---|---|
| `new` | （DM 无此任务） | 平台侧已建、从未下发（`lastOp` 缺失且 DM 无任务） |
| `running` | `Running` | — |
| `finished` | `Finished` | — |
| `failed` | `Stopped` | `lastOp ∉ {pause, stop}` **且** `lastError != null`（自行死亡，非人工暂停/停止） |
| `paused` | `Stopped` | `lastOp == pause` |
| `stopped` | `Stopped` | `lastOp == stop`，**或** `lastOp` 缺失（平台外创建 / 平台重启无意图）→ **默认值** |

- 判定优先级：先看 `lastOp == stop|pause`（人工意图优先），其余落 `lastError` 判 `failed`/`stopped`。
- 契约须在 `x-dm-compat` 注明本表；`stopped` 为无意图兜底，避免「重启即 failed」。
- 文案/UI 颜色不属契约，前端仅按枚举分支。

### 验收用例（@ds-测试 断言对象）

| # | 构造 | 期望 `state` |
|---|---|---|
| S1 | DM `Running` | `running` |
| S2 | DM `Finished` | `finished` |
| S3 | DM `Stopped` + `lastError!=null` + `lastOp=start` | `failed` |
| S4 | DM `Stopped` + `lastError!=null` + `lastOp=stop` | `stopped`（**不得**误判 failed） |
| S5 | DM `Stopped` + `lastOp=pause` | `paused` |
| S6 | 平台外建任务 / 重启后无 `lastOp` | `stopped`（默认） |

## 10. 动作集合与凭据红线（D15/D16）

### 10.1 `allowedActions`（D15）
- 稳定 enum：`[start, pause, resume, stop, delete]`；`/tasks/{name}/state`（写）与 `/tasks/{name}/status`（读）**同源返回**。
- 期望语义（服务端按 `state` 映射，客户端不推导）：
  | state | allowedActions |
  |---|---|
  | `new` / `stopped` / `failed` | `[start, delete]` |
  | `running` | `[pause, stop]` |
  | `paused` | `[resume, stop]` |
  | `finished` | `[delete]` |
- 前端：`allowedActions` 存在即据此渲染；仅缺失时回退 `state` 分支（兼容路径，标记待删）。

### 10.2 凭据零回显（D16，红线）
- 事实：DM v7.1.6 `GET /api/v1/tasks` 明文返回 `target_config.password`；`/api/v1/sources` 掩码。
- 要求：后端代理对**所有** DM 原生响应做剥离/掩码，任何 `/tasks*`、`/sources*` 响应与日志**不得**含上下游口令。
- **自有落库路径同口径**：`config.targetDatabase.password` 属**我方**落库/序列化路径（不在 DM 侧），读回任务时同样**不得回显**（键不存在，或值 `******`/空）。
- 验证：`check_contract.py` 增反向断言（响应 schema 不得暴露 password 字段）+ 契约测试对 `/tasks` 响应做「无口令」断言；AC-SEC 增「经后端 `/tasks` 响应不得出现目标库口令」。
- **金丝雀断言**：写入唯一口令后，遍历 `/api/tasks`、`/tasks/{name}`、`/tasks/{name}/status`、`/tasks/{name}/yaml` 及任一 4xx/5xx 错误体与服务端日志，断言**均不含金丝雀子串**。
- **静态存储（at-rest，2026-09-24 @ds-测试 复核）**：任何含凭据的文件（`CREDENTIALS.txt`、`tidb-target.env`、`dm-tasks/source-mysql-*.yaml`、`README.md` 等）**不得** world/group 可读；现为 `600 tidb:tidb`、`dm-tasks/`=700（父目录 `/data/dm-mysql` 保持 755，mysqld 需穿越，不得收紧）。`README.md` 第 11 行内联 `dm` 明文口令仅 `chmod` 止血 → **POC 收尾轮换时必须删除该字面**（非可选）。新增/变更凭据文件一律并入本清单，收口归 @ds-代码审核 D16 清单。
- **字符串 blob 通道（D16-A，红线）**：读模型**不得**暴露 `rawYaml`（或任何承载原始 `task.yaml` 文本）的响应字段——字符串内容无法用 schema 校验，内联 `target_config.password` 会从键名扫描与运行期 `scrub()` 双双漏过。因此：`rawYaml` 仅作**写通道**（`TaskYamlWrite`/`TaskYamlUpdate`，`writeOnly:true`，入 `writeOnlyRequestFields`）；`/tasks/{name}/yaml` **由结构化 `config` 渲染**（password 因 `writeOnly` 省略）；运行期 rawYaml 只作写入口，解析后凭据进 `SecretProvider`、**不持久化原串**、日志/审计不记；若响应将出现原始文档串则 **fail-closed**。
- **门禁**：`check_contract.py` 登记 `x-credential-handling.stringBlobResponseForbidden`，**响应可达的字符串 blob 字段一律 FAIL**，并加 must-FAIL 变异「rawYaml 内联口令」；回归加结构断言「`Task` 无 `rawYaml`」+ 字符串内容扫描（`password:`/`passwd:` + 已知口令）。

## 11. DM OpenAPI v7.1.6 能力映射与缺口兜底（D17）

> 取证：@ds-代码审核 本机直连 `10.168.2.241:8261` 实测（31 paths / 60 schemas）；详细矩阵见 `docs/architecture/dm-openapi-v7.1.6-capability.md`。

### 11.1 可直接代理（OpenAPI 原生）
- tasks/sources CRUD、source enable/disable/relay、`GET /tasks/{name}/status`（每 source 一条 SubTaskStatus：`stage`、`dump|load|sync_status`、`seconds_behind_master`、`synced`、`unresolved_groups`）、`.../sources/{s}/schemas/...`（库表浏览）、`.../migrate_targets`（route-rules 预览）、`/cluster/masters|workers`（健康）。
- 请求体字段：`StartTaskRequest{remove_meta, safe_mode_time_duration, source_name_list, start_time}`、`StopTaskRequest{source_name_list, timeout_duration}`；`Task` 含 `ignore_checking_items`、`on_duplicate`、`shard_mode`。
- 响应形状：`POST /tasks`→**201 `OperateTaskResponse`**（非 Task）；`POST /tasks/templates/import`→**202**（异步）；`DELETE /tasks|sources/{name}`→**204**、失败 **400**（DM 仅 GET source/task 文档化 404）。`GET /tasks` 支持 `with_status`/`stage`/`source_name_list` 过滤（代理须透传）。

### 11.2 缺口 → 兜底（必须按此实现）
| 产品能力 | DM v7.1.6 OpenAPI | 兜底 |
|---|---|---|
| `pause` / `resume` | **无**（仅 `POST /tasks/{name}/start` `/stop`；`TaskStage` enum `[Stopped,Running,Finished]` 无 `Paused`） | 后端封装 **dmctl `pause-task` / `resume-task`**；`desiredState:paused` 仅由后端状态机产生，**不**从 DM stage 反推 |
| `check-task` 预检 | **无端点** | 后端封装 **dmctl `check-task`**；原生 YAML **必须由 `POST /api/v1/tasks/converters` 生成**（OpenAPI Task JSON→`task_config_file`），**禁止手写原生渲染器**（map/seq、`mysql-instances` vs `source-config` 偏差，2026-09-24校准）；`OperateTaskResponse.check_result` 仅作 start/stop 附带补充，**不替代** `/task-precheck` |
| 任务日志 | **无端点** | 后端自实现（worker 日志/落库）；不得透传原生 |
| YAML 导出 | **无端点**（仅 `POST /tasks/converters` 可转换） | 后端以**落库 config → `converters`** 渲染，导出前**脱敏**（D16）；`/tasks/{name}/yaml` 同口径 |
| 版本探测 | `dm.json` 自称 `info.version=6.0.0`（与二进制 7.1.6 不符）；`/cluster/info` 只回 cluster_id | 以 **dmctl / 二进制 / 配置**为准；契约 `x-dm-compat` 记录已校准 v7.1.6 |
| `Task` JSON 形状 | OpenAPI schema 强校验：`POST/PUT /tasks` 缺 `required`（`on_duplicate`、`enhance_online_schema_change`）即 **400** | `toDMOpenAPITask` 输出**必须过 `POST /tasks/converters` 校验**（合入必跑门禁）；补 `on_duplicate`(缺省 `error`)、`enhance_online_schema_change`(缺省 **`true`**，勿下发 `false`)；**删**非 schema 键 `case_sensitive`/`block_allow_list`；`routes`→`table_migrate_rule[]`、`filters`→`binlog_filter_rule`(map: name→rule) |
| dmctl 结果判定 | `pause/resume/check-task` 失败仍 **exit=0**（仅 JSON `result:false`+`msg`）；仅客户端错误（缺文件）exit≠0 | 后端**必须解析 JSON `result`/`msg`** 判成败，**禁止只看退出码**（否则 D14/D15 误置 `paused/stopped`，红线级）；`DMCTL_BIN` **钉 v7.1.6 绝对路径**（宿主 `tiup dmctl` 默认 v8.5.8，禁用） |
| 空源 / 空 `source_conf` | `POST /tasks/converters` 对 `source_config.source_conf: []` 返回 **HTTP 500**（非 400） | 后端**渲染/下发前拦截**「空源」，映射 `E_PARAM_RANGE`（写侧 422+42201 / 诊断域恒 200+`valid:false`），**禁止把 DM 5xx 透传**（D12-b） |

### 11.3 监控字段映射（喂状态/延迟/阶段与 PRECHECK）
- `stage`（+ 契约 `nativeState`）→ 阶段展示与 §9 状态消歧输入；
- `seconds_behind_master` → 延迟指标；
- `unresolved_groups` → 分片 DDL 冲突，进 `PRECHECK_*` 告警（D8）；**来源取 `GET /tasks/{name}/status.sync_status.unresolved_groups`**（check-task 输出未必含）。
- **PRECHECK 映射按 `code=NNNNN`**（`20003/20031/10001/26001/26003…`）**弃关键字匹配**（decode 串含 "router" 会误命中 `PRECHECK_ROUTE_OVERLAP`，2026-09-24 校准）。

### 11.4 安全（承 D16）
- 代理对 task/source 响应**白名单化**：DM 在 **GET 时隐藏整块 `security`**（三字段 `required`，含 `*_content`）——故剔除/置空范围从 `password` **扩到 `security.*`**（含一切 `*password*`、`*_content` 键）；source 与 task 的 GET 响应一律抹 `security` 整对象。**不入日志/审计原文**；`/tasks/{name}/yaml` 同口径。列为后端合入门禁。

### 11.5 POC 目标口径（2026-09-24 定，@ds-测试 取证）
- 目标地址：**`10.168.2.241:4000`**（现网同口径）；`192.168.2.241` 仅宿主内可达，**不得**写入文档/配置。
- 目标账号：**`dm_verify`（最小权限）**，授权仅 `dm_meta.*` / `shop.*` / `shop_merged.*`（DDL/DML，无 SUPER/GRANT）；**不落 root**。超范围库须**扩授 dm_verify**。
- 目标库映射（选项 **B**）：single→`shop`，shards→`shop_merged`（现网 live 口径）。
- **POC 运行面（2026-09-24 定 —— @易鹏 选 ②）**：**独立 DM 控制面 `dmprobe`**（tiup 另起 cluster，目录 `/data/dm-deploy-probe`，端口 master **8361** / worker **8362-8364** / peer **8391** / **:18080**，`server_configs.master.openapi: true`），零触碰 live master/worker 与 2 个 live 任务。共置与 scale-out 第 4 worker **均撤销**。
- **数据面隔离（必须）**：新 cluster `meta-schema = probe_dm_meta`（避开 live `dm_meta`）；目标库 single→**`probe_shop`**、shards→**`probe_shop_merged`**（避开 live `shop`/`shop_merged`）。三者须建库并 `GRANT ... TO 'dm_verify'@'%'`。收尾 `tiup dm destroy dmprobe` + drop `probe_*`。
- **worker 容量**：本部署 **1 worker = 1 source**（`-w`→`46033 not free`、无多源开关）；独立控制面天然规避，**不再 scale-out live**。
- **共源读取（前置门槛）**：`dmprobe` 与 live 同读上游 3306/3307/3308 **允许**（MySQL 多副本），但 **server-id 必须按 cluster/worker 唯一**——同源相同 server-id 会触发 MySQL 踢旧连接、两 side 互踢。relay-dir / `meta-schema` / 端口全独立。建 task **前**须在源核 `SHOW PROCESSLIST`/`SHOW REPLICAS`（或 `SHOW SLAVE HOSTS`）确认两 cluster 连接并存无被 kill，并确认源端 binlog 保留覆盖两 cluster 起点；未过门槛不得建 task。
- **源配置编辑**：`dmctl config source -p` 是 **export**（非 update）；无单源 update；唯一变更是 **master 级整树 `config import`**，无法 per-source 隔离 ⇒ 属 **P1**，在新 cluster / 维护窗口补测，不在 live 上试。
- 凭据外置：`/data/dm-mysql/tidb-target.env`（0600、4 键、**不入仓**、未回显）；后端读该文件做连通预检。
- 后续：POC 结束轮换 `root`@`%`（口令已外泄）。

### 11.6 DM 错误码 → 契约码映射（404 语义统一，2026-09-24 定）
- **未知任务**（`GET /tasks/{name}`、`/tasks/{name}/status`、`/tasks/{name}/yaml`）**一律 404 `E_NOT_FOUND`**；`state:"new"` 仅表示**客户端草稿（未创建）**，不用于服务端资源查询（只读面现状 200 `new` 作废）。
- DM `GET /tasks/{name}` 返回 **400 + `error_code 46018`**（task not exist）→ 映射 **404 `E_NOT_FOUND`**。
- 通用规则：dm-master **可达**但返回业务错误码时，按「DM `error_code` → 契约码」表映射；**502 仅限 dm-master 控制面不可达**（D12-b）。未识别 DM 码 → 原码进 `data`，HTTP 按语义（4xx/5xx），**不得伪装 404**。
- 方法不匹配：契约宜 **405**（P1 polish；只读面现回 404 可接受，不阻塞）。
