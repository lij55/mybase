-- ONLY in a disposable database; minimal stand-in for Supabase Auth.
create role anon nologin;
create role authenticated nologin;
create schema auth;
grant usage on schema auth to authenticated;
create table auth.users (id uuid primary key);
create function auth.uid() returns uuid language sql stable as $$
  select nullif(current_setting('request.jwt.claim.sub', true), '')::uuid;
$$;
insert into auth.users values
  ('11111111-1111-4111-8111-111111111111'),
  ('22222222-2222-4222-8222-222222222222');

-- Exercise prepare SQL under a non-superuser CREATEROLE account, as in Supabase.
create role demo_prepare_admin nologin createrole;
grant connect on database postgres to demo_prepare_admin with grant option;
