# 镜像版本核对（2026-10-05）

基于各组件官方稳定发行和官方镜像仓库核对，固定以下版本。Supabase 自托管模板的原始来源仍保留在 [UPSTREAM.md](../UPSTREAM.md)；以下为本项目独立升级的组合。仅针对全新环境验证，不涉及已有数据库升级。

| 组件镜像 | 原版本 | 新版本 | 官方来源 |
| --- | --- | --- | --- |
| `supabase/studio` | `2026.09.07-sha-7996410` | `2026.09.28-sha-5e59b60` | [发行/镜像](https://hub.docker.com/r/supabase/studio/tags?name=2026.09.28-sha-5e59b60) |
| `supabase/gotrue` | `v2.196.0` | `v2.197.0` | [发行/镜像](https://github.com/supabase/auth/releases/tag/v2.197.0) |
| `postgrest/postgrest` | `v14.17` | `v16.4` | [发行/镜像](https://github.com/PostgREST/postgrest/releases/tag/v16.4) |
| `supabase/storage-api` | `v1.74.0` | `v1.79.31` | [发行/镜像](https://github.com/supabase/storage/releases/tag/v1.79.31) |
| `darthsim/imgproxy` | `v3.31.4` | `v4.0.17` | [发行/镜像](https://github.com/imgproxy/imgproxy/releases/tag/v4.0.17) |
| `supabase/edge-runtime` | `v1.76.2` | `v1.77.4` | [发行/镜像](https://github.com/supabase/edge-runtime/releases/tag/v1.77.4) |
| `supabase/postgres` | `17.6.1.136` | `17.11.0.003` | [发行/镜像](https://hub.docker.com/r/supabase/postgres/tags?name=17.11.0.003) |
| `supabase/supavisor` | `2.9.12` | `2.9.13` | [发行/镜像](https://github.com/supabase/supavisor/releases/tag/v2.9.13) |
| `nginx` | `1.28.0-alpine` | `1.30.5-alpine` | [发行/镜像](https://hub.docker.com/r/library/nginx/tags?name=1.30.5-alpine) |
| `traefik` | `v3.6` | `v3.7.13` | [发行/镜像](https://github.com/traefik/traefik/releases/tag/v3.7.13) |
| `python` | `3.13-slim` | `3.14.8-slim` | [发行/镜像](https://hub.docker.com/r/library/python/tags?name=3.14.8-slim) |

Realtime `v2.140.7`、Envoy `v1.39.1` 和 postgres-meta `v0.99.0` 已为核对时的稳定版本，保持不变。PostgreSQL 保持 17 主版本。Nginx 选用 stable 系列。三个 demo 共享固定的 Python 基础镜像，业务逻辑不变。

PostgREST 16 要求 PostgreSQL 14 或以上，本项目 PostgreSQL 17 满足要求；未配置被修改的自定义 JWT role claim 路径，也未暴露系统 schema。imgproxy 4 的兼容性通过真实私有 PNG 缩放及匿名/跨用户隔离测试验证。

## 拉取镜像的 digest

本次 Linux x86_64 验证使用以下仓库 manifest digest；固定标签尚未改为 digest 引用。

| 镜像 | RepoDigest |
| --- | --- |
| `supabase/studio:2026.09.28-sha-5e59b60` | `sha256:e4b6110f496ddcd3b3ceb8a23caf59016586a23b5cd363099fbc7b224152ebbc` |
| `supabase/gotrue:v2.197.0` | `sha256:1736a63078f5922b198c4cbe50f80ab9a2d3b54fe8b7b6cfb2e9dc5dbbc12c6b` |
| `postgrest/postgrest:v16.4` | `sha256:d155c6718ed9a9f990d159a2ab7c0a3f16944dbb6d0a0344557421042acfe0df` |
| `supabase/storage-api:v1.79.31` | `sha256:4e0d73f5c2aef4dfaf31233d4086dde78c55e5d18cf954479795e7dcbb3e1448` |
| `darthsim/imgproxy:v4.0.17` | `sha256:db0b4b9cd690c8b3590203dea300fb759a18c4ec2af7b37424f0bdef23ce317d` |
| `supabase/edge-runtime:v1.77.4` | `sha256:ad45164b7548bf5820ed7be714789c17ac2865edce79a09cfb4c3756c3d365a8` |
| `supabase/postgres:17.11.0.003` | `sha256:7374d196da7e301512cc5329e18040e0f7bb856287b323777cdadecccbc6c7e4` |
| `supabase/supavisor:2.9.13` | `sha256:07f1a6098ffc04b80263bca4eb5c3e7bd2e03dfd1fc465aa108d7329000a1a4e` |
| `nginx:1.30.5-alpine` | `sha256:0985e772fb9f729e6fa0980da05fca5d9c468e870eed43071545afa9d2e27d94` |
| `traefik:v3.7.13` | `sha256:24841fe2de7304c149343d877d2923b4c8800a38ba015dea9174c23b20e344a0` |
| `python:3.14.8-slim` | `sha256:c3e521df8b2b498a7a682e7e18676771cb80c6b75b8699af886b2d554ce40151` |
