.DEFAULT_GOAL := help
.PHONY: help init check up down restart ps logs pull smoke backup psql test unit integration
help:
	@printf '%s\n' 'make up       初始化并启动（读取 .env）' 'make init     生成 .env、随机密钥和 caddy/Caddyfile，已有配置不覆盖' 'make check    校验配置' 'make ps       容器状态' 'make logs     最近日志；SERVICE=auth 可筛选' 'make smoke    本机 API / 安全边界检查' 'make down     停止并保留数据' 'make restart  重新应用配置' 'make pull     拉取固定版本镜像' 'make backup   停机一致性备份，完成后恢复原运行服务' 'make psql     数据库交互终端' 'make test     配置 + 安全边界 + 关键功能集成测试（先 make up）' 'make unit     无 Docker 的配置逻辑测试' 'make integration  本地 API 集成测试，创建并清理临时数据'
init check up down restart ps logs pull smoke backup psql:
	@python3 scripts/manage.py $@ $(if $(SERVICE),--service $(SERVICE),)
test:
	@$(MAKE) --no-print-directory unit
	@$(MAKE) --no-print-directory integration

unit:
	@python3 -m unittest discover -s tests -v

integration:
	@python3 scripts/integration.py
