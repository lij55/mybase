let session = null;
try { session = JSON.parse(sessionStorage.getItem('mybase-session')); } catch { sessionStorage.removeItem('mybase-session'); }
let refreshPromise;
export const el = id => document.getElementById(id);
export function message(text, bad = false) {
  el('message').textContent = text;
  el('message').classList.toggle('error', bad);
}
function save(value) {
  if (value && !value.expires_at) value.expires_at = Math.floor(Date.now() / 1000) + (value.expires_in || 3600);
  session = value;
  if (value) sessionStorage.setItem('mybase-session', JSON.stringify(value));
  else sessionStorage.removeItem('mybase-session');
}
async function request(path, method, body, token) {
  const response = await fetch(path, {
    method, headers: { 'Content-Type': 'application/json', ...(token ? { Authorization: `Bearer ${token}` } : {}) },
    ...(method === 'GET' ? {} : { body: JSON.stringify(body || {}) }),
  });
  const result = await response.json();
  if (!response.ok) {
    const error = new Error(result.error || '请求失败'); error.status = response.status; throw error;
  }
  return result;
}
export async function api(path, method = 'GET', body = {}) {
  if (session && session.expires_at * 1000 < Date.now() + 30000) {
    refreshPromise ||= request('/api/refresh', 'POST', { refresh_token: session.refresh_token })
      .then(save).catch(error => { save(null); throw error; }).finally(() => { refreshPromise = null; });
    await refreshPromise;
  }
  return request(path, method, body, session?.access_token);
}
export function node(tag, text, className) {
  const element = document.createElement(tag);
  if (text !== undefined) element.textContent = text;
  if (className) element.className = className;
  return element;
}
export async function action(button, work) {
  button.disabled = true; message('');
  try { await work(); } catch (error) { message(error.message, true); }
  finally { button.disabled = false; }
}
export async function init(onLogin) {
  const show = async () => {
    const user = await api('/api/me');
    await onLogin(user);
    el('identity').textContent = user.email || user.id;
    el('login').hidden = true; el('workspace').hidden = false; el('logout').hidden = false;
  };
  el('login-form').addEventListener('submit', event => {
    event.preventDefault();
    action(el('sign-in'), async () => {
      save(await request('/api/login', 'POST', { email: el('email').value, password: el('password').value }));
      el('password').value = '';
      try { await show(); } catch (error) { save(null); throw error; }
    });
  });
  el('logout').addEventListener('click', () => action(el('logout'), async () => {
    try { await api('/api/logout', 'POST'); } finally { save(null); location.reload(); }
  }));
  if (session) {
    try { await show(); } catch (error) {
      save(null); el('login').hidden = false; el('workspace').hidden = true; el('logout').hidden = true;
      message(error.message, true);
    }
  }
}
