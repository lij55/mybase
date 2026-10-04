# 当前实例的功能测试

## 运行

```bash
make up && make test        # 启动并执行全部验收
make unit                  # 14 项离线单元测试，无需 .env / Docker
make integration           # 11 项集成测试，需要已启动的实例
```

`make test` 顺序执行 unit 与 integration，即使使用 `make -j test` 也不会同时运行两阶段。任一阶段失败返回非零退出码，停止后续阶段。服务未启动、缺少 .env、权限不足和清理失败都视为失败，不会静默跳过。逐个用例显示 `ok` / `FAIL` / `ERROR`。

依赖沿用项目的 Python 3.11+、Docker Compose 与 Linux 环境，不下载测试 SDK。请求直接访问 `.env` 配置的本机端口，不使用机器 HTTP 代理。连接池测试以现有数据库镜像启动临时 `psql` 容器，使用 host 网络连接 `DB_SESSION_PORT` / `DB_TRANSACTION_PORT`；密码通过环境传入，不放进命令行参数。

## 覆盖范围

| 集成用例 | 成功与拒绝路径 |
| --- | --- |
| Auth sessions | 创建已确认测试用户、密码登录、获取用户、错误密码/非法 JWT 拒绝、刷新、退出后 refresh token 失效 |
| Auth signup | 实际 settings 与 `DISABLE_SIGNUP` 一致；关闭注册时 signup 拒绝；开启时不发送真实注册邮件 |
| Gateway | Auth/REST 健康、缺少/错误 key 拒绝、匿名管理 API 拒绝、公开管理路径/编码穿越隔离、Studio 未登录拒绝 |
| REST/RLS | 完整增查改删、默认所有者、字段约束、跨用户读改删插入隔离、所有权转移拒绝、匿名拒绝、管理 key 查询 |
| RPC | 临时 SECURITY INVOKER 函数、自身/他人不同结果、匿名调用拒绝 |
| Storage | 私有 bucket、普通/含空格文件名、上传下载覆盖列举删除、跨用户及匿名拒绝、越权操作不改变原文件、签名 URL 无认证下载 |
| Edge Functions | 中文参数/默认参数、未登录/anon/非法 JWT 拒绝、错误方法/JSON、浏览器式 CORS 预检 |
| Realtime changes | 等待数据库订阅与实际投递就绪后插入，两位用户只收到自己的 INSERT；收到后额外观察 1 秒确认无越权事件 |
| Realtime broadcast/presence | WebSocket 广播回送的实际载荷、Presence track 后收到加入事件 |
| SQL poolers | 两个宿主机端口均完成真实 SQL 事务，临时表写入/读取及回滚后不存在 |
| Studio | Basic Auth 拒绝未登录请求、正确凭据能取得 HTML 页面 |

离线测试保留原有 8 项配置测试，另有 4 项客户端回归测试，检查 WebSocket 分片、ping/pong、客户端掩码、扩展长度、关闭/超时失败及 HTTP 错误信息不输出签名 URL。

## 数据隔离与失败诊断

每个用例使用 UUID 后缀临时资源，不复用业务表、用户或 bucket。表策略来源于 `examples/001_todos.sql`，Storage 策略来源于 `examples/002_storage.sql`，因此示例权限退化也会导致验收失败。测试不会启用额外扩展或改变注册配置。

清理注册在资源创建时，按依赖逆序执行：关闭订阅，清空/删除 bucket，删除策略、RPC、表，最后删除用户。使用 unittest cleanup，单个断言或清理失败不阻止其他已登记清理操作。SQL/HTTP 有超时，PostgREST schema cache 使用有截止时间的重试，Realtime 在订阅成功后使用最长 75 秒的实际事件探测等待新建表进入复制服务的 publication 缓存（当前镜像约每 60 秒刷新），期间发送心跳。探测成功后再执行正式单次插入及隔离断言；持续无事件仍会失败。整套集成测试通常耗时数秒至约 90 秒。

如果失败，先查看用例名及 HTTP 状态，再运行 `make logs SERVICE=auth`（或 rest、storage、realtime 等对应服务）。请求异常不打印 token、密码或响应中的 session。强制杀进程、主机断电或服务在清理阶段不可达时仍可能遗留 `test_` / `test-` 资源，按本次资源名核对后处理，不要批量删除未知业务资源。

## 通过不代表什么

这些测试验证当前本机入口和临时示例策略的关键路径。未启用的 GraphQL/vector/cron、SMTP/邮件/OAuth/MFA、图片转换/S3 协议、公网 Tunnel/HTTPS/WSS、浏览器完整交互、私有 Realtime 频道授权、UPDATE/DELETE 事件、长连接重连和负载性能均不在本次自动验收范围。RLS 测试不能代替业务自己的表和租户授权测试。备份恢复已有独立演练记录，不在 `make test` 中停机执行。
