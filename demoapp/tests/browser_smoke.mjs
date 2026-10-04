// UI smoke against running demo routes, with intercepted API fixtures (no real users/data).
// Start Chromium with --remote-debugging-port=9223 before running this script.
import { writeFile } from 'node:fs/promises';
const tabs = await (await fetch('http://127.0.0.1:9223/json/list')).json();
const socket = new WebSocket(tabs.find(tab => tab.type === 'page').webSocketDebuggerUrl);
await new Promise(resolve => socket.addEventListener('open', resolve, { once: true }));
let id = 0;
const pending = new Map(), errors = [], calls = [];
function send(method, params = {}) {
  const requestId = ++id;
  return new Promise((resolve, reject) => {
    pending.set(requestId, { resolve, reject });
    socket.send(JSON.stringify({ id: requestId, method, params }));
  });
}
const U1 = '11111111-1111-4111-8111-111111111111', U2 = '22222222-2222-4222-8222-222222222222';
const apps = [{ id: 'app_todo', name: 'Todo 管理' }, { id: 'app_notes', name: 'Quick Notes' }];
let users = [{ id: U1, email: 'admin@example.com' }], grants = new Set(), items = [];
socket.addEventListener('message', async event => {
  const message = JSON.parse(event.data);
  if (message.id) {
    const request = pending.get(message.id); pending.delete(message.id);
    if (message.error) request.reject(new Error(message.error.message)); else request.resolve(message.result);
  }
  if (message.method === 'Runtime.exceptionThrown') errors.push(message.params.exceptionDetails.text);
  if (message.method !== 'Fetch.requestPaused') return;
  const { requestId, request } = message.params;
  try {
    const url = new URL(request.url), path = url.pathname, method = request.method;
    const body = request.postData ? JSON.parse(request.postData) : {};
    calls.push({ path, method, body });
    let result;
    if (path === '/api/login' || path === '/api/refresh') result = { access_token: 'fixture-token', refresh_token: 'fixture-refresh', expires_in: 3600 };
    else if (path === '/api/me') result = { id: U1, email: 'admin@example.com' };
    else if (path === '/api/apps') result = { apps };
    else if (path === '/api/users' && method === 'GET') result = { users, page: 1 };
    else if (path === '/api/users') { result = { id: U2, email: body.email }; users.push(result); }
    else if (path === '/api/memberships' && method === 'GET') result = { app_ids: [...grants] };
    else if (path === '/api/memberships') { method === 'POST' ? grants.add(body.app_id) : grants.delete(body.app_id); result = { ok: true }; }
    else if (path === '/api/items' && method === 'GET') result = items;
    else if (path === '/api/items') { result = [{ id: U2, ...body, done: false }]; items.push(result[0]); }
    else if (path.startsWith('/api/items/') && method === 'PATCH') { items[0].done = body.done; result = items; }
    else if (path.startsWith('/api/items/')) { result = items; items = []; }
    else if (path === '/api/logout') result = { ok: true };
    else throw new Error('Unexpected fixture request ' + path);
    await send('Fetch.fulfillRequest', { requestId, responseCode: 200,
      responseHeaders: [{ name: 'Content-Type', value: 'application/json' }], body: Buffer.from(JSON.stringify(result)).toString('base64') });
  } catch (error) { errors.push(error.message); await send('Fetch.failRequest', { requestId, errorReason: 'Failed' }); }
});
async function evaluate(expression) {
  const result = await send('Runtime.evaluate', { expression, returnByValue: true, awaitPromise: true });
  if (result.exceptionDetails) throw new Error(result.exceptionDetails.text);
  return result.result.value;
}
async function until(expression) {
  for (let attempt = 0; attempt < 100; attempt++) {
    if (await evaluate(expression)) return;
    await new Promise(resolve => setTimeout(resolve, 50));
  }
  throw new Error('UI timed out: ' + expression + '; message=' + await evaluate("document.querySelector('#message')?.textContent"));
}
async function open(host) {
  await send('Page.navigate', { url: `http://${host}.localhost:8090/` });
  await until("document.querySelector('#login-form') && document.readyState === 'complete'");
  await evaluate("sessionStorage.clear(); document.querySelector('#email').value='admin@example.com'; document.querySelector('#password').value='long-password-123'; document.querySelector('#login-form').requestSubmit()");
  await until("document.querySelector('#workspace')?.hidden === false");
}
try {
  await send('Page.enable'); await send('Runtime.enable');
  await send('Fetch.enable', { patterns: [{ urlPattern: '*://*.localhost:8090/api/*' }] });
  await open('authz');
  await until("document.querySelector('#users button')");
  await evaluate("document.querySelector('#new-email').value='new@example.com'; document.querySelector('#new-password').value='long-password-123'; document.querySelector('#create-user').requestSubmit()");
  await until("document.querySelector('#permissions input') && document.querySelector('#selected-user').textContent.includes('new@example.com')");
  await evaluate("document.querySelector('#permissions input').click()");
  await until("document.querySelector('#message').textContent.includes('已授予')");
  if (!grants.has('app_todo')) throw new Error('Grant not submitted');
  await evaluate("document.querySelector('#permissions input').click()");
  await until("document.querySelector('#message').textContent.includes('已撤销')");
  if (grants.size) throw new Error('Revoke not submitted');
  apps.push({ id: 'app_third', name: '应用三' });
  await evaluate("document.querySelector('#reload-apps').click()");
  await until("document.querySelectorAll('#permissions input').length === 3");
  await writeFile('/tmp/mybase-demo-admin.png', Buffer.from((await send('Page.captureScreenshot')).data, 'base64'));
  console.log('Admin UI: create user, grant, revoke, discover new App: OK');
  for (const kind of ['todo', 'notes']) {
    items = [];
    await open(kind);
    await evaluate("document.querySelector('#content').value='测试内容 <script>alert(1)</script>'; document.querySelector('#add-item').requestSubmit()");
    await until("document.querySelectorAll('#items li').length === 1");
    if (await evaluate("document.querySelector('#items script') !== null")) throw new Error('Unsafe content rendering');
    if (kind === 'todo') {
      await evaluate("document.querySelector('#items input').click()");
      await until("document.querySelector('#items li')?.classList.contains('done')");
    }
    await evaluate("document.querySelector('#items button').click()");
    await until("document.querySelectorAll('#items li').length === 0");
    await evaluate("const v=JSON.parse(sessionStorage.getItem('mybase-session')); v.expires_at=1; sessionStorage.setItem('mybase-session', JSON.stringify(v)); location.reload()");
    await until("document.querySelector('#workspace')?.hidden === false && JSON.parse(sessionStorage.getItem('mybase-session'))?.expires_at > Date.now()/1000");
    console.log(kind + ' UI: add, ' + (kind === 'todo' ? 'complete, ' : '') + 'delete, expired-session refresh: OK');
  }
  if (!calls.some(call => call.path === '/api/refresh')) throw new Error('Refresh was not exercised');
  if (errors.length) throw new Error(errors.join('; '));
  console.log('Browser console: no uncaught exceptions');
} finally { socket.close(); }
