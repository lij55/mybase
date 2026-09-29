# 部署到云主机与 Cloudflare Tunnel

## 1. 准备主机

选择有持久化 SSD 的 Linux 主机，安装 Docker Engine、Compose 2.24.4+、Make、Python 3.11+。项目目录应放在持久化磁盘；默认单机部署，主机故障会导致整体停机。升级内核或 Docker 前安排维护窗口。

将整个项目复制到服务器（不要复制另一环境的运行中数据库目录），运行 `make init`。云安全组无需为 Tunnel 开放 80/443/8000/8001/5432/6543；SSH 仅允许管理员 IP 或通过私网访问。Tunnel 需要可用 DNS 和到 Cloudflare 的出站连接，镜像仓库、SMTP、函数依赖下载也需要出站网络。

本封装所有宿主机监听均为 loopback。不要为了“让前端能访问”改成 `0.0.0.0`，前端应走 Tunnel 的 HTTPS 域名。

## 2. 建立 Tunnel

在 Cloudflare 管理的域名下准备 `api.example.com`。

1. 在 Cloudflare One 的 Networks / Connectors / Cloudflare Tunnels 中创建 **remotely managed** tunnel，选择 cloudflared。
2. 复制安装命令里的 tunnel token，只将 token 填入服务器 `.env` 的 `TUNNEL_TOKEN`，不要提交到版本库。
3. 添加 Published application route / Public hostname：主机名 `api.example.com`，服务类型 HTTP，目标 **`public-api:8080`**。
4. 不配置指向 `api-gw`、`studio`、`meta` 或 PostgreSQL 的公开路由。目标中的 `localhost` 是 cloudflared 容器自身，不是宿主机。

控制台路径可能调整，参见[官方创建流程](https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/get-started/create-remote-tunnel/)。不要使用随机域名的 Quick Tunnel 作为长期 Auth 回调地址。

## 3. 修改环境变量

```dotenv
TUNNEL_ENABLED=true
TUNNEL_TOKEN=填入实际token
SUPABASE_PUBLIC_URL=https://api.example.com
API_EXTERNAL_URL=https://api.example.com/auth/v1
SITE_URL=https://app.example.com
ADDITIONAL_REDIRECT_URLS=https://app.example.com/auth/callback
DISABLE_SIGNUP=false
ENABLE_EMAIL_AUTOCONFIRM=false
SMTP_HOST=smtp.example.com
SMTP_PORT=587
SMTP_USER=填入实际用户名
SMTP_PASS='填入实际密码'
SMTP_ADMIN_EMAIL=noreply@example.com
SMTP_SENDER_NAME=Mybase
```

域名与 SMTP 示例必须替换成你的实际配置。建议先保留 `DISABLE_SIGNUP=true`，确认邮件与 RLS 后再开放。配置 SMTP 供应商要求的发信域名验证记录（SPF、DKIM 等），实际验证注册、重置密码和邀请邮件。

```bash
make check
make up
make logs SERVICE=cloudflared
```

容器 Running 只说明进程启动，并不代表 Tunnel 已注册成功。必须在 Cloudflare 控制台检查 connector **Healthy**，再从外部网络验收。

## 4. Cloudflare 配置与验收

为整个 API hostname 设置 Cache Rule **Bypass cache**。不要启用 Cache Everything；Auth、REST、私有 Storage 不能共享缓存。源站添加 `Cache-Control: no-store`，但控制台强制缓存规则仍需移除。公开静态资源如需 CDN 缓存，后续单独设计 bucket / 域名和缓存策略。

启用 WebSockets；不要对业务 API 配置交互式 Cloudflare Access 登录或 JS Challenge，否则浏览器 SDK、预检和 WebSocket 握手可能失败。Access 适合管理入口；业务用户身份应由 Supabase Auth + RLS 控制。使用 WAF / 速率限制防滥用，但先验证 OPTIONS、Auth 回调、上传和 Realtime 不受误拦截。

从主机外部执行（不需要带私钥）：

```bash
curl -i https://api.example.com/healthz       # 200，入口进程正常
curl -i https://api.example.com/              # 404，不应出现 Studio
curl -i https://api.example.com/pg/           # 404
curl -i https://api.example.com/rest/v1/      # 未带 apikey 应被拒绝
```

再通过前端完成注册确认、登录、增删改查、跨用户 RLS 隔离、文件上传下载与 Realtime 订阅。检查浏览器 Network：HTTP 无混合内容、CORS 预检成功、WebSocket 为 101；断线后能够重连。`/healthz` 不检查数据库，不能作为唯一生产健康信号。

## 5. 管理入口

推荐 SSH 转发：

```bash
ssh -N -L 8001:127.0.0.1:8001 your-user@your-server
```

然后访问本机 `http://localhost:8001`，使用 `.env` 的 Dashboard 凭证。如果确实需要公开 Studio，使用独立域名与 Cloudflare Access 身份策略，同时保留 Basic Auth；这需要新增受保护的路由，本仓库默认不公开它。

OAuth 提供商要额外启用上游 Compose 中对应的 `GOTRUE_EXTERNAL_*` 变量；回调使用 `https://api.example.com/auth/v1/callback`。前端登录后的业务跳转 URL 则在 `ADDITIONAL_REDIRECT_URLS` 配置，这两种回调不可混淆。

Tunnel 适合 HTTP / HTTPS / WebSocket，不是浏览器直接连接 PostgreSQL 的方式。远程 SQL 管理用 SSH 转发，或另行配置私网访问。服务端大量数据库流量通常更适合云内私网。
