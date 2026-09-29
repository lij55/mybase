# 当前实例的主要功能与简短示例

这套 Supabase 为前端提供数据库、用户认证、文件服务、实时通信和服务端函数。它是固定版本的单机自托管实例，不等同于 Supabase 托管平台的全部产品能力。

本文状态核对于 **2026-09-29**，依据实际 `.env` 的非敏感开关、Compose 配置、数据库扩展查询及 [集成验证记录](verification.md)。示例用于说明调用方式，本次文档更新不会创建业务表、启用扩展或改变注册开关。

## 1. 功能与当前状态

| 功能 | 典型用途 | 当前状态 |
| --- | --- | --- |
| PostgreSQL / SQL | 业务数据、关联查询、事务、索引、JSON | 可用；业务表需自行建立 |
| REST API / SDK CRUD | 前端查询与修改数据库 | 可用；已实测临时表和权限隔离 |
| RLS 行级权限 | 用户只访问自己的数据、租户隔离 | 可用；必须针对每张业务表设计策略 |
| 数据库函数 RPC | 聚合查询、事务内业务逻辑 | REST 服务支持；需自行创建函数与授权 |
| Auth 密码登录 / session | 用户身份、登录状态、JWT | 已实测；当前禁止新用户自助注册 |
| 邮箱确认、找回密码、Magic Link | 邮件认证和账号恢复 | 服务具备能力，但当前 SMTP 未配置，不能视为已可用 |
| OAuth、手机登录、SAML | 外部身份提供商、短信、企业 SSO | 未配置；需供应商凭证与容器配置 |
| MFA | 增强认证 | 未做当前实例端到端验收，业务上线前需单独配置与测试 |
| Storage | 私有文件、bucket、签名 URL | 本地文件后端可用，私有读写和跨用户拒绝已实测 |
| 图片转换 / S3 兼容接口 | 图片处理、兼容存储工具 | 服务配置具备入口，未做专项端到端验收 |
| Realtime | 数据库变化、广播、在线状态 | 服务和 WebSocket 握手已验证；业务事件投递需另行验收 |
| Edge Functions | 受控服务端逻辑、对接外部 API | 已实测 `hello` 的用户鉴权调用 |
| GraphQL | 按需选择字段及关联数据 | 路由已配置；当前 `pg_graphql` 尚未启用，需先配置扩展 |
| 向量检索、定时 SQL | 语义相似度搜索、周期数据库任务 | `vector`、`pg_cron` 可用但未启用 |
| Studio | 表、SQL、用户、文件管理 | 可用；本机 8001，经 Basic Auth 保护 |
| SQL 连接池 | 后端、迁移、BI 报表连接 | Session / Transaction 入口可用 |
| 公网 HTTPS / WSS | 前端从外网访问 | Tunnel 配置已准备；当前开关关闭，需实际域名和 token |

## 2. 示例共用的准备工作

在自己的前端项目中安装 `@supabase/supabase-js`，再创建客户端。以下采用 Vite 的环境变量写法：

```ts
import { createClient } from '@supabase/supabase-js'

const supabase = createClient(
  import.meta.env.VITE_SUPABASE_URL,       // 本地 http://localhost:8000
  import.meta.env.VITE_SUPABASE_ANON_KEY,  // 复制当前实例 ANON_KEY
)
```

这些变量来自前端项目的 `.env.local`。不要把服务端 `.env` 整份复制到前端；`SERVICE_ROLE_KEY`、`JWT_SECRET` 和数据库密码绝不能放入浏览器。

本文的 `todos` 示例需要先以管理员身份运行 [001_todos.sql](../examples/001_todos.sql)，并以真实业务用户登录。文件示例还需执行 [002_storage.sql](../examples/002_storage.sql)。这些 SQL 是一次性建表示例，不要在已有同名对象的数据库中重复执行。完整接入步骤见 [使用文档](usage.md)。

## 3. 数据库与自动 REST API

PostgreSQL 支持表关系、约束、事务、索引与 SQL 查询。PostgREST 根据数据库对象提供 API，SDK 将请求发给 `/rest/v1/`，不需要为每张表手写一组 CRUD 路由。

例如，新增并读取当前用户自己的待办事项：

```ts
const added = await supabase.from('todos')
  .insert({ title: '完成第一条待办' })
  .select('id,title,done')
  .single()
if (added.error) throw added.error

const listed = await supabase.from('todos')
  .select('id,title,done')
  .eq('done', false)
  .order('created_at', { ascending: false })
  .range(0, 19)
if (listed.error) throw listed.error
console.log(listed.data)
```

当前默认最大返回 1000 行，实际业务应分页。索引、查询性能、迁移和事务设计仍需要开发者负责。

## 4. RLS：让数据库执行用户权限

RLS 根据请求中的用户 JWT 判断哪些行可以访问。示例表已经使用如下规则的等价配置：

```sql
-- 原理片段，不需要在已执行的 001_todos.sql 上再执行。
create policy own_rows on public.todos
for select to authenticated
using ((select auth.uid()) = user_id);
```

