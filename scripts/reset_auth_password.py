#!/usr/bin/env python3
"""Reset an existing Supabase Auth user's password through the local admin API."""
import argparse
import getpass
import json
import sys
import uuid
import warnings
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import ProxyHandler, Request, build_opener

import manage


def reset_password(values, user_id, password):
    """Use the server secret key; send only the requested password update."""
    try:
        user_id = str(uuid.UUID(user_id))
    except (ValueError, AttributeError):
        raise ValueError('用户 UUID 格式无效') from None
    if not 12 <= len(password) <= 128:
        raise ValueError('密码长度须为 12–128 个字符')
    key = values.get('SUPABASE_SECRET_KEY')
    if not key:
        raise ValueError('缺少 SUPABASE_SECRET_KEY，请检查根目录 .env')
    port = int(values['PUBLIC_API_PORT'])
    if not 1 <= port <= 65535:
        raise ValueError('PUBLIC_API_PORT 无效')
    url = f'http://127.0.0.1:{port}/auth/v1/admin/users/{user_id}'
    request = Request(url, method='PUT',
                      headers={'apikey': key, 'Authorization': 'Bearer ' + key,
                               'Content-Type': 'application/json'},
                      data=json.dumps({'password': password}).encode())
    # Local admin credentials must not be sent through environment HTTP proxies.
    try:
        with build_opener(ProxyHandler({})).open(request, timeout=15) as response:
            response.read()
    except HTTPError as error:
        messages = {401: '管理密钥无效', 403: '管理权限不足', 404: '用户不存在',
                    422: '密码不符合 Auth 要求或与旧密码相同'}
        raise ValueError(f'重置失败（HTTP {error.code}）：' + messages.get(error.code, '请检查用户 UUID、Auth 密码要求和服务状态')) from None
    except (URLError, TimeoutError, OSError):
        raise ValueError('无法连接本机 Supabase，请检查服务状态（make ps / make up）') from None


def main(argv=None):
    parser = argparse.ArgumentParser(description='管理员重置 Supabase Auth 用户密码，无需旧密码或 SMTP')
    parser.add_argument('user_id', help='用户 UUID，可在 Studio → Authentication → Users 中查看')
    parser.add_argument('--env-file', type=Path, default=manage.ROOT / '.env', help='配置文件路径，默认仓库根目录 .env')
    args = parser.parse_args(argv)
    try:
        # Fail before prompting if the user ID or configuration is invalid.
        user_id = str(uuid.UUID(args.user_id))
        if not args.env_file.is_file():
            raise ValueError(f'配置文件不存在：{args.env_file}')
        values = manage.effective_env(manage.read_env(args.env_file))
        if not values.get('SUPABASE_SECRET_KEY'):
            raise ValueError('缺少 SUPABASE_SECRET_KEY，请检查 .env')
        with warnings.catch_warnings():
            warnings.simplefilter('error', getpass.GetPassWarning)
            password = getpass.getpass('新密码（12–128 个字符）：')
            confirmation = getpass.getpass('再次输入新密码：')
        if password != confirmation:
            raise ValueError('两次密码不同，未修改密码')
        reset_password(values, user_id, password)
    except getpass.GetPassWarning:
        print('失败：无法隐藏密码输入，请在交互终端运行', file=sys.stderr)
        return 1
    except (ValueError, OSError) as error:
        print(f'失败：{error}', file=sys.stderr)
        return 1
    except (EOFError, KeyboardInterrupt):
        print('\n已取消，未确认密码重置结果', file=sys.stderr)
        return 1
    print(f'已重置 Auth 用户 {user_id} 的密码；用户 UUID 和应用授权保持不变。')
    return 0


if __name__ == '__main__':
    sys.exit(main())
