-- Chào Bà: Row Level Security smoke test for chaoba/server/schema.sql on Postgres.
-- Run against a database initialised by deploy/postgres/*.sql + schema.sql (docker compose does this):
--   docker compose exec -T postgres psql -U chaoba -d chaoba -v ON_ERROR_STOP=1 -f /deploy/rls_test.sql
-- Everything runs in one transaction that is rolled back, so the database is left unchanged.
-- Prints "RLS OK" on success; any failed check raises an exception (psql exits non-zero).
\set ON_ERROR_STOP on
begin;

-- ---------------------------------------------------------------- fixtures (as the table owner, RLS bypassed)
insert into elder (id, display_name, honorific, auth_user_id, simulated)
values ('rls_e1', 'Bà Thử', 'bà', '00000000-0000-0000-0000-0000000000e1', true);

insert into family_member (elder_id, auth_user_id, name, relation, role) values
  ('rls_e1', '00000000-0000-0000-0000-00000000000a', 'Lan',  'daughter', 'primary'),
  ('rls_e1', '00000000-0000-0000-0000-00000000000b', 'Minh', 'son',      'viewer'),
  ('rls_e1', '00000000-0000-0000-0000-00000000000c', 'Hoa',  'doctor',   'clinician');

insert into consent (elder_id, kind, granted, granted_by, ts) values
  ('rls_e1', 'family_sharing',    true,  'self', now() - interval '1 day'),
  ('rls_e1', 'clinician_sharing', false, 'self', now() - interval '1 day');

insert into call_session (id, elder_id, channel, day, started_at, status, transcript, transcript_expires_at)
values ('rls_c1', 'rls_e1', 'web', 1, now(), 'completed', '[{"text":"xin chào"}]', now() + interval '7 days');

insert into daily_light (elder_id, day, date, light, baseline_ready)
values ('rls_e1', 1, current_date, 'green', true);

-- ---------------------------------------------------------------- checks (as an ordinary signed-in user)
set local role authenticated;

do $$
declare
  primary_u  constant text := '00000000-0000-0000-0000-00000000000a';
  viewer_u   constant text := '00000000-0000-0000-0000-00000000000b';
  clinic_u   constant text := '00000000-0000-0000-0000-00000000000c';
  elder_u    constant text := '00000000-0000-0000-0000-0000000000e1';
  stranger_u constant text := '00000000-0000-0000-0000-0000000000ff';
  n int;
begin
  -- 1. A stranger (no family_member row) sees nothing.
  perform set_config('request.jwt.claim.sub', stranger_u, true);
  select count(*) into n from elder where id = 'rls_e1';
  if n <> 0 then raise exception 'RLS FAIL 1: stranger can read the elder profile'; end if;
  select count(*) into n from daily_light where elder_id = 'rls_e1';
  if n <> 0 then raise exception 'RLS FAIL 1: stranger can read daily lights'; end if;

  -- 2. Transcripts: the primary carer can read them, a viewer cannot.
  perform set_config('request.jwt.claim.sub', primary_u, true);
  select count(*) into n from call_session where elder_id = 'rls_e1';
  if n <> 1 then raise exception 'RLS FAIL 2: primary carer cannot read the call session'; end if;
  perform set_config('request.jwt.claim.sub', viewer_u, true);
  select count(*) into n from call_session where elder_id = 'rls_e1';
  if n <> 0 then raise exception 'RLS FAIL 2: viewer can read transcripts'; end if;
  select count(*) into n from daily_light where elder_id = 'rls_e1';
  if n <> 1 then raise exception 'RLS FAIL 2: viewer cannot read the daily light'; end if;

  -- 3. A viewer cannot record consent changes.
  begin
    insert into consent (elder_id, kind, granted, granted_by) values ('rls_e1', 'family_sharing', false, 'Minh');
    raise exception 'RLS FAIL 3: viewer inserted a consent row';
  exception when insufficient_privilege then
    null; -- expected: new row violates row-level security policy
  end;

  -- 4. Clinician sees the profile only after the elder grants clinician_sharing.
  perform set_config('request.jwt.claim.sub', clinic_u, true);
  select count(*) into n from elder where id = 'rls_e1';
  if n <> 0 then raise exception 'RLS FAIL 4: clinician reads profile without clinician_sharing consent'; end if;
  perform set_config('request.jwt.claim.sub', elder_u, true);
  insert into consent (elder_id, kind, granted, granted_by) values ('rls_e1', 'clinician_sharing', true, 'self');
  perform set_config('request.jwt.claim.sub', clinic_u, true);
  select count(*) into n from elder where id = 'rls_e1';
  if n <> 1 then raise exception 'RLS FAIL 4: clinician cannot read profile after consent'; end if;

  -- 5. Withdrawing family_sharing (the elder's own decision) hides health data from family roles.
  perform set_config('request.jwt.claim.sub', elder_u, true);
  insert into consent (elder_id, kind, granted, granted_by) values ('rls_e1', 'family_sharing', false, 'self');
  perform set_config('request.jwt.claim.sub', viewer_u, true);
  select count(*) into n from daily_light where elder_id = 'rls_e1';
  if n <> 0 then raise exception 'RLS FAIL 5: viewer still sees lights after family_sharing was withdrawn'; end if;
  perform set_config('request.jwt.claim.sub', elder_u, true);
  select count(*) into n from daily_light where elder_id = 'rls_e1';
  if n <> 1 then raise exception 'RLS FAIL 5: the elder lost access to their own lights'; end if;

  raise notice 'all RLS checks passed';
end $$;

select 'RLS OK' as result;
rollback;