`authenticated` 是数据库角色，`auth.uid()` 是当前业务用户 UUID。前端即使移除用户过滤条件，也不应读到其他人的记录；插入、更新、删除同样需要各自的 grants 和策略。

现有集成测试已用两个临时用户验证隔离。开发新表时应继续验证“允许”和“拒绝”两类情况。使用管理 key、管理员 SQL 或设计不当的高权限函数可能绕过这些限制。

## 5. RPC：通过 API 调用数据库函数

适合把聚合查询或需要在一次数据库事务中完成的逻辑放在数据库内。以下函数依赖 `todos` 示例表，使用调用者权限，因此查询仍受该表 RLS 约束。

管理员可在开发库执行：

```sql
begin;
create or replace function public.my_open_todo_count()
returns bigint
language sql stable security invoker
set search_path = ''
as $$
  select count(*) from public.todos where done = false;
$$;
revoke execute on function public.my_open_todo_count() from public, anon;
grant execute on function public.my_open_todo_count() to authenticated;
commit;
```

前端登录后调用：

```ts
const { data, error } = await supabase.rpc('my_open_todo_count')
if (error) throw error
console.log('我的未完成数量：', data)
```

这是可选示例函数，当前没有自动安装。复杂逻辑应评审函数执行权限，不能为解决权限报错就全部改成 `security definer`。调用形式见[官方 RPC 文档](https://supabase.com/docs/reference/javascript/rpc)。

## 6. Auth：登录与会话

Auth 管理业务用户、密码验证及用户 JWT。Studio Basic Auth 账号不会自动成为 Auth 用户。

```ts
const signedIn = await supabase.auth.signInWithPassword({
  email: 'your-user@example.com',
  password: '该业务用户的密码',
})
if (signedIn.error) throw signedIn.error

const current = await supabase.auth.getUser()
if (current.error) throw current.error
console.log(current.data.user?.id)

// 用户主动退出时调用：
// await supabase.auth.signOut()
```

当前 `DISABLE_SIGNUP=true`，不能直接通过前端注册新账号。测试账号需先由管理员创建；对外开放注册前应配置真实 SMTP、邮箱确认、业务回调和注册策略。账号创建不应通过在前端使用 service role 实现。

SDK 登录后将用户 access token 带到请求中，使 REST、Storage 等服务使用对应用户权限。邮件登录、密码恢复、OAuth、短信、MFA 等流程要按业务逐项配置与验收，不能仅因为 Auth 容器健康就认为全部认证方式可用。

## 7. Storage：私有文件与临时下载地址

对象存储 API 将文件内容与元数据管理分开。当前文件实际写到 `volumes/storage`，不是自动上传云存储。

执行私有 bucket 示例后，可把文件放到 `用户UUID/对象名` 下：

```ts
// file 为页面文件选择框获得的 File 对象。
const { data: { user }, error: userError } = await supabase.auth.getUser()
if (userError) throw userError
if (!user) throw new Error('请先登录')

const objectPath = `${user.id}/${crypto.randomUUID()}`
const uploaded = await supabase.storage.from('user-files').upload(objectPath, file)
if (uploaded.error) throw uploaded.error

const signed = await supabase.storage.from('user-files')
  .createSignedUrl(objectPath, 60)
if (signed.error) throw signed.error
console.log(signed.data.signedUrl) // 60 秒内可用于下载，持有链接者可访问
```

使用 ASCII 对象键，将中文原文件名放在业务元数据里。私有 bucket 的访问策略需要正确设置；不要把 bucket 设为公开来规避 403。公开 bucket 的文件读取不提供与私有 bucket 相同的隔离保障。

当前请求大小同时受到 Storage、Nginx 与公网代理的限制。备份不仅要包含 PostgreSQL，还必须包含文件目录。S3 兼容接口是访问协议，和“把 Storage 后端切换到 AWS S3”等配置不是同一件事。

## 8. Realtime：订阅变化、消息广播与在线状态

Postgres Changes 可以在业务表变化时通知前端。`001_todos.sql` 已把示例表加入 `supabase_realtime` publication；用户的读权限仍需正确配置。

```ts
const channel = supabase.channel('my-todo-updates')
  .on('postgres_changes', {
    event: 'INSERT', schema: 'public', table: 'todos',
  }, payload => {
    console.log('收到新增记录：', payload.new)
    // 可在此重新查询列表。
  })
  .subscribe(status => console.log('订阅状态：', status))

// 页面卸载或退出登录时清理：
// await supabase.removeChannel(channel)
```

业务上线前需实际执行插入并验证事件到达。当前验证记录只证明 WebSocket 握手成功，不证明所有事件、删除语义和重连行为已验证。

Broadcast 用于协作事件或房间消息，Presence 用于在线成员/状态同步。这两类能力由 Realtime 提供，私有房间要另外设计 channel 授权；业务表的 RLS 不会自动变成所有房间的成员规则。参见[Broadcast](https://supabase.com/docs/guides/realtime/broadcast) 与 [Presence](https://supabase.com/docs/guides/realtime/presence)。

本实例公开入口拒绝 `/realtime/v1/api` 前缀，所以不要依赖“未订阅时通过 HTTP 发送广播”的 SDK 回退路径；广播应等待 channel 成功订阅后通过 WebSocket 发送。关键业务状态持久化到数据库，并在重连后重新查询；不要把实时通知当作可靠消息队列。

## 9. Edge Functions：前端之外的服务端逻辑

适合调用外部服务、处理需要秘密凭证的操作、封装业务校验。运行环境是本机 Deno 容器，不会自动分布到全球节点。

当前已经有要求真实用户登录的 `hello`：

```ts
const { data, error } = await supabase.functions.invoke('hello', {
  body: { name: '开发者' },
})
if (error) throw error
console.log(data.message) // Hello 开发者!
```

源码在 [hello/index.ts](../volumes/functions/hello/index.ts)。主入口检查 JWT 签名，hello 再通过 Auth 验证真实用户；公开 anon JWT 本身不能证明用户已经登录。

新增函数时在 `volumes/functions/函数名/index.ts` 编写代码并重启 `functions`。对外 API 密钥只能放在服务端配置中，且需明确加入容器环境；第三方 webhook 还需要独立的供应商签名验证方案。

## 10. GraphQL：当前需先启用扩展

网关已经配置 `/graphql/v1` 路由，但实际数据库查询结果显示 `pg_graphql` 的 `installed_version` 为空。不能据此路由就宣称业务 GraphQL 已可用。

如需使用，可先在开发环境按[官方扩展说明](https://supabase.com/docs/guides/database/extensions/pg_graphql)启用 `pg_graphql`，检查 schema/表权限，并在接口中验证实际生成的字段名。下面仅演示 HTTP 调用结构：

```ts
// 前置条件：已启用扩展，todos 表存在且当前用户有访问权限。
const { data: { session } } = await supabase.auth.getSession()
if (!session) throw new Error('请先登录')
const response = await fetch(`${import.meta.env.VITE_SUPABASE_URL}/graphql/v1`, {
  method: 'POST',
  headers: {
    'Content-Type': 'application/json',
    apikey: import.meta.env.VITE_SUPABASE_ANON_KEY,
    Authorization: `Bearer ${session.access_token}`,
  },
  body: JSON.stringify({
    query: '{ todosCollection(first: 5) { edges { node { id title } } } }',
  }),
})
if (!response.ok) throw new Error(`HTTP ${response.status}`)
const result = await response.json()
if (result.errors) throw new Error(JSON.stringify(result.errors))
console.log(result.data)
```

`todosCollection` 等名称取决于实际 schema 与命名配置；GraphQL 也使用数据库权限模型，不能绕过 RLS。入口不要加末尾斜线。参见[官方 GraphQL 概览](https://supabase.com/docs/guides/graphql)。

## 11. 数据库扩展：可扩展，不代表已经启用

当前只读查询结果如下，后续开启扩展后状态会变化：

| 扩展 | 当前镜像可用版本 | 当前数据库状态 | 用途 |
| --- | --- | --- | --- |
| `pg_net` | 0.20.3 | 已启用 | 数据库侧异步 HTTP 能力，具体调用/出站目标需单独设计 |
| `pg_graphql` | 1.5.11 | 未启用 | 数据库驱动的 GraphQL |
| `vector` | 0.8.2 | 未启用 | 向量存储、相似度检索 |
| `pg_cron` | 1.6.4 | 未启用 | 周期 SQL 任务 |
| `pg_trgm` | 1.6 | 未启用 | 字符串相似度与相关索引能力 |

可以在 `make psql` 中只读查看：

```sql
select name, default_version, installed_version
from pg_available_extensions
where name in ('pg_net', 'pg_graphql', 'vector', 'pg_cron', 'pg_trgm')
order by name;
```

例如做语义搜索时，可以评估启用 `vector`、设计向量列和索引，再通过 RPC 查询；当前实例不会自动替你生成 embeddings 或配置模型服务。参见[官方 pgvector 说明](https://supabase.com/docs/guides/database/extensions/pgvector)。

## 12. 管理、报表连接与能力边界

Studio 提供 SQL 和资源管理，地址为 `http://localhost:8001`。BI/后端可通过 Supavisor 连接 PostgreSQL；远程管理推荐 SSH 转发，报表使用专用只读账号和经过授权的 reporting 视图，详见 [SQL 与报表使用](usage.md)。

本仓库另提供 `make backup` 一致性冷备份、恢复操作手册、状态和集成检查。这些是本地运维工具，当前没有自动备份调度、PITR、高可用、全局多区域、托管分支环境、完整日志聚合或完整多项目控制台。

公网接入仍需填写域名和 Tunnel token；邮件仍需 SMTP。选择某项功能时，先检查上表的当前状态、完成相应配置，再做与实际业务相关的验收。
