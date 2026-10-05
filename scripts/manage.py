#!/usr/bin/env python3
"""Small deployment wrapper; uses Python and OpenSSL for ES256 keys. Never executes .env as shell code."""
import argparse
import auth_keys as auth_credentials
import hashlib
import json
import ipaddress
import os
from pathlib import Path
import re
import secrets
import subprocess
import sys
import time
import urllib.error
import urllib.request
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
SECRET_BYTES = {'POSTGRES_PASSWORD': 24,
 'JWT_SECRET': 32,
 'DASHBOARD_PASSWORD': 24,
 'SECRET_KEY_BASE': 48,
 'REALTIME_DB_ENC_KEY': 8,
 'VAULT_ENC_KEY': 16,
 'PG_META_CRYPTO_KEY': 32,
 'S3_PROTOCOL_ACCESS_KEY_ID': 16,
 'S3_PROTOCOL_ACCESS_KEY_SECRET': 32}

# Runtime defaults are kept out of the generated user configuration.
DEFAULTS = {'SUPABASE_PUBLISHABLE_KEY': '',
 'SUPABASE_SECRET_KEY': '',
 'JWT_KEYS': '',
 'JWT_JWKS': '',
 'DASHBOARD_USERNAME': 'supabase',
 'POSTGRES_HOST': 'db',
 'POSTGRES_DB': 'postgres',
 'POSTGRES_PORT': '5432',
 'POOLER_PROXY_PORT_TRANSACTION': '6543',
 'POOLER_DEFAULT_POOL_SIZE': '20',
 'POOLER_MAX_CLIENT_CONN': '100',
 'POOLER_TENANT_ID': 'mybase',
 'POOLER_DB_POOL_SIZE': '5',
 'STUDIO_DEFAULT_ORGANIZATION': 'Default Organization',
 'STUDIO_DEFAULT_PROJECT': 'Default Project',
 'OPENAI_API_KEY': '',
 'SITE_URL': 'https://my.supabase.local',
 'ADDITIONAL_REDIRECT_URLS': '',
 'JWT_EXPIRY': '3600',
 'DISABLE_SIGNUP': 'true',
 'MAILER_URLPATHS_CONFIRMATION': '/auth/v1/verify',
 'MAILER_URLPATHS_INVITE': '/auth/v1/verify',
 'MAILER_URLPATHS_RECOVERY': '/auth/v1/verify',
 'MAILER_URLPATHS_EMAIL_CHANGE': '/auth/v1/verify',
 'ENABLE_EMAIL_SIGNUP': 'true',
 'ENABLE_EMAIL_AUTOCONFIRM': 'false',
 'SMTP_ADMIN_EMAIL': 'admin@example.com',
 'SMTP_HOST': '',
 'SMTP_PORT': '587',
 'SMTP_USER': '',
 'SMTP_PASS': '',
 'SMTP_SENDER_NAME': 'Mybase',
 'ENABLE_ANONYMOUS_USERS': 'false',
 'ENABLE_PHONE_SIGNUP': 'false',
 'ENABLE_PHONE_AUTOCONFIRM': 'false',
 'GLOBAL_S3_BUCKET': 'stub',
 'REGION': 'stub',
 'STORAGE_TENANT_ID': 'stub',
 'FUNCTIONS_VERIFY_JWT': 'true',
 'PGRST_DB_SCHEMAS': 'public,graphql_public',
 'PGRST_DB_MAX_ROWS': '1000',
 'PGRST_DB_EXTRA_SEARCH_PATH': 'public',
 'API_GW_HTTP_PORT': '8000',
 'KONG_HTTP_PORT': '8000',
 'KONG_HTTPS_PORT': '8443',
 'ANON_KEY_ASYMMETRIC': '',
 'SERVICE_ROLE_KEY_ASYMMETRIC': '',
 'IMGPROXY_AUTO_WEBP': 'true',
 'COMPOSE_PROJECT_NAME': 'mybase',
 'PUBLIC_API_PORT': '8000',
 'STUDIO_PORT': '8001',
 'DB_SESSION_PORT': '5432',
 'DB_TRANSACTION_PORT': '6543',
 'UP_TIMEOUT': '300',
 'STORAGE_FILE_SIZE_LIMIT': '52428800',
 'CADDY_PORT': '8080',
 'CADDY_BIND': '127.0.0.1',
 'PUBLIC_HOST': 'my.supabase.local'}

