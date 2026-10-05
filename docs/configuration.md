# 环境变量

`.env.example` 是最小模板，仅包含 `PUBLIC_HOST` 和实际使用的密钥；端口、内部数据库、Auth 等参数使用代码和 Compose 中的默认值，可按需追加到 `.env`。`.env` 是本地真实配置。`make init` 只补全空密钥，非空内容保留；数据库已经初始化后缺失密钥会拒绝启动，防止意外生成不匹配的新密钥。`.env` 不能当作 shell 脚本 `source`。

为使 Python 校验与 Compose 读取一致，本封装采用简单的 dotenv 子集：每行 `KEY=value`；注释单独成行；含 `$` 或 `#` 的密码用单引号包裹，如 `SMTP_PASS='abc$def#123'`。不支持变量插值、多行值、嵌套引号或反斜线转义。脚本避免 shell 导出的同名环境变量覆盖 `.env`。

## 常用变量

| 变量 | 说明 |
| --- | --- |
| `PUBLIC_HOST` | 统一基础域名，默认 `my.supabase.local`；API 为 `api.` 子域名，管理入口为 `admin.` 子域名 |
| 自动派生 URL | SDK 根地址 `https://api.<PUBLIC_HOST>`；Auth 外部地址为该地址加 `/auth/v1`，无需在 `.env` 重复填写 |
| `SITE_URL` | 前端站点根地址，默认 `https://<PUBLIC_HOST>`；部署业务前端时按需指定 |
| `ADDITIONAL_REDIRECT_URLS` | 逗号分隔的允许回调 URL，如 `https://app.example.com/auth/callback`；避免过宽通配符 |
| `PUBLIC_API_PORT` / `STUDIO_PORT` | 本机 API / Studio 端口，默认 8000 / 8001；不影响外部 URL |
| `DB_SESSION_PORT` / `DB_TRANSACTION_PORT` | 仅改变宿主机端口；内部 `POSTGRES_PORT=5432` 不动 |
| `COMPOSE_PROJECT_NAME` | 初次部署前决定；修改会选择新的 Docker 网络和命名卷，不能用来直接复制实例 |
| `UP_TIMEOUT` | 服务启动后的健康检查等待秒数，默认 300；不限制镜像下载时间 |
| `DISABLE_SIGNUP` | 默认 `true`；要开放注册改为 `false` 并配置 SMTP |
| `ENABLE_EMAIL_AUTOCONFIRM` | 默认 `false`；仅隔离的本地开发可临时启用；公网 URL 模式拒绝启用 |
| `SMTP_HOST/PORT/USER/PASS` | 邮件服务参数；还要填写 `SMTP_ADMIN_EMAIL`、`SMTP_SENDER_NAME` |
| `FUNCTIONS_VERIFY_JWT` | 默认 `true`；函数内部仍须判断用户身份与业务权限 |
| `STORAGE_FILE_SIZE_LIMIT` | Supabase Storage 限制，默认 50 MiB；Nginx 也有 `client_max_body_size 50m`，更大文件需要同步调整并核对 Cloudflare 限制 |

内部数据库 `db:5432/postgres` 是本封装固定的拓扑。外接普通 PostgreSQL 不是修改几个变量就可以完成：Supabase 依赖额外角色、扩展和初始化迁移。

## Caddy 配置生成

`make init` 从 `caddy/Caddyfile.example` 生成 `caddy/Caddyfile`，域名由 `PUBLIC_HOST` 派生，默认 `api.my.supabase.local` / `admin.my.supabase.local`。可按需追加 `CADDY_PORT`（默认 `8080`）、`PUBLIC_API_PORT`（默认 `8000`）、`STUDIO_PORT`（默认 `8001`）。

修改 `PUBLIC_HOST` 或端口后运行 `make init` / `make up`，仍符合生成模板的 Caddyfile 会自动同步；手工修改的 Caddyfile 保留，需自行更新。随后 reload Caddy。文件不包含密码，Studio 沿用 Envoy 的 Dashboard 凭证，默认用户名 `supabase`。

