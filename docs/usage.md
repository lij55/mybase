# 使用方式

## Studio 与第一个业务表

访问 `http://localhost:8001`，使用 `.env` 的 Dashboard 用户名密码进入。Studio 是项目级管理工具，管理员可以查看和修改业务数据；业务用户使用前端的 Supabase Auth 登录，不使用 Studio 账号。

在 SQL Editor 中执行 [001_todos.sql](../examples/001_todos.sql)，或 `make psql` 后用 `\i /path/to/file`（注意 psql 在容器内，看不到宿主机任意路径）。从宿主机直接输入文件可以用：

```bash
docker compose -f docker-compose.yml -f compose.override.yml exec -T db \
  psql -v ON_ERROR_STOP=1 -U postgres -d postgres < examples/001_todos.sql
```

示例不是自动迁移，不要重复运行到已有同名表的库。真实项目应在版本库中管理编号 SQL 迁移，先在测试库执行，再部署到生产；不要把所有变更留在 Studio 的手动操作里。

脚本创建 `todos`，启用 RLS，仅允许登录用户访问自己的数据。`user_id` 由数据库从 JWT 读取。必须用两个不同用户验证跨用户不可读写；不要把前端的 `.eq('user_id', ...)` 过滤当作权限控制。详细机制见[官方 RLS 文档](https://supabase.com/docs/guides/database/postgres/row-level-security)。

## 前端 SDK

在自己的 Vite 项目中：

```bash
npm install @supabase/supabase-js
```

前端项目的 `.env.local`（不是本仓库服务端 `.env`）：

```dotenv
VITE_SUPABASE_URL=http://localhost:8000
VITE_SUPABASE_ANON_KEY=复制本仓库.env中的ANON_KEY
```

公网时 URL 改成 `https://api.example.com`。可参考 [client.ts](../examples/client.ts) 的登录、CRUD、上传和订阅函数。Next.js 对应公开变量可使用 `NEXT_PUBLIC_` 前缀；SSR 登录需使用相应服务端 Cookie 方案，不能把单个用户 session 缓存在共享全局客户端里。

只有 `ANON_KEY` 可以出现在浏览器。用户登录后 SDK 自动带上用户 access token，数据库据此应用 RLS。

## 注册与登录

默认 `DISABLE_SIGNUP=true`。本地体验可以在 `.env` 设置 `DISABLE_SIGNUP=false`、`ENABLE_EMAIL_AUTOCONFIRM=true`，然后 `make up`；该模式不验证邮箱所有权，只用于隔离开发。

公网必须 `ENABLE_EMAIL_AUTOCONFIRM=false` 并配置真实 SMTP。注册示例：

```ts
const { data, error } = await supabase.auth.signUp({
  email, password,
  options: { emailRedirectTo: 'https://app.example.com/auth/callback' },
})
if (error) throw error
// 邮件确认开启时，初次注册不一定返回 session；提示用户检查邮箱。
```

确认邮件 URL、Auth 站点 URL、前端回调页面、白名单四者必须匹配。修改域名后，重新生成旧邮件链接。根据业务需要再启用 OAuth、MFA 和针对登录/注册的速率限制。

## Storage、Realtime、Functions

执行 [002_storage.sql](../examples/002_storage.sql) 建立私有 bucket；路径格式为 `用户UUID/文件名`，RLS 检查目录归属。私有文件使用 SDK download 或短期 signed URL，不要为了消除 403 改成 public bucket。实际文件在 `volumes/storage`，仅备份数据库不够。

Realtime 示例表已加入 `supabase_realtime` publication。SDK 使用 WebSocket，Cloudflare 需允许握手；前端应处理断线重连并在重新连接时查询最新状态。默认 Postgres Changes 不等于可靠消息队列，关键业务不要依赖只收到一次事件。删除事件的过滤/旧行可见性有特殊约束，需要完整验证或采用软删除。

函数代码在 `volumes/functions/`，本仓库提供兼容当前密钥模式的 `hello`。例如 `supabase.functions.invoke('hello', { body: { name: 'World' } })`。修改后重启函数容器：

```bash
docker compose -f docker-compose.yml -f compose.override.yml restart functions
```

`FUNCTIONS_VERIFY_JWT=true` 检查有效 JWT，但公开 anon JWT 也能通过签名验证。需要登录的函数必须再调用 Auth 校验用户，业务操作优先使用用户 JWT 客户端以保留 RLS，不要无条件使用 service role。第三方 webhook 的签名验证与 JWT 策略需另行设计。

## SQL 客户端与报表

如果“报表”指 BI（例如 Metabase / Grafana），不需要把数据库公开到互联网。BI 与 Supabase 同私网时走私网连接；管理员本地客户端用 SSH 转发：

```bash
ssh -N -L 15432:127.0.0.1:5432 your-user@your-server
```

客户端连接 `127.0.0.1:15432`，数据库 `postgres`。Supavisor 用户名格式为 `postgres.mybase`（后缀取 `POOLER_TENANT_ID`），密码为 `POSTGRES_PASSWORD`。该管理员账号仅用于初始化和管理，不要交给报表用户。

为 BI 创建专用 login 角色，只授予独立 reporting schema 的必要视图 SELECT 权限，设置 statement timeout、连接数限制；不要给 superuser、service_role 或全部 public 表权限。跨租户报表必须明确数据授权范围。大量分析建议用只读副本或定时导出的分析库，避免与线上事务抢资源。本仓库未自动部署 BI 软件。

Session 端口适合迁移和需要会话状态的客户端；Transaction 端口适合短事务服务端连接，使用前核对 ORM 的 prepared statements 和会话特性。HTTP Tunnel 不提供普通 PostgreSQL DSN。

Storage 对象键有字符限制，建议使用 `UUID` 等 ASCII 名称，把中文原文件名保存在业务表的展示字段中。本项目实测空格名称可以正确传递，但中文对象键被当前 Storage 版本拒绝。参见[官方文件名限制](https://supabase.com/docs/guides/storage/uploads/file-limits)。

## 可选的集成验证

运行 `make up && make test` 验证配置和当前已启用的关键功能；`make integration` 可单独运行实例测试，`make unit` 只运行离线测试。集成测试按用例创建临时用户、随机名称的业务表、RPC 与私有 bucket，覆盖会话、CRUD/RLS、签名下载、Functions、Realtime 实际事件、广播/Presence、Studio 和连接池，最后逐项清理。此命令会写入测试数据，只在开发/演练环境执行；进程被强制中断时可能留下 `test_` / `test-` 前缀资源，需要核对并清理。详见[测试说明](testing.md)。
