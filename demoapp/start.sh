#!/usr/bin/env bash
set -euo pipefail

demo_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
init_requested=false
up_args=()
for arg in "$@"; do
  if [[ "$arg" == --init ]]; then
    init_requested=true
  elif [[ "$arg" == --help || "$arg" == -h ]]; then
    echo "用法：$0 [--init] [Compose up 参数]"
    echo "--init：初始化 demo 数据库、交互创建/选择管理员并生成 demoapp/.env；需已启动 Supabase。"
    exit 0
  else
    up_args+=("$arg")
  fi
done
command -v docker >/dev/null || { echo "需要安装 Docker 和 Compose 插件。" >&2; exit 1; }
docker compose version >/dev/null
if "$init_requested"; then
  python3 "$demo_dir/init_demo.py"
fi
if [[ ! -f "$demo_dir/.env" ]]; then
  (umask 077; cp "$demo_dir/.env.example" "$demo_dir/.env")
  echo "已创建 demoapp/.env。请运行 ./demoapp/start.sh --init 自动初始化，或按 README 手动填写。" >&2
  exit 1
fi
compose=(docker compose --project-directory "$demo_dir" --env-file "$demo_dir/.env" -f "$demo_dir/compose.yml")
"${compose[@]}" config --quiet
"${compose[@]}" up -d --build --wait "${up_args[@]}"
"${compose[@]}" ps

printf '\nDemo 已启动。请在 Supabase 一侧配置 Data API：\n'
printf '  在仓库根 .env 的 PGRST_DB_SCHEMAS 中保留已有 schema，并追加 app_todo,app_notes。\n'
printf '  默认配置示例：PGRST_DB_SCHEMAS=public,graphql_public,app_todo,app_notes\n'
printf '  不要暴露内部 schema app_access。保存后手动执行：\n\n'
printf 'cd -- %q\n' "$(dirname -- "$demo_dir")"
cat <<'COMMANDS'
docker compose -f docker-compose.yml -f compose.override.yml up -d --no-deps rest studio

若根 .env 自定义了 COMPOSE_PROJECT_NAME，请在上述 docker compose 后添加 -p <部署名称>。
以上配置和命令仅打印，未自动修改或执行。
COMMANDS
