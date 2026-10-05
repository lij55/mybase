-- ONLY after the fixtures, prepare script and migrations in a disposable database.
do $$ begin
  if not exists (select 1 from pg_roles where rolname = 'app_authorizer'
    and rolcanlogin and rolinherit and not rolsuper and not rolcreatedb
    and not rolcreaterole and not rolreplication and not rolbypassrls) then
    raise exception 'Prepared authorizer must be a restricted login';
  end if;
  if not exists (select 1 from pg_authid where rolname = 'app_authorizer'
    and rolpassword is not null) then
    raise exception 'Prepared authorizer password missing';
  end if;
end $$;
insert into app_access.memberships values
  ('app_todo', '11111111-1111-4111-8111-111111111111'),
  ('app_notes', '22222222-2222-4222-8222-222222222222');

set role authenticated;
select set_config('request.jwt.claim.sub', '11111111-1111-4111-8111-111111111111', false);
insert into app_todo.todos(title) values ('U1 task');
update app_todo.todos set done = true;
do $$ begin
  if (select count(*) from app_todo.todos where done) <> 1 then
    raise exception 'Authorized todo CRUD failed';
  end if;
  if (select count(*) from app_access.memberships) <> 1 then
    raise exception 'Membership RLS exposes other users';
  end if;
  begin
    insert into app_notes.notes(content) values ('unauthorized');
    raise exception 'Cross-app write succeeded';
  exception when insufficient_privilege then null;
  end;
  begin
    insert into app_todo.todos(title, user_id)
      values ('spoof', '22222222-2222-4222-8222-222222222222');
    raise exception 'Spoofed owner write succeeded';
  exception when insufficient_privilege then null;
  end;
  begin
    insert into app_access.memberships values ('app_notes', auth.uid());
    raise exception 'User granted their own membership';
  exception when insufficient_privilege then null;
  end;
end $$;

select set_config('request.jwt.claim.sub', '22222222-2222-4222-8222-222222222222', false);
insert into app_notes.notes(content) values ('U2 note');
do $$ begin
  if (select count(*) from app_todo.todos) <> 0 then
    raise exception 'Cross-app read leaked rows';
  end if;
end $$;
reset role;
-- Grant same App to U2: still cannot see U1's personal rows.
insert into app_access.memberships values ('app_todo', '22222222-2222-4222-8222-222222222222');
set role authenticated;
do $$ begin
  if (select count(*) from app_todo.todos) <> 0 then
    raise exception 'Cross-user read leaked rows';
  end if;
end $$;
reset role;

set role app_authorizer;
delete from app_access.memberships where app_id = 'app_todo'
  and user_id = '11111111-1111-4111-8111-111111111111';
do $$ begin
  begin
    perform count(*) from app_notes.notes;
    raise exception 'Authorization DB role can read business data';
  exception when insufficient_privilege then null;
  end;
end $$;
reset role;

set role authenticated;
select set_config('request.jwt.claim.sub', '11111111-1111-4111-8111-111111111111', false);
do $$ begin
  if (select count(*) from app_todo.todos) <> 0 then
    raise exception 'Revocation did not restrict reads';
  end if;
  begin
    insert into app_todo.todos(title) values ('revoked');
    raise exception 'Revocation did not restrict writes';
  exception when insufficient_privilege then null;
  end;
end $$;
reset role;

-- New App requires no CHECK-enum update. Discovery excludes app_access.
create schema app_third;
create schema app_fourth;
set role app_authorizer;
insert into app_access.memberships values ('app_third', '11111111-1111-4111-8111-111111111111');
do $$ begin
  if (select count(*) from pg_namespace
      where nspname ~ '^app_[a-z][a-z0-9_]{0,58}$' and nspname <> 'app_access') <> 4 then
    raise exception 'Automatic discovery failed';
  end if;
end $$;
reset role;
select 'SQL security checks passed' as result;
