-- Second: standalone business app. Requires admin/sql/001_init.sql.
begin;
create schema app_todo;
comment on schema app_todo is 'Todo 管理';
revoke all on schema app_todo from public, anon;
revoke create on schema app_todo from authenticated;
grant usage on schema app_todo to authenticated;
create table app_todo.todos (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null default auth.uid() references auth.users(id),
  title text not null check (char_length(btrim(title)) between 1 and 1000),
  done boolean not null default false,
  created_at timestamptz not null default now()
);
create index todos_user_id_idx on app_todo.todos(user_id);
revoke all on app_todo.todos from public, anon, authenticated;
grant select, insert, update, delete on app_todo.todos to authenticated;
alter table app_todo.todos enable row level security;
create policy todos_member_owner on app_todo.todos for all to authenticated
  using (user_id = (select auth.uid()) and app_access.can_access_app('app_todo'))
  with check (user_id = (select auth.uid()) and app_access.can_access_app('app_todo'));
notify pgrst, 'reload schema';
commit;
