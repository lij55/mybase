"""Small same-origin demo backend. Business requests always retain the user's JWT."""
import json
import os
import re
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlsplit
from urllib.request import Request, urlopen


class Problem(Exception):
    def __init__(self, status, message):
        self.status, self.message = status, message


def valid_uuid(value):
    try:
        return str(uuid.UUID(str(value)))
    except (ValueError, TypeError, AttributeError):
        raise Problem(400, '无效的用户或记录 ID')


def app_name(value):
    return isinstance(value, str) and bool(re.fullmatch(r'app_[a-z][a-z0-9_]{0,58}', value)) and value != 'app_access'


class Application:
    def __init__(self):
        self.kind = os.environ['APP_KIND']
        if self.kind not in {'admin', 'todo', 'notes'}:
            raise ValueError('Unknown APP_KIND')
        self.url = os.environ['SUPABASE_URL'].rstrip('/')
        self.anon = os.environ['SUPABASE_ANON_KEY']
        if self.kind == 'admin':
            self.service = os.environ['SUPABASE_SERVICE_ROLE_KEY']
            self.dsn = os.environ['DATABASE_URL']
            self.admins = {valid_uuid(x.strip()) for x in os.environ['ADMIN_USER_IDS'].split(',') if x.strip()}
            if not self.admins:
                raise ValueError('ADMIN_USER_IDS must contain at least one Auth UUID')
        else:
            self.schema = os.environ.get('APP_SCHEMA', 'app_todo' if self.kind == 'todo' else 'app_notes')
            if not app_name(self.schema):
                raise ValueError('Invalid APP_SCHEMA')
            self.table = 'todos' if self.kind == 'todo' else 'notes'

    def upstream(self, path, method='GET', body=None, token=None, admin=False, headers=None):
        key = self.service if admin else self.anon
        request_headers = {'apikey': key, 'Authorization': 'Bearer ' + (key if admin else token or key),
                           'Content-Type': 'application/json', **(headers or {})}
        request = Request(self.url + path, data=json.dumps(body).encode() if body is not None else None,
                          method=method, headers=request_headers)
        try:
            with urlopen(request, timeout=15) as response:
                raw = response.read()
                return json.loads(raw) if raw else None
        except HTTPError as error:
            try:
                details = json.loads(error.read())
                message = details.get('msg') or details.get('message') or details.get('error_description') or '请求失败'
            except (ValueError, AttributeError):
                message = '上游请求失败'
            # Never relay an upstream gateway/configuration error containing server details.
            if error.code >= 500:
                raise Problem(502, 'Supabase 暂时不可用')
            raise Problem(error.code, str(message))
        except (URLError, TimeoutError):
            raise Problem(502, '无法连接 Supabase')

    def connection(self):
        import psycopg
        from psycopg.rows import dict_row
        return psycopg.connect(self.dsn, connect_timeout=5, row_factory=dict_row,
                               options='-c statement_timeout=5000')

    @staticmethod
    def discover(connection):
        return connection.execute("""
            select nspname as id,
                   coalesce(nullif(obj_description(oid, 'pg_namespace'), ''), nspname) as name
            from pg_namespace
            where nspname ~ '^app_[a-z][a-z0-9_]{0,58}$' and nspname <> 'app_access'
            order by nspname
        """).fetchall()

    def dispatch(self, method, path, query, body, token):
        if method == 'POST' and path in {'/api/login', '/api/refresh'}:
            if path == '/api/login':
                if not isinstance(body.get('email'), str) or not isinstance(body.get('password'), str):
                    raise Problem(400, '请输入邮箱与密码')
                payload = {k: body[k] for k in ('email', 'password')}
                return self.upstream('/auth/v1/token?grant_type=password', 'POST', payload)
            if not isinstance(body.get('refresh_token'), str):
                raise Problem(400, '缺少刷新凭据')
            return self.upstream('/auth/v1/token?grant_type=refresh_token', 'POST', {'refresh_token': body['refresh_token']})

        if not token:
            raise Problem(401, '请先登录')
        user = self.upstream('/auth/v1/user', token=token)
        user_id = valid_uuid(user.get('id'))
        if self.kind == 'admin' and user_id not in self.admins:
            raise Problem(403, '此账号没有授权后台管理权限')
        if method == 'GET' and path == '/api/me':
            return {'id': user_id, 'email': user.get('email'), 'kind': self.kind}
        if method == 'POST' and path == '/api/logout':
            self.upstream('/auth/v1/logout?scope=local', 'POST', token=token)
            return {'ok': True}
        if self.kind == 'admin':
            return self.admin_request(method, path, query, body)
        return self.business_request(method, path, body, token)

    def admin_request(self, method, path, query, body):
        if method == 'GET' and path == '/api/users':
            try:
                page = int(query.get('page', ['1'])[0])
            except ValueError:
                raise Problem(400, '页码无效')
            if not 1 <= page <= 100000:
                raise Problem(400, '页码无效')
            result = self.upstream(f'/auth/v1/admin/users?page={page}&per_page=50', admin=True)
            return {'users': [{'id': u['id'], 'email': u.get('email'), 'created_at': u.get('created_at')}
                              for u in result['users']], 'page': page}
        if method == 'POST' and path == '/api/users':
            email, password = body.get('email'), body.get('password')
            if not isinstance(email, str) or '@' not in email or len(email) > 254:
                raise Problem(400, '请输入有效邮箱')
            if not isinstance(password, str) or not 12 <= len(password) <= 128:
                raise Problem(400, '密码长度须为 12–128 个字符')
            result = self.upstream('/auth/v1/admin/users', 'POST',
                                   {'email': email.strip(), 'password': password, 'email_confirm': True}, admin=True)
            user = result.get('user', result)
            return {'id': user['id'], 'email': user.get('email')}
        if method == 'GET' and path == '/api/apps':
            with self.connection() as connection:
                return {'apps': self.discover(connection)}
        if path == '/api/memberships' and method == 'GET':
            uid = valid_uuid(query.get('user_id', [''])[0])
            with self.connection() as connection:
                rows = connection.execute('select app_id from app_access.memberships where user_id = %s order by app_id',
                                          (uid,)).fetchall()
                return {'app_ids': [row['app_id'] for row in rows]}
        if path == '/api/memberships' and method in {'POST', 'DELETE'}:
            uid, app = valid_uuid(body.get('user_id')), body.get('app_id')
            if not app_name(app):
                raise Problem(400, '无效的应用 schema')
            with self.connection() as connection:
                if method == 'POST' and app not in {row['id'] for row in self.discover(connection)}:
                    raise Problem(404, '应用 schema 不存在，请刷新列表')
                if method == 'POST':
                    connection.execute('insert into app_access.memberships (app_id, user_id) values (%s, %s) on conflict do nothing',
                                       (app, uid))
                else:
                    # Allow cleanup of grants for an application whose schema was removed.
                    connection.execute('delete from app_access.memberships where app_id = %s and user_id = %s', (app, uid))
            return {'ok': True}
        raise Problem(404, '接口不存在')

    def business_request(self, method, path, body, token):
        profile = {'Accept-Profile': self.schema, 'Content-Profile': self.schema, 'Prefer': 'return=representation'}
        if method == 'GET' and path == '/api/items':
            return self.upstream(f'/rest/v1/{self.table}?select=*&order=created_at.desc&limit=500', token=token, headers=profile)
        if method == 'POST' and path == '/api/items':
            field, limit = ('title', 1000) if self.kind == 'todo' else ('content', 10000)
            value = body.get(field)
            if not isinstance(value, str) or not 1 <= len(value.strip()) <= limit:
                raise Problem(400, f'内容长度须为 1–{limit} 个字符')
            return self.upstream(f'/rest/v1/{self.table}', 'POST', {field: value.strip()}, token, headers=profile)
        match = re.fullmatch(r'/api/items/([^/]+)', path)
        if match and method in {'PATCH', 'DELETE'}:
            item = valid_uuid(match[1])
            payload = None
            if method == 'PATCH':
                if self.kind != 'todo' or type(body.get('done')) is not bool:
                    raise Problem(400, '无效的完成状态')
                payload = {'done': body['done']}
            result = self.upstream(f'/rest/v1/{self.table}?id=eq.{item}', method, payload, token, headers=profile)
            if not result:
                raise Problem(404, '记录不存在或没有操作权限')
            return result
        raise Problem(404, '接口不存在')


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        # Request bodies, tokens, query strings and user identities are not logged.
        print(f'{self.command} {self.path.split("?")[0]} {args[1] if len(args) > 1 else ""}', flush=True)

    def send(self, status, payload, content_type='application/json; charset=utf-8'):
        data = json.dumps(payload, ensure_ascii=False).encode() if content_type.startswith('application/json') else payload
        self.send_response(status)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(data)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Referrer-Policy', 'no-referrer')
        self.send_header('Content-Security-Policy', "default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; object-src 'none'; frame-ancestors 'none'; base-uri 'none'")
        self.end_headers()
        self.wfile.write(data)

    def handle_request(self):
        path = urlsplit(self.path)
        try:
            if self.command == 'GET' and path.path == '/healthz':
                return self.send(200, {'ok': True})
            if not path.path.startswith('/api/'):
                assets = {'/': ('index.html', 'text/html; charset=utf-8'),
                          '/app.js': ('app.js', 'text/javascript; charset=utf-8'),
                          '/common.js': ('common.js', 'text/javascript; charset=utf-8'),
                          '/style.css': ('style.css', 'text/css; charset=utf-8')}
                if self.command != 'GET' or path.path not in assets:
                    raise Problem(404, '页面不存在')
                file, mime = assets[path.path]
                root = Path(os.environ.get('STATIC_DIR', '/app/static'))
                return self.send(200, (root / file).read_bytes(), mime)
            body = {}
            if self.command != 'GET':
                origin = urlsplit(self.headers.get('Origin', ''))
                if origin.scheme not in {'http', 'https'} or origin.netloc != self.headers.get('Host'):
                    raise Problem(403, '仅接受当前站点发起的操作')
                if self.headers.get('Content-Type', '').split(';')[0] != 'application/json':
                    raise Problem(415, '需要 JSON 请求')
                try:
                    length = int(self.headers.get('Content-Length', '0'))
                    if not 0 < length <= 32768:
                        raise Problem(413, '请求体过大或为空')
                    body = json.loads(self.rfile.read(length))
                except (ValueError, UnicodeError):
                    raise Problem(400, 'JSON 请求无效')
                if not isinstance(body, dict):
                    raise Problem(400, 'JSON 必须是对象')
            auth = self.headers.get('Authorization', '')
            token = auth[7:] if auth.startswith('Bearer ') else None
            result = self.server.application.dispatch(self.command, path.path, parse_qs(path.query), body, token)
            self.send(200, result)
        except Problem as error:
            self.send(error.status, {'error': error.message})
        except Exception as error:
            # Database details/DSN must not be returned to the browser or logged.
            print(f'Request failed: {type(error).__name__}', flush=True)
            self.send(500, {'error': '服务配置或数据库操作失败，请检查 SQL 初始化与服务日志'})

    do_GET = do_POST = do_PATCH = do_DELETE = handle_request


if __name__ == '__main__':
    application = Application()
    server = ThreadingHTTPServer(('0.0.0.0', int(os.environ.get('PORT', '8080'))), Handler)
    server.application = application
    server.serve_forever()
