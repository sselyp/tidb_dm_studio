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

- [ ] DM 版本与 dm-master/dm-worker 拓扑（待 @易鹏）→ 校准 precheck 项与 API 版本差异
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
