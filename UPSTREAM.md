# 上游来源

- 仓库：https://github.com/supabase/supabase
- 发布标签：`self-hosted/v0.8.2`
- Commit：`564eab8ad7840b13324f68b1bfac074ef8d51c21`
- 获取日期：2026-09-29
- `docker-compose.yml`、`volumes/` 来自该 commit 的 `docker/`，原始许可证见 `UPSTREAM-LICENSE`。
- 本地定制在 `compose.override.yml`、`config/`、`scripts/` 和 `.env.example`，基础 Compose 已启用 ES256/JWKS 配置。
- 未启用上游可选 Logs/Vector、S3 或外部数据库组合。镜像使用固定版本标签；正式供应链管控还应记录各平台 digest。
- 本项目有自己的启动与备份流程，不要在这里直接运行上游 `reset.sh` / `update.sh`。
- `volumes/functions/hello/index.ts` 为本地替换示例：使用新 opaque publishable key 和用户 ES256 JWT 的鉴权示例。

- Realtime 单独升级到 `v2.140.7`（2026-10-01 发布），镜像 digest：`sha256:5c995fe7d7b827560ef9590a6c9ad527128d058efceabf37e0c55cf922b30a47`。管理 API 仍使用内部 HS256；采用原生 `/healthcheck` 作为存活检查，功能就绪通过公开 WebSocket 冒烟和集成测试验证。

- 2026-10-05 核对并升级其余 11 种组件/基础镜像，版本、官方来源及 digest 见 [镜像版本核对](docs/image-versions.md)，验收见 [验证记录](docs/verification.md)。
