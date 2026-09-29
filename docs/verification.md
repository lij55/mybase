# 验证记录

环境：2026-09-29，Linux x86_64，Docker Compose 2.33.0，Python 3.14。上游版本见 [UPSTREAM.md](../UPSTREAM.md)。

已完成：

- `.env` 安全初始化、重复初始化不换密钥、缺失原密钥拒绝覆盖已有数据库。
- `make up && make test` 通过：12 项离线测试（8 项配置、4 项测试客户端回归）和 11 项真实实例功能测试；Compose 合并与变量校验。
- 实际拉取并启动 12 个服务，全部 healthy；重复 `make up` 成功。
- 实际监听：8000、8001、5432、6543 仅绑定 127.0.0.1。
- Auth/REST 可达；未带 key 请求被拒绝；Studio Basic Auth；公开根路径、pg、MCP、Realtime 管理路径与编码目录穿越请求被拒绝。
- Auth 登录、当前用户、错误凭据拒绝、会话刷新、退出后刷新失效、注册配置；REST 完整 CRUD、约束和 RLS 跨用户读/改/删/插入隔离、匿名拒绝；RPC 按调用者 RLS 返回结果。
- 私有 Storage 上传/下载/覆盖/列举/删除、带空格对象键、匿名及跨用户隔离、签名 URL 无认证下载。
- hello Edge Function 的用户调用、默认参数、匿名及非法 JWT 拒绝、方法/JSON 校验、CORS 预检。
- 经业务入口的 Realtime 握手、INSERT 事件投递及 RLS 隔离、WebSocket 广播、Presence track。
- Studio Basic Auth 登录后返回页面；Session / Transaction 宿主机端口执行 SQL 事务并验证回滚。
- 冷备份归档生成成功，并自动恢复原运行服务。

独立恢复演练通过：使用 `mybase-20260929-190223.tar.gz`，校验 SHA-256 后恢复到独立目录、项目名与端口；保留原密钥与 db-config，数据库 system_identifier 与源实例一致，`make up` 和完整集成测试通过。演练容器及网络已移除，临时目录和命名卷保留供检查（位置见 [恢复结果](restore-result.json)）。此次使用新建开发库，未衡量生产大数据集的恢复时长。

尚未验证：实际 Cloudflare 账户下的 Tunnel/DNS、公网 HTTPS/WSS、真实 SMTP/邮件回调/OAuth、前端浏览器完整交互、Realtime UPDATE/DELETE 语义、私有频道授权及重连、图片转换/S3 协议、MFA、压测、高可用与大数据集恢复时长。上述项需要实际账户、域名、业务负载和进一步验收，不能从容器 healthy 推断已经完成。

修复过的兼容问题：新版 REST OpenAPI 根路径需管理 key；Nginx 要保留对象名 URL 转义；官方 Realtime 网关需固定 DNS alias；上游新版 hello 的 opaque key 示例需替换为本部署 HS256 兼容的用户鉴权示例。
