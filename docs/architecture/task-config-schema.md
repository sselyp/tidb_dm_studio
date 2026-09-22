# P0 — 任务配置 `jsonSchema` + `formLayout` 契约

> Owner: 架构师。字段级形态以此为准；接口形状以 `api/openapi.yaml`（v0.9.0）为准。
> 目标：前端**只做渲染**，不硬编码任何 DM 参数；后端下发 schema，前后端同源。
> 注：具体预检项与少量版本相关字段（`online-ddl`、`validators` 等）待 DM 版本确定后校准，其余结构冻结。

## 1. 端点

```
GET /api/task-schema        # 返回 { version, jsonSchema, formLayout }
```

`version` 跟随 `api/openapi.yaml` 的 `info.version`（当前 `0.9.0`），前端据此判断是否需重取。
写侧提交体（已冻结）：`{ name, config: TaskConfig }`，其中 `config.sources[]` 复用读侧 `SourceInstance`。

## 2. 响应结构

```jsonc
{
  "version": "0.9.0",
  "jsonSchema": { "$schema": "https://json-schema.org/draft/2020-12/schema", "type": "object", "properties": { /* TaskConfig */ }, "required": ["sources"] },
  "formLayout": {
    "steps": [ /* Step[] */ ],
    "ui": { "/name": { /* UiField */ } }
  }
}
```

### 2.1 `UiField`（`formLayout.ui`，键为 JSON Pointer）

| 字段 | 类型 | 说明 |
|---|---|---|
| `widget` | string | 见 §3 控件表 |
| `help` | string | 帮助文案（悬浮/说明） |
| `placeholder` | string | 占位符 |
| `options` | `{label,value}[]` | 静态枚举（与 `jsonSchema` 的 `enum` 一致，供 UI 直读） |
| `visibleWhen` | object | 条件显示，见 §4 |
| `advanced` | bool | true 折叠进「高级」 |
| `unit` | string | 数值单位（如 `s`、`MiB`、`条/秒`） |
| `order` | int | 组内排序（可选） |

### 2.2 `Step` / `Group`

```jsonc
{ "key": "basic", "title": "基础信息", "description": "...",
  "groups": [ { "key": "meta", "title": "任务元信息", "fields": ["/name", "/taskMode"] } ] }
```

- `fields` 用 JSON Pointer，指向 `jsonSchema` 中的路径。
- 分组只影响布局；校验一律以 `jsonSchema` 为准。

## 3. 控件映射（`widget`）

| widget | 适用 | 备注 |
|---|---|---|
| `input` | string | |
| `password` | string (`writeOnly`) | 零回显；数据源口令走 `SecretProvider` |
| `textarea` | string 多行 | |
| `number` | integer/number | 带 `min/max/unit` |
| `switch` | boolean | |
| `select` | enum | 单选 |
| `radio` | enum | 少量选项 |
| `multi-select` | array\<enum\> | |
| `key-value` | object 自由键值 | 如 `session`、`filter-args` |
| `array-table` | array\<object\> | 如 `sources[]`、`routes[]`、`block-allow-list` |
| `code-yaml` | string | YAML 透传（`rawYaml` 分支） |
| `tag-list` | array\<string\> | 如 `case-sensitive` 表名列表 |
| `cron-hint` | — | 预留 |

## 4. 条件显示与继承

### 4.1 `visibleWhen`（前端渲染用）

```jsonc
{ "/sources/*/binlogGtid": { "visibleWhen": { "field": "/taskMode", "in": ["incremental", "all"] } } }
```

- 求值失败一律**显示**（安全默认），服务端仍会终校验。
- 组合条件用 `{ "all": [...] } / { "any": [...] }`。

### 4.2 默认值 + per-source override（已冻结：物化展开）

- `TaskConfig` 含**全局默认段**（如 `syncers`、`mydumpers`、`loaders`、`routes`、`filters`）。
- `SourceInstance` 可含**同名 override 段**；保存时后端把「全局默认 + source override」**物化展开**到每个 source，落库即展开态。
- 读接口恒返回**已展开的有效值**，前端表单只渲染有效值、**不做隐式合并**。
- config hash 对落库展开态计算（去重/幂等/审计 beforeHash 一致）。

## 5. 字段目录（按向导步骤）

> 路径相对 `config`（即 `TaskConfig`）。`S` = 支持 per-source override。★ = 常用，默认展示；其余 `advanced:true` 折叠。

