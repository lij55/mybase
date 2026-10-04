# 三个独立应用，共用 Supabase

这里包含授权后台、Todo 和 Quick Notes。每个应用有自己的 Dockerfile、镜像、页面和后端，运行时从环境变量读取配置。共用 Python HTTP 后端代码和静态样式，不需要 Node 或前端构建；只有授权后台需要 psycopg 数据库驱动。

| 应用 | 目录 | 默认入口 | 数据 |
| --- | --- | --- | --- |
| 授权后台 | [admin](admin/README.md) | http://authz.localhost:8090 | 共用 `app_access.memberships`，调用 Auth 管理 API |
| Todo | [todo](todo/README.md) | http://todo.localhost:8090 | 独立 `app_todo.todos` |
| Quick Notes | [notes](notes/README.md) | http://notes.localhost:8090 | 独立 `app_notes.notes` |

授权后台按数据库中的 schema 自动发现应用，不维护手填应用列表。按“发现应用”刷新即可获取新增应用。勾选为用户授予访问权，取消勾选撤销。用户账号共用，每个应用的数据仍按用户与成员资格执行 RLS。完整边界和正式应用约定见[多 App 文档](../docs/multi-app.md)。

## 1. 启动 Supabase，并手动执行 SQL

在仓库根目录执行 `make up`。**应用容器不会自动运行 SQL**，由你按以下顺序统一运行：

| 顺序 | 文件 | 用途 |
| --- | --- | --- |
| 1 | [admin/sql/001_init.sql](admin/sql/001_init.sql) | 共用授权表、权限检查函数、后台能力角色；兼容旧文档的 A/B CHECK 约束 |
| 2 | [todo/sql/001_init.sql](todo/sql/001_init.sql) | Todo schema、表、权限、RLS |
| 3 | [notes/sql/001_init.sql](notes/sql/001_init.sql) | Notes schema、表、权限、RLS |

全部子应用统一使用 `sql/001_init.sql` 命名；后续迁移为 `sql/002_<用途>.sql`、`sql/003_<用途>.sql`，按 App 分别记录执行版本。业务初始化用于首次建库，重复执行会失败，不要重复运行到同名 schema。共享初始化可重复执行，但它不是任意旧结构的自动迁移工具。

在仓库根目录依次执行（或在 Studio 逐份执行同样的 SQL）：

```bash
docker compose -f docker-compose.yml -f compose.override.yml exec -T db \
  psql -v ON_ERROR_STOP=1 -U postgres -d postgres < demoapp/admin/sql/001_init.sql
docker compose -f docker-compose.yml -f compose.override.yml exec -T db \
  psql -v ON_ERROR_STOP=1 -U postgres -d postgres < demoapp/todo/sql/001_init.sql
docker compose -f docker-compose.yml -f compose.override.yml exec -T db \
  psql -v ON_ERROR_STOP=1 -U postgres -d postgres < demoapp/notes/sql/001_init.sql
```

如果根 `.env` 自定义了 `COMPOSE_PROJECT_NAME`，为命令添加匹配的 `-p`；自定义数据库名时也应替换 `-d postgres`。

在 Studio SQL Editor 为后台创建独立的数据库登录，替换下面的密码，不要使用占位密码：

```sql
create role demo_authorizer login inherit password '<替换为独立的随机密码>';
grant connect on database postgres to demo_authorizer;
grant app_authorizer to demo_authorizer;
```

`app_authorizer` 只有共用成员表的 SELECT/INSERT/DELETE 权限，以及对应 RLS 策略；它不能读写 Todo 或 Notes。后台使用该数据库连接自动发现 schema、管理成员资格。不要给它 `postgres`、`service_role`、超级用户或绕过 RLS 的能力。

在**仓库根 `.env`** 增加或更新下面一行，再执行 `make up`：

```dotenv
PGRST_DB_SCHEMAS=public,graphql_public,app_todo,app_notes
```

`app_access` 是保留的内部 schema，不得暴露。若已有其他业务 schema，应继续保留它们。

## 2. 创建第一个后台管理员

管理员资格由 `ADMIN_USER_IDS` UUID 白名单控制，独立于应用授权；拥有 Todo 权限不会获得后台权限。已有 Auth 用户时直接使用其 UUID。否则在仓库根目录执行：

```bash
python3 demoapp/bootstrap_admin.py
```

