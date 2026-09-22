# frontend

React + TypeScript + Vite + Ant Design。

## 运行

```bash
npm install
npm run dev      # http://localhost:5173 ，/api 代理到后端 8080
npm run build    # tsc --noEmit && vite build
npm run lint     # 类型检查
```

## 约定

- 认证走 HttpOnly Cookie（`dm_session`），前端不持有 token；
  state-changing 请求带上 `X-CSRF-Token` 双提交头（值取自可读 cookie）。
- 登录态与 `mustChangePassword` 由 `GET /api/me` 获取，用于路由守卫。
- 首登强制改密：`mustChangePassword=true` 时所有路由重定向到 `/account`，不可跳过。
- 任务表单 schema 由后端下发，前后端不硬编码参数。