### Step 1 基础信息
| Pointer | widget | 取值/默认 | 说明 |
|---|---|---|---|
| `/name` | input | string, 必填 | 任务名，全局唯一 |
| `/taskMode` | radio | `all`(默认)/`full`/`incremental` | 任务模式 |
| `/caseSensitive` | switch | bool, 默认 false | 大小写敏感 |
| `/metaSchema` | input | string | 库表信息所在库，默认同下游 |
| `/timezone` | select | IANA tz / 空 | 上游时区 |

### Step 2 上游（多源 `sources[]`，`array-table`）
| Pointer | widget | 取值/默认 | 说明 |
|---|---|---|---|
| `/sources` | array-table | `minItems=1` | 复用读侧 `SourceInstance` |
| `/sources/*/sourceRef` | select | 必填 | 引用已配置数据源 |
| `/sources/*/metaSnapshot` | key-value | `{binlogName,binlogPos,binlogGtid}` | 全量起点快照 |
| `/sources/*/binlogName` | input | string | 增量起点；full 隐藏（`visibleWhen`） |
| `/sources/*/binlogPos` | number | int | 同上 |
| `/sources/*/binlogGtid` | input | string | 与 binlogName/Pos 二选一 |
| `/sources/*/routeRules` | multi-select | string[] | S，覆盖全局 `routes` |
| `/sources/*/blockAllowList` | array-table | `{schemaPattern,tablePattern}` | S |
| `/sources/*/filters` | multi-select | string[] | S，引用 `filters` |
| `/sources/*/expressionFilter` | array-table | `{schemaPattern,tablePattern,expression}` | S |

### Step 3 同步对象（全局）
| Pointer | widget | 取值/默认 | 说明 |
|---|---|---|---|
| `/routes` | array-table | `{schemaPattern,tablePattern,targetSchema,targetTable}` | 映射/重命名 |
| `/blockAllowList` | array-table | `{schemaPattern,tablePattern}` | 限定范围 |
| `/filters` | array-table | `{name,expression}` | |
| `/expressionFilter` | array-table | 同 §Step2 | |

### Step 4 高级参数（默认 `advanced:true`）
| Pointer | widget | 默认 | 说明 |
|---|---|---|---|
| `/targetDatabase` | key-value | `{host,port,user,password,session}` | 下游 TiDB；口令 `password` 零回显 |
| `/onlineDdl` | switch | true | DM 2.0 默认开启；版本相关待校准 |
| `/onlineDdlShadowTableRules` | array-table | | |
| `/shadowTableRules` | array-table | | |
| `/mydumpers` | array-table | `{global,threads,chunkFilesize,...}` | S 可覆盖 |
| `/loaders` | array-table | `{global,poolSize,dir,...}` | S |
| `/syncers` | array-table | `{global,workerCount,batch,queueSize,...}` | S |
| `/validators` | array-table | `{global,mode,...}` | 版本相关待校准 |
| `/exprFilter` | code-yaml | | 透传 |
| `/relayDir` | input | | |
| `/collationCompatible` | select | | 版本相关待校准 |

> 其余 `task.yaml` 字段以 `additionalProperties:true` 保 round-trip：未上表单的键经 `code-yaml`（YAML 双视图）可见/可改，**不丢**。

## 6. 校验与错误映射

- 前端即时校验（必填/类型/范围/正则）来自 `jsonSchema`；冲突类规则**不前端自造**。
- 权威判据是服务端 `validate` / `check-task` 返回的 `PRECHECK_*`；`ValidationData.valid` + `data.errors[].errorCode` 驱动标红。
- 字段级错误：`FieldError.errorCode`（`E_* ∪ PRECHECK_*`，已 `enum` 冻结）→ `errorCodes.ts` 常量映射文案。
- 多源合并冲突 5 个稳定码（表名/主键/route-rules 覆盖/同名 task/字符集时区）随 `check-task` 进 `ValidationData` 告警。

## 7. 待校准（依赖 DM 版本）

- `online-ddl` 及其 shadow rules 的字段集合与默认。
- `validators` 是否可用、字段形态。
- 版本相关的 precheck 项与 `PRECHECK_*` 触发条件。
- `Task.sources` 多源在当前版本是否允许 `length>1`（运行时校验，契约不变形）。
