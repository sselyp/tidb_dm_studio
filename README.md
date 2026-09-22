# TiDB DM Studio

Web 可视化平台，用于配置、预检、启停与监控 **MySQL → TiDB** 的 DM 数据迁移，
替代手写 `task.yaml` + `dmctl`。

## 目标链路

数据源管理 → 任务配置（全参数） → 预检 `check-task` → 启停/迁移 → 监控与日志

## 仓库结构

```
docs/       P0 架构、设计与参数清单
api/        接口契约（单一事实源）：OpenAPI + 契约校验脚本
backend/    Go 服务：DM OpenAPI 代理 + 增强层
frontend/   React + TypeScript + Vite + Ant Design
deploy/     部署编排（docker-compose / systemd / 镜像）
scripts/    工程与 CI 辅助脚本
```

## 技术栈

| 层 | 选型 |
|---|---|
| 后端 | Go（复用 dm-master OpenAPI，做代理 + 增强层） |
| 前端 | React + TypeScript + Vite + Ant Design |
| 契约 | OpenAPI 3，`info.version` 记录版本；`check_contract.py` 校验 |
| 认证 | HttpOnly + SameSite=Lax Cookie（`dm_session`）+ 服务端会话 + CSRF 双提交 |

## 本地开发

```bash
cp .env.example .env      # 填入本地配置，勿提交
make backend              # 启动后端
make frontend             # 启动前端
make contract             # 校验接口契约
```

## 工程约束

- 不硬编码内部地址 / 密钥；全部走环境变量或配置文件，仓库只留 `.env.example`。
- 提交前需通过 `check_contract.py` 与 CI（后端 build/test、前端 lint/build）。

## License

Apache-2.0，见 [LICENSE](./LICENSE)。
