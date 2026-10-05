// Node's built-in crypto keeps key generation and validation dependency-free.
const crypto = require('node:crypto');
const fs = require('node:fs');
if (Number(process.versions.node.split('.')[0]) < 18) { console.error('Node.js >= 18 required'); process.exit(1); }
function generate() {
  const {privateKey} = crypto.generateKeyPairSync('ec', {namedCurve: 'P-256'});
  const raw = privateKey.export({format: 'jwk'});
  const key = {...raw, kid: crypto.randomUUID(), alg: 'ES256', use: 'sig', key_ops: ['sign', 'verify'], ext: true};
  const {d, ...publicKey} = key;
  publicKey.key_ops = ['verify'];
  const sign = role => {
    const iat = Math.floor(Date.now() / 1000);
    const content = Buffer.from(JSON.stringify({alg: 'ES256', typ: 'JWT', kid: key.kid})).toString('base64url') + '.' + Buffer.from(JSON.stringify({role, iss: 'supabase', iat, exp: iat + 5 * 365 * 86400})).toString('base64url');
    return content + '.' + crypto.sign('sha256', Buffer.from(content), {key: privateKey, dsaEncoding: 'ieee-p1363'}).toString('base64url');
  };
  const opaque = prefix => {
    const content = prefix + crypto.randomBytes(17).toString('base64url').slice(0, 22);
    return content + '_' + crypto.createHash('sha256').update('supabase-self-hosted|' + content).digest('base64url').slice(0, 8);
  };
  return {SUPABASE_PUBLISHABLE_KEY: opaque('sb_publishable_'), SUPABASE_SECRET_KEY: opaque('sb_secret_'), ANON_KEY_ASYMMETRIC: sign('anon'), SERVICE_ROLE_KEY_ASYMMETRIC: sign('service_role'), JWT_KEYS: JSON.stringify([key]), JWT_JWKS: JSON.stringify({keys: [publicKey]})};
}
function validate(v) {
  const keys = JSON.parse(v.JWT_KEYS), jwks = JSON.parse(v.JWT_JWKS);
  if (keys.length !== 1 || jwks.keys.length !== 1) throw Error('expected one ES256 key');
  const key = keys[0], pub = jwks.keys[0];
  if (pub.kty !== 'EC' || pub.crv !== 'P-256' || key.kty !== 'EC' || key.crv !== 'P-256' || key.alg !== 'ES256' || !key.kid || !key.d || pub.d || pub.k || pub.alg !== 'ES256') throw Error('invalid ES256 JWKS');
  const privateKey = crypto.createPrivateKey({key, format: 'jwk'});
  const publicKey = crypto.createPublicKey({key: pub, format: 'jwk'});
  const derived = crypto.createPublicKey(privateKey).export({format: 'jwk'});
  if (derived.x !== pub.x || derived.y !== pub.y || pub.kid !== key.kid) throw Error('key pair mismatch');
  for (const [field, role] of [['ANON_KEY_ASYMMETRIC', 'anon'], ['SERVICE_ROLE_KEY_ASYMMETRIC', 'service_role']]) {
    const parts = v[field].split('.');
    const header = JSON.parse(Buffer.from(parts[0], 'base64url'));
    const payload = JSON.parse(Buffer.from(parts[1], 'base64url'));
    if (parts.length !== 3 || header.alg !== 'ES256' || header.kid !== key.kid || payload.role !== role || payload.exp <= Date.now()/1000 || !crypto.verify('sha256', Buffer.from(parts.slice(0, 2).join('.')), {key: publicKey, dsaEncoding: 'ieee-p1363'}, Buffer.from(parts[2], 'base64url'))) throw Error('invalid internal JWT');
  }
  for (const [field, prefix] of [['SUPABASE_PUBLISHABLE_KEY', 'sb_publishable_'], ['SUPABASE_SECRET_KEY', 'sb_secret_']]) {
    if (!new RegExp('^' + prefix + '[A-Za-z0-9_-]{22}_[A-Za-z0-9_-]{8}$').test(v[field])) throw Error('invalid API key');
    const content = v[field].slice(0, -9);
    const checksum = crypto.createHash('sha256').update('supabase-self-hosted|' + content).digest('base64url').slice(0, 8);
    if (v[field].slice(-8) !== checksum) throw Error('invalid API key checksum');
  }
}
try {
  if (process.argv[2] === 'generate') process.stdout.write(JSON.stringify(generate()));
  else validate(JSON.parse(fs.readFileSync(0, 'utf8')));
} catch { console.error('ES256 密钥、签名或 API key 配置无效'); process.exit(1); }