def effective_env(values):
    result = {**DEFAULTS, **values}
    host = result['PUBLIC_HOST']
    if not re.fullmatch(r'[a-zA-Z0-9]+(?:[.-][a-zA-Z0-9]+)*', host):
        raise ValueError('PUBLIC_HOST 必须是域名，不带协议、端口或路径')
    # Existing deployments without PUBLIC_HOST keep their explicit URLs.
    if 'PUBLIC_HOST' in values or not values.get('SUPABASE_PUBLIC_URL'):
        result['SUPABASE_PUBLIC_URL'] = f'https://api.{host}'
        result['API_EXTERNAL_URL'] = result['SUPABASE_PUBLIC_URL'] + '/auth/v1'
    if not values.get('SITE_URL'):
        result['SITE_URL'] = f'https://{host}'
    result['CADDY_API_HOST'] = f'api.{host}'
    result['CADDY_ADMIN_HOST'] = f'admin.{host}'
    return result



def read_env(path):
    values = {}
    for number, line in enumerate(path.read_text().splitlines(), 1):
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        if not re.match(r'^[A-Za-z][A-Za-z0-9_]*=', line):
            raise ValueError(f'.env 第 {number} 行必须为 KEY=value')
        key, value = line.split('=', 1)
        value = value.strip()
        if key in values:
            raise ValueError(f'.env 重复变量：{key}')
        if value.startswith("'") and value.endswith("'"):
            value = value[1:-1]
            if "'" in value or '\\' in value:
                raise ValueError(f'{key}: 单引号值不支持嵌套引号或反斜线')
        elif value.startswith('"') and value.endswith('"'):
            value = value[1:-1]
            if any(c in value for c in '$\\"'):
                raise ValueError(f'{key}: 特殊字符请使用单引号字面值')
        elif any(c in value for c in '$#\'"\\'):
            raise ValueError(f'{key}: 特殊字符请使用单引号字面值')
        values[key] = value
    return values


AUTH_FIELDS = ('SUPABASE_PUBLISHABLE_KEY', 'SUPABASE_SECRET_KEY',
               'ANON_KEY_ASYMMETRIC', 'SERVICE_ROLE_KEY_ASYMMETRIC', 'JWT_KEYS', 'JWT_JWKS')


def auth_keys(action, values=None):
    if action == 'generate':
        return auth_credentials.generate()
    if action == 'validate':
        return auth_credentials.validate(values or {})
    raise ValueError(f'未知密钥操作：{action}')


def init_caddy(root, values):
    path = root / 'caddy/Caddyfile'
    values = effective_env(values)
    bind = str(ipaddress.IPv4Address(values['CADDY_BIND']))
    api = values['CADDY_API_HOST']
    admin = values['CADDY_ADMIN_HOST']
    for host in (api, admin):
        if not re.fullmatch(r'[a-zA-Z0-9]+(?:[.-][a-zA-Z0-9]+)*', host):
            raise ValueError('CADDY_API_HOST / CADDY_ADMIN_HOST 必须是域名，不带协议、端口或路径')
    if api.lower() == admin.lower():
        raise ValueError('Caddy API 与管理域名必须不同')
    ports = [int(values.get(k, default)) for k, default in
             [('CADDY_PORT', '8080'), ('PUBLIC_API_PORT', '8000'), ('STUDIO_PORT', '8001')]]
    if len(set(ports)) != 3 or any(p < 1024 or p > 65535 for p in ports):
        raise ValueError('Caddy/API/Studio 端口必须不同且位于 1024..65535')
    template = (root / 'caddy/Caddyfile.example').read_text()
    if path.exists():
        # Refresh only files that still exactly match our generated layout.
        pattern = re.escape(template)
        for key in ('CADDY_API_HOST', 'CADDY_ADMIN_HOST', 'CADDY_PORT', 'PUBLIC_API_PORT', 'STUDIO_PORT'):
            pattern = pattern.replace(re.escape('@@' + key + '@@'), r'[a-zA-Z0-9.-]+' if 'HOST' in key else r'[0-9]+')
        pattern = pattern.replace(re.escape('@@CADDY_BIND@@'), r'[0-9.]+')
        existing = path.read_text().replace('existing caddy/Caddyfile is never overwritten.',
                                            'unmodified generated files are refreshed; custom files are preserved.')
        # Upgrade the previous generated 404 fallback while preserving custom files.
        existing = existing.replace(
            '\t# Unknown hosts must never fall through to Studio.\n\thandle {\n\t\trespond "Not found" 404\n\t}',
            '\t# All other hosts go to the demo Traefik entrypoint; preserve Host routing.\n\thandle {\n\t\treverse_proxy 127.0.0.1:8090\n\t}')
        if not re.fullmatch(pattern, existing):
            return
    template = template.replace('@@CADDY_BIND@@', bind)
    for key, value in zip(('CADDY_API_HOST', 'CADDY_ADMIN_HOST', 'CADDY_PORT', 'PUBLIC_API_PORT', 'STUDIO_PORT'),
                          (api, admin, *ports)):
        template = template.replace('@@' + key + '@@', str(value))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(template)


