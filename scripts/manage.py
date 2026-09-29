#!/usr/bin/env python3
"""Small, dependency-free deployment wrapper. Never executes .env as shell code."""
import argparse
import base64
import hashlib
import hmac
import json
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
SECRET_BYTES = {
    'POSTGRES_PASSWORD': 24, 'JWT_SECRET': 32, 'DASHBOARD_PASSWORD': 24,
    'SECRET_KEY_BASE': 48, 'REALTIME_DB_ENC_KEY': 8, 'VAULT_ENC_KEY': 16,
    'PG_META_CRYPTO_KEY': 32, 'LOGFLARE_PUBLIC_ACCESS_TOKEN': 32,
    'LOGFLARE_PRIVATE_ACCESS_TOKEN': 32, 'S3_PROTOCOL_ACCESS_KEY_ID': 16,
    'S3_PROTOCOL_ACCESS_KEY_SECRET': 32, 'MINIO_ROOT_PASSWORD': 24,
}


def read_env(path):
    values = {}
    for number, line in enumerate(path.read_text().splitlines(), 1):
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        if not re.match(r'^[A-Z][A-Z0-9_]*=', line):
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


def b64(data):
    return base64.urlsafe_b64encode(data).decode().rstrip('=')


def jwt(secret, role):
    now = int(time.time())
    payload = {'role': role, 'iss': 'supabase', 'iat': now, 'exp': now + 5 * 365 * 86400}
    content = b64(b'{"alg":"HS256","typ":"JWT"}') + '.' + b64(json.dumps(payload).encode())
    return content + '.' + b64(hmac.new(secret.encode(), content.encode(), hashlib.sha256).digest())


def init(root=ROOT):
    path = root / '.env'
    if not path.exists():
        if (root / 'volumes/db/data/PG_VERSION').exists():
            raise ValueError('检测到已有数据库但 .env 丢失，请恢复原密钥，禁止自动重建')
        with open(path, 'x', opener=lambda p, f: os.open(p, f, 0o600)) as handle:
            handle.write((root / '.env.example').read_text())
    values = read_env(path)
    missing = [k for k in [*SECRET_BYTES, 'ANON_KEY', 'SERVICE_ROLE_KEY'] if not values.get(k)]
    if missing and (root / 'volumes/db/data/PG_VERSION').exists():
        raise ValueError('已有数据库缺少密钥，请恢复原 .env，不要生成替换密钥')
    new = {k: secrets.token_hex(SECRET_BYTES[k]) for k in missing if k in SECRET_BYTES}
    secret = new.get('JWT_SECRET', values.get('JWT_SECRET'))
    for k, role in [('ANON_KEY', 'anon'), ('SERVICE_ROLE_KEY', 'service_role')]:
        if k in missing:
            new[k] = jwt(secret, role)
    text = path.read_text()
    for k, v in new.items():
        if k in values:
            text = re.sub(r'^' + k + r'=.*$', k + '=' + v, text, flags=re.M)
        else:
            text += f'\n{k}={v}\n'
    if new:
        tmp = path.with_suffix('.env.partial')
        with open(tmp, 'w', opener=lambda p, f: os.open(p, f, 0o600)) as handle:
            handle.write(text)
        tmp.replace(path)
    path.chmod(0o600)
    print('配置已就绪：.env（密钥不显示，已有非空值不覆盖）')
    return read_env(path)


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
    for k, role in [('ANON_KEY', 'anon'), ('SERVICE_ROLE_KEY', 'service_role')]:
        try:
            header, payload, signature = v[k].split('.')
            expected = b64(hmac.new(v['JWT_SECRET'].encode(), f'{header}.{payload}'.encode(), hashlib.sha256).digest())
            data = json.loads(base64.urlsafe_b64decode(payload + '=' * (-len(payload) % 4)))
            assert hmac.compare_digest(signature, expected)
            assert data['role'] == role and data['exp'] > time.time()
        except (ValueError, KeyError, AssertionError):
            raise ValueError(f'{k} 签名、角色或有效期错误，必须与 JWT_SECRET 配套') from None
    for k in ['JWT_JWKS', 'JWT_KEYS', 'SUPABASE_PUBLISHABLE_KEY', 'SUPABASE_SECRET_KEY', 'ANON_KEY_ASYMMETRIC', 'SERVICE_ROLE_KEY_ASYMMETRIC']:
        if v.get(k):
            raise ValueError(f'{k}: 此封装使用上游兼容的 HS256 模式；迁移 ES256 需一起更新各服务配置')
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
    for k in ['TUNNEL_ENABLED', 'DISABLE_SIGNUP', 'ENABLE_EMAIL_AUTOCONFIRM', 'FUNCTIONS_VERIFY_JWT']:
        if v.get(k) not in ('true', 'false'):
            raise ValueError(f'{k} 必须为 true 或 false')
    if v['TUNNEL_ENABLED'] == 'true':
        if not v.get('TUNNEL_TOKEN'):
            raise ValueError('启用 Tunnel 前必须填写 TUNNEL_TOKEN')
        if any(urlparse(v[k]).scheme != 'https' or urlparse(v[k]).hostname in ('localhost', '127.0.0.1') for k in ['SUPABASE_PUBLIC_URL', 'SITE_URL']):
            raise ValueError('启用 Tunnel 必须配置公网 HTTPS API 和前端 URL')
        if v['ENABLE_EMAIL_AUTOCONFIRM'] == 'true' or v.get('ENABLE_PHONE_AUTOCONFIRM') == 'true':
            raise ValueError('公网模式禁止自动确认邮箱/手机号')
        if v['FUNCTIONS_VERIFY_JWT'] != 'true':
            raise ValueError('公网模式必须启用 Functions JWT 校验')
        if v['DISABLE_SIGNUP'] == 'false' and not v.get('SMTP_HOST'):
            raise ValueError('公网开放注册前必须配置可用的 SMTP_HOST')
    if v.get('TUNNEL_TRANSPORT_PROTOCOL') not in ('auto', 'http2', 'quic'):
        raise ValueError('TUNNEL_TRANSPORT_PROTOCOL 必须为 auto/http2/quic')


