import importlib.util
import json
import os
import threading
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen

spec = importlib.util.spec_from_file_location('demo_server', Path(__file__).resolve().parents[1] / 'common/server.py')
server = importlib.util.module_from_spec(spec)
spec.loader.exec_module(server)
USER = '11111111-1111-4111-8111-111111111111'
OTHER = '22222222-2222-4222-8222-222222222222'


def application(kind='admin'):
    with patch.dict(os.environ, {'APP_KIND': kind, 'SUPABASE_URL': 'http://supabase',
                                 'SUPABASE_PUBLISHABLE_KEY': 'public', 'SUPABASE_SECRET_KEY': 'secret',
                                 'DATABASE_URL': 'postgresql://restricted', 'ADMIN_USER_IDS': USER}, clear=True):
        return server.Application()


class AuthorizationTests(unittest.TestCase):
    def test_non_admin_cannot_create_user_or_change_memberships(self):
        app = application()
        app.upstream = Mock(return_value={'id': OTHER})
        app.connection = Mock()
        for path in ['/api/users', '/api/memberships', '/api/apps']:
            with self.assertRaises(server.Problem) as caught:
                app.dispatch('POST', path, {}, {'user_id': USER, 'app_id': 'app_todo'}, 'valid-user-token')
            self.assertEqual(caught.exception.status, 403)
        app.connection.assert_not_called()
        self.assertTrue(all(call.args == ('/auth/v1/user',) for call in app.upstream.call_args_list))

    def test_missing_token_is_rejected_before_any_upstream_request(self):
        app = application()
        app.upstream = Mock()
        with self.assertRaises(server.Problem) as caught:
            app.dispatch('GET', '/api/apps', {}, {}, None)
        self.assertEqual(caught.exception.status, 401)
        app.upstream.assert_not_called()

    def test_business_writes_use_fixed_schema_and_user_token(self):
        app = application('todo')
        app.upstream = Mock(side_effect=[{'id': USER}, [{'id': OTHER}]])
        app.dispatch('POST', '/api/items', {},
                     {'title': '  task  ', 'schema': 'app_notes', 'user_id': OTHER}, 'user-token')
        call = app.upstream.call_args_list[-1]
        self.assertEqual(call.args, ('/rest/v1/todos', 'POST', {'title': 'task'}, 'user-token'))
        self.assertEqual(call.kwargs['headers']['Content-Profile'], 'app_todo')
        self.assertFalse(hasattr(app, 'service'))
        self.assertFalse(hasattr(app, 'dsn'))

    def test_noop_delete_is_reported_as_not_found(self):
        app = application('notes')
        app.upstream = Mock(side_effect=[{'id': USER}, []])
        with self.assertRaises(server.Problem) as caught:
            app.dispatch('DELETE', f'/api/items/{OTHER}', {}, {}, 'token')
        self.assertEqual(caught.exception.status, 404)

    def test_grant_requires_discovered_schema(self):
        app = application()
        app.upstream = Mock(return_value={'id': USER})
        connection = Mock()
        app.connection = Mock()
        app.connection.return_value.__enter__ = Mock(return_value=connection)
        app.connection.return_value.__exit__ = Mock(return_value=False)
        app.discover = Mock(return_value=[{'id': 'app_todo', 'name': 'Todo'}])
        with self.assertRaises(server.Problem) as caught:
            app.dispatch('POST', '/api/memberships', {}, {'user_id': OTHER, 'app_id': 'app_missing'}, 'token')
        self.assertEqual(caught.exception.status, 404)
        connection.execute.assert_not_called()
        app.dispatch('POST', '/api/memberships', {}, {'user_id': OTHER, 'app_id': 'app_todo'}, 'token')
        self.assertEqual(connection.execute.call_args.args[1], ('app_todo', OTHER))

    def test_app_contract_rejects_reserved_and_injected_names(self):
        for name in ['app_access', 'public', 'app_', 'app_A', 'app_todo;drop schema public', 'app_' + 'x'*60]:
            self.assertFalse(server.app_name(name), name)
        for name in ['app_todo', 'app_notes', 'app_third_4']:
            self.assertTrue(server.app_name(name), name)

    def test_user_creation_does_not_implicitly_grant_membership(self):
        app = application()
        app.upstream = Mock(side_effect=[{'id': USER}, {'id': OTHER, 'email': 'new@example.com'}])
        app.connection = Mock()
        result = app.dispatch('POST', '/api/users', {}, {'email': 'new@example.com', 'password': 'long-password-123'}, 'token')
        self.assertEqual(result['id'], OTHER)
        app.connection.assert_not_called()
        self.assertTrue(app.upstream.call_args.kwargs['admin'])
        self.assertTrue(app.upstream.call_args.args[2]['email_confirm'])


class HTTPTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.http = server.ThreadingHTTPServer(('127.0.0.1', 0), server.Handler)
        cls.http.application = Mock()
        cls.http.application.dispatch.return_value = {'ok': True}
        cls.url = f'http://127.0.0.1:{cls.http.server_port}'
        cls.thread = threading.Thread(target=cls.http.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.http.shutdown(); cls.http.server_close(); cls.thread.join()

    def test_cross_origin_mutation_rejected(self):
        self.http.application.dispatch.reset_mock()
        request = Request(self.url + '/api/users', data=b'{}', method='POST',
                          headers={'Content-Type': 'application/json', 'Origin': 'https://attacker.example'})
        with self.assertRaises(HTTPError) as caught:
            urlopen(request)
        self.assertEqual(caught.exception.code, 403)
        caught.exception.close()
        self.http.application.dispatch.assert_not_called()

    def test_same_origin_json_accepted(self):
        request = Request(self.url + '/api/users', data=b'{}', method='POST',
                          headers={'Content-Type': 'application/json', 'Origin': self.url})
        with urlopen(request) as response:
            self.assertEqual(json.load(response), {'ok': True})
            self.assertIn("script-src 'self'", response.headers['Content-Security-Policy'])

    def test_static_path_traversal_rejected(self):
        with self.assertRaises(HTTPError) as caught:
            urlopen(self.url + '/../../.env')
        self.assertEqual(caught.exception.code, 404)
        caught.exception.close()


if __name__ == '__main__':
    unittest.main()
