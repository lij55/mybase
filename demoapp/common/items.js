import { api, init, el, node, action } from '/common.js';
const todo = document.title.startsWith('Todo');
async function load() {
  const items = await api('/api/items');
  el('items').replaceChildren();
  el('empty').hidden = items.length !== 0;
  for (const item of items) {
    const row = node('li', undefined, `item${item.done ? ' done' : ''}`);
    if (todo) {
      const checkbox = node('input'); checkbox.type = 'checkbox'; checkbox.checked = item.done;
      checkbox.setAttribute('aria-label', `完成任务：${item.title}`);
      checkbox.addEventListener('change', () => action(checkbox, async () => {
        try { await api(`/api/items/${item.id}`, 'PATCH', { done: checkbox.checked }); await load(); }
        catch (error) { checkbox.checked = item.done; throw error; }
      }));
      row.append(checkbox);
    }
    const content = node('div', item.title || item.content, 'content');
    const remove = node('button', '删除');
    remove.setAttribute('aria-label', `删除${todo ? '任务' : '笔记'}`);
    remove.addEventListener('click', () => action(remove, async () => {
      await api(`/api/items/${item.id}`, 'DELETE'); await load();
    }));
    row.append(content, remove); el('items').append(row);
  }
}
el('add-item').addEventListener('submit', event => {
  event.preventDefault();
  action(el('add'), async () => {
    await api('/api/items', 'POST', { [todo ? 'title' : 'content']: el('content').value });
    el('content').value = ''; await load();
  });
});
el('reload').addEventListener('click', () => action(el('reload'), load));
await init(load);
