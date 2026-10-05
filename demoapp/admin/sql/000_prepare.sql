-- Run as postgres before 001_init.sql. No interactive input is required.
-- Demo password is stored below. Change it before deployment and use the same
-- password (URL-encoded) in demoapp/.env DATABASE_URL.
-- This is a PostgreSQL login, NOT a Supabase Auth user.
begin;
do $$ begin
  if not exists (select 1 from pg_roles where rolname = 'app_authorizer') then
    create role app_authorizer;
  end if;
  -- New roles have no elevated attributes by default. Existing roles must
  -- already be restricted: Supabase postgres cannot change SUPERUSER/BYPASSRLS.
  if exists (select 1 from pg_roles where rolname = 'app_authorizer'
    and (rolsuper or rolcreatedb or rolcreaterole or rolreplication or rolbypassrls)) then
    raise exception 'app_authorizer has elevated privileges; use a restricted role before initializing';
  end if;
end $$;
alter role app_authorizer with login inherit
  password 'demo-app-authorizer-change-me';
grant connect on database postgres to app_authorizer;
-- Schema/table privileges and RLS policies are granted by 001_init.sql.
commit;