def init(root=ROOT):
    path = root / '.env'
    if not path.exists():
        if (root / 'volumes/db/data/PG_VERSION').exists():
            raise ValueError('检测到已有数据库但 .env 丢失，请恢复原密钥，禁止自动重建')
        with open(path, 'x', opener=lambda p, f: os.open(p, f, 0o600)) as handle:
            handle.write((root / '.env.example').read_text())
    values = read_env(path)
    missing = [k for k in [*SECRET_BYTES, *AUTH_FIELDS] if not values.get(k)]
    if missing and (root / 'volumes/db/data/PG_VERSION').exists():
        raise ValueError('已有数据库缺少密钥，请恢复原 .env，不要生成替换密钥')
    new = {k: secrets.token_hex(SECRET_BYTES[k]) for k in missing if k in SECRET_BYTES}
    absent = [k for k in AUTH_FIELDS if not values.get(k)]
    if absent:
        if len(absent) != len(AUTH_FIELDS):
            raise ValueError('新密钥配置不完整，请恢复完整密钥组；不会自动替换部分密钥')
        new.update(auth_keys('generate'))
    text = path.read_text()
    for k, v in new.items():
        literal = "'" + v + "'" if k in ('JWT_KEYS', 'JWT_JWKS') else v
        line = k + '=' + literal
        if k in values:
            text = re.sub(r'^' + k + r'=.*$', lambda _: line, text, flags=re.M)
        else:
            text += '\n' + line + '\n'
    if new:
        tmp = path.with_suffix('.env.partial')
        with open(tmp, 'w', opener=lambda p, f: os.open(p, f, 0o600)) as handle:
            handle.write(text)
        tmp.replace(path)
    path.chmod(0o600)
    print('配置已就绪：.env（密钥不显示，已有非空值不覆盖）')
    values = read_env(path)
    init_caddy(root, values)
    print('Caddy 配置已就绪：caddy/Caddyfile（自动同步生成配置，手工修改的文件保留）')
    return effective_env(values)


