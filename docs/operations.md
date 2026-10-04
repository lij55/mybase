# 运维与备份恢复

## 日常操作

| 操作 | 命令 / 方法 |
| --- | --- |
| 启动并等待健康 | `make up` |
| 应用 `.env` 变化 | `make up`（或 `make restart`，同义） |
| 状态 | `make ps` |
| 最近日志 | `make logs SERVICE=storage`，不指定则显示全部 |
| 实时日志 | `docker compose -f docker-compose.yml -f compose.override.yml logs -f --tail=100 auth` |
| 拉取固定镜像 | `make pull`；不会自动选择最新版 |
| 停止并保留数据 | `make down` |
| 入口自检 | `make smoke` |
| 备份 | `make backup`，会暂停业务 |

容器配置 `restart: unless-stopped`，Docker 服务启动后会恢复之前运行的容器；手动 stop/down 后不会凭空重建。需要宿主机启用 Docker 开机启动。健康检查失败不一定自动重启容器，需监控告警和人工处理。

各容器 json-file 日志轮转为每份 10 MB、3 份。Nginx 日志不记录查询参数，其他上游服务日志仍可能包含敏感内容；导出日志时先检查。默认未启用 Logflare / Vector，因此 Studio 的 Logs Explorer 不提供完整聚合日志。需要时独立评估启用成本与 Docker socket 权限。

## 备份范围与一致性

`make backup` 会记录当前运行服务，停止整个项目（包括数据库、API和连接池），用固定的 PostgreSQL 镜像内的 tar 工具打包，最后重新启动原来运行的服务。归档包含：

- `project/`：配置、原 `.env`、数据库 `volumes/db/data`、文件 `volumes/storage`、函数、SQL 和文档。
- `db-config/`：命名卷中的 PostgreSQL / pgsodium 配置和解密所需资料。
- 不包含 backups 自身、Git 元数据、Python 缓存和可再生成的 Deno 缓存。

输出在 `backups/mybase-时间.tar.gz`，附 SHA-256 校验文件。失败的 `.partial` 不是有效备份。备份结束后运行 `make ps` 与 `make smoke`；`start` 恢复进程，不替代业务可用性验证。强制杀死备份进程或宿主机断电可能无法执行恢复服务步骤，此时手动 `make up`。

这是**有停机的物理冷备份**，适合小规模单机。时间点一致性通过停止写入和数据库获得，备份耗时随磁盘大小增长。不要在运行中的数据目录上普通 `tar` / `cp` 并把它当作可靠备份。

归档包含数据库密码、JWT 签名密钥 和业务数据。权限默认为 `0600`，异地保存前应加密，备份系统需独立访问凭证。定期做恢复演练，例如每月一次；按业务定义 RPO/RTO，示例可从每日备份、保留 7 日 + 4 周 + 6 月开始，并监控备份新鲜度、大小和可恢复性。定时任务使用项目的绝对工作目录，确保同一时间只有一个备份/升级任务，业务高峰不要执行冷备份。

不能接受停机时，需要 PostgreSQL 基础备份 + WAL 归档/PITR、Storage 对象版本化及一致性方案，或使用托管服务。`pg_dump` 适合逻辑迁移，但不自动包含 Storage 文件、所有角色和加密配置，不能代替本项目完整灾备。

## 在全新主机恢复

只从可信的归档恢复。以下操作要求目标目录和目标 Docker 命名卷是新建、空的；**不要覆盖正在运行的实例**。必须先用原版本、相同 CPU 架构恢复，验证后再升级。不要先 `make init` 生成新密码。

1. 将归档及 `.sha256` 下载到独立目录，校验：

   ```bash
   sha256sum -c mybase-YYYYMMDD-HHMMSS.tar.gz.sha256
   mkdir restore-stage
   sudo tar --numeric-owner -xzf mybase-YYYYMMDD-HHMMSS.tar.gz -C restore-stage
   ```

2. 把 `restore-stage/project` 放到最终持久化路径。保留数据库与 Storage 原 UID/GID；不要对整个目录递归 `chown`。只确保部署用户可读取和编辑 `.env`、脚本和配置。原 `.env` 也必须恢复，保持 `COMPOSE_PROJECT_NAME`，默认 `mybase`。
3. 在项目目录创建但不启动容器；这会准备命名卷。隔离演练环境不要连接生产公网入口或启用生产发信，避免发送生产邮件或争用域名。

   ```bash
   docker compose -f docker-compose.yml -f compose.override.yml create
   docker volume inspect mybase_db-config
   ```

   卷名默认是 `mybase_db-config`；修改过项目名时同步替换以下命令中的卷名。`create` 遇到镜像缺失会尝试拉取，数据文件尚不会执行数据库启动。

4. 将解出的 `db-config` 恢复到空命名卷。下面命令中的源路径替换为实际**绝对路径**：

   ```bash
   docker run --rm --network none --user 0 \
     --mount type=bind,source=/absolute/restore-stage/db-config,target=/restore,readonly \
     --mount type=volume,source=mybase_db-config,target=/target \
     --entrypoint sh supabase/postgres:17.6.1.136 \
     -c 'cp -a /restore/. /target/'
   ```

5. 执行 `make check`、`make up`、`make smoke`。核对用户、业务表行数、Storage 对象可下载、登录与跨用户 RLS、Realtime、函数。核实公网域名与 Tunnel 后再切流。只有完成验证，才可淘汰旧实例或旧备份。

不同 CPU 架构、不同 PostgreSQL 大版本或跨云迁移时优先设计逻辑导出/导入及扩展兼容方案，不能直接复制物理目录。

## 升级与回滚

不使用 Watchtower 等工具自动升级整个 Supabase 栈。上游服务之间有版本依赖，单独把一个镜像改成 `latest` 可能破坏兼容性。

1. 记录当前上游 commit、Compose 配置、镜像 digest，执行完整备份。
2. 在独立主机/独立项目目录恢复备份，关闭 Tunnel 和生产发信，验证现有版本能启动。
3. 获取新官方 self-hosted 发布标签，对比 Compose、所有 `volumes` 初始化/网关/函数脚本、变量模板；保留本地 override 的端口限制、日志和公网路径控制。
4. 按上游发布说明执行迁移。初始化目录里的 SQL 只在空库初始化时生效，更新这些文件并不会自动迁移现有数据。
5. 跑业务测试、RLS、邮件、Storage、Realtime，安排维护窗口上线。
6. 如果新版本已经迁移数据库，回退镜像可能不兼容；使用升级前整套备份恢复到新实例，再切换流量。

主版本升级如 PostgreSQL 17→后续版本，需要专门的 pg_upgrade 或逻辑迁移流程，不是只替换镜像标签。参考[官方升级说明](https://supabase.com/docs/guides/self-hosting/updating)。

## 监控建议

监控磁盘空间/inodes、CPU/RAM/OOM、容器重启与 health、数据库连接/锁等待/慢查询、Storage 增长、备份是否成功、SMTP 失败、Tunnel connector 状态和外部 HTTPS 成功率。阈值按实测负载设置；磁盘保留足够余量给 WAL、备份和镜像升级。

`/healthz` 仅检测 Nginx 存活，`make smoke` 额外经过 Auth/REST，但仍不是完整业务测试。生产应设一个只读、低权限的合成查询，并从外部网络验证。不要通过公开 service_role key 创建监控。
