import contextlib
import io
import os
from pathlib import Path
import shutil
import sys
import subprocess
import tempfile
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import init_demo

USER = '11111111-1111-4111-8111-111111111111'


class InitTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        shutil.copy(init_demo.ROOT / '.env.example', self.root / '.env.example')
        shutil.copytree(init_demo.ROOT / 'caddy', self.root / 'caddy',
                        ignore=shutil.ignore_patterns('Caddyfile'))
        with contextlib.redirect_stdout(io.StringIO()):
            init_demo.manage.init(self.root)
        demo = self.root / 'demoapp'
        demo.mkdir()
        shutil.copy(init_demo.ROOT / 'demoapp/.env.example', demo / '.env.example')
        for app in ('admin', 'todo', 'notes'):
            shutil.copytree(init_demo.ROOT / f'demoapp/{app}/sql', demo / app / 'sql')

    def tearDown(self):
        self.temp.cleanup()

    def run_init(self, schema_exists=False, entered=''):
        def sql_result(values, sql, capture=False):
            return Mock(stdout=('t' if schema_exists or 'auth.users' in sql else 'f') + '\n')
        with patch.object(init_demo.subprocess, 'run') as run, \
                patch.object(init_demo, 'psql', side_effect=sql_result) as sql, \
                patch.object(init_demo.bootstrap_admin, 'create_admin', return_value=USER) as create, \
                patch('builtins.input', return_value=entered) as prompt, \
                contextlib.redirect_stdout(io.StringIO()):
            init_demo.initialize(self.root)
        return run, sql, create, prompt

    def test_first_run_creates_complete_private_env(self):
        _, sql, create, _ = self.run_init()
        path = self.root / 'demoapp/.env'
        values = init_demo.manage.read_env(path)
        root_values = init_demo.manage.read_env(self.root / '.env')
        self.assertEqual(path.stat().st_mode & 0o777, 0o600)
        self.assertEqual(values['ADMIN_USER_IDS'], USER)
        self.assertEqual(values['SUPABASE_PUBLISHABLE_KEY'], root_values['SUPABASE_PUBLISHABLE_KEY'])
        self.assertEqual(values['SUPABASE_SECRET_KEY'], root_values['SUPABASE_SECRET_KEY'])
        self.assertEqual(values['SUPABASE_DOCKER_NETWORK'], 'mybase_default')
        self.assertEqual(values['TRAEFIK_BIND'], '127.0.0.1')
        self.assertIn('app_authorizer:demo-app-authorizer-change-me@db:5432/postgres', values['DATABASE_URL'])
        create.assert_called_once()
        self.assertTrue(any('create schema app_todo;' in c.args[1] for c in sql.call_args_list))
        self.assertTrue(any('create schema app_notes;' in c.args[1] for c in sql.call_args_list))

    def test_init_does_not_modify_or_start_supabase(self):
        root_env = self.root / '.env'
        caddy = self.root / 'caddy/Caddyfile'
        before_env = root_env.read_bytes()
        before_caddy = caddy.read_bytes()
        with patch.object(init_demo.manage, 'init', side_effect=AssertionError('Supabase init forbidden')):
            run, _, _, _ = self.run_init()
        run.assert_not_called()
        self.assertEqual(root_env.read_bytes(), before_env)
        self.assertEqual(caddy.read_bytes(), before_caddy)

    def test_missing_root_env_fails_without_creating_it(self):
        root_env = self.root / '.env'
        root_env.unlink()
        with self.assertRaisesRegex(ValueError, '先自行启动'):
            init_demo.initialize(self.root)
        self.assertFalse(root_env.exists())
        self.assertFalse((self.root / 'demoapp/.env').exists())

    def test_existing_studio_user_skips_creation(self):
        _, _, create, _ = self.run_init(entered=USER)
        create.assert_not_called()

    def test_repeated_init_preserves_data_settings_and_existing_admin(self):
        self.run_init()
        root_path = self.root / '.env'
        init_demo.write_env(root_path, root_path.read_text(),
                            {'COMPOSE_PROJECT_NAME': 'custom',
                             'PGRST_DB_SCHEMAS': 'public,graphql_public,app_crm'})
        demo_path = self.root / 'demoapp/.env'
        init_demo.write_env(demo_path, demo_path.read_text(),
                            {'TRAEFIK_PORT': '9090', 'TODO_HOST': 'todo.example.com',
                             'SUPABASE_DOCKER_NETWORK': ''})
        _, sql, create, prompt = self.run_init(schema_exists=True)
        create.assert_not_called()
        prompt.assert_not_called()
        self.assertFalse(any('create schema app_todo;' in c.args[1] for c in sql.call_args_list))
        self.assertFalse(any('create schema app_notes;' in c.args[1] for c in sql.call_args_list))
        values = init_demo.manage.read_env(demo_path)
        self.assertEqual(values['TRAEFIK_PORT'], '9090')
        self.assertEqual(values['TODO_HOST'], 'todo.example.com')
        self.assertEqual(values['SUPABASE_DOCKER_NETWORK'], 'custom_default')
        self.assertEqual(init_demo.manage.read_env(root_path)['PGRST_DB_SCHEMAS'],
                         'public,graphql_public,app_crm')

    def test_password_sql_literal_and_url_encoding(self):
        self.assertEqual(init_demo.prepare_password("alter role app_authorizer password 'a''b@:/';"), "a'b@:/")
        self.assertEqual(init_demo.quote("a'b@:/", safe=''), 'a%27b%40%3A%2F')

    def test_unconfirmed_user_does_not_write_demo_env(self):
        with patch.object(init_demo.subprocess, 'run'), \
                patch.object(init_demo, 'psql', return_value=Mock(stdout='f\n')), \
                patch('builtins.input', return_value=USER), \
                contextlib.redirect_stdout(io.StringIO()), \
                self.assertRaisesRegex(ValueError, '邮箱未确认'):
            init_demo.initialize(self.root)
        self.assertFalse((self.root / 'demoapp/.env').exists())


class StartScriptTests(unittest.TestCase):
    def test_init_is_consumed_and_runs_before_compose_start(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            shutil.copy(init_demo.ROOT / 'demoapp/start.sh', root / 'start.sh')
            commands = root / 'commands'
            bin_dir = root / 'bin'
            bin_dir.mkdir()
            docker = bin_dir / 'docker'
            docker.write_text('#!/usr/bin/env bash\nprintf "docker %s\\n" "$*" >> "$COMMAND_LOG"\n')
            python = bin_dir / 'python3'
            python.write_text('#!/usr/bin/env bash\nprintf "python %s\\n" "$*" >> "$COMMAND_LOG"\ntouch "$DEMO_ENV"\n')
            docker.chmod(0o755)
            python.chmod(0o755)
            env = {**os.environ, 'PATH': str(bin_dir) + ':' + os.environ['PATH'],
                   'COMMAND_LOG': str(commands), 'DEMO_ENV': str(root / '.env')}
            subprocess.run(['bash', str(root / 'start.sh'), '--force-recreate', '--init'],
                           cwd='/', env=env, check=True, capture_output=True)
            lines = commands.read_text().splitlines()
            self.assertEqual(lines[0], 'docker compose version')
            self.assertEqual(lines[1], f'python {root}/init_demo.py')
            self.assertIn('config --quiet', lines[2])
            self.assertIn('up -d --build --wait --force-recreate', lines[3])
            self.assertFalse(any('--init' in line for line in lines))
            self.assertTrue(lines[4].endswith(' ps'))
