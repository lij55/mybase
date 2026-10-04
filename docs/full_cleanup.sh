#!/usr/bin/env bash
# 手动执行：bash doc/full_cleanup.sh
# 清空测试数据，保留 .env、Caddy 配置、Edge Functions 和 backups。
# 此文件故意不设置可执行权限。
set -euo pipefail

if [[ $# -gt 0 ]]; then
  if [[ $# -eq 1 && ( "$1" == '--help' || "$1" == '-h' ) ]]; then
    printf '%s\n' '用法：bash doc/full_cleanup.sh' \
      '删除本项目容器、网络、命名卷及数据库、Storage、Studio snippets 数据。' \
      '保留配置、密钥、函数代码和备份；不会自动启动新实例。'
    exit 0
  fi
  printf '%s\n' '不支持该参数；查看帮助：bash doc/full_cleanup.sh --help' >&2
  exit 1
fi

script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)
project_root=$(cd -- "$script_dir/.." && pwd -P)
cd -- "$project_root"

for file in .env scripts/manage.py docker-compose.yml compose.override.yml; do
  if [[ ! -f "$file" ]]; then
    printf '缺少 %s，停止清理。请确认脚本位于项目 doc/ 目录。\n' "$file" >&2
    exit 1
  fi
done

# 不允许持久化目录的符号链接把清理指向项目外。
for directory in volumes volumes/db volumes/db/data volumes/storage volumes/snippets; do
  if [[ -L "$directory" ]]; then
    printf '%s 是符号链接，停止清理，请先确认其真实位置。\n' "$directory" >&2
    exit 1
  fi
done

printf '项目目录：%s\n' "$project_root"
printf '%s\n' \
  '将永久删除当前项目的容器、网络和命名卷（含 db-config、deno-cache）。' \
  '将清空 volumes/db/data、volumes/storage、volumes/snippets。' \
  '保留 .env、Caddy 配置、函数代码和 backups。'
read -r -p '确认清空测试环境请输入 FULL_CLEANUP：' confirmation || exit 1
if [[ "$confirmation" != 'FULL_CLEANUP' ]]; then
  printf '%s\n' '已取消，未执行清理。'
  exit 1
fi

remove_command=(rm)
if (( EUID != 0 )); then
  # 数据目录可能由容器的 UID 或 root 创建；先确认权限再停止服务。
  sudo -v
  remove_command=(sudo rm)
fi

# 复用管理脚本：读取 .env 字面值，使用固定 Compose 组合及正确项目名。
# down 失败时立即退出，不删除持久化目录。
python3 - <<'PY'
from pathlib import Path
import sys

sys.path.insert(0, 'scripts')
import manage

values = manage.effective_env(manage.read_env(Path('.env')))
manage.compose(values, ['down', '--volumes', '--remove-orphans'])
PY

"${remove_command[@]}" -rf -- \
  "$project_root/volumes/db/data" \
  "$project_root/volumes/storage" \
  "$project_root/volumes/snippets"

printf '%s\n' \
  '清理完成，当前实例已停止。' \
  '使用原配置重新初始化：make up && make smoke' \
  '若还需重新生成密钥，先手动删除 .env，再运行 make init 并检查 PUBLIC_HOST。'
