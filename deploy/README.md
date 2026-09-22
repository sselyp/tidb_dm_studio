# deploy

部署编排。目标形态：**内网私有部署**，支持容器与裸机两种。

```
deploy/
├── docker-compose.yml      # 本地/内网一键起（backend + frontend + redis 可选）
├── .env.example            # 部署变量示例，勿提交真实值
└── systemd/                # 裸机 systemd 单元（待补）
```

约定：

- 生产配置全部经环境变量注入（对齐根 `.env.example`）。
- HTTPS 由前置反向代理终止；`cookieAuth` 的 `Secure` 随部署是否 HTTPS 自动开关。
- 多实例部署时启用 Redis 作为 `SessionStore` 与契约中的共享会话存储。