def validate(v):
    for k, length in SECRET_BYTES.items():
        if len(v.get(k, '')) < length * 2 or v[k].startswith(('your-', 'this_')):
            raise ValueError(f'{k} 缺失或过短；请使用 make init 生成的值')
    for k, length in [('REALTIME_DB_ENC_KEY', 16), ('VAULT_ENC_KEY', 32)]:
        if len(v[k]) != length:
            raise ValueError(f'{k} 必须为 {length} 字符')
    for k in ['POSTGRES_PASSWORD', 'DASHBOARD_PASSWORD', 'DASHBOARD_USERNAME']:
        if not re.fullmatch('[A-Za-z0-9_-]+', v.get(k, '')):
            raise ValueError(f'{k} 仅支持字母数字下划线和连字符，避免 URI/模板转义错误')
    auth_keys('validate', v)
    if v.get('POSTGRES_PORT') != '5432' or v.get('POSTGRES_HOST') != 'db' or v.get('POSTGRES_DB') != 'postgres':
        raise ValueError('内部数据库固定为 db:5432/postgres；宿主机改用 DB_SESSION_PORT')
    if not re.fullmatch('[a-z0-9][a-z0-9_-]*', v.get('COMPOSE_PROJECT_NAME', '')):
        raise ValueError('COMPOSE_PROJECT_NAME 格式不正确')
    for k in ['SUPABASE_PUBLIC_URL', 'API_EXTERNAL_URL', 'SITE_URL']:
        u = urlparse(v.get(k, ''))
        if u.scheme not in ('http', 'https') or not u.hostname or u.query or u.fragment or any(c in v[k] for c in '|&\\'):
            raise ValueError(f'{k} 必须是完整、无 query/fragment 的 HTTP(S) URL')
    if v['API_EXTERNAL_URL'] != v['SUPABASE_PUBLIC_URL'].rstrip('/') + '/auth/v1':
        raise ValueError('API_EXTERNAL_URL 必须为 SUPABASE_PUBLIC_URL + /auth/v1（本版本要求）')
    ports = [int(v[k]) for k in ['PUBLIC_API_PORT', 'STUDIO_PORT', 'DB_SESSION_PORT', 'DB_TRANSACTION_PORT']]
    if len(set(ports)) != len(ports) or any(p < 1024 or p > 65535 for p in ports):
        raise ValueError('四个宿主机端口必须各不相同，且位于 1024..65535')
    for k in ['DISABLE_SIGNUP', 'ENABLE_EMAIL_AUTOCONFIRM', 'FUNCTIONS_VERIFY_JWT']:
        if v.get(k) not in ('true', 'false'):
            raise ValueError(f'{k} 必须为 true 或 false')
    if urlparse(v['SUPABASE_PUBLIC_URL']).hostname not in ('localhost', '127.0.0.1', '::1'):
        if any(urlparse(v[k]).scheme != 'https' for k in ['SUPABASE_PUBLIC_URL', 'SITE_URL']):
            raise ValueError('公网部署必须配置 HTTPS API 和前端 URL')
        if v['ENABLE_EMAIL_AUTOCONFIRM'] == 'true' or v.get('ENABLE_PHONE_AUTOCONFIRM') == 'true':
            raise ValueError('公网模式禁止自动确认邮箱/手机号')
        if v['FUNCTIONS_VERIFY_JWT'] != 'true':
            raise ValueError('公网模式必须启用 Functions JWT 校验')
        if v['DISABLE_SIGNUP'] == 'false' and not v.get('SMTP_HOST'):
            raise ValueError('公网开放注册前必须配置可用的 SMTP_HOST')


def compose(v, args, **kwargs):
    # .env is authoritative; prevent exported shell variables overriding it.
    env = {k: value for k, value in os.environ.items() if k not in v and not k.startswith('COMPOSE_')}
    env.update(v)
    cmd = ['docker', 'compose', '--project-directory', str(ROOT), '--env-file', str(ROOT / '.env'),
           '-p', v['COMPOSE_PROJECT_NAME'], '-f', str(ROOT / 'docker-compose.yml'), '-f', str(ROOT / 'compose.override.yml')]
    return subprocess.run(cmd + args, env=env, check=True, **kwargs)


def config(v):
    data = compose(v, ['config', '--format', 'json'], capture_output=True)
    return json.loads(data.stdout)


def smoke(v):
    base = f"http://127.0.0.1:{v['PUBLIC_API_PORT']}"
    # Ignore machine-wide HTTP proxy for local health checks.
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    def expect(url, codes, headers=None):
        req = urllib.request.Request(url, headers=headers or {})
        try:
            with opener.open(req, timeout=15) as r:
                code = r.status
        except urllib.error.HTTPError as exc:
            code = exc.code
        if code not in codes:
            raise ValueError(f'{url}: 期望 {codes}，实际 {code}')
    for path in ['/healthz', '/auth/v1/health']:
        expect(base + path, [200], {'apikey': v['SUPABASE_PUBLISHABLE_KEY'], 'Authorization': 'Bearer ' + v['SUPABASE_PUBLISHABLE_KEY']})
    expect(base + '/rest/v1/', [200], {'apikey': v['SUPABASE_SECRET_KEY']})
    expect(base + '/rest/v1/', [401, 403])
    for path in ['/', '/pg/', '/api/platform/profile', '/mcp', '/realtime/v1/api/tenants', '/auth/v1/%2e%2e/%2e%2e/pg/']:
        expect(base + path, [404])
    expect(f"http://127.0.0.1:{v['STUDIO_PORT']}/", [401])
    # Native Realtime /healthcheck is liveness only. Check the public tenant's
    # WebSocket authentication separately using the new publishable key.
    from integration_support import WebSocket
    from types import SimpleNamespace
    try:
        ws = WebSocket(SimpleNamespace(values=v))
        ws.close()
    except (OSError, AssertionError) as exc:
        raise ValueError('Realtime WebSocket 握手或新 API key 校验失败') from exc
    print('冒烟通过：Auth、REST、Realtime WebSocket、未认证拒绝、管理路径隔离、Studio Basic Auth')


