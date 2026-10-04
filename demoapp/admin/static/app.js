import { api, init, el, node, action, message } from '/common.js';
let apps = [], users = [], selected = null, page = 1;

async function loadUsers() {
  const result = await api(`/api/users?page=${page}`);
  users = result.users;
  el('page').textContent = `第 ${page} 页`;
  el('previous').disabled = page === 1;
  el('next').disabled = users.length < 50;
  el('users').replaceChildren();
  if (!users.length) el('users').append(node('p', '本页暂无用户。', 'muted'));
  for (const user of users) {
    const button = node('button', user.email || '无邮箱用户', 'user');
    button.type = 'button';
    button.classList.toggle('selected', user.id === selected?.id);
    button.append(node('small', user.id));
    button.addEventListener('click', () => action(button, async () => {
      selected = user;
      await loadPermissions();
      for (const row of el('users').children) row.classList.toggle('selected', row === button);
    }));
    el('users').append(button);
  }
}
async function loadApps() {
  apps = (await api('/api/apps')).apps;
  await loadPermissions();
}
async function loadPermissions() {
  const user = selected;
  el('permissions').replaceChildren();
  if (!user) return;
  el('selected-user').textContent = `${user.email || user.id} 的应用权限`;
  const granted = new Set((await api(`/api/memberships?user_id=${encodeURIComponent(user.id)}`)).app_ids);
  if (selected?.id !== user.id) return;
  el('permissions').replaceChildren();
  const known = new Set(apps.map(app => app.id));
  const all = [...apps, ...[...granted].filter(id => !known.has(id)).map(id => ({ id, name: `${id}（schema 已移除）`, removed: true }))];
  if (!all.length) el('permissions').append(node('p', '尚未发现业务应用，请先执行应用 SQL，再点击“发现应用”。', 'muted'));
  for (const app of all) {
    const label = node('label', undefined, 'permission');
    const checkbox = node('input'); checkbox.type = 'checkbox'; checkbox.checked = granted.has(app.id);
    const text = node('div', app.name); text.append(node('small', ` / ${app.id}`, 'muted'));
    checkbox.addEventListener('change', () => {
      const enable = checkbox.checked;
      action(checkbox, async () => {
        try {
          await api('/api/memberships', enable ? 'POST' : 'DELETE', { user_id: user.id, app_id: app.id });
          message(`${enable ? '已授予' : '已撤销'} ${app.name} 的访问权`);
          if (app.removed) await loadPermissions();
        } catch (error) { checkbox.checked = !enable; throw error; }
      });
    });
    label.append(checkbox, text); el('permissions').append(label);
  }
}
el('create-user').addEventListener('submit', event => {
  event.preventDefault();
  action(el('create'), async () => {
    const user = await api('/api/users', 'POST', { email: el('new-email').value, password: el('new-password').value });
    el('new-password').value = ''; el('new-email').value = '';
    selected = user; page = 1;
    await loadUsers(); await loadPermissions();
    message(`账号已创建：${user.email}。请为其勾选应用权限。`);
  });
});
el('reload-users').addEventListener('click', () => action(el('reload-users'), loadUsers));
el('reload-apps').addEventListener('click', () => action(el('reload-apps'), loadApps));
el('previous').addEventListener('click', () => action(el('previous'), async () => { page--; await loadUsers(); }).then(() => { el('previous').disabled = page === 1; }));
el('next').addEventListener('click', () => action(el('next'), async () => { page++; await loadUsers(); }).then(() => { el('next').disabled = users.length < 50; }));
await init(async () => { await loadApps(); await loadUsers(); });