def compose(v, args, **kwargs):
    # .env is authoritative; prevent exported shell variables overriding it.
    env = {k: value for k, value in os.environ.items() if k not in v and not k.startswith('COMPOSE_')}
    cmd = ['docker', 'compose', '--project-directory', str(ROOT), '--env-file', str(ROOT / '.env'),
           '-p', v['COMPOSE_PROJECT_NAME'], '-f', str(ROOT / 'docker-compose.yml'), '-f', str(ROOT / 'compose.override.yml'), '--profile', 'tunnel']
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
        expect(base + path, [200], {'apikey': v['ANON_KEY'], 'Authorization': 'Bearer ' + v['ANON_KEY']})
    expect(base + '/rest/v1/', [200], {'apikey': v['SERVICE_ROLE_KEY']})
    expect(base + '/rest/v1/', [401, 403])
    for path in ['/', '/pg/', '/api/platform/profile', '/mcp', '/realtime/v1/api/tenants', '/auth/v1/%2e%2e/%2e%2e/pg/']:
        expect(base + path, [404])
    expect(f"http://127.0.0.1:{v['STUDIO_PORT']}/", [401])
    print('冒烟通过：Auth、REST、未认证拒绝、管理路径隔离、Studio Basic Auth')


def backup(v):
    cfg = config(v)
    services = compose(v, ['ps', '--status', 'running', '--services'], capture_output=True, text=True).stdout.split()
    folder = ROOT / 'backups'
    folder.mkdir(mode=0o700, exist_ok=True)
    folder.chmod(0o700)
    stamp = time.strftime('%Y%m%d-%H%M%S')
    target = folder / f'mybase-{stamp}.tar.gz'
    partial = target.with_suffix('.gz.partial')
    volume = cfg['volumes']['db-config']['name']
    image = cfg['services']['db']['image']
    print('停止写入及数据库以创建一致性冷备份；完成/失败后恢复原运行服务。', flush=True)
    try:
        compose(v, ['stop', '-t', '60'])
        with open(partial, 'xb', opener=lambda p, f: os.open(p, f, 0o600)) as handle:
            subprocess.run(['docker', 'run', '--rm', '--network', 'none', '--user', '0',
                '--mount', f'type=bind,source={ROOT},target=/snapshot/project,readonly',
                '--mount', f'type=volume,source={volume},target=/snapshot/db-config,readonly',
                '--entrypoint', 'tar', image, '-czf', '-', '--exclude=project/backups',
                '--exclude=project/.git', '--exclude=project/.agents', '--exclude=project/.codex',
                '--exclude=__pycache__', '-C', '/snapshot', 'project', 'db-config'], stdout=handle, check=True)
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
        v = read_env(ROOT / '.env')
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
        services = [s for s in cfg['services'] if s != 'cloudflared' or v['TUNNEL_ENABLED'] == 'true']
        if args.action != 'pull' and v['TUNNEL_ENABLED'] != 'true':
            compose(v, ['stop', 'cloudflared'])
        compose(v, ['pull', *services] if args.action == 'pull' else ['up', '-d', '--wait', '--wait-timeout', v['UP_TIMEOUT'], *services])
        if args.action != 'pull':
            smoke(v)
            print(f"Studio: http://localhost:{v['STUDIO_PORT']}  API: {v['SUPABASE_PUBLIC_URL']}")
            if v['TUNNEL_ENABLED'] == 'true':
                print('Tunnel 进程已启动；需在 Cloudflare 控制台另行核验 Healthy 和公网路由。')
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
