# 授权后台

创建共用 Auth 用户；按 app_ schema 自动发现应用；授予和撤销访问权。管理员由 ADMIN_USER_IDS 白名单控制。

统一启动、环境变量和首次管理员创建步骤见[demoapp README](../README.md)。Dockerfile 的构建上下文为上级 `demoapp`，而不是本目录。

## SQL

先执行 [sql/000_prepare.sql](sql/000_prepare.sql)，创建带密码的 PostgreSQL 登录账号 `app_authorizer`；密码直接保存在 SQL 中，部署前修改并同步到 `DATABASE_URL`。再执行 [sql/001_init.sql](sql/001_init.sql)，创建共享授权结构并授予权限。两份 SQL 由管理员手动执行，容器不会自动迁移。后续变更按 `sql/002_<用途>.sql` 递增。

## 单独构建与启动

在 `demoapp` 下执行：

```bash
cp admin/.env.example admin/.env
# 编辑该文件后：
docker build -f admin/Dockerfile -t mybase-demo-admin:local .
docker run --rm --network mybase_default --env-file admin/.env \
  -p 127.0.0.1:8091:8080 mybase-demo-admin:local
```

访问 http://localhost:8091。统一 Compose/Traefik 部署只读取 `demoapp/.env`，无需子目录 `.env`。不同应用单独运行时请分配不同宿主机端口。
