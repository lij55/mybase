#!/usr/bin/env bash
# Packaged beside project/ and db-config/ by make backup.
set -euo pipefail
restore_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
python3 - "$restore_root" <<'PY'
import pathlib
import subprocess
import sys

root = pathlib.Path(sys.argv[1])
project = root / 'project'
source = root / 'db-config'
if not (project / '.env').is_file() or not source.is_dir():
    sys.exit('请运行备份根目录中的 restore.sh；必须包含 project/.env 和 db-config/。')
sys.path.insert(0, str(project / 'scripts'))
import manage

v = manage.effective_env(manage.read_env(project / '.env'))
manage.validate(v)
cfg = manage.config(v)
volume = cfg['volumes']['db-config']['name']
image = cfg['services']['db']['image']

def run(args, **kwargs):
    return subprocess.run(args, check=True, **kwargs)

# Refuse any existing volume, including stopped instances, before creating containers.
volumes = run(['docker', 'volume', 'ls', '--format', '{{.Name}}'],
              capture_output=True, text=True).stdout.splitlines()
if volume in volumes:
    sys.exit(f'拒绝覆盖已有卷 {volume}。请在全新 Docker 环境恢复，或确认旧卷不再需要后手动处理。')
manage.compose(v, ['create'])
run(['docker', 'run', '--rm', '--network', 'none', '--user', '0',
     '--mount', f'type=bind,source={source},target=/restore,readonly',
     '--mount', f'type=volume,source={volume},target=/target',
     '--entrypoint', 'sh', image, '-ec',
     'test -z "$(ls -A /target)" || { echo "目标卷非空，拒绝覆盖" >&2; exit 1; }; '
     'cp -a /restore/. /target/'])
print(f'已恢复 {volume}，容器尚未启动。后续在以下目录进行日常操作：\n{project}')
print('进入 project 后执行：make check && make up && make smoke')
PY
