# backend

Go 服务：**DM OpenAPI 代理 + 增强层**。不重复实现 DM 调度，缺失能力再补 `dmctl/pkg` 封装。

## 结构

```
cmd/server/        进程入口
internal/          业务实现（按领域分包）
```

## 运行

```bash
go run ./cmd/server          # 需先准备 .env（见仓库根 .env.example）
go build -o bin/server ./cmd/server
```

## 约定

- 认证：`cookieAuth`（`dm_session`，HttpOnly + SameSite=Lax）+ 服务端会话，
  state-changing 请求校验 CSRF 双提交头 `X-CSRF-Token`。
- 口令存储 Argon2id（m=64MiB / t=3 / p=1，可配）+ 每用户随机盐。
- 数据源口令经 `SecretProvider`（默认 AES-256-GCM，主密钥 `DM_WEB_MASTER_KEY`）加密后入库。
- 地址 / 凭据全部走 env，禁止硬编码。
