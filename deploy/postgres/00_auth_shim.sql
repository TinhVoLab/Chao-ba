-- Chào Bà: minimal stand-in for Supabase's `auth` schema so chaoba/server/schema.sql runs on plain Postgres.
-- On Supabase this file is NOT needed (auth.uid() and the `authenticated` role already exist).
-- auth.uid() reads the JWT subject the same way Supabase does: from the `request.jwt.claim.sub` setting.
create schema if not exists auth;

create or replace function auth.uid() returns uuid language sql stable as $$
  select nullif(current_setting('request.jwt.claim.sub', true), '')::uuid
$$;

do $$ begin
  if not exists (select 1 from pg_roles where rolname = 'authenticated') then
    create role authenticated nologin;
  end if;
end $$;

grant usage on schema auth to authenticated;
grant execute on function auth.uid() to authenticated;
