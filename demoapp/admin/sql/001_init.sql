-- First: shared authorization objects. Execute as postgres, not an app user.
begin;
create schema if not exists app_access;
comment on schema app_access is 'Reserved internal authorization schema; never expose through Data API';
revoke all on schema app_access from public, anon;
revoke create on schema app_access from authenticated;
grant usage on schema app_access to authenticated;

create table if not exists app_access.memberships (
  app_id text not null,
  user_id uuid not null references auth.users(id) on delete cascade,
  primary key (app_id, user_id)
);
-- Upgrade the previous documentation example that allowed only app_a/app_b.
alter table app_access.memberships drop constraint if exists memberships_app_id_check;
alter table app_access.memberships add constraint memberships_app_id_check
  check (app_id ~ '^app_[a-z][a-z0-9_]{0,58}$' and app_id <> 'app_access');
create index if not exists memberships_user_id_idx on app_access.memberships (user_id);
revoke all on app_access.memberships from public, anon, authenticated;
grant select on app_access.memberships to authenticated;
alter table app_access.memberships enable row level security;
drop policy if exists memberships_read_own on app_access.memberships;
create policy memberships_read_own on app_access.memberships
  for select to authenticated using (user_id = (select auth.uid()));

create or replace function app_access.can_access_app(target_app text)
returns boolean language sql stable security invoker
set search_path = pg_catalog
as $$
  select exists (
    select 1 from app_access.memberships m
    where m.app_id = target_app and m.user_id = (select auth.uid())
  );
$$;
revoke all on function app_access.can_access_app(text) from public, anon;
grant execute on function app_access.can_access_app(text) to authenticated;

-- Capability role, intentionally NOLOGIN. Grant to a separate login below.
do $$ begin
  if not exists (select 1 from pg_roles where rolname = 'app_authorizer') then
    create role app_authorizer nologin;
  end if;
end $$;
grant usage on schema app_access to app_authorizer;
grant select, insert, delete on app_access.memberships to app_authorizer;
drop policy if exists memberships_manage on app_access.memberships;
create policy memberships_manage on app_access.memberships
  for all to app_authorizer using (true) with check (true);
notify pgrst, 'reload schema';
commit;