旧 `.env` 未指定 `PUBLIC_HOST` 时保留显式 API URL；迁移时添加 `PUBLIC_HOST`，删除旧 `SUPABASE_PUBLIC_URL`、`API_EXTERNAL_URL`、`CADDY_API_HOST` 和 `CADDY_ADMIN_HOST`，避免直接使用 Compose 时沿用旧 URL。已有密钥必须保留。未启用的 Logflare、MinIO、Kong 等变量不再生成，也不再要求备用密钥。

API 域名根路径 `/` 返回 404 是 API 与管理界面隔离的预期行为。使用 `/healthz` 或 `/auth/v1/health` 检查 API；管理界面从 `admin.<PUBLIC_HOST>` 访问。

公网校验根据 `SUPABASE_PUBLIC_URL` 是否使用非 loopback 主机名判断，不再依赖 Tunnel 开关。

## 密钥模式与轮换

新环境使用 **opaque API key + ES256**：浏览器使用 `SUPABASE_PUBLISHABLE_KEY`（`sb_publishable_...`），可信服务端使用 `SUPABASE_SECRET_KEY`（`sb_secret_...`）。`make init` 需要 Node.js >= 18，使用内置 crypto 生成 P-256 密钥，无 npm 依赖。根 `.env` 不再生成旧版 `ANON_KEY` / `SERVICE_ROLE_KEY`。

`JWT_KEYS` 含 ES256 私钥，仅传给 Auth；`JWT_JWKS` 仅含公钥，传给 PostgREST、Realtime、Storage 和 Functions。Auth 签发的用户 access token 默认一小时。网关将 opaque key 转为内部 `ANON_KEY_ASYMMETRIC` / `SERVICE_ROLE_KEY_ASYMMETRIC` JWT（五年有效），保留请求中的用户 JWT。内部 JWT 不用于前端配置。`JWT_SECRET` 保留供数据库初始化、Supavisor 和内部管理服务使用，不负责新用户令牌签名。Realtime 管理接口在最新版仍使用内部 HS256；容器通过原生 `/healthcheck` 检查进程存活，`make smoke` 另外验证公开入口的 WebSocket 握手与 publishable key，`make integration` 验证 ES256 用户订阅、Broadcast、Presence 和数据库事件。无需额外生成 HS256 健康检查令牌。

重复运行 `make init` 保留完整密钥组；部分缺失会报错，避免产生不匹配的密钥。API key 可以独立更换为相同格式的新随机 key，然后重新应用配置并更新客户端，无需更换 ES256 签名密钥，也不会使用户会话失效。更换 ES256 密钥需要成组更新私钥、公钥和内部 JWT，会使旧用户会话失效。本封装不自动轮换密钥。配置依据[官方自托管密钥文档](https://supabase.com/docs/guides/self-hosting/self-hosted-auth-keys)。

`SUPABASE_PUBLISHABLE_KEY` 可公开，但它不等于“允许访问所有数据”：所有暴露表必须有适当的 grants 和 RLS。`SUPABASE_SECRET_KEY` 会绕过 RLS，绝不能放进 `VITE_*` / `NEXT_PUBLIC_*` 或浏览器包。

修改 `POSTGRES_PASSWORD` 不会自动修改已经初始化数据库的角色密码。修改加密密钥可能导致已有数据或配置无法解密。密钥轮换需要备份、数据库角色更新和各服务联动，不能通过删除 `.env` 后重跑 `make init` 实现。定期记录 API JWT 到期日并提前演练轮换。

`make restart` 与 `make up` 一样通过 Compose 应用配置变化；单纯 `docker compose restart` 不会重新加载容器环境变量。修改挂载配置文件而 Compose 未重建容器时，需明确重启相关容器。

高级参数可按需追加到 `.env`；`API_GW_HTTP_PORT` / `KONG_*` 已被本地 override 的端口规则覆盖，宿主机入口请只修改 `PUBLIC_API_PORT` / `STUDIO_PORT`。其他可选上游组合文件未打包。
