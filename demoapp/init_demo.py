"""First-run setup for the local Supabase + demo Compose deployment."""
import os
import re
import subprocess
import tempfile
from urllib.parse import quote
from uuid import UUID

import bootstrap_admin

manage = bootstrap_admin.manage
ROOT = bootstrap_admin.ROOT


def write_env(path, text, updates):
    """Preserve comments and other settings; atomically write a private env file."""
    for key, value in updates.items():
        if any(c in value for c in "\n\r'\\"):
            raise ValueError(f'{key}: unsupported env characters')
        line = f"{key}='{value}'"
        pattern = r'^' + re.escape(key) + r'=.*$'
        if re.search(pattern, text, flags=re.M):
            text = re.sub(pattern, lambda _: line, text, flags=re.M)
        else:
            text += f'\n{line}\n'
    fd, name = tempfile.mkstemp(prefix='.env.', suffix='.partial', dir=path.parent)
    try:
        with os.fdopen(fd, 'w') as handle:
            handle.write(text)
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def prepare_password(sql):
    # Read the SQL literal actually used by 000_prepare.sql, including escaped quotes.
    passwords = re.findall(r"\bpassword\s+'((?:[^']|'')*)'", sql, flags=re.I)
    if len(passwords) != 1:
        raise ValueError('000_prepare.sql 必须包含一个 PASSWORD SQL 字符串')
    return passwords[0].replace("''", "'")


def psql(values, sql, capture=False):
    return manage.compose(values, ['exec', '-T', 'db', 'psql', '-X', '-v',
                                  'ON_ERROR_STOP=1', '-U', 'postgres', '-d',
                                  values['POSTGRES_DB'], '-At'],
                          input=sql, text=True, capture_output=capture)


def initialize(root=ROOT):
    demo = root / 'demoapp'
    path = demo / '.env'
    text = (path if path.exists() else demo / '.env.example').read_text()
    existing = manage.read_env(path) if path.exists() else {}
    prepare = (demo / 'admin/sql/000_prepare.sql').read_text()
    password = prepare_password(prepare)
    root_env = root / '.env'
    if not root_env.exists():
        raise ValueError('缺少根 .env，请先自行启动并验证 Supabase')
    values = manage.effective_env(manage.read_env(root_env))
    if not values.get('ANON_KEY') or not values.get('SERVICE_ROLE_KEY'):
        raise ValueError('根 .env 缺少 ANON_KEY 或 SERVICE_ROLE_KEY，请先完成 Supabase 配置')
    schemas = {s.strip() for s in values['PGRST_DB_SCHEMAS'].split(',')}
    if not {'app_todo', 'app_notes'} <= schemas:
        print('提示：请在 Supabase 一侧配置 PGRST_DB_SCHEMAS 包含 app_todo,app_notes 并应用；本脚本不会修改它。')
    print('准备数据库账号及共享授权结构……', flush=True)
    psql(values, prepare)
    psql(values, (demo / 'admin/sql/001_init.sql').read_text())
    for app in ('todo', 'notes'):
        schema = f'app_{app}'
        found = psql(values, f"select exists(select 1 from pg_namespace where nspname = '{schema}');", True)
        if found.stdout.strip() == 't':
            print(f'{schema} 已存在，保留现有数据，跳过首次建表。')
        else:
            psql(values, (demo / app / 'sql/001_init.sql').read_text())
    admins = existing.get('ADMIN_USER_IDS', '').strip()
    if not admins:
        admins = input('已有 Studio/Auth 用户？输入其 UUID；直接回车则创建新管理员：').strip()
    if not admins:
        admins = bootstrap_admin.create_admin(values)
    ids = [str(UUID(user.strip())) for user in admins.split(',')]
    for user in ids:
        found = psql(values, f"select exists(select 1 from auth.users where id = '{user}'::uuid and email_confirmed_at is not null);", True)
        if found.stdout.strip() != 't':
            raise ValueError(f'Auth 用户 {user} 不存在或邮箱未确认，请在 Studio 中检查')
    write_env(path, text, {
        'SUPABASE_DOCKER_NETWORK': existing.get('SUPABASE_DOCKER_NETWORK') or values['COMPOSE_PROJECT_NAME'] + '_default',
        'SUPABASE_ANON_KEY': values['ANON_KEY'],
        'SUPABASE_SERVICE_ROLE_KEY': values['SERVICE_ROLE_KEY'],
        'DATABASE_URL': f'postgresql://app_authorizer:{quote(password, safe="")}@db:5432/{values["POSTGRES_DB"]}',
        'ADMIN_USER_IDS': ','.join(ids),
    })
    print('初始化完成：demoapp/.env 已生成（权限 0600，密钥不显示）。')


if __name__ == '__main__':
    try:
        initialize()
    except (ValueError, subprocess.CalledProcessError) as error:
        raise SystemExit(f'初始化失败：{error}')
