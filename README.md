# PunchCard

自托管的多平台自动签到系统。在网页里添加账户、设置时间，剩下的交给它。

---

## 它能做什么

很多平台有「每天打卡」才能维持的东西——比如抖音的**续火花**，需要每天和好友互发消息。手动做很烦，每个平台单独写脚本又难维护。

PunchCard 用一套插件化的框架解决这个问题：新增平台只写一个插件类，其余不变。

**目前随附**

- **douyin（抖音续火花）** — 扫码登录、同步好友、每日自动发送，全流程在网页里操作
- **bilibili（B 站每日登录）** — 短信验证码登录或填 SESSDATA，每日调一次导航接口触发签到

> 以上两个在「平台插件」页标为**内置**，表示随项目附带；只是标签，同样可以卸载（先删该平台账户）。

## 快速开始

### 后端

```bash
cd backend
py -m venv .venv
.venv\Scripts\pip install -r requirements.txt
.venv\Scripts\python -m playwright install chromium   # 抖音插件需要，约 150 MB
.venv\Scripts\python run.py
```

后端启动后访问 `http://127.0.0.1:8000`，首次打开会提示创建管理员账户。

### 前端（开发模式）

```bash
cd frontend
npm install
npm run dev   # http://127.0.0.1:5173，/api 自动代理到后端
```

前端构建后由后端直接托管：`npm run build` 产出 `frontend/dist`，重启后端即可。

## Linux 部署

```bash
# 系统依赖
sudo apt update && sudo apt install -y python3 python3-venv nodejs npm

# 后端
cd /opt/punchcard/backend
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python -m playwright install --with-deps chromium

# 前端构建
cd /opt/punchcard/frontend && npm install && npm run build

# 启动
cd /opt/punchcard/backend && .venv/bin/python run.py
```

**守护进程**（用 systemd 保持常驻）：

```bash
sudo cp deploy/punchcard.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now punchcard
```

部署注意：

- 非 root 用户运行；以 root 跑 Chromium 需在 systemd 里加 `PUNCHCARD_CHROME_NO_SANDBOX=1`
- 备份时 `backend/data/` 要整体备份——数据库和加密密钥必须配对迁移，丢失 `secret.key` 则所有凭证永久无法解密

## 环境变量

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `PUNCHCARD_HOST` | `127.0.0.1` | 监听地址；局域网访问时改为 `0.0.0.0` |
| `PUNCHCARD_PORT` | `8000` | 监听端口 |
| `PUNCHCARD_DATABASE_URL` | `sqlite:///data/punchcard.db` | 数据库连接串 |
| `PUNCHCARD_TZ` | `Asia/Shanghai` | 调度时区 |
| `PUNCHCARD_SECRET_KEY` | 自动生成 | Fernet 加密密钥（base64）；未设置则持久化到 `data/secret.key` |
| `PUNCHCARD_CHROME_NO_SANDBOX` | 关闭 | root 运行 Chromium 时设 `1` |
| `PUNCHCARD_COOKIE_SECURE` | 关闭 | 非 HTTPS 下强制 Cookie 带 Secure 标记时设 `1` |
| `PUNCHCARD_RELOAD` | 关闭 | 设 `1` 开启热重载（仅开发，生产勿开） |

## 写一个新平台插件

在 `backend/data/plugins/` 下建文件夹，放一个 `plugin.py`：

```python
from app.plugins.base import BasePlugin, CheckinResult, FieldSpec

class BilibiliPlugin(BasePlugin):
    platform = "bilibili"
    name = "哔哩哔哩"
    credential_fields = [
        FieldSpec(key="cookie", label="Cookie", type="textarea"),
    ]

    def checkin(self, credentials: dict, extra: dict) -> CheckinResult:
        # 调用平台接口……
        return CheckinResult(success=True, message="签到成功")

plugin = BilibiliPlugin()
```

到「平台插件」页点「重新加载」即可，不需要改框架任何代码。也可以直接在网页上传 ZIP 安装。

插件还可以声明 `login_supported`（交互式登录）和 `friends_supported`（同步好友列表），前端会自动渲染对应 UI。

## 架构

```
backend/           FastAPI + SQLite + APScheduler
  app/
    core/          配置 / 数据库 / 鉴权 / 调度器 / 加密
    plugins/       BasePlugin 基类 + 插件注册表
    api/           REST 接口
  data/plugins/   平台插件安装目录

frontend/          Vue 3 + Element Plus + Vite
```

## License

MIT
