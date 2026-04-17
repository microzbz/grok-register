# Grok 账号批量注册工具

基于 [DrissionPage](https://github.com/g1879/DrissionPage) 的 Grok (x.ai) 账号自动注册脚本，使用 Cloudflare Worker 临时邮箱接收验证码，通过 Chrome 扩展修复 CDP `MouseEvent.screenX/screenY` 缺陷绕过 Cloudflare Turnstile。

注册完成后自动推送 SSO token 到 [grok2api](https://github.com/chenyme/grok2api) 号池。

## 特性

- Cloudflare Worker 临时邮箱（支持自有域名）
- Cloudflare Turnstile 自动绕过（Chrome 扩展 patch `MouseEvent.screenX/screenY`）
- 无头服务器支持（Xvfb 虚拟显示器，自动检测 Linux 环境）
- 中英文界面自动适配
- 自动推送 SSO token 到 grok2api（支持 append 合并模式）

---

## 环境要求

- Python 3.10+
- Chromium 或 Chrome 浏览器
- 已部署可收件的 Cloudflare Worker 邮箱服务
- Worker 对应的邮箱域名、接口地址和管理密码
- 可选：[grok2api](https://github.com/chenyme/grok2api) 实例（用于自动导入 SSO token）

---

## 安装

```bash
pip install -r requirements.txt
```

无头服务器（Linux）额外安装：

```bash
apt install -y xvfb
pip install PyVirtualDisplay
# 推荐用 playwright 装 chromium（避免 snap 版 AppArmor 限制）
pip install playwright && python -m playwright install chromium && python -m playwright install-deps chromium
```

---

## 配置文件（config.json）

```bash
cp config.example.json config.json
```

编辑 `config.json`：

```json
{
    "run": { "count": 10 },
    "cloudflare_mail_api_base": "https://your-worker.example.com",
    "cloudflare_mail_admin_password": "",
    "cloudflare_mail_domain": "transsionclaw.com",
    "proxy": "",
    "browser_proxy": "",
    "api": {
        "endpoint": "",
        "token": "",
        "append": true
    }
}
```

### 字段说明

| 字段 | 类型 | 说明 |
|------|------|------|
| `run.count` | int | 注册轮数，`0` 为无限循环，可通过 `--count` 覆盖 |
| `cloudflare_mail_api_base` | string | Cloudflare Worker 地址，例如 `https://mail.example.com` |
| `cloudflare_mail_admin_password` | string | Worker `x-admin-auth` 对应的管理密码 |
| `cloudflare_mail_domain` | string | Worker 配置的收件域名，例如 `transsionclaw.com` |
| `proxy` | string | Worker API 请求代理（可选） |
| `browser_proxy` | string | 浏览器代理，无头服务器需翻墙时填写（可选） |
| `api.endpoint` | string | grok2api 地址，支持填 `http://127.0.0.1:8000` 或完整 `/admin/api/tokens/add` 地址，留空跳过推送 |
| `api.token` | string | grok2api 的 `app_key` |
| `api.pool` | string | 导入号池，推荐 `auto`，也可填 `basic` / `super` / `heavy` |
| `api.append` | bool | `true` 走 `/admin/api/tokens/add` 追加导入，`false` 覆盖指定 pool |

---

## Cloudflare Worker 邮箱说明

- 当前脚本会先调用 Worker 的 `/admin/new_address` 创建邮箱，再使用返回的 `jwt` 访问 `/api/mails`
- 你提供的 Worker 需要开放这两个接口，并且 `cloudflare_mail_domain` 必须和 Worker 内的 `EMAIL_DOMAIN` 一致
- `cloudflare_mail_admin_password` 必须和 Worker 环境变量 `ADMIN_PASSWORD` 一致

---

## 启动方式

```bash
# 按 config.json 中 run.count 执行（默认 10 轮）
python DrissionPage_example.py

# 指定轮数
python DrissionPage_example.py --count 50

# 无限循环
python DrissionPage_example.py --count 0
```

无头服务器会自动启用 Xvfb，无需额外配置。

---

## 输出文件

```
sso/
  sso_<timestamp>.txt     ← 每行一个 SSO token
logs/
  run_<timestamp>.log     ← 每轮注册的邮箱、密码和结果
```

目录在首次运行时自动创建。

---

## 文件结构

```
├── DrissionPage_example.py     # 主脚本
├── email_register.py           # Cloudflare Worker 临时邮箱封装
├── config.json                 # 配置文件（不入库）
├── config.example.json         # 配置模板
├── requirements.txt            # Python 依赖
├── turnstilePatch/             # Chrome 扩展（Turnstile patch）
│   ├── manifest.json
│   └── script.js
├── sso/                        # SSO token 输出（自动创建）
└── logs/                       # 运行日志（自动创建）
```

---

## 无头服务器部署注意

- snap 版 chromium 在 root 下有 AppArmor 限制，推荐用 playwright 安装的 chromium
- 服务器直连 x.ai 可能被墙，需在 `browser_proxy` 填写代理地址
- 脚本自动检测 Linux 环境并启用 Xvfb + playwright chromium 路径

---

## 致谢

- [kevinr229/grok-maintainer](https://github.com/kevinr229/grok-maintainer) — 原始项目
- [grok2api](https://github.com/chenyme/grok2api) — Grok API 代理
- Cloudflare Email Worker — 临时邮箱服务