脚本交互输入邮箱和密码，读取根 `.env` 的管理密钥并调用本机 Auth 创建账号，只输出新用户 UUID，不写配置、不授予业务 App 权限。管理员创建的账号直接确认邮箱，无邀请或确认邮件；这适合当前由你统一创建账号的模式。初始密码通过可信渠道交给用户。

## 3. 配置并启动三个镜像

```bash
cd demoapp
cp .env.example .env
chmod 600 .env
```

编辑 `demoapp/.env`（与根 `.env` 是两个文件，不能 source）：

- `SUPABASE_ANON_KEY`：复制根 `.env` 的 `ANON_KEY`。
- `SUPABASE_SERVICE_ROLE_KEY`：复制根 `.env` 的 `SERVICE_ROLE_KEY`，仅注入授权后台。
- `DATABASE_URL`：`postgresql://demo_authorizer:<URL编码后的密码>@db:5432/postgres`。
- `ADMIN_USER_IDS`：上述管理员的 Auth UUID，多个 UUID 用逗号分隔。
- `SUPABASE_DOCKER_NETWORK`：默认 `mybase_default`，自定义部署名称时通常是 `<COMPOSE_PROJECT_NAME>_default`；可用 `docker network ls` 确认。

`SUPABASE_URL=http://api-gw:8000` 是容器内部网关 URL，不是浏览器 URL。容器里的 `localhost` 指自己，不能用它连接宿主机 Supabase。

```bash
docker compose --env-file .env -f compose.yml config --quiet
docker compose --env-file .env -f compose.yml up -d --build --wait
docker compose --env-file .env -f compose.yml ps
```

Compose 构建 `mybase-demo-admin:local`、`mybase-demo-todo:local`、`mybase-demo-notes:local` 三个镜像，并启动 Traefik。各 App 不向宿主机暴露端口；Traefik 按 Host 分流到它们的 8080 端口。`/healthz` 只验证应用进程，SQL 初始化与上游连接需通过登录/业务操作验收。

默认 Traefik 只监听宿主机 `127.0.0.1:8090`。若浏览器无法解析 `.localhost` 子域名，可在 hosts 文件加入：

```text
127.0.0.1 authz.localhost todo.localhost notes.localhost
```

启动后访问表中三个入口。远程主机可以 SSH 转发 `8090`，或者配置 HTTPS 入口及真实域名。公开部署需为登录和 API 提供 HTTPS；域名由 `ADMIN_HOST`、`TODO_HOST`、`NOTES_HOST` 调整，Traefik 不自动配置证书。当前应用密码登录不需要浏览器直连 Supabase，也不需要 CORS。

