# frontend

PunchCard 的 Web 前端：Vue 3 + Element Plus + Vite。

- 开发模式：`npm run dev`（默认 `http://127.0.0.1:5173`，`/api` 已代理到后端 `8000`）
- 生产构建：`npm run build`（产物 `dist/`，由后端 `app/main.py` 直接托管）

主要入口：

- `src/api/index.js` — axios 实例与全部后端接口封装
- `src/router/index.js` — 路由与页面标题
- `src/views/` — 概览 / 账户管理 / 任务设置 / 平台插件 / 签到日志
- `src/utils/format.js` — 跨页面复用的格式化工具（平台名/配色/时间）
