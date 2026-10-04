# 常见问题与部署取舍

## 故障定位

先运行 `make ps`，再看对应服务 `make logs SERVICE=...`。日志或 `docker compose config` 可能包含凭证，不要原样上传到公开 issue。

| 现象 | 常见原因 | 处理 |
| --- | --- | --- |
| `!override` / `!reset` 解析失败 | Compose 太旧 | 升级到 2.24.4+，使用 `docker compose`，不是旧 Python `docker-compose` |
| Docker socket permission denied | Docker 未启动或用户无访问权限 | 检查 daemon 和用户组；重新登录生效。不要把 socket chmod 为 666 |
| 镜像拉取超时 | DNS、代理、仓库不可达、限流 | 为 Docker daemon 配置合规代理或可信镜像源；shell 代理不一定影响 Docker daemon；不要改成来历不明的镜像 |
| Functions 健康失败 | Deno/JSR 依赖无法下载 | 检查 functions 日志及容器出站 DNS/HTTPS；使用可信依赖缓存 |
| `address already in use` | 默认端口冲突 | 改 `.env` 的 `PUBLIC_API_PORT` / `STUDIO_PORT` / `DB_*_PORT`；API URL 同步调整 |
| 数据库持续重启 | 磁盘满、目录权限、版本不兼容、内存不足 | 检查 db 日志、磁盘和 OOM；保留原数据，不要删目录“重试” |
| 修改数据库密码后登录失败 | `.env` 与数据库角色密码不一致 | 恢复原变量，按计划更新所有相关角色及连接参数 |
| `401` / `Invalid JWT` | anon/service JWT 和 JWT_SECRET 不配套、token 过期、系统时钟偏差 | 检查成套配置和 NTP；`make check` 验签；重新登录，不要关闭鉴权 |
| 查询空数组 / `42501` / 上传 403 | 没登录、grants/RLS/bucket 策略不匹配 | 用实际用户 JWT 检查角色、owner 和策略；不要把 service key 放前端解决 |
| API 根路径 404 | 预期路径隔离 | SDK 用 API 根 URL，但测试服务用 `/auth/v1/health`；Studio 在本机 8001 |
| CORS / 浏览器返回 HTML | Cloudflare Access / Challenge / WAF 拦截 API | 检查 OPTIONS 与具体响应；业务 API 不使用交互式登录门禁，调整规则后重测 |
| 邮件发送失败 / 回调到 localhost | SMTP 无效、变量或跳转白名单错误 | 校验发信域名、三个 URL 和 allow list，`make up` 应用，再重新发送邮件 |
| 大文件 413 | Storage、Nginx 或 Cloudflare 单请求上限 | 三层都检查；本项目默认 50 MiB；优先分块/可恢复上传或适合的对象存储方案 |
| 长请求 524 / 超时 | 同步任务超过边缘或源站时间限制 | 改异步作业 + 查询状态，不假设 Tunnel 没有代理超时 |
| Realtime 握手失败/常断开 | WebSockets/WAF、空闲超时、代理重启 | 检查 101，保留心跳与退避重连，恢复后重新查询状态 |
| 改了配置仍无变化 | 只做了 restart 或修改挂载配置未重载 | `.env` 改动用 `make up`；Nginx 配置改动明确 restart public-api |
| Studio Logs Explorer 空白 | 默认未启用上游可选日志栈 | 用 Docker 日志；如需聚合日志再独立启用并评估权限 |
| 同时启动第二份实例冲突 | 共用了目录、宿主机端口或项目名 | 使用独立目录、不同项目名和全部宿主机端口；不要共享数据目录 |

Cloudflare 的上传限制由套餐与配置决定，参见[413 官方说明](https://developers.cloudflare.com/support/troubleshooting/http-status-codes/4xx-client-error/error-413/)。大文件可考虑 Supabase 的[可恢复上传](https://supabase.com/docs/guides/storage/uploads/resumable-uploads)，还要验证自托管反向代理与实际存储后端支持情况。

Cloudflare 支持 WebSocket，但边缘发布或连接空闲可导致断开，参见[官方 WebSocket 说明](https://developers.cloudflare.com/network/websockets/)。它不是持久消息投递保证。

## Tunnel 的适用边界

优点是源站无需公网监听业务端口，证书与域名入口统一，适合单机自托管和没有固定入站 IP 的环境。代价是新增第三方网络依赖、代理限制和一跳链路；无健康 connector 时，全部 API 都不可用。

多个 cloudflared 副本可以降低连接器进程故障影响，但同一机器、同一数据库仍然是单点。把第二个 connector 放在另一台主机，也不自动获得数据库高可用。主用户在中国大陆时，必须从真实运营商网络实测延迟、丢包、WSS 和大文件，不应仅按服务器到 Cloudflare 的速度判断用户体验。

## 替代方案

以下是针对这个项目需求的选择建议，不是价格或 SLA 承诺；具体限制以供应商当前套餐为准。

| 方案 | 适用场景 | 主要取舍 |
| --- | --- | --- |
| **托管 Supabase** | 想把时间主要花在前端业务、生产可靠性要求较高 | 本任务的优先替代建议；减少数据库/备份/升级运维，但需评估区域、费用、配额与供应商依赖 |
| **本仓库 + Cloudflare Tunnel** | 要控制数据和主机、可承担单机维护 | 成本可控、接口接近 Supabase；自己负责恢复、更新、邮件、容量和安全 |
| **Supabase + Caddy/Nginx HTTPS + 公网负载均衡** | 已有成熟云网络与反向代理运维，或不希望依赖 Tunnel | 链路更直接，但需管理入站、证书、源站防护和负载均衡；仍保留 API/Studio 隔离 |
| **Supabase CLI 本地环境** | 仅做本机开发和迁移验证 | 开发体验更直接；不把 CLI 开发栈当作长期生产部署 |
| **托管 PostgreSQL + 自己的后端** | 主要需要 SQL 数据而非完整 BaaS | 更容易按后端业务边界授权，但 Auth/文件/实时功能要另选或实现；普通托管 PG 不是 Supabase 数据库的直接替身 |
| **Appwrite** | 接受不同 SDK/数据模型的 BaaS 项目 | 值得比较，但不是 Supabase API 的即插即用替代；迁移需改业务代码 |
| **PocketBase** | 小型原型、单机简单应用 | 部署轻量；SQLite 架构与 Supabase 不同，且官方提示生产关键业务需谨慎评估版本兼容与成熟度 |

如果当前目标是快速上线一个前端业务，我建议先比较托管 Supabase 的总成本与“云主机 + 备份 + 邮件 + 运维时间”。如果明确要自托管，这套单机配置可以作为起点，先完成异地恢复演练再承接真实用户。

来源：[Supabase 自托管边界](https://supabase.com/docs/guides/self-hosting)、[官方反向代理方案](https://supabase.com/docs/guides/self-hosting/self-hosted-proxy-https)、[CLI 本地开发](https://supabase.com/docs/guides/local-development)、[Appwrite 自托管](https://appwrite.io/docs/advanced/self-hosting)、[PocketBase 文档](https://pocketbase.io/docs/)。
