"""Run migrations and RLS assertions only in a newly created disposable container."""
import subprocess
import time
import uuid
from pathlib import Path


def main():
    root = Path(__file__).resolve().parents[1]
    name = 'mybase-demo-sql-' + uuid.uuid4().hex[:12]
    image = 'supabase/postgres:17.6.1.136'
    subprocess.run(['docker', 'run', '-d', '--name', name, '--network', 'none', '--user', 'postgres',
                    '--entrypoint', 'bash', image, '-c',
                    'initdb -D /tmp/demo-db -A trust >/tmp/init.log 2>&1 && exec postgres -D /tmp/demo-db -k /tmp -c listen_addresses='],
                   check=True, capture_output=True, text=True)
    try:
        for _ in range(60):
            result = subprocess.run(['docker', 'exec', name, 'pg_isready', '-h', '/tmp', '-U', 'postgres'], capture_output=True)
            if result.returncode == 0:
                break
            time.sleep(0.5)
        else:
            raise RuntimeError('Temporary PostgreSQL did not become ready')
        files = ['tests/sql_fixture.sql', 'admin/sql/001_init.sql', 'admin/sql/001_init.sql',
                 'todo/sql/001_init.sql', 'notes/sql/001_init.sql', 'tests/sql_security.sql']
        for file in files:
            result = subprocess.run(['docker', 'exec', '-i', name, 'psql', '-h', '/tmp', '-U', 'postgres',
                                     '-d', 'postgres', '-v', 'ON_ERROR_STOP=1'],
                                    input=(root / file).read_text(), text=True, capture_output=True)
            if result.returncode:
                raise RuntimeError(file + '\n' + result.stdout + result.stderr)
            print(file + ': OK')
    finally:
        # Only the unique container created above, with no network or mounted data.
        subprocess.run(['docker', 'rm', '-f', name], check=True, capture_output=True)


if __name__ == '__main__':
    main()
