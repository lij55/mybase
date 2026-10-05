import contextlib
import io
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import manage


class ConfigurationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        shutil.copy(manage.ROOT / '.env.example', self.root / '.env.example')
        shutil.copytree(manage.ROOT / 'caddy', self.root / 'caddy', ignore=shutil.ignore_patterns('Caddyfile'))
        with contextlib.redirect_stdout(io.StringIO()):
            self.values = manage.init(self.root)

    def tearDown(self):
        self.temp.cleanup()

    def test_secure_valid_defaults(self):
        manage.validate(self.values)
        self.assertEqual((self.root / '.env').stat().st_mode & 0o777, 0o600)
        self.assertNotEqual(self.values['SUPABASE_PUBLISHABLE_KEY'], self.values['SUPABASE_SECRET_KEY'])

    def test_repeated_init_preserves_secrets(self):
        before = (self.root / '.env').read_bytes()
        with contextlib.redirect_stdout(io.StringIO()):
            manage.init(self.root)
        self.assertEqual(before, (self.root / '.env').read_bytes())

    def test_caddy_init_preserves_custom_config(self):
        path = self.root / 'caddy/Caddyfile'
        self.assertIn('127.0.0.1:8000', path.read_text())
        path.write_text('# custom config\n')
        with contextlib.redirect_stdout(io.StringIO()):
            manage.init(self.root)
        self.assertEqual(path.read_text(), '# custom config\n')

    def test_caddy_upgrades_generated_fallback_to_demo(self):
        path = self.root / 'caddy/Caddyfile'
        text = path.read_text()
        path.write_text(text.replace(
            '\t# All other hosts go to the demo Traefik entrypoint; preserve Host routing.\n\thandle {\n\t\treverse_proxy 127.0.0.1:8090\n\t}',
            '\t# Unknown hosts must never fall through to Studio.\n\thandle {\n\t\trespond "Not found" 404\n\t}'))
        manage.init_caddy(self.root, self.values)
        self.assertEqual(path.read_text(), text)
        self.assertIn('reverse_proxy 127.0.0.1:8090', text)
        self.assertNotIn('respond "Not found" 404', text)

    def test_caddy_bind_refreshes_legacy_and_generated_configs(self):
        path = self.root / 'caddy/Caddyfile'
        self.assertIn('bind 127.0.0.1', path.read_text())
        self.values['CADDY_BIND'] = '0.0.0.0'
        manage.init_caddy(self.root, self.values)
        self.assertIn('bind 0.0.0.0', path.read_text())
        self.assertIn('reverse_proxy 127.0.0.1:8000', path.read_text())
        self.values['CADDY_BIND'] = '127.0.0.1'
        manage.init_caddy(self.root, self.values)
        self.assertIn('bind 127.0.0.1', path.read_text())
        self.values['CADDY_BIND'] = '0.0.0.0 { respond 200 }'
        with self.assertRaises(ValueError):
            manage.init_caddy(self.root, self.values)

    def test_caddy_custom_hosts_ports_and_invalid_hosts(self):
        path = self.root / 'caddy/Caddyfile'
        path.unlink()
        self.values.update(PUBLIC_HOST='example.com', PUBLIC_API_PORT='9000')
        manage.init_caddy(self.root, self.values)
        self.assertIn('@api host api.example.com', path.read_text())
        self.assertIn('127.0.0.1:9000', path.read_text())
        path.unlink()
        self.values['PUBLIC_HOST'] = 'evil.example { respond 200 }'
        with self.assertRaises(ValueError):
            manage.init_caddy(self.root, self.values)

    def test_minimal_env_and_shared_domain(self):
        raw = manage.read_env(self.root / '.env')
        self.assertEqual(set(raw), {'PUBLIC_HOST', *manage.SECRET_BYTES, *manage.AUTH_FIELDS})
        self.assertEqual(self.values['SUPABASE_PUBLIC_URL'], 'https://api.my.supabase.local')
        self.assertEqual(self.values['API_EXTERNAL_URL'], 'https://api.my.supabase.local/auth/v1')
        text = (self.root / 'caddy/Caddyfile').read_text()
        self.assertIn('@api host api.my.supabase.local', text)
        self.assertIn('@admin host admin.my.supabase.local', text)

    def test_domain_change_refreshes_generated_caddy_and_urls(self):
        path = self.root / '.env'
        path.write_text(path.read_text().replace('PUBLIC_HOST=my.supabase.local', 'PUBLIC_HOST=example.com'))
        with contextlib.redirect_stdout(io.StringIO()):
            values = manage.init(self.root)
        self.assertEqual(values['SUPABASE_PUBLIC_URL'], 'https://api.example.com')
        self.assertEqual(values['API_EXTERNAL_URL'], 'https://api.example.com/auth/v1')
        self.assertIn('@admin host admin.example.com', (self.root / 'caddy/Caddyfile').read_text())
        manage.validate(values)

    def test_public_host_overrides_stale_urls(self):
        values = manage.effective_env({'PUBLIC_HOST': 'example.com',
                                      'SUPABASE_PUBLIC_URL': 'http://localhost:8000',
                                      'API_EXTERNAL_URL': 'http://localhost:8000/auth/v1'})
        self.assertEqual(values['SUPABASE_PUBLIC_URL'], 'https://api.example.com')
        self.assertEqual(values['API_EXTERNAL_URL'], 'https://api.example.com/auth/v1')
        with mock.patch.object(manage.subprocess, 'run') as run:
            manage.compose(values, ['config'])
        self.assertEqual(run.call_args.kwargs['env']['SUPABASE_PUBLIC_URL'], values['SUPABASE_PUBLIC_URL'])

    def test_legacy_urls_and_caddy_upgrade(self):
        values = manage.effective_env({'SUPABASE_PUBLIC_URL': 'http://localhost:8000',
                                      'API_EXTERNAL_URL': 'http://localhost:8000/auth/v1'})
        self.assertEqual(values['SUPABASE_PUBLIC_URL'], 'http://localhost:8000')
        path = self.root / 'caddy/Caddyfile'
        path.write_text(path.read_text().replace(
            'unmodified generated files are refreshed; custom files are preserved.',
            'existing caddy/Caddyfile is never overwritten.').replace(
            'api.my.supabase.local', 'api.localhost').replace(
            'admin.my.supabase.local', 'admin.localhost'))
        manage.init_caddy(self.root, self.values)
        self.assertIn('@api host api.my.supabase.local', path.read_text())

    def test_es256_signature_and_public_jwks(self):
        import json
        public = json.loads(self.values['JWT_JWKS'])['keys'][0]
        self.assertEqual(public['alg'], 'ES256')
        self.assertNotIn('d', public)
        self.assertNotIn('k', public)
        self.values['ANON_KEY_ASYMMETRIC'] = self.values['SERVICE_ROLE_KEY_ASYMMETRIC']
        with self.assertRaisesRegex(ValueError, '签名'):
            manage.validate(self.values)

    def test_auth_keys_without_node(self):
        with mock.patch.object(manage.subprocess, 'run', wraps=manage.subprocess.run) as run:
            values = manage.auth_keys('generate')
            manage.auth_keys('validate', values)
        self.assertTrue(run.call_args_list)
        self.assertTrue(all(call.args[0][0] == 'openssl' for call in run.call_args_list))

    def test_tampered_signature_and_api_key_rejected(self):
        for field in ('ANON_KEY_ASYMMETRIC', 'SUPABASE_SECRET_KEY'):
            values = dict(self.values)
            value = values[field]
            index = value.rfind('.') + 1 if '.' in value else len(value) - 1
            values[field] = value[:index] + ('A' if value[index] != 'A' else 'B') + value[index + 1:]
            with self.assertRaisesRegex(ValueError, '签名'):
                manage.auth_keys('validate', values)

    def test_mismatched_jwks_rejected(self):
        other = manage.auth_keys('generate')
        self.values['JWT_JWKS'] = other['JWT_JWKS']
        with self.assertRaises(ValueError):
            manage.validate(self.values)

    def test_partial_key_group_is_not_regenerated(self):
        path = self.root / '.env'
        path.write_text(path.read_text().replace(self.values['SUPABASE_SECRET_KEY'], ''))
        before = path.read_bytes()
        with self.assertRaisesRegex(ValueError, '不完整'):
            manage.init(self.root)
        self.assertEqual(path.read_bytes(), before)

    def test_api_key_rotation_does_not_change_signing_keys(self):
        other = manage.auth_keys('generate')
        self.values['SUPABASE_PUBLISHABLE_KEY'] = other['SUPABASE_PUBLISHABLE_KEY']
        self.values['SUPABASE_SECRET_KEY'] = other['SUPABASE_SECRET_KEY']
        manage.validate(self.values)

    def test_data_without_env_refuses_regeneration(self):
        data = self.root / 'volumes/db/data'
        data.mkdir(parents=True)
        (data / 'PG_VERSION').write_text('17')
        (self.root / '.env').unlink()
        with self.assertRaisesRegex(ValueError, '已有数据库'):
            manage.init(self.root)

    def test_public_mode_requires_real_configuration(self):
        self.values.update(SUPABASE_PUBLIC_URL='https://api.example.com', API_EXTERNAL_URL='https://api.example.com/auth/v1', SITE_URL='https://app.example.com')
        manage.validate(self.values)
        self.values['ENABLE_EMAIL_AUTOCONFIRM'] = 'true'
        with self.assertRaisesRegex(ValueError, '自动确认'):
            manage.validate(self.values)

    def test_smtp_required_for_public_signup(self):
        self.values.update(SUPABASE_PUBLIC_URL='https://api.example.com', API_EXTERNAL_URL='https://api.example.com/auth/v1', SITE_URL='https://app.example.com', DISABLE_SIGNUP='false')
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
