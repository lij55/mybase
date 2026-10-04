"""Explicitly create the first Auth user. Does not grant apps or modify .env."""
import getpass
import json
import sys
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import manage


def main():
    values = manage.effective_env(manage.read_env(ROOT / '.env'))
    email = input('初始管理员邮箱：').strip()
    password = getpass.getpass('初始密码（至少 12 字符）：')
    if '@' not in email or not 12 <= len(password) <= 128:
        raise SystemExit('邮箱无效或密码长度不符合要求')
    if password != getpass.getpass('再次输入密码：'):
        raise SystemExit('两次密码不同')
    key = values['SERVICE_ROLE_KEY']
    if not key:
        raise SystemExit('请先在仓库根目录执行 make init')
    url = f"http://127.0.0.1:{values['PUBLIC_API_PORT']}/auth/v1/admin/users"
    request = Request(url, method='POST',
                      headers={'apikey': key, 'Authorization': 'Bearer ' + key, 'Content-Type': 'application/json'},
                      data=json.dumps({'email': email, 'password': password, 'email_confirm': True}).encode())
    try:
        with urlopen(request, timeout=15) as response:
            result = json.load(response)
    except HTTPError as error:
        raise SystemExit(f'创建失败（HTTP {error.code}），请检查重复邮箱和 Auth 密码要求')
    except URLError:
        raise SystemExit('无法连接本机 Supabase，请先 make up')
    user = result.get('user', result)
    print('已创建账号；将以下 UUID 填入 demoapp/.env 的 ADMIN_USER_IDS：')
    print(user['id'])


if __name__ == '__main__':
    main()
