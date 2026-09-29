"""Acceptance tests for enabled local features, using isolated disposable fixtures."""
import base64
import os
from pathlib import Path
import secrets
import subprocess
import sys
import time
import unittest
import urllib.parse
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'scripts'))
import manage
from integration_support import Instance, WebSocket


class InstanceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.instance = Instance()
        # Fail explicitly when the stack is down, before creating any resources.
        cls.instance.api('GET', '/healthz', raw=True, authenticated=False)

    def setUp(self):
        self.api = self.instance.api
        self.sql = self.instance.sql
        self.suffix = uuid.uuid4().hex[:12]
        self.table = 'test_todos_' + self.suffix
        self.bucket = 'test-files-' + self.suffix

    def user(self):
        email = f'test-{uuid.uuid4().hex}@example.invalid'
        password = secrets.token_hex(24)
        user = self.api('POST', '/auth/v1/admin/users', {'email': email, 'password': password,
                        'email_confirm': True}, admin=True)
        self.addCleanup(self.api, 'DELETE', '/auth/v1/admin/users/' + user['id'], admin=True)
        session = self.api('POST', '/auth/v1/token?grant_type=password', {'email': email, 'password': password})
        self.assertTrue(session.get('access_token'), 'Login must return an access token')
        self.assertTrue(session.get('refresh_token'), 'Login must return a refresh token')
        self.assertEqual(session['user']['id'], user['id'])
        return dict(id=user['id'], token=session['access_token'], refresh=session['refresh_token'], email=email)

    def table_fixture(self):
        self.addCleanup(self.sql, f'drop table if exists public.{self.table}; notify pgrst, \'reload schema\';')
        self.sql((manage.ROOT / 'examples/001_todos.sql').read_text().replace('todos', self.table))
        self.sql("notify pgrst, 'reload schema';")
        self.instance.wait_for_table(self.table, self.a['token'])
        return '/rest/v1/' + self.table

    def storage_fixture(self):
        # LIFO cleanup: empty bucket, remove bucket, then remove policies, then users.
        for action in ('read', 'insert', 'update', 'delete'):
            self.addCleanup(self.sql, f'drop policy if exists test_{self.suffix}_{action} on storage.objects;')
        self.sql((manage.ROOT / 'examples/002_storage.sql').read_text().replace('user-files', self.bucket)
                 .replace('user_files_', 'test_' + self.suffix + '_'))
        self.addCleanup(self.api, 'DELETE', '/storage/v1/bucket/' + self.bucket, admin=True)
        self.addCleanup(self.api, 'POST', '/storage/v1/bucket/' + self.bucket + '/empty', {}, admin=True)
        return '/storage/v1/object/' + self.bucket + '/'

    def test_auth_sessions_and_invalid_credentials(self):
        a = self.user()
        self.assertEqual(self.api('GET', '/auth/v1/user', token=a['token'])['id'], a['id'])
        self.api('POST', '/auth/v1/token?grant_type=password', {'email': a['email'], 'password': 'wrong'}, codes=(400,))
        self.api('GET', '/auth/v1/user', token='invalid.jwt.token', codes=(401, 403))
        session = self.api('POST', '/auth/v1/token?grant_type=refresh_token', {'refresh_token': a['refresh']})
        self.assertEqual(session['user']['id'], a['id'])
        self.assertEqual(self.api('GET', '/auth/v1/user', token=session['access_token'])['id'], a['id'])
        self.api('POST', '/auth/v1/logout?scope=global', token=session['access_token'], codes=(204,))
        self.api('POST', '/auth/v1/token?grant_type=refresh_token', {'refresh_token': session['refresh_token']}, codes=(400,))

    def test_gateway_security_boundaries(self):
        manage.smoke(self.instance.values)
        self.api('GET', '/rest/v1/', headers={'apikey': 'invalid-key'}, raw=True, codes=(401, 403))
        self.api('GET', '/auth/v1/admin/users', codes=(401, 403))

    def test_auth_signup_configuration(self):
        settings = self.api('GET', '/auth/v1/settings')
        disabled = self.instance.values['DISABLE_SIGNUP'] == 'true'
        self.assertEqual(settings['disable_signup'], disabled)
        if disabled:
            self.api('POST', '/auth/v1/signup', {'email': f'test-{self.suffix}@example.invalid',
                'password': secrets.token_hex(24)}, codes=(400, 403, 422))

    def test_rest_crud_rls_and_constraints(self):
        self.a, b = self.user(), self.user()
        path = self.table_fixture()
        row = self.api('POST', path, {'title': 'probe'}, token=self.a['token'], codes=(201,))[0]
        self.assertEqual(row['user_id'], self.a['id'])
        item = path + '?id=eq.' + row['id']
        self.assertEqual(self.api('GET', item, token=self.a['token']), [row])
        self.assertEqual(self.api('GET', path, token=b['token']), [])
        self.api('GET', path, codes=(401, 403))
        self.api('POST', path, {'title': 'anonymous'}, codes=(401, 403))
        self.api('POST', path, {'title': 'forged', 'user_id': self.a['id']}, token=b['token'], codes=(403,))
        self.api('POST', path, {'title': ''}, token=self.a['token'], codes=(400,))
        self.assertEqual(self.api('PATCH', item, {'title': 'hijacked'}, token=b['token']), [])
        self.assertEqual(self.api('DELETE', item, token=b['token']), [])
        self.assertEqual(self.api('GET', item, token=self.a['token']), [row])
        self.api('PATCH', item, {'user_id': b['id']}, token=self.a['token'], codes=(403,))
        updated = self.api('PATCH', item, {'title': 'updated', 'done': True}, token=self.a['token'])
        self.assertEqual([(r['title'], r['done']) for r in updated], [('updated', True)])
        self.assertEqual(len(self.api('GET', path, admin=True)), 1)
        self.assertEqual(self.api('DELETE', item, token=self.a['token'])[0]['id'], row['id'])
        self.assertEqual(self.api('GET', path, token=self.a['token']), [])

    def test_rpc_respects_caller_rls(self):
        self.a, b = self.user(), self.user()
        path = self.table_fixture()
        function = 'test_count_' + self.suffix
        self.addCleanup(self.sql, f'drop function if exists public.{function}();')
        self.sql(f'''create function public.{function}() returns bigint language sql stable security invoker
            set search_path = '' as $$ select count(*) from public.{self.table}; $$;
            revoke execute on function public.{function}() from public, anon;
            grant execute on function public.{function}() to authenticated;
            notify pgrst, 'reload schema';''')
        # Wait on the actual RPC, not on an already cached table.
        rpc = '/rest/v1/rpc/' + function
        deadline = time.monotonic() + 15
        while True:
            try:
                self.assertEqual(self.api('POST', rpc, {}, token=self.a['token']), 0)
                break
            except AssertionError:
                if time.monotonic() >= deadline:
                    raise
                time.sleep(0.2)
        self.api('POST', path, {'title': 'rpc probe'}, token=self.a['token'], codes=(201,))
        self.assertEqual(self.api('POST', rpc, {}, token=self.a['token']), 1)
        self.assertEqual(self.api('POST', rpc, {}, token=b['token']), 0)
        self.api('POST', rpc, {}, codes=(401, 403))

    def test_storage_crud_signed_urls_and_isolation(self):
        self.a, b = self.user(), self.user()
        path = self.storage_fixture()
        for name in ('plain.txt', 'space name.txt'):
            with self.subTest(name=name):
                obj = self.a['id'] + '/' + name
                target = path + urllib.parse.quote(obj)
                self.api('POST', target, b'original', token=self.a['token'], raw=True)
                self.assertEqual(self.api('GET', target, token=self.a['token'], raw=True), b'original')
                self.api('GET', target, token=b['token'], raw=True, codes=(400, 403, 404))
                self.api('GET', target, raw=True, codes=(400, 403, 404))
                self.api('PUT', target, b'forbidden', token=b['token'], raw=True, codes=(400, 403, 404))
                self.api('POST', path + b['id'] + '/forged.txt', b'forbidden', token=self.a['token'], raw=True, codes=(400, 403))
                listed = self.api('POST', '/storage/v1/object/list/' + self.bucket, {'prefix': self.a['id']}, token=self.a['token'])
                self.assertIn(name, [r['name'] for r in listed])
                self.assertEqual(self.api('POST', '/storage/v1/object/list/' + self.bucket,
                    {'prefix': self.a['id']}, token=b['token']), [])
                self.api('DELETE', '/storage/v1/object/' + self.bucket, {'prefixes': [obj]}, token=b['token'])
                self.assertEqual(self.api('GET', target, token=self.a['token'], raw=True), b'original')
                self.api('PUT', target, b'updated', token=self.a['token'], raw=True)
                signed_path = '/storage/v1/object/sign/' + self.bucket + '/' + urllib.parse.quote(obj)
                self.api('POST', signed_path, {'expiresIn': 60}, token=b['token'], codes=(400, 403, 404))
                signed = self.api('POST', signed_path, {'expiresIn': 60}, token=self.a['token'])
                signed_url = urllib.parse.quote('/storage/v1' + signed['signedURL'], safe='/%?=&')
                content = self.api('GET', signed_url, authenticated=False, raw=True)
                self.assertTrue(content == b'updated', 'Signed URL must return updated contents')
                self.api('DELETE', '/storage/v1/object/' + self.bucket, {'prefixes': [obj]}, token=self.a['token'])
                self.api('GET', target, token=self.a['token'], raw=True, codes=(400, 404))

    def test_edge_function_auth_validation_and_cors(self):
        a = self.user()
        path = '/functions/v1/hello'
        self.assertEqual(self.api('POST', path, {'name': '开发者'}, token=a['token']), {'message': 'Hello 开发者!'})
        self.assertEqual(self.api('POST', path, {}, token=a['token']), {'message': 'Hello World!'})
        self.api('POST', path, {}, codes=(401,))
        self.api('POST', path, {}, authenticated=False, codes=(401,))
        self.api('POST', path, {}, token='invalid.jwt.token', codes=(401,))
        self.api('GET', path, token=a['token'], codes=(405,))
        self.api('POST', path, b'{invalid', token=a['token'], raw=True, codes=(400,))
        _, headers = self.instance.request('OPTIONS', path, authenticated=False, raw=True,
            headers={'Origin': 'http://localhost:5173', 'Access-Control-Request-Method': 'POST',
                     'Access-Control-Request-Headers': 'authorization,apikey,content-type'})
        self.assertIn(headers['Access-Control-Allow-Origin'], ('*', 'http://localhost:5173'))
        self.assertIn('authorization', headers['Access-Control-Allow-Headers'].lower())
        self.assertIn('POST', headers['Access-Control-Allow-Methods'])

    def test_realtime_changes_delivery_and_rls(self):
        self.a, b = self.user(), self.user()
        path = self.table_fixture()
        sockets = []
        for user in (self.a, b):
            ws = WebSocket(self.instance)
            self.addCleanup(ws.close)
            ws.join('realtime:' + self.table, user['token'], [{'event': 'INSERT', 'schema': 'public', 'table': self.table}])
            sockets.append(ws)

        def is_change(message, user, title):
            if message.get('event') != 'postgres_changes':
                return False
            record = message['payload']['data']['record']
            self.assertEqual(record['user_id'], user['id'], 'Realtime leaked a cross-user row')
            return record['title'] == title

        # Realtime refreshes its publication OID cache periodically (60 s in this
        # image). A successful join/system reply alone does not mean that a new
        # table is in that cache. Probe delivery before asserting one-shot writes.
        deadline = time.monotonic() + 75
        for ws, user in zip(sockets, (self.a, b)):
            while True:
                for connection in sockets:
                    connection.send('phoenix', 'heartbeat', {}, 'ready-heartbeat')
                self.api('POST', path, {'title': 'readiness'}, token=user['token'], codes=(201,))
                try:
                    ws.until(lambda m: is_change(m, user, 'readiness'), timeout=2)
                    break
                except TimeoutError:
                    if time.monotonic() >= deadline:
                        self.fail('Realtime did not deliver a readiness event within 75 seconds')
        own = self.api('POST', path, {'title': 'a event'}, token=self.a['token'], codes=(201,))[0]
        marker = self.api('POST', path, {'title': 'b event'}, token=b['token'], codes=(201,))[0]
        for ws, expected in zip(sockets, (own, marker)):
            event = ws.until(lambda m: is_change(m, {'id': expected['user_id']}, expected['title']))
            record = event['payload']['data']['record']
            self.assertEqual(record['id'], expected['id'])
            self.assertEqual(record['user_id'], expected['user_id'])
            # A quiet window also catches an extra cross-user event after the own event.
            with self.assertRaises(TimeoutError):
                ws.until(lambda m: is_change(m, {'id': expected['user_id']}, expected['title']), timeout=1)

    def test_realtime_broadcast_and_presence(self):
        a = self.user()
        ws = WebSocket(self.instance)
        self.addCleanup(ws.close)
        topic = 'realtime:test_room_' + self.suffix
        ws.join(topic, a['token'])
        ws.send(topic, 'broadcast', {'type': 'broadcast', 'event': 'probe', 'payload': {'value': self.suffix}}, 'broadcast')
        message = ws.until(lambda m: m.get('event') == 'broadcast')
        self.assertEqual(message['payload']['payload']['value'], self.suffix)
        ws.send(topic, 'presence', {'type': 'presence', 'event': 'track', 'payload': {'probe': self.suffix}}, 'track')
        presence = ws.until(lambda m: m.get('event') == 'presence_diff' and bool(m['payload'].get('joins')))
        self.assertEqual(presence['payload']['joins']['probe']['metas'][0]['probe'], self.suffix)

    def test_sql_session_and_transaction_poolers(self):
        v = self.instance.values
        # Reuse the installed database image's psql, so the host needs no extra package.
        image = manage.config(v)['services']['db']['image']
        for port_name in ('DB_SESSION_PORT', 'DB_TRANSACTION_PORT'):
            with self.subTest(mode=port_name):
                env = dict(os.environ, PGPASSWORD=v['POSTGRES_PASSWORD'], PGCONNECT_TIMEOUT='10')
                try:
                    result = subprocess.run(['docker', 'run', '--rm', '--network', 'host', '-i',
                        '--env', 'PGPASSWORD', '--env', 'PGCONNECT_TIMEOUT', '--entrypoint', 'psql', image,
                        '-X', '-qAt', '-v', 'ON_ERROR_STOP=1', '-h', '127.0.0.1', '-p', v[port_name],
                        '-U', 'postgres.' + v['POOLER_TENANT_ID'], '-d', 'postgres'],
                        input='begin; create temporary table acceptance_probe (n int) on commit drop; '
                              'insert into acceptance_probe values (42); select n from acceptance_probe; rollback; '
                              "select to_regclass('pg_temp.acceptance_probe') is null;\n",
                        text=True, capture_output=True, env=env, timeout=30)
                except (OSError, subprocess.SubprocessError):
                    self.fail('Pooler client failed or timed out; captured output omitted')
                self.assertEqual(result.returncode, 0, 'Pooler SQL transaction failed; captured output omitted')
                self.assertEqual(result.stdout.strip(), '42\nt')

    def test_studio_authenticated_access(self):
        v = self.instance.values
        credentials = base64.b64encode((v['DASHBOARD_USERNAME'] + ':' + v['DASHBOARD_PASSWORD']).encode()).decode()
        base = f"http://127.0.0.1:{v['STUDIO_PORT']}"
        self.api('GET', '/', base=base, authenticated=False, raw=True, codes=(401,))
        body, headers = self.instance.request('GET', '/', base=base, authenticated=False, raw=True,
            headers={'Authorization': 'Basic ' + credentials})
        self.assertIn('text/html', headers['Content-Type'])
        self.assertIn(b'<html', body.lower())


if __name__ == '__main__':
    unittest.main()
