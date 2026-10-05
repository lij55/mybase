# 验证记录

## 2026-10-05：其余组件镜像升级验收

在新密钥机制基础上，将 11 种组件/基础镜像升级至固定稳定版本，完整版本、官方来源和拉取 digest 见 [镜像版本核对](image-versions.md)。Realtime、Envoy 和 postgres-meta 保持已核对版本。使用独立临时目录、端口、网络、项目名和全新密钥验证，数据库实际版本为 PostgreSQL 17.11。

- 全部核心服务与三个 demo 镜像构建、启动及健康检查通过。
- 23 项根单元测试、18 项 demo 单元测试、13 项真实 Supabase 集成测试通过。
- 新增私有 PNG 经 Storage/imgproxy 缩放到 2×2 的真实测试，验证匿名与跨用户访问被拒绝；其余集成覆盖 Auth ES256/刷新、JWKS、REST/RPC RLS、Storage CRUD/签名 URL、Functions、Realtime、Studio 和两个连接池。
- 三个 demo 经 Traefik 3.7.13 和真实 Chromium 验证：Admin 登录、应用发现、创建用户、授权/撤权及越权拒绝；Todo 新增/完成/删除、Notes 新增/删除；两用户隔离、安全渲染、会话刷新、旧 token 撤权即时生效和退出全部通过，无浏览器未捕获异常。
- PostgreSQL 新镜像上重复执行初始化 SQL、SQL 安全检查通过；diff 校验通过。

本次不需要兼容补丁，demo 业务逻辑没有修改，只更新镜像版本。测试容器、网络、卷、专用 demo 镜像及含密钥的临时环境均已清理；已下载的正式组件镜像保留供后续部署。

## 2026-10-05：新密钥机制与三个 demo 应用

使用独立目录、项目名、端口和新生成密钥初始化全新环境，未改动已有运行实例。Realtime 升级至 `v2.140.7`，应用使用 `sb_publishable_` / `sb_secret_`，用户会话使用 ES256。

- 23 项根配置/客户端单元测试、18 项 demo 单元测试、12 项真实 Supabase 集成测试通过；Compose 配置、Node/Shell 语法和 diff 校验通过。
- 真实集成测试验证 ES256 登录与刷新、公开 JWKS 不含私钥或对称密钥、Auth、REST/RPC RLS、Storage、Functions、Realtime Broadcast/Presence/数据库事件隔离、Studio 和两个连接池。
- 三个 demo 使用各自真实镜像，经隔离的 Traefik Host 路由访问；Chromium 请求连接真实 Auth、PostgREST 和数据库，没有 API 拦截或模拟数据。
- Admin：ES256 登录、发现 Todo/Notes、创建用户且不自动授权、授予/撤销两应用访问权；普通用户访问管理接口及自行授权均被拒绝。
- Todo：浏览器新增、完成、删除；Notes：浏览器新增、删除。两应用验证内容安全渲染、两用户数据隔离、跨用户删除被拒绝、ES256 会话自动刷新和退出。Todo 跨用户修改被拒绝；Notes 不支持编辑，请求按原有契约返回 400。
- 撤权后，原有有效 ES256 access token 立即无法读取已有记录或新增记录；secret key 仅注入 Admin，未注入 Todo/Notes。
- 修正首次部署说明：先启动默认 Supabase 并创建 demo schema，再将其加入 `PGRST_DB_SCHEMAS`。提前暴露不存在的 schema 会造成 PostgREST schema cache/健康检查失败。Traefik 健康状态更新后还需等待动态路由加载，容器 healthy 不等于路由已经可达。

Realtime 容器使用原生 `/healthcheck` 检查存活；公开 WebSocket 握手由 smoke 验证，功能由集成测试验证，不生成自定义 HS256 健康检查令牌。demo 后端仅更新环境变量读取，业务逻辑、SQL 和前端代码未修改。临时容器、网络、卷与含密钥的测试目录在验收后清理。

## 2026-09-29：此前验证记录

环境：2026-09-29，Linux x86_64，Docker Compose 2.33.0，Python 3.14。上游版本见 [UPSTREAM.md](../UPSTREAM.md)。

已完成：

- `.env` 安全初始化、重复初始化不换密钥、缺失原密钥拒绝覆盖已有数据库。
- `make up && make test` 通过：12 项离线测试（8 项配置、4 项测试客户端回归）和 11 项真实实例功能测试；Compose 合并与变量校验。
- 实际拉取并启动 12 个服务，全部 healthy；重复 `make up` 成功。
- 实际监听：8000、8001、5432、6543 仅绑定 127.0.0.1。
- Auth/REST 可达；未带 key 请求被拒绝；Studio Basic Auth；公开根路径、pg、MCP、Realtime 管理路径与编码目录穿越请求被拒绝。
- Auth 登录、当前用户、错误凭据拒绝、会话刷新、退出后刷新失效、注册配置；REST 完整 CRUD、约束和 RLS 跨用户读/改/删/插入隔离、匿名拒绝；RPC 按调用者 RLS 返回结果。
- 私有 Storage 上传/下载/覆盖/列举/删除、带空格对象键、匿名及跨用户隔离、签名 URL 无认证下载。
- hello Edge Function 的用户调用、默认参数、匿名及非法 JWT 拒绝、方法/JSON 校验、CORS 预检。
- 经业务入口的 Realtime 握手、INSERT 事件投递及 RLS 隔离、WebSocket 广播、Presence track。
- Studio Basic Auth 登录后返回页面；Session / Transaction 宿主机端口执行 SQL 事务并验证回滚。
- 冷备份归档生成成功，并自动恢复原运行服务。

独立恢复演练通过：使用 `mybase-20260929-190223.tar.gz`，校验 SHA-256 后恢复到独立目录、项目名与端口；保留原密钥与 db-config，数据库 system_identifier 与源实例一致，`make up` 和完整集成测试通过。演练容器及网络已移除，临时目录和命名卷保留供检查（位置见 [恢复结果](restore-result.json)）。此次使用新建开发库，未衡量生产大数据集的恢复时长。

尚未验证：实际 Cloudflare 账户下的 Tunnel/DNS、公网 HTTPS/WSS、真实 SMTP/邮件回调/OAuth、前端浏览器完整交互、Realtime UPDATE/DELETE 语义、私有频道授权及重连、图片转换/S3 协议、MFA、压测、高可用与大数据集恢复时长。上述项需要实际账户、域名、业务负载和进一步验收，不能从容器 healthy 推断已经完成。

修复过的兼容问题：新版 REST OpenAPI 根路径需管理 key；Nginx 要保留对象名 URL 转义；官方 Realtime 网关需固定 DNS alias；hello 示例携带用户 ES256 JWT，并使用 opaque publishable key。