def backup(v):
    cfg = config(v)
    services = compose(v, ['ps', '--status', 'running', '--services'], capture_output=True, text=True).stdout.split()
    folder = ROOT / 'backups'
    folder.mkdir(mode=0o700, exist_ok=True)
    folder.chmod(0o700)
    stamp = time.strftime('%Y%m%d-%H%M%S')
    target = folder / f'mybase-{stamp}.tar.gz'
    partial = target.with_suffix('.gz.partial')
    archive_root = target.name[:-7]
    volume = cfg['volumes']['db-config']['name']
    image = cfg['services']['db']['image']
    print('停止写入及数据库以创建一致性冷备份；完成/失败后恢复原运行服务。', flush=True)
    try:
        compose(v, ['stop', '-t', '60'])
        with open(partial, 'xb', opener=lambda p, f: os.open(p, f, 0o600)) as handle:
            subprocess.run(['docker', 'run', '--rm', '--network', 'none', '--user', '0',
                '--mount', f'type=bind,source={ROOT},target=/snapshot/{archive_root}/project,readonly',
                '--mount', f'type=volume,source={volume},target=/snapshot/{archive_root}/db-config,readonly',
                '--mount', f'type=bind,source={ROOT / "scripts/restore.sh"},target=/snapshot/{archive_root}/restore.sh,readonly',
                '--entrypoint', 'tar', image, '-czf', '-', f'--exclude={archive_root}/project/backups',
                f'--exclude={archive_root}/project/.git', f'--exclude={archive_root}/project/.agents', f'--exclude={archive_root}/project/.codex',
                '--exclude=__pycache__', '-C', '/snapshot', archive_root], stdout=handle, check=True)
        partial.replace(target)
        with target.open('rb') as handle:
            digest = hashlib.file_digest(handle, 'sha256').hexdigest()
        target.with_suffix('.gz.sha256').write_text(f'{digest}  {target.name}\n')
        print(f'备份完成：{target}（含明文密钥，请加密并异地保存）')
    finally:
        if services:
            compose(v, ['start', *services])


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=['init', 'check', 'up', 'down', 'restart', 'ps', 'logs', 'pull', 'smoke', 'backup', 'psql'])
    parser.add_argument('--service')
    args = parser.parse_args()
    os.chdir(ROOT)
    if args.action in ('init', 'up', 'restart'):
        v = init()
    else:
        v = effective_env(read_env(ROOT / '.env'))
    if args.action == 'init':
        return
    # Permit stop/diagnostics even after an invalid manual edit.
    if args.action not in ('down', 'ps', 'logs'):
        validate(v)
    if args.action == 'check':
        config(v)
        print('变量和 Compose 校验通过（不输出密钥）')
    elif args.action in ('up', 'restart', 'pull'):
        cfg = config(v)
        services = list(cfg['services'])
        compose(v, ['pull', *services] if args.action == 'pull' else ['up', '-d', '--wait', '--wait-timeout', v['UP_TIMEOUT'], *services])
        if args.action != 'pull':
            smoke(v)
            print(f"Studio: http://localhost:{v['STUDIO_PORT']}  API: {v['SUPABASE_PUBLIC_URL']}")
    elif args.action == 'down':
        compose(v, ['down', '--remove-orphans'])
    elif args.action == 'ps':
        compose(v, ['ps', '-a'])
    elif args.action == 'logs':
        compose(v, ['logs', '--tail', '150'] + ([args.service] if args.service else []))
    elif args.action == 'smoke':
        smoke(v)
    elif args.action == 'backup':
        backup(v)
    elif args.action == 'psql':
        compose(v, ['exec', 'db', 'psql', '-U', 'postgres', '-d', 'postgres'])


if __name__ == '__main__':
    try:
        main()
    except (ValueError, OSError, subprocess.CalledProcessError, urllib.error.URLError) as exc:
        # Compose config failures may embed values: keep captured output private.
        print(f'失败：{exc if not isinstance(exc, subprocess.CalledProcessError) else "Docker 命令失败，请检查 make logs / Docker 状态"}', file=sys.stderr)
        sys.exit(1)
