# 上游来源

- 仓库：https://github.com/supabase/supabase
- 发布标签：`self-hosted/v0.8.2`
- Commit：`564eab8ad7840b13324f68b1bfac074ef8d51c21`
- 获取日期：2026-09-29
- `docker-compose.yml`、`volumes/` 来自该 commit 的 `docker/`，原始许可证见 `UPSTREAM-LICENSE`。
- 本地定制在 `compose.override.yml`、`config/`、`scripts/` 和 `.env.example`，基础 Compose 保留原样。
- 未启用上游可选 Logs/Vector、S3 或外部数据库组合。镜像使用固定版本标签；正式供应链管控还应记录各平台 digest。
- 本项目有自己的启动与备份流程，不要在这里直接运行上游 `reset.sh` / `update.sh`。
- `volumes/functions/hello/index.ts` 为本地替换示例：上游 hello 使用新 opaque key，本部署使用 HS256，因此改为兼容的用户鉴权示例。
