"""Generate and validate Supabase ES256 credentials using Python standard library and OpenSSL."""
import base64
import hashlib
import hmac
import json
import re
import secrets
import time
import uuid
import os
from pathlib import Path
import subprocess
import tempfile


def _openssl(*args, data=None):
    try:
        return subprocess.run(['openssl', *args], input=data, capture_output=True, check=True).stdout
    except FileNotFoundError:
        raise ValueError('密钥初始化与校验需要 openssl，请安装系统 OpenSSL 软件包') from None
    except subprocess.CalledProcessError:
        raise ValueError('ES256 密钥、签名或 API key 配置无效') from None


# DER encoding only; all elliptic-curve and signature operations use OpenSSL.
_P256_OID = bytes.fromhex('06082a8648ce3d030107')
_SPKI_PREFIX = bytes.fromhex('3059301306072a8648ce3d020106082a8648ce3d03010703420004')


def _der(tag, value):
    length = len(value)
    size = length.to_bytes((length.bit_length() + 7) // 8 or 1, 'big')
    return bytes([tag]) + (bytes([length]) if length < 128 else bytes([128 + len(size)]) + size) + value


def _parts(data, tag):
    if len(data) < 2 or data[0] != tag:
        raise ValueError('invalid DER tag')
    size, start = data[1], 2
    if size & 128:
        count = size & 127
        if not count or count > 4 or len(data) < 2 + count:
            raise ValueError('invalid DER length')
        size = int.from_bytes(data[2:2 + count], 'big')
        start += count
    end = start + size
    if end > len(data):
        raise ValueError('truncated DER')
    return data[start:end], data[end:]


def _private_der(secret):
    return _der(0x30, bytes.fromhex('020101') + _der(4, secret) + _der(0xa0, _P256_OID))


def _public_coordinates(der):
    if len(der) != len(_SPKI_PREFIX) + 64 or not der.startswith(_SPKI_PREFIX):
        raise ValueError('invalid P-256 public key')
    return der[-64:-32], der[-32:]


def _signature_raw(der):
    content, rest = _parts(der, 0x30)
    r, content = _parts(content, 2)
    s, content = _parts(content, 2)
    if rest or content or not r or not s or r[0] & 128 or s[0] & 128:
        raise ValueError('invalid ECDSA signature')
    return int.from_bytes(r, 'big').to_bytes(32, 'big') + int.from_bytes(s, 'big').to_bytes(32, 'big')


def _signature_der(raw):
    if len(raw) != 64:
        raise ValueError('invalid signature length')
    def integer(part):
        part = part.lstrip(b'\x00') or b'\x00'
        return _der(2, (b'\x00' if part[0] & 128 else b'') + part)
    return _der(0x30, integer(raw[:32]) + integer(raw[32:]))


def _write_temp(root, name, data):
    path = Path(root) / name
    with path.open('xb') as stream:
        os.chmod(path, 0o600)
        stream.write(data)
    return str(path)


def _encode(value):
    return base64.urlsafe_b64encode(value).rstrip(b'=').decode('ascii')


def _decode(value):
    return base64.b64decode(value + '=' * (-len(value) % 4), altchars=b'-_', validate=True)


def _json(value):
    return json.dumps(value, separators=(',', ':'))


def generate():
    private = _openssl('ecparam', '-name', 'prime256v1', '-genkey', '-noout', '-outform', 'DER')
    content, rest = _parts(private, 0x30)
    version, content = _parts(content, 2)
    secret, content = _parts(content, 4)
    if rest or version != b'\x01' or len(secret) != 32:
        raise ValueError('invalid P-256 private key')
    public = _openssl('ec', '-inform', 'DER', '-pubout', '-outform', 'DER', data=private)
    x, y = _public_coordinates(public)
    key = dict(kty='EC', crv='P-256', x=_encode(x), y=_encode(y),
               d=_encode(secret), kid=str(uuid.uuid4()), alg='ES256',
               use='sig', key_ops=['sign', 'verify'], ext=True)
    pub = {k: v for k, v in key.items() if k != 'd'}
    pub['key_ops'] = ['verify']

    def sign(role):
        iat = int(time.time())
        content = '.'.join(_encode(_json(v).encode()) for v in (
            dict(alg='ES256', typ='JWT', kid=key['kid']),
            dict(role=role, iss='supabase', iat=iat, exp=iat + 5 * 365 * 86400)))
        with tempfile.TemporaryDirectory(prefix='mybase-auth-') as root:
            path = _write_temp(root, 'private.der', private)
            signature = _openssl('dgst', '-sha256', '-sign', path, '-keyform', 'DER', data=content.encode())
        return content + '.' + _encode(_signature_raw(signature))

    def opaque(prefix):
        content = prefix + _encode(secrets.token_bytes(17))[:22]
        return content + '_' + _checksum(content)

    return dict(SUPABASE_PUBLISHABLE_KEY=opaque('sb_publishable_'),
                SUPABASE_SECRET_KEY=opaque('sb_secret_'), ANON_KEY_ASYMMETRIC=sign('anon'),
                SERVICE_ROLE_KEY_ASYMMETRIC=sign('service_role'),
                JWT_KEYS=_json([key]), JWT_JWKS=_json({'keys': [pub]}))


def _checksum(content):
    return _encode(hashlib.sha256(('supabase-self-hosted|' + content).encode()).digest())[:8]


def validate(values):
    _openssl('version')
    try:
        keys = json.loads(values['JWT_KEYS'])
        pubs = json.loads(values['JWT_JWKS'])['keys']
        if len(keys) != 1 or len(pubs) != 1:
            raise ValueError('expected one ES256 key')
        key, pub = keys[0], pubs[0]
        for item in (key, pub):
            if item['kty'] != 'EC' or item['crv'] != 'P-256' or item['alg'] != 'ES256' or not item['kid']:
                raise ValueError('invalid ES256 key')
        if 'd' in pub or 'k' in pub or pub['kid'] != key['kid']:
            raise ValueError('invalid public key')

        def coordinate(value):
            raw = _decode(value)
            if len(raw) != 32:
                raise ValueError('invalid P-256 coordinate')
            return raw

        private = _private_der(coordinate(key['d']))
        derived = _openssl('ec', '-inform', 'DER', '-pubout', '-outform', 'DER', data=private)
        public = _SPKI_PREFIX + coordinate(pub['x']) + coordinate(pub['y'])
        if derived != public or coordinate(key['x']) != coordinate(pub['x']) or coordinate(key['y']) != coordinate(pub['y']):
            raise ValueError('key pair mismatch')
        for field, role in (('ANON_KEY_ASYMMETRIC', 'anon'), ('SERVICE_ROLE_KEY_ASYMMETRIC', 'service_role')):
            header_raw, payload_raw, signature_raw = values[field].split('.')
            header, payload = json.loads(_decode(header_raw)), json.loads(_decode(payload_raw))
            if header['alg'] != 'ES256' or header['kid'] != key['kid'] or payload['role'] != role or payload['exp'] <= time.time():
                raise ValueError('invalid internal JWT')
            signature = _signature_der(_decode(signature_raw))
            with tempfile.TemporaryDirectory(prefix='mybase-auth-') as root:
                public_path = _write_temp(root, 'public.der', public)
                signature_path = _write_temp(root, 'signature.der', signature)
                _openssl('dgst', '-sha256', '-verify', public_path, '-keyform', 'DER',
                         '-signature', signature_path, data=(header_raw + '.' + payload_raw).encode())
        for field, prefix in (('SUPABASE_PUBLISHABLE_KEY', 'sb_publishable_'), ('SUPABASE_SECRET_KEY', 'sb_secret_')):
            value = values[field]
            if not re.fullmatch(prefix + r'[A-Za-z0-9_-]{22}_[A-Za-z0-9_-]{8}', value) or not hmac.compare_digest(value[-8:], _checksum(value[:-9])):
                raise ValueError('invalid API key')
    except Exception:
        raise ValueError('ES256 密钥、签名或 API key 配置无效') from None
