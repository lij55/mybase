import io
import json
from pathlib import Path
import sys
import unittest
from unittest import mock
from urllib.error import HTTPError

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import reset_auth_password as reset


class ResetPasswordTests(unittest.TestCase):
    user_id = '11111111-1111-4111-8111-111111111111'
    values = {'SUPABASE_SECRET_KEY': 'server-secret', 'PUBLIC_API_PORT': '9000'}
    password = 'new-password-123'

    def test_admin_request_and_proxy_bypass(self):
        with mock.patch.object(reset, 'build_opener') as build:
            reset.reset_password(self.values, self.user_id, self.password)
        self.assertEqual(build.call_args.args[0].proxies, {})
        request = build.return_value.open.call_args.args[0]
        self.assertEqual(request.get_method(), 'PUT')
        self.assertEqual(request.full_url, f'http://127.0.0.1:9000/auth/v1/admin/users/{self.user_id}')
        self.assertEqual(json.loads(request.data), {'password': self.password})
        self.assertEqual(request.get_header('Apikey'), 'server-secret')
        self.assertEqual(request.get_header('Authorization'), 'Bearer server-secret')

    def test_invalid_input_never_sends_request(self):
        with mock.patch.object(reset, 'build_opener') as build:
            for user, password in [('not-a-uuid', self.password), (self.user_id, 'short')]:
                with self.assertRaises(ValueError):
                    reset.reset_password(self.values, user, password)
            with self.assertRaises(ValueError):
                reset.reset_password({'PUBLIC_API_PORT': '9000'}, self.user_id, self.password)
        build.assert_not_called()

    def test_failure_does_not_expose_response_secrets(self):
        error = HTTPError('http://localhost', 422, 'secret detail', {}, io.BytesIO(b'password secret detail'))
        with mock.patch.object(reset, 'build_opener') as build:
            build.return_value.open.side_effect = error
            with self.assertRaisesRegex(ValueError, 'HTTP 422') as caught:
                reset.reset_password(self.values, self.user_id, self.password)
        self.assertNotIn('secret', str(caught.exception))

    def test_confirmation_mismatch_never_updates(self):
        with mock.patch.object(reset.manage, 'read_env', return_value=self.values), \
             mock.patch.object(reset.Path, 'is_file', return_value=True), \
             mock.patch.object(reset.getpass, 'getpass', side_effect=[self.password, 'different']), \
             mock.patch.object(reset, 'reset_password') as update, \
             mock.patch('sys.stderr', new_callable=io.StringIO):
            self.assertEqual(reset.main([self.user_id]), 1)
        update.assert_not_called()


if __name__ == '__main__':
    unittest.main()
