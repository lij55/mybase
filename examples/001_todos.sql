-- Run once in Studio SQL Editor or make psql. Application schema example.
begin;
create table public.todos (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null default auth.uid() references auth.users(id) on delete cascade,
  title text not null check (char_length(title) between 1 and 1000),
  done boolean not null default false,
  created_at timestamptz not null default now()
);
create index todos_user_id_idx on public.todos(user_id);
alter table public.todos enable row level security;
revoke all on public.todos from anon, authenticated;
grant select, insert, update, delete on public.todos to authenticated;
create policy todos_select on public.todos for select to authenticated
  using ((select auth.uid()) = user_id);
create policy todos_insert on public.todos for insert to authenticated
  with check ((select auth.uid()) = user_id);
create policy todos_update on public.todos for update to authenticated
  using ((select auth.uid()) = user_id) with check ((select auth.uid()) = user_id);
create policy todos_delete on public.todos for delete to authenticated
  using ((select auth.uid()) = user_id);
-- Enable publication only for tables that need database change subscriptions.
alter publication supabase_realtime add table public.todos;
commit;
