import contextlib
import io
from pathlib import Path
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import manage


class ConfigurationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        shutil.copy(manage.ROOT / '.env.example', self.root / '.env.example')
        with contextlib.redirect_stdout(io.StringIO()):
            self.values = manage.init(self.root)

    def tearDown(self):
        self.temp.cleanup()

    def test_secure_valid_defaults(self):
        manage.validate(self.values)
        self.assertEqual((self.root / '.env').stat().st_mode & 0o777, 0o600)
        self.assertNotEqual(self.values['ANON_KEY'], self.values['SERVICE_ROLE_KEY'])

    def test_repeated_init_preserves_secrets(self):
        before = (self.root / '.env').read_bytes()
        with contextlib.redirect_stdout(io.StringIO()):
            manage.init(self.root)
        self.assertEqual(before, (self.root / '.env').read_bytes())

    def test_wrong_jwt_secret_rejected(self):
        self.values['JWT_SECRET'] = 'a' * 64
        with self.assertRaisesRegex(ValueError, '签名'):
            manage.validate(self.values)

    def test_data_without_env_refuses_regeneration(self):
        data = self.root / 'volumes/db/data'
        data.mkdir(parents=True)
        (data / 'PG_VERSION').write_text('17')
        (self.root / '.env').unlink()
        with self.assertRaisesRegex(ValueError, '已有数据库'):
            manage.init(self.root)

    def test_public_mode_requires_real_configuration(self):
        self.values['TUNNEL_ENABLED'] = 'true'
        with self.assertRaisesRegex(ValueError, 'TUNNEL_TOKEN'):
            manage.validate(self.values)
        self.values['TUNNEL_TOKEN'] = 'example-token'
        with self.assertRaisesRegex(ValueError, 'HTTPS'):
            manage.validate(self.values)
        self.values.update(SUPABASE_PUBLIC_URL='https://api.example.com', API_EXTERNAL_URL='https://api.example.com/auth/v1', SITE_URL='https://app.example.com')
        manage.validate(self.values)
        self.values['ENABLE_EMAIL_AUTOCONFIRM'] = 'true'
        with self.assertRaisesRegex(ValueError, '自动确认'):
            manage.validate(self.values)

    def test_smtp_required_for_public_signup(self):
        self.values.update(TUNNEL_ENABLED='true', TUNNEL_TOKEN='example', SUPABASE_PUBLIC_URL='https://api.example.com', API_EXTERNAL_URL='https://api.example.com/auth/v1', SITE_URL='https://app.example.com', DISABLE_SIGNUP='false')
        with self.assertRaisesRegex(ValueError, 'SMTP_HOST'):
            manage.validate(self.values)

    def test_env_is_literal_and_never_shell(self):
        path = self.root / 'parser.env'
        path.write_text("SMTP_PASS='a$secret#foo'\n")
        self.assertEqual(manage.read_env(path)['SMTP_PASS'], 'a$secret#foo')
        path.write_text('SMTP_PASS=$(touch /tmp/should-not-exist)\n')
        with self.assertRaises(ValueError):
            manage.read_env(path)

    def test_duplicate_ports_rejected(self):
        self.values['STUDIO_PORT'] = self.values['PUBLIC_API_PORT']
        with self.assertRaisesRegex(ValueError, '端口'):
            manage.validate(self.values)


if __name__ == '__main__':
    unittest.main()
