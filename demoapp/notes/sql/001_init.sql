-- Third: standalone business app. Requires admin/sql/001_init.sql.
begin;
create schema app_notes;
comment on schema app_notes is 'Quick Notes';
revoke all on schema app_notes from public, anon;
revoke create on schema app_notes from authenticated;
grant usage on schema app_notes to authenticated;
create table app_notes.notes (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null default auth.uid() references auth.users(id),
  content text not null check (char_length(btrim(content)) between 1 and 10000),
  created_at timestamptz not null default now()
);
create index notes_user_id_idx on app_notes.notes(user_id);
revoke all on app_notes.notes from public, anon, authenticated;
grant select, insert, delete on app_notes.notes to authenticated;
alter table app_notes.notes enable row level security;
create policy notes_member_owner on app_notes.notes for all to authenticated
  using (user_id = (select auth.uid()) and app_access.can_access_app('app_notes'))
  with check (user_id = (select auth.uid()) and app_access.can_access_app('app_notes'));
notify pgrst, 'reload schema';
commit;
