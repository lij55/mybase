# Todo

添加任务、切换完成状态、删除任务。只允许已授权用户操作自己的记录。

统一启动、环境变量和首次管理员创建步骤见[demoapp README](../README.md)。Dockerfile 的构建上下文为上级 `demoapp`，而不是本目录。

## SQL

统一命名的 [sql/001_init.sql](sql/001_init.sql) 由管理员手动执行，容器不会自动迁移。先执行 ../admin/sql/001_init.sql，再执行本文件，业务初始化不要重复执行。后续变更按 `sql/002_<用途>.sql` 递增。

## 单独构建与启动

在 `demoapp` 下执行：

```bash
cp todo/.env.example todo/.env
# 编辑该文件后：
docker build -f todo/Dockerfile -t mybase-demo-todo:local .
docker run --rm --network mybase_default --env-file todo/.env \
  -p 127.0.0.1:8091:8080 mybase-demo-todo:local
```

访问 http://localhost:8091。统一 Compose/Traefik 部署只读取 `demoapp/.env`，无需子目录 `.env`。不同应用单独运行时请分配不同宿主机端口。
