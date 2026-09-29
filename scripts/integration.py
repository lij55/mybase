#!/usr/bin/env python3
"""Opt-in local integration test. Creates temporary users/table/bucket and cleans up."""
import base64
import json
import secrets
import socket
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
import manage

v = manage.read_env(manage.ROOT / '.env')
manage.validate(v)
base = f"http://127.0.0.1:{v['PUBLIC_API_PORT']}"
opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
suffix = uuid.uuid4().hex[:12]
table = 'test_todos_' + suffix
bucket = 'test-files-' + suffix
users = []
files = []


def api(method, path, data=None, token=None, admin=False, raw=False, codes=(200,)):
    key = v['SERVICE_ROLE_KEY'] if admin else v['ANON_KEY']
    headers = {'apikey': key, 'Authorization': 'Bearer ' + (token or key)}
    if data is not None:
        headers['Content-Type'] = 'text/plain' if raw else 'application/json'
        data = data if raw else json.dumps(data).encode()
    if method == 'POST' and path.startswith('/rest/'):
        headers['Prefer'] = 'return=representation'
    req = urllib.request.Request(base + path, data=data, headers=headers, method=method)
    try:
        with opener.open(req, timeout=30) as response:
            status, body = response.status, response.read()
    except urllib.error.HTTPError as error:
        status, body = error.code, error.read()
    if status not in codes:
        # Do not leak tokens or user objects in failures.
        raise AssertionError(f'{method} {path.split("?")[0]} returned {status}, expected {codes}; body omitted')
    if raw:
        return body
    return json.loads(body) if body else None


def sql(text):
    manage.compose(v, ['exec', '-T', 'db', 'psql', '-v', 'ON_ERROR_STOP=1', '-U', 'postgres', '-d', 'postgres'], input=text, capture_output=True, text=True)


try:
    for i in range(2):
        email = f'test-{suffix}-{i}@example.invalid'
        password = secrets.token_hex(24)
        user = api('POST', '/auth/v1/admin/users', {'email': email, 'password': password, 'email_confirm': True}, admin=True)
        users.append({'id': user['id']})
        session = api('POST', '/auth/v1/token?grant_type=password', {'email': email, 'password': password})
        users[-1]['token'] = session['access_token']
    a, b = users
    sql((manage.ROOT / 'examples/001_todos.sql').read_text().replace('todos', table))
    sql((manage.ROOT / 'examples/002_storage.sql').read_text().replace('user-files', bucket).replace('user_files_', 'test_' + suffix + '_'))
    sql("notify pgrst, 'reload schema';")
    # Schema cache notification is asynchronous.
    for attempt in range(30):
        try:
            api('GET', '/rest/v1/' + table, token=a['token'])
            break
        except AssertionError:
            if attempt == 29:
                raise
            time.sleep(0.2)
    row = api('POST', '/rest/v1/' + table, {'title': 'integration probe'}, token=a['token'], codes=(201,))[0]
    assert row['user_id'] == a['id']
    assert len(api('GET', '/rest/v1/' + table, token=a['token'])) == 1
    assert api('GET', '/rest/v1/' + table, token=b['token']) == []
    api('POST', '/rest/v1/' + table, {'title': 'forbidden', 'user_id': a['id']}, token=b['token'], codes=(403,))
    api('POST', '/rest/v1/' + table, {'title': 'forbidden anon'}, codes=(401, 403))
    api('PATCH', '/rest/v1/' + table + '?id=eq.' + row['id'], {'title': 'hijacked'}, token=b['token'], codes=(204,))
    assert api('GET', '/rest/v1/' + table, token=a['token'])[0]['title'] == 'integration probe'
    print('PASS Auth: two logins; RLS: ownership, cross-user read/update/insert and anon denial')
    for name in ['plain.txt', 'space name.txt']:
        obj = a['id'] + '/' + name
        files.append(obj)
        path = '/storage/v1/object/' + bucket + '/' + urllib.parse.quote(obj)
        api('POST', path, b'integration file', token=a['token'], raw=True)
        assert api('GET', path, token=a['token'], raw=True) == b'integration file'
        api('GET', path, token=b['token'], raw=True, codes=(400, 403, 404))
    print('PASS Storage: private uploads/downloads, escaped spaces, cross-user denial')
    result = api('POST', '/functions/v1/hello', {'name': 'World'}, token=a['token'])
    assert result['message'] == 'Hello World!'
    api('POST', '/functions/v1/hello', {'name': 'World'}, codes=(401,))
    print('PASS Edge Function: authenticated hello invocation and anon denial')
    # A WebSocket protocol upgrade, without printing the key-bearing request.
    with socket.create_connection(('127.0.0.1', int(v['PUBLIC_API_PORT'])), timeout=10) as sock:
        wskey = base64.b64encode(secrets.token_bytes(16)).decode()
        target = '/realtime/v1/websocket?apikey=' + v['ANON_KEY'] + '&vsn=1.0.0'
        request = f'GET {target} HTTP/1.1\r\nHost: localhost\r\nUpgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Key: {wskey}\r\nSec-WebSocket-Version: 13\r\n\r\n'
        sock.sendall(request.encode())
        assert b' 101 ' in sock.recv(4096).split(b'\r\n', 1)[0]
    print('PASS Realtime: WebSocket 101 handshake through public-api')
finally:
    # Unique fixture names prevent modifying existing application resources.
    if files:
        api('DELETE', '/storage/v1/object/' + bucket, {'prefixes': files}, admin=True, codes=(200, 404))
    policies = '\n'.join('drop policy if exists test_' + suffix + '_' + action + ' on storage.objects;' for action in ['read', 'insert', 'update', 'delete'])
    sql(f'drop table if exists public.{table};\n' + policies)
    api('DELETE', '/storage/v1/bucket/' + bucket, admin=True, codes=(200, 400, 404))
    for user in users:
        api('DELETE', '/auth/v1/admin/users/' + user['id'], admin=True)
    print('Temporary integration fixtures removed')
