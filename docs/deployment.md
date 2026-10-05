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

生成的 Caddyfile 默认监听 `127.0.0.1:8080`，域名为 `api.my.supabase.local` / `admin.my.supabase.local`。只需修改 `.env` 的 `PUBLIC_HOST`，Caddy 与 Supabase 自动使用同一基础域名。运行 `make init` / `make up` 时会同步未被手工修改的 Caddyfile；手工修改的配置需自行维护。

配置 `.env`：

```dotenv
PUBLIC_HOST=example.com
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

Caddy 安装和进程管理独立于 `make up`。后端端口来自初次生成时的 `PUBLIC_API_PORT` / `STUDIO_PORT`，改端口后运行 `make init` 同步生成配置，再 reload Caddy。默认 HTTP listener 用于外部已终止 TLS 的入口，入口须保留原始 Host；不匹配 API/Studio 域名的请求默认转发到 `127.0.0.1:8090`（demo Traefik），保留原始 Host。不要把此 HTTP listener 直接当作公网 HTTPS 服务。

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

完整的配置读取、认证及安全边界命令见 [README 手动 smoke 验证](../README.md#手动-smoke-验证)。启动 Caddy 后验证 Host 路由（默认配置使用 `api.my.supabase.local` / `admin.my.supabase.local`）：

```bash
curl -i -H 'Host: api.my.supabase.local' http://127.0.0.1:8080/healthz  # 200
# 先按 README「手动 smoke 验证」读取 SUPABASE_PUBLISHABLE_KEY
curl -i -H 'Host: api.my.supabase.local' \
  -H "apikey: ${SUPABASE_PUBLISHABLE_KEY}" -H "Authorization: Bearer ${SUPABASE_PUBLISHABLE_KEY}" \
  http://127.0.0.1:8080/auth/v1/health                           # 200
curl -i -H 'Host: api.my.supabase.local' http://127.0.0.1:8080/         # 404
curl -i -H 'Host: api.my.supabase.local' http://127.0.0.1:8080/pg/      # 404
curl -i -H 'Host: admin.my.supabase.local' http://127.0.0.1:8080/       # 401 Basic Auth
curl -i -H 'Host: unknown.example.com' http://127.0.0.1:8080/     # Traefik 无匹配路由时 404；未启动时 502
```

管理界面使用 `.env` 的 `DASHBOARD_USERNAME` / `DASHBOARD_PASSWORD`。外部入口配置完成后，另行验证 HTTPS、Studio 登录、Auth 回调、文件上传和 Realtime WebSocket。Caddy reverse_proxy 保留请求路径并支持 WebSocket 升级。业务 API 不应使用交互式登录门禁或共享缓存。

数据库的 5432 / 6543 仍只监听本机；此 Caddyfile 只路由 HTTP/WebSocket。

要让宿主机 Caddy 监听所有 IPv4 网卡，在根 `.env` 添加 `CADDY_BIND=0.0.0.0`，然后运行 `make init`。生成配置使用 `bind 0.0.0.0`，默认端口仍为 `8080`；反向代理上游保持 `127.0.0.1`。手工修改过的 Caddyfile 需自行修改 `bind`。启动命令：

```bash
caddy run --config caddy/Caddyfile --adapter caddyfile
```

已有 Caddy 进程时使用 `caddy reload --config caddy/Caddyfile --adapter caddyfile`。API / Studio 按配置域名分流；其他请求转发到 demo Traefik 的 `127.0.0.1:8090`。Traefik 仍按 demo 域名分流，未匹配路由时返回 404；未启动 Traefik 时 Caddy 返回 502。

Demo 域名（默认 `authz.localhost`、`todo.localhost`、`notes.localhost`）可通过同一 Caddy 入口访问。它们会落入默认路由，由 Traefik 根据原始 Host 分流。修改 demo 的 `TRAEFIK_PORT` 时需同步修改 Caddy 默认上游端口。
