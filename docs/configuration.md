# 环境变量

`.env.example` 是完整模板，`.env` 是本地真实配置。`make init` 只补全空密钥，非空内容保留；数据库已经初始化后缺失密钥会拒绝启动，防止意外生成不匹配的新密钥。`.env` 不能当作 shell 脚本 `source`。

为使 Python 校验与 Compose 读取一致，本封装采用简单的 dotenv 子集：每行 `KEY=value`；注释单独成行；含 `$` 或 `#` 的密码用单引号包裹，如 `SMTP_PASS='abc$def#123'`。不支持变量插值、多行值、嵌套引号或反斜线转义。脚本避免 shell 导出的同名环境变量覆盖 `.env`。

## 常用变量

| 变量 | 说明 |
| --- | --- |
| `SUPABASE_PUBLIC_URL` | SDK 的 API 根地址；本地 `http://localhost:8000`；公网 `https://api.example.com` |
| `API_EXTERNAL_URL` | **此固定版本**要求 `https://api.example.com/auth/v1`，不要套用旧版不带路径的示例 |
| `SITE_URL` | 前端站点根地址，如 `https://app.example.com` |
| `ADDITIONAL_REDIRECT_URLS` | 逗号分隔的允许回调 URL，如 `https://app.example.com/auth/callback`；避免过宽通配符 |
| `PUBLIC_API_PORT` / `STUDIO_PORT` | 本机 API / Studio 端口；改 API 端口也要同步上面两个 API URL |
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

`make init` 同时从 `caddy/Caddyfile.example` 生成 `caddy/Caddyfile`。初次生成读取 `CADDY_API_HOST`（默认 `api.localhost`）、`CADDY_ADMIN_HOST`（默认 `admin.localhost`）、`CADDY_PORT`（默认 `8080`）以及 `PUBLIC_API_PORT` / `STUDIO_PORT`。旧 `.env` 缺少 Caddy 变量时使用默认值；不要求重新生成密钥。

已有 Caddyfile 不覆盖，因此之后修改域名或端口需同步编辑该文件并 reload Caddy。文件不包含密码，Studio 沿用 Envoy 网关的 Dashboard 凭证。旧 `.env` 中遗留的 Tunnel 变量不再使用，可自行删除；项目不管理外部入口。

公网校验根据 `SUPABASE_PUBLIC_URL` 是否使用非 loopback 主机名判断，不再依赖 Tunnel 开关。

## 密钥模式与轮换

本封装使用上游仍支持的 **HS256 / ANON_KEY / SERVICE_ROLE_KEY** 兼容模式，生成的两枚 API JWT 有效期五年；用户 access token 默认一小时。空的 `SUPABASE_PUBLISHABLE_KEY` / `SUPABASE_SECRET_KEY` 不用于前端。选择兼容模式是为了不引入额外密钥生成依赖，不代表已实现最新 ES256 自动轮换。

如需 ES256 与 `sb_publishable_` / `sb_secret_`，应按[官方迁移文档](https://supabase.com/docs/guides/self-hosting/self-hosted-auth-keys)整体迁移 Auth、PostgREST、Realtime、Storage、Functions、Envoy，并修改本封装的校验；不能只往 `.env` 填几枚新密钥。

`ANON_KEY` 可公开，但它不等于“允许访问所有数据”：所有暴露表必须有适当的 grants 和 RLS。`SERVICE_ROLE_KEY` 会绕过 RLS，绝不能放进 `VITE_*` / `NEXT_PUBLIC_*` 或浏览器包。

修改 `POSTGRES_PASSWORD` 不会自动修改已经初始化数据库的角色密码。修改加密密钥可能导致已有数据或配置无法解密。密钥轮换需要备份、数据库角色更新和各服务联动，不能通过删除 `.env` 后重跑 `make init` 实现。定期记录 API JWT 到期日并提前演练轮换。

`make restart` 与 `make up` 一样通过 Compose 应用配置变化；单纯 `docker compose restart` 不会重新加载容器环境变量。修改挂载配置文件而 Compose 未重建容器时，需明确重启相关容器。

模板保留部分上游高级参数供参考；`API_GW_HTTP_PORT` / `KONG_*` 已被本地 override 的端口规则覆盖，宿主机入口请只修改 `PUBLIC_API_PORT` / `STUDIO_PORT`。模板注释里的其他可选上游组合文件未打包，不能直接照抄为命令运行。
