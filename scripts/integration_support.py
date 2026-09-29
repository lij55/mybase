"""Dependency-free HTTP, SQL and WebSocket helpers for local acceptance tests."""
import base64
import hashlib
import http.client
import json
import secrets
import socket
import struct
import subprocess
import time
import urllib.error
import urllib.request

import manage


class Instance:
    def __init__(self):
        self.values = manage.read_env(manage.ROOT / '.env')
        manage.validate(self.values)
        self.base = f"http://127.0.0.1:{self.values['PUBLIC_API_PORT']}"
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def request(self, method, path, data=None, token=None, admin=False,
                raw=False, codes=(200,), headers=None, authenticated=True, base=None):
        key = self.values['SERVICE_ROLE_KEY' if admin else 'ANON_KEY']
        request_headers = {'apikey': key, 'Authorization': 'Bearer ' + (token or key)} if authenticated else {}
        if data is not None:
            request_headers['Content-Type'] = 'text/plain' if raw else 'application/json'
            data = data if raw else json.dumps(data).encode()
        if path.startswith('/rest/') and method in ('POST', 'PATCH', 'DELETE'):
            request_headers['Prefer'] = 'return=representation'
        request_headers.update(headers or {})
        request = urllib.request.Request((base or self.base) + path, data=data,
                                         headers=request_headers, method=method)
        try:
            with self.opener.open(request, timeout=15) as response:
                status, body, response_headers = response.status, response.read(), response.headers
        except urllib.error.HTTPError as error:
            status, body, response_headers = error.code, error.read(), error.headers
        except (OSError, urllib.error.URLError, http.client.HTTPException):
            raise AssertionError('Local HTTP request failed; run make up and inspect make logs') from None
        if status not in codes:
            # URLs may contain signed tokens; response bodies may contain sessions.
            raise AssertionError(f'{method} request returned HTTP {status}, expected {codes}; details omitted')
        try:
            decoded = body if raw else json.loads(body) if body else None
        except (ValueError, UnicodeError):
            raise AssertionError('Expected a JSON response; body omitted') from None
        return decoded, response_headers

    def api(self, *args, **kwargs):
        return self.request(*args, **kwargs)[0]

    def sql(self, statement):
        try:
            result = manage.compose(self.values, ['exec', '-T', 'db', 'psql', '-X', '-qAt',
                '-v', 'ON_ERROR_STOP=1', '-U', 'postgres', '-d', 'postgres'],
                input=statement, capture_output=True, text=True, timeout=30)
        except (OSError, subprocess.SubprocessError):
            raise AssertionError('SQL command failed; inspect database logs (captured output omitted)') from None
        return result.stdout.strip()

    def wait_for_table(self, table, token):
        deadline = time.monotonic() + 15
        while True:
            try:
                self.api('GET', '/rest/v1/' + table, token=token)
                return
            except AssertionError:
                if time.monotonic() >= deadline:
                    raise
                time.sleep(0.2)


class WebSocket:
    """Small RFC 6455 JSON client: masking, fragmentation, ping/pong and deadlines."""
    def __init__(self, instance):
        self.sock = socket.create_connection(('127.0.0.1', int(instance.values['PUBLIC_API_PORT'])), timeout=15)
        self.buffer = b''
        try:
            key = base64.b64encode(secrets.token_bytes(16)).decode()
            path = '/realtime/v1/websocket?apikey=' + instance.values['ANON_KEY'] + '&vsn=1.0.0'
            self.sock.sendall((f'GET {path} HTTP/1.1\r\nHost: localhost\r\nUpgrade: websocket\r\n'
                f'Connection: Upgrade\r\nSec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n').encode())
            while b'\r\n\r\n' not in self.buffer:
                chunk = self.sock.recv(4096)
                if not chunk:
                    raise AssertionError('WebSocket handshake closed early')
                self.buffer += chunk
                if len(self.buffer) > 65536:
                    raise AssertionError('Oversized WebSocket handshake')
            header, self.buffer = self.buffer.split(b'\r\n\r\n', 1)
            expected = base64.b64encode(hashlib.sha1((key + '258EAFA5-E914-47DA-95CA-C5AB0DC85B11').encode()).digest())
            fields = {name.lower(): value.strip() for name, value in
                      (line.split(b':', 1) for line in header.split(b'\r\n')[1:])}
            if b' 101 ' not in header.split(b'\r\n')[0] or fields.get(b'sec-websocket-accept') != expected:
                raise AssertionError('Invalid WebSocket upgrade')
        except Exception:
            self.close()
            raise

    def close(self):
        self.sock.close()

    def send_frame(self, payload, opcode=1):
        mask = secrets.token_bytes(4)
        size = len(payload)
        length = bytes([0x80 | size]) if size < 126 else bytes([0x80 | 126]) + struct.pack('!H', size)
        self.sock.sendall(bytes([0x80 | opcode]) + length + mask + bytes(c ^ mask[i % 4] for i, c in enumerate(payload)))

    def send(self, topic, event, payload, ref):
        self.send_frame(json.dumps(dict(topic=topic, event=event, payload=payload, ref=ref)).encode())

    def read_exact(self, size, deadline):
        while len(self.buffer) < size:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError('Realtime message deadline exceeded')
            self.sock.settimeout(remaining)
            data = self.sock.recv(4096)
            if not data:
                raise AssertionError('Realtime connection closed')
            self.buffer += data
        result, self.buffer = self.buffer[:size], self.buffer[size:]
        return result

    def receive(self, deadline):
        message = b''
        while True:
            first, second = self.read_exact(2, deadline)
            size = second & 127
            if size in (126, 127):
                size = int.from_bytes(self.read_exact(2 if size == 126 else 8, deadline), 'big')
            if size > 1048576 or second & 128:
                raise AssertionError('Invalid or oversized server WebSocket frame')
            payload = self.read_exact(size, deadline)
            opcode = first & 15
            if opcode == 8:
                raise AssertionError('Realtime sent close frame')
            if opcode == 9:
                self.send_frame(payload, opcode=10)
                continue
            if opcode == 10:
                continue
            if opcode not in (0, 1):
                raise AssertionError('Unexpected WebSocket opcode')
            message += payload
            if first & 128:
                return json.loads(message)

    def until(self, predicate, timeout=15):
        deadline = time.monotonic() + timeout
        while True:
            message = self.receive(deadline)
            if message.get('event') == 'phx_error':
                raise AssertionError('Realtime channel error')
            if predicate(message):
                return message

    def join(self, topic, token, changes=None):
        self.send(topic, 'phx_join', {'config': {'broadcast': {'ack': True, 'self': True},
            'presence': {'key': 'probe'}, 'postgres_changes': changes or []}, 'access_token': token}, 'join')
        reply = self.until(lambda m: m.get('event') == 'phx_reply' and m.get('ref') == 'join')
        if reply['payload']['status'] != 'ok':
            raise AssertionError('Realtime join rejected')
        if changes:
            system = self.until(lambda m: m.get('event') == 'system')
            if system['payload'].get('status') != 'ok':
                raise AssertionError('Realtime database subscription failed')
