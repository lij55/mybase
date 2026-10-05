# 多 App 共用 Supabase：独立 schema、权限与迁移

## 结论与适用范围

当前 Mybase 是一套自托管 Supabase，连接一个 PostgreSQL 数据库。自托管 Studio 不支持托管平台式的多组织、多 project，见[官方自托管说明](https://supabase.com/docs/guides/self-hosting)。Docker Compose 的项目名称只用于容器编排，不会创建多个 Supabase project。

接受共用登录体系时，推荐每个 App 使用独立 schema、显式数据库权限、RLS 和独立迁移。schema 负责组织表和避免名称冲突；权限与 RLS 负责控制访问。该方案提供逻辑隔离，共用服务、资源和管理权限，不提供完整实例隔离。

例如 `app_a.orders` 与 `app_b.orders` 是两张独立的表，可以有不同字段、索引和策略。登录用户都来自同一个 `auth.users`，但是否能访问某个 App 由业务授权决定。

## 哪些复用，哪些独立

| 内容 | 是否复用 | 实际边界与维护方式 |
| --- | --- | --- |
| Supabase project、Studio、API 网关与 URL | 复用 | 同一个项目和管理入口；Studio 管理员可管理所有 App，不能按 schema 自动隔离管理员。 |
| PostgreSQL 实例、数据库、连接池 | 复用 | 都在同一个数据库中；连接数、CPU、内存、磁盘和故障影响范围共用。 |
| Auth 用户与凭据 | 复用 | 共用 `auth.users`、密码、OAuth 身份和 JWT 信任体系；删除账号会影响使用该账号的所有 App。 |
| Auth 设置 | 复用 | 注册开关、SMTP、邮件模板、OAuth 提供商、Site URL 与回调白名单是项目级设置。 |
| 浏览器登录状态 | 各 App 自行维护 | 共用账号不等于不同域名自动登录；浏览器存储和 Cookie 有域名边界。跨域免登录需要另行设计。 |
| API 密钥与内置数据库角色 | 复用 | 共用 `SUPABASE_PUBLISHABLE_KEY`、`SUPABASE_SECRET_KEY`、`anon`、`authenticated`、`service_role`；不是每 App 独立凭据。 |
| App 成员资格与业务权限 | 独立判断 | 为同一个用户分别授予 `app_a`、`app_b` 资格；登录成功不会自动获得所有 App 权限。 |
| 业务表、索引、序列、函数、视图 | 按 schema 独立 | 各 App 使用自己的 schema；跨 schema 引用必须显式设计，默认避免互相依赖。 |
| 业务 profile | 按 App 独立 | 可分别建立 `app_a.profiles`、`app_b.profiles`，引用同一个 `auth.users.id`，各自保存业务字段。 |
| 迁移与生成的客户端类型 | 按 App 独立维护 | 各 App 分别管理版本和 SQL；共用基础授权结构另设迁移。 |
| Storage 服务与物理存储 | 复用 | 可按 App 分 bucket，例如 `app-a-files`、`app-b-files`，再配置独立对象策略；业务 schema 的 RLS 不会保护 Storage。 |
| Realtime 服务 | 复用 | 订阅时指定业务 schema/table；每张表单独启用 Postgres Changes，Broadcast/Presence 需独立频道与授权设计。 |
| Edge Functions 运行时 | 复用 | 使用不同函数名/目录，例如 `app-a-orders`；函数需自行校验用户和 App 权限，不能依赖目录名隔离。 |
| 备份、恢复、升级与停机 | 复用 | 本仓库冷备份与恢复覆盖整个实例；各 App 无法独立升级数据库或通过整机备份独立回滚。 |

## 隔离必须由数据库执行

客户端设置 `db.schema = 'app_a'` 只是查询默认值。用户可以修改请求并访问 `app_b`，因此不能靠前端配置、表名前缀、URL 或传入的 `app_id` 阻止跨 App 访问。

本示例同时检查两件事：用户具有当前 App 的成员资格，且只能操作自己拥有的行。App 资格由管理员写入数据库，前端不能自行授予；用户可编辑的 `user_metadata` 不适合作为授权依据。

所有登录用户都使用 `authenticated` 角色；表上的 `GRANT` 允许该角色执行哪些操作，RLS 再决定能操作哪些行。公开 API 中的每张业务表都应配置两层控制，见[官方 RLS 文档](https://supabase.com/docs/guides/database/postgres/row-level-security)。

用户如果同时被授予两个 App 的资格，其 JWT 可以访问两个 App 中被策略允许的数据。共用 Auth 的授权针对用户，不能证明请求来自哪一个前端 App；如果需要限制某个 App 后端只能访问自己的 schema，应另外使用受限数据库角色。`postgres`、管理员和具备绕过 RLS 权限的 `service_role` 不属于此隔离边界，不能把共用管理员凭据当成 App 专属凭据。

## 正式应用约定与自动发现

授权后台、Todo 和 Quick Notes 已实现在 [demoapp](../demoapp/README.md)。后台每次点击“发现应用”时查询 PostgreSQL 的 `pg_namespace`，自动识别符合约定的业务 schema，不使用手填应用注册表。

后续正式应用必须遵守以下约定：

| 项目 | 约定 |
| --- | --- |
| 唯一应用标识 | 一个业务 App 对应一个 schema，标识就是 schema 名称。 |
| schema 命名 | `app_` 前缀，后接小写字母起头的小写字母、数字、下划线；全名不超过 63 字节，例如 `app_todo`、`app_notes`、`app_crm`。 |
| 保留名称 | `app_access` 是共用内部授权 schema，后台发现时明确排除；不得作为业务 App 或加入 API 暴露列表。 |
| 展示名称 | 用 `COMMENT ON SCHEMA app_crm IS '客户管理'` 设置名称；没有注释时显示 schema 名。 |
| 授权依据 | `app_access.memberships` 的 `(app_id, user_id)`，`app_id` 必须使用实际 schema 名，用户来自共用 `auth.users.id`。 |
| 新 App 的默认权限 | 创建 schema 不自动授权任何用户；管理员显式勾选授予，用户不能自行添加成员资格。 |
| 业务表安全 | 每张表显式 GRANT、启用 RLS，同时检查 App 成员资格与行归属/团队权限。 |
| SQL 文件 | 各 App 使用 `sql/001_init.sql`；后续编号递增为 `sql/002_<用途>.sql`，按 App 独立跟踪版本，由维护者统一执行。 |
| 跨 App 引用 | 默认避免跨业务 schema 依赖；共用对象和跨 App 数据访问必须显式设计。 |

新 schema 被发现不代表其安全策略或 Data API 已配置完成。需要 Data API 时仍须手动更新根 `.env` 的 `PGRST_DB_SCHEMAS` 并执行 `make up`；新增容器和 Traefik 路由也需单独配置。自动发现只负责后台的应用列表，不会自动开放接口、授予权限或部署应用。

后台会显示已被删除 schema 的残留授权并允许撤销。移除 App 时应清理对应成员记录；如果日后重建同名 schema 而保留旧记录，旧授权会重新生效。重命名 schema 属于权限标识变更，应同时更新策略、环境变量、客户端和成员记录。

## 用户创建与授权管理

一个账号可以访问多个 App，但只能操作业务策略允许的数据。当前采用维护者创建账号的方式，不发送邀请或邮件确认：

1. 首个管理员通过 `demoapp/bootstrap_admin.py` 或现有 Auth 管理入口创建，随后把其 UUID 填入后台的 `ADMIN_USER_IDS`。
2. 管理员登录授权后台，创建用户邮箱与初始密码；账号进入共用 Auth，但不会自动获得 App 资格。
3. 选择该用户，勾选 Todo、Notes 或自动发现的正式 App。勾选写入一条成员记录，取消勾选删除该记录。
4. 用户用同一个账号登录各 App；不同域名各自维护浏览器会话，不会自动跨域免登录。

新增 10 个用户就是创建 10 个 Auth 账号，再分别分配所需 App，每个“用户 + App”对应一条授权记录；不需要为各 App 重复创建用户。新增第 3、第 4 个 App 只要提供 schema、建表/RLS 迁移，执行后在后台刷新并分配资格；成员表不再使用固定 A/B 枚举 CHECK，无需为每个 App 修改约束。

后台管理员资格与业务成员资格分离：`ADMIN_USER_IDS` 是部署白名单，不是通过给用户勾选某个业务 App 获得。后台需要 service role key 创建/列出 Auth 用户，同时使用单独的受限数据库登录管理成员记录；这些凭据只注入后台容器。Todo 和 Notes 只使用公开 key 与用户 JWT，没有数据库密码或管理密钥。

撤销 App 资格保留账号和历史业务数据，后续请求由数据库检查拒绝访问；不是删除共用 Auth 账号。当前不实现删除 Auth 用户。将来集成 OAuth/OIDC/Keycloak 时应保持 Supabase 可识别的用户 UUID 与会话，授权继续按 UUID 判断，不按邮箱或外部可编辑 metadata 判断。当前密码登录入口可以替换，但直接传入外部 Keycloak JWT 不会自动成为 Supabase 会话。

## 建表、授权与 RLS 示例

可执行的完整 SQL 是代码的唯一维护入口：先执行 [admin/sql/001_init.sql](../demoapp/admin/sql/001_init.sql)，再分别执行 [todo/sql/001_init.sql](../demoapp/todo/sql/001_init.sql) 和 [notes/sql/001_init.sql](../demoapp/notes/sql/001_init.sql)。[demoapp README](../demoapp/README.md)提供执行命令、配置和首次管理员创建步骤。容器不会自动运行 SQL。

共享迁移建立内部成员表、`app_access.can_access_app(text)` 检查函数和受限后台能力角色。该函数使用 `SECURITY INVOKER`，以调用者权限检查成员表；普通用户只能读取自己的成员记录，没有写权限。

新增正式应用时，下面是可保存为 `sql/001_init.sql` 的最小示例；执行前应先安装共享授权迁移，业务初始化不要重复执行：

```sql
begin;
create schema app_crm;
comment on schema app_crm is '客户管理';
revoke all on schema app_crm from public, anon;
revoke create on schema app_crm from authenticated;
grant usage on schema app_crm to authenticated;

create table app_crm.contacts (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null default auth.uid() references auth.users(id),
  name text not null check (char_length(btrim(name)) between 1 and 200),
  created_at timestamptz not null default now()
);
create index contacts_user_id_idx on app_crm.contacts(user_id);
revoke all on app_crm.contacts from public, anon, authenticated;
grant select, insert, update, delete on app_crm.contacts to authenticated;
alter table app_crm.contacts enable row level security;
create policy contacts_member_owner on app_crm.contacts for all to authenticated
  using (user_id = (select auth.uid()) and app_access.can_access_app('app_crm'))
  with check (user_id = (select auth.uid()) and app_access.can_access_app('app_crm'));
notify pgrst, 'reload schema';
commit;
```

`USING` 限制现有行的可见和可操作范围；`WITH CHECK` 限制插入或更新后的行，防止伪造归属。默认 `user_id` 不代替策略。示例适用于个人数据；团队数据应使用团队成员/角色规则，仍须检查 App 资格。UUID 主键不需要额外序列权限，序列主键需按用途授权。

新增表必须在同一迁移中显式配置权限与策略，不要对整个 schema 的未来对象默认 `GRANT ALL`。函数和视图也需要独立审查，特别是 `SECURITY DEFINER` 函数与可能绕过调用者 RLS 的视图。机制见[官方 RLS 文档](https://supabase.com/docs/guides/database/postgres/row-level-security)。

## 暴露 schema 与客户端使用

例如在根 `.env` 保留已有 schema 并追加新应用：

```dotenv
PGRST_DB_SCHEMAS=public,graphql_public,app_todo,app_notes,app_crm
```

执行 `make up` 应用环境变量变化；只运行 `docker compose restart` 不会更新环境变量。不要暴露 `app_access`、`auth`、`storage` 等内部 schema。

使用 SDK 的正式 App 可以指定默认 schema：

```javascript
const supabase = createClient(SUPABASE_URL, SUPABASE_PUBLISHABLE_KEY, {
  db: { schema: 'app_crm' },
})
// 登录后：成员资格仍由数据库检查。
const { data, error } = await supabase.from('contacts').insert({ name: '客户 A' }).select()
```

自定义 schema 的客户端用法见[官方文档](https://supabase.com/docs/guides/api/using-custom-schemas)。前端不能使用 service role key。TypeScript 类型分别包含对应业务 schema；显式泛型可采用 `createClient<Database, 'app_crm'>(...)`。

三个 demo 的浏览器只调用同源后端；后端固定业务 schema，并转发公开 key 与该用户 JWT 到 Data API。最终权限仍由数据库执行，修改前端不会绕过它。

共用 Auth 的 `SITE_URL` 只有一个默认值。正式应用使用 OAuth、邮件确认或密码恢复时，将各 App 回调加入 `ADDITIONAL_REDIRECT_URLS`，并在请求中明确指定当前 App 回调。详见[部署说明](deployment.md)。

## 独立迁移与运维边界

App 各自维护 `sql/001_init.sql`、`sql/002_<用途>.sql` 等版本；共享授权迁移由部署维护者先执行，业务 App 只引用它，不重复创建。每条迁移使用完整 schema 名，默认不修改其他 App。

版本记录需区分 `(app_id, version)`；如果多个 App 使用同一个迁移工具的全局版本表，必须协调版本与发布顺序，不能让它们分别认为自己独占数据库。后台自动发现不会执行迁移。当前由维护者统一执行，管理员凭据技术上仍能修改所有 schema，迁移范围需要审查；可另设受限迁移角色缩小权限。

独立迁移不等于独立恢复。整个实例恢复会同时回滚各 App 与共用 Auth；按 schema 导出只是补充，不自动包含 Auth 用户、Storage 文件和跨 schema 依赖。数据库升级、备份、恢复和停机仍需协调所有 App。

## 隔离验收

在开发/演练环境使用真实用户 JWT 验证；管理员或 service role 请求不能证明 RLS 生效。以下是本方案上线前的验收清单，本文示例未自动执行到当前数据库。

| 操作 | 预期 |
| --- | --- |
| 只具备 Todo 资格的用户，在 Todo 插入/查询自己的订单 | 成功。 |
| 同一用户将客户端 schema 改为 Notes，或直接构造 Notes REST 请求 | 查询返回空集合；插入失败；更新/删除不能影响任何行。 |
| Todo 的另一用户查询或修改前一用户的订单 | 查询不可见；更新/删除不能影响该行。 |
| 用户插入他人的 `user_id`，或把自己的订单改为他人所有 | 被 `WITH CHECK` 拒绝。 |
| 未登录请求访问两套业务表 | 无访问权限。 |
| 普通用户尝试修改 memberships 或通过 REST 请求内部授权表 | 无写权限；内部 schema 未暴露。 |
| 管理员撤销 Todo 资格后，用户再次读写 Todo | 查询不可见；写入被限制。 |
| 用户被明确授予两个 App 资格 | 可以分别访问两个 App 中自己的数据。 |

RLS 拒绝 SELECT 通常表现为空结果，UPDATE/DELETE 可能是成功状态但影响零行；验收需要检查返回数据或实际变化，不能只看 HTTP 状态码。Storage、Realtime、RPC 与 Edge Functions 若启用，也要分别验证跨 App 访问，因为它们不会自动继承所有业务表策略。

如果后续需要独立用户体系、App 专属管理员/密钥、独立恢复，或隔离资源和故障，应改为每 App 一套 Supabase，并分别配置数据目录、端口和密钥。