Traefik 使用 Docker provider、限定标签和 `exposedByDefault=false`，不会自动发布现有 Supabase 容器。它需要读取宿主机 Docker socket；后台之外的 App 均无此挂载，也不接收数据库密码或 service role key。配置与标签依据[官方 Docker provider 文档](https://doc.traefik.io/traefik/reference/install-configuration/providers/docker/)。

各自单独构建时，**构建上下文都是 demoapp**：

```bash
docker build -f admin/Dockerfile -t mybase-demo-admin:local .
docker build -f todo/Dockerfile -t mybase-demo-todo:local .
docker build -f notes/Dockerfile -t mybase-demo-notes:local .
```

也可使用各目录的 `.env.example` 准备仅包含该应用所需变量的配置，单独运行（示例用端口 8091 绕过 Traefik）：

```bash
docker run --rm --network mybase_default --env-file todo/.env \
  -p 127.0.0.1:8091:8080 mybase-demo-todo:local
```

统一部署使用根 `demoapp/.env`，无需再维护三个子目录 `.env`。Compose 明确挑选变量，不会把后台管理密钥注入 Todo/Notes。`.env` 不进入镜像或版本库；不要输出包含密钥的完整 `docker compose config`。

## 4. 创建用户与分配权限

登录授权后台，输入邮箱与初始密码创建用户，然后选择用户、勾选应用。创建账号不自动授权。可以让同一用户只访问 Todo、只访问 Notes，或同时访问两者。

例如增加 10 个用户：逐个创建账号，对每个账号选择所需 App；界面支持按页查看已有用户，每页 50 人。暂不提供邀请、批量导入、删除 Auth 账号或后台管理员管理。此处“撤销用户”指撤销其 App 访问权；共用账号及其历史数据保留。

进入 Todo/Notes 后使用相同账号密码登录，各域名的浏览器会话独立。后端每次调用 Auth 验证用户，业务操作用公开 key + 该用户 JWT 调用固定 schema 的 Data API，保留 RLS。授权后台每次都再检查管理员白名单，不能通过前端修改 UUID 或角色自提权。

会话暂保存在当前标签页的 `sessionStorage`，支持 access token 自动刷新；退出调用 Auth 本地注销并清除本地会话。Auth 本地注销不保证现有 JWT 立即失效，App 撤权由数据库成员记录直接控制。密码不保存在浏览器存储。Python 标准库 HTTP 服务用于此小型 demo，正式应用应沿用授权协议并选择适合自己的服务框架。

后续 OAuth/OIDC/Keycloak 集成应保留 Supabase 可识别的用户 UUID 与会话：通常通过 Supabase Auth 接入提供商，再替换登录入口。直接把 Keycloak token 传入当前应用不会自动生效，因为后端用 `/auth/v1/user` 验证 Supabase 会话，RLS 使用 `auth.uid()`。外部身份若映射到新的 Auth UUID，需要重新分配成员资格；不要依赖邮箱推断授权。

## 5. 新增正式应用

1. 按[正式应用约定](../docs/multi-app.md#正式应用约定与自动发现)选择唯一 `app_<名称>` schema；内部共用 `app_access` 为例外保留名称。
2. 新 App 提供 `sql/001_init.sql`，设置 schema 注释为展示名称，建表、显式 GRANT、启用 RLS，检查 `app_access.can_access_app('<schema>')` 和行归属。
3. 你执行 SQL 后，后台点击“发现应用”即可看到它，**无需修改后台代码或成员表 CHECK 枚举**；尚未授予的新 App 默认无人可用。
4. 需要 Data API 时，仍须手动把 schema 加到根 `.env` 的 `PGRST_DB_SCHEMAS`，再 `make up`。自动发现不会自动暴露接口或代替安全审查。
5. App 容器通过自己的 Dockerfile 和环境变量配置部署；本示例 Compose 若要托管它，还需要新增服务及 Traefik 标签。数据库自动发现不负责创建镜像或反向代理路由。

## 验证与维护

在仓库根目录执行离线验证，不会修改 Supabase：

```bash
python3 -m unittest discover -s demoapp/tests -v
```

在仓库根目录运行隔离 SQL 验证（需要 Docker 权限和数据库镜像）：

```bash
python3 demoapp/tests/check_sql.py
```

它创建无网络、无数据卷的新临时 PostgreSQL 容器，安装最小 Auth 测试替身、执行真实迁移并检查 RLS，最后删除自己创建的容器；不会连接当前 Supabase。`tests/sql_fixture.sql` 和 `tests/sql_security.sql` 只供临时库测试，**不得执行到现有实例**。测试覆盖共享初始化重复执行、新 App 自动发现、跨用户/跨 App 隔离、伪造归属、成员表自提权、受限后台 DB 权限与撤权；不替代真实 Supabase Auth 的端到端验收。

可选浏览器测试需要 Node 22+ 和本机 Chromium：先启动 demo Compose，再在单独终端启动 `chromium --headless --no-proxy-server --remote-debugging-port=9223 --user-data-dir=/tmp/mybase-demo-browser-test about:blank`，然后运行 `node demoapp/tests/browser_smoke.mjs`。该脚本通过浏览器拦截 `/api/` 请求提供测试数据，验证创建用户、授予/撤销、发现新 App、业务增删和会话刷新，不创建真实账号或数据；测试完成后关闭临时浏览器。使用默认三个域名和 8090 端口。

手动验收：创建两个用户，只给 U1 Todo、只给 U2 Notes。分别登录两个 App，确认能操作已授权 App，未授权 App 插入被拒绝；管理员撤销 U1 Todo 后，其后续读取不可见、写入失败。给两人都授予 Todo，确认彼此数据不可见；用普通账号登录后台，确认 403。这些测试必须使用用户 JWT，不能用 service role。更完整的检查见[隔离验收](../docs/multi-app.md#隔离验收)。

```bash
docker compose --env-file .env -f compose.yml logs --tail=100 admin
docker compose --env-file .env -f compose.yml down
```

停止 demo 不删除 Supabase 数据。修改 `.env` 后重新 `up -d`；修改代码后 `up -d --build`。SQL 由你继续手动执行。业务恢复、备份和停机仍按[实例运维](../docs/operations.md)管理全部 App。
