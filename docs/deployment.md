# 部署与 Caddy 路由

项目只管理 Supabase 后端，并在 `make init` 时创建供宿主机 Caddy 使用的 `caddy/Caddyfile`。外部 HTTPS 入口由你独立管理，本项目没有 Tunnel 服务、token 或启动开关。

## 入口选择

推荐不同子域名，使用同一个 Caddy 监听端口按 Host 分流：

| Host | 后端（宿主机地址） | 用途 |
| --- | --- | --- |
| `api.example.com` | `127.0.0.1:8000` → public-api → Envoy | Auth、REST、GraphQL、Storage、Realtime、Functions |
| `admin.example.com` | `127.0.0.1:8001` → Envoy → Studio | 管理界面；保留 Dashboard Basic Auth |

Supabase API 本身已有 `/auth/v1`、`/rest/v1` 等 prefix。同域名也可以按这些路径分流，并把根路径留给 Studio；但两个子域名更方便独立设置访问策略。这里不额外加 `/api` 或 `/admin` 前缀，避免需要调整 SDK、回调、Studio 静态资源及跳转路径。管理域名指向网关，不直接指向无 Basic Auth 的 `studio:3000`。

## 初始化与启动

```bash
make init
```

生成的 Caddyfile 默认监听 `127.0.0.1:8080`，域名为 `api.localhost` / `admin.localhost`。编辑 `caddy/Caddyfile`，把两个 Host 换成真实域名。初次生成也可以在 `.env` 中预先设置 `CADDY_API_HOST`、`CADDY_ADMIN_HOST`、`CADDY_PORT`；已有文件始终保留，后续改 `.env` 不会重新渲染 Caddyfile。

配置 `.env`：

```dotenv
SUPABASE_PUBLIC_URL=https://api.example.com
API_EXTERNAL_URL=https://api.example.com/auth/v1
SITE_URL=https://app.example.com
ADDITIONAL_REDIRECT_URLS=https://app.example.com/auth/callback
```

`SITE_URL` 是业务前端，不是 Studio。默认保持 `DISABLE_SIGNUP=true`；开放注册前配置并验证 SMTP。公网 URL 模式要求 HTTPS、邮箱/手机确认和 Functions JWT 校验。

```bash
make check
make up
caddy validate --config caddy/Caddyfile --adapter caddyfile
caddy run --config caddy/Caddyfile --adapter caddyfile
# 修改后，在另一个终端执行：
caddy reload --config caddy/Caddyfile --adapter caddyfile
```

Caddy 安装和进程管理独立于 `make up`。后端端口来自初次生成时的 `PUBLIC_API_PORT` / `STUDIO_PORT`，改端口后须同步编辑 Caddyfile。默认 HTTP listener 用于外部已终止 TLS 的入口，入口须保留原始 Host；不匹配的 Host 返回 404。不要把此 HTTP listener 直接当作公网 HTTPS 服务。

此配置使用宿主机 loopback 地址。若 Caddy 放入普通 bridge 网络容器，需要调整网络与 upstream；容器内的 `127.0.0.1` 并非宿主机。

若由宿主机 Caddy 直接提供公网 HTTPS，可将生成文件改成下面的两个站点块，并配置 DNS 与 80/443 入站访问，Caddy 自动管理证书：

```caddyfile
api.example.com {
    reverse_proxy 127.0.0.1:8000
}
admin.example.com {
    reverse_proxy 127.0.0.1:8001
}
```

## 验收

启动 Caddy 后验证 Host 路由（默认配置使用 `api.localhost` / `admin.localhost`）：

```bash
curl -i -H 'Host: api.example.com' http://127.0.0.1:8080/healthz  # 200
curl -i -H 'Host: api.example.com' http://127.0.0.1:8080/         # 404
curl -i -H 'Host: api.example.com' http://127.0.0.1:8080/pg/      # 404
curl -i -H 'Host: admin.example.com' http://127.0.0.1:8080/       # 401 Basic Auth
curl -i -H 'Host: unknown.example.com' http://127.0.0.1:8080/     # 404
```

管理界面使用 `.env` 的 `DASHBOARD_USERNAME` / `DASHBOARD_PASSWORD`。外部入口配置完成后，另行验证 HTTPS、Studio 登录、Auth 回调、文件上传和 Realtime WebSocket。Caddy reverse_proxy 保留请求路径并支持 WebSocket 升级。业务 API 不应使用交互式登录门禁或共享缓存。

数据库的 5432 / 6543 仍只监听本机；此 Caddyfile 只路由 HTTP/WebSocket。
