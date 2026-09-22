# 接口契约

本目录是前后端接口的**单一事实源**。

```
api/
├── openapi.yaml        # 当前生效契约（版本记录在 info.version，如 0.6）
├── check_contract.py   # 契约校验脚本（CI 与本地共用）
└── README.md
```

## 约定

- **不按版本号命名文件**：`openapi.yaml` 始终是当前契约，版本写在 `info.version`
  （当前随 v0.6 起，之后每轮改动递增）。这样 CI、代码生成、文档引用路径永不漂移。
- 契约改动与实现同 PR 提交；CI 会跑 `check_contract.py`，不通过不允许合并。
- 若要保留历史快照，放 `api/versions/openapi-vX.Y.yaml`（只读、不参与 CI）。

## 校验

```bash
python3 api/check_contract.py api/openapi.yaml
```

CI: `.github/workflows/ci.yml` 的 `contract` job（`api/openapi.yaml` 存在时执行）。

## 已定稿要点（v0.6）

- 全局 `security: cookieAuth`，cookie 名 `dm_session`（HttpOnly + SameSite=Lax）；
  除 `POST /api/login` 与健康检查外，`/api/**` 未认证返回 401。
- 认证接口：`POST /api/login`、`POST /api/logout`、`POST /api/password`、`GET /api/me`。
- 错误码：40101 `E_UNAUTHENTICATED`、40102 `E_INVALID_CREDENTIALS`、
  40301 `E_FORBIDDEN`、40302 `E_PASSWORD_CHANGE_REQUIRED`、
  42206 `E_WEAK_PASSWORD`、42901 `E_RATE_LIMITED`；错误体统一走 `data.errors`。
- 所有 `password` 字段 `writeOnly`、零回显；改密成功吊销该用户全部会话（含当前）。
- `Task.sources` 为数组、`minItems=1`；单库=1、合并>1，版本差异只在运行时校验。
- 多源合并冲突以稳定的 `PRECHECK_*` 码进 `ValidationData` 告警。
