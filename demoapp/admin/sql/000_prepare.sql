-- Run as postgres before 001_init.sql. No interactive input is required.
-- Demo password is stored below. Change it before deployment and use the same
-- password (URL-encoded) in demoapp/.env DATABASE_URL.
-- This is a PostgreSQL login, NOT a Supabase Auth user.
begin;
do $$ begin
  if not exists (select 1 from pg_roles where rolname = 'app_authorizer') then
    create role app_authorizer;
  end if;
end $$;
alter role app_authorizer with login inherit nosuperuser nocreatedb
  nocreaterole noreplication nobypassrls
  password 'demo-app-authorizer-change-me';
grant connect on database postgres to app_authorizer;
-- Schema/table privileges and RLS policies are granted by 001_init.sql.
commit;
