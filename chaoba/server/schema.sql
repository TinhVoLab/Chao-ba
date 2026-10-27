-- Chào Bà – production schema for Postgres / Supabase (the prototype uses SQLite with the same table names).
-- Principles: no audio column anywhere; transcripts expire after 7 days; every family read is logged;
-- Row Level Security for roles: primary (main family carer), viewer (other family), elder_self, clinician.

create extension if not exists pgcrypto;

-- ---------------------------------------------------------------- core tables
create table elder (
  id            text primary key,
  display_name  text not null,
  name_en       text,
  honorific     text not null default 'bà' check (honorific in ('bà','ông')),
  age           int,
  province      text,
  dialect       text default 'south',
  lives_alone   boolean,
  channel_pref  text check (channel_pref in ('pstn','web')),
  profile       jsonb not null default '{}'::jsonb,   -- conditions, medications, goals (no free-text clinical notes)
  auth_user_id  uuid unique,                           -- set when the elder has their own login (elder_self)
  opted_out     boolean not null default false,
  simulated     boolean not null default false,
  created_at    timestamptz not null default now()
);

create table family_member (
  id            uuid primary key default gen_random_uuid(),
  elder_id      text not null references elder(id) on delete cascade,
  auth_user_id  uuid not null,                         -- auth.users.id
  name          text not null,
  relation      text,
  role          text not null check (role in ('primary','viewer','clinician')),
  created_at    timestamptz not null default now(),
  unique (elder_id, auth_user_id)
);

create table consent (
  id           bigserial primary key,
  elder_id     text not null references elder(id) on delete cascade,
  kind         text not null check (kind in ('daily_call','voice_metrics','family_sharing','clinician_sharing','research_use')),
  granted      boolean not null,
  granted_by   text not null,                          -- 'self' | family member name | 'elder (in call)'
  witness      text,
  scope_vi     text,
  scope_en     text,
  ts           timestamptz not null default now()
);

create table call_session (
  id                     text primary key,
  elder_id               text not null references elder(id) on delete cascade,
  channel                text not null check (channel in ('web','pstn','sim')),
  day                    int,
  started_at             timestamptz not null,
  ended_at               timestamptz,
  status                 text not null,
  end_reason             text,                         -- completed | emergency | opt_out | declined
  emergency              boolean not null default false,
  prompt_version         text,
  engine                 text,
  transcript             jsonb,                        -- text + timings only; NULLed after expiry
  transcript_expires_at  timestamptz,
  simulated              boolean not null default false
  -- deliberately NO audio / recording_url column
);

create table call_analysis (
  call_id      text primary key references call_session(id) on delete cascade,
  elder_id     text not null references elder(id) on delete cascade,
  day          int,
  summary_vi   text, summary_en text,
  mood         int check (mood between 1 and 5),
  symptoms     jsonb not null default '{}'::jsonb,     -- symptom -> verbatim quotes
  recall_score int check (recall_score between 0 and 3),
  recall_cue_level text,
  memory_facts_new jsonb not null default '[]'::jsonb,
  followup_hooks   jsonb not null default '[]'::jsonb,
  emergency    boolean not null default false,
  prompt_version text,
  metrics      jsonb not null,                         -- CallMetrics
  created_at   timestamptz not null default now()
);

create table memory_fact (
  id          bigserial primary key,
  elder_id    text not null references elder(id) on delete cascade,
  day         int,
  fact_vi     text not null,
  question_vi text, cue_vi text,
  keywords    jsonb default '[]'::jsonb,
  source      text not null,                           -- profile | call
  created_at  timestamptz not null default now()
);

create table metric_daily (                            -- DailyRecord
  elder_id  text not null references elder(id) on delete cascade,
  day       int not null,
  date      date not null,
  channel   text not null,
  answered  boolean not null,
  valid     boolean not null,
  speech_rate_sps real, pause_ratio real, filled_pause_rate real, mattr real, recall_score real,
  mood      int,
  symptoms  jsonb not null default '{}'::jsonb,
  summary_vi text, summary_en text,
  simulated boolean not null default true,
  primary key (elder_id, day)
);

create table baseline (
  elder_id  text not null references elder(id) on delete cascade,
  metric    text not null,
  from_day  int not null default 1,
  center    real, scale real,
  updated_at timestamptz not null default now(),
  primary key (elder_id, metric, from_day)
);

create table daily_light (
  elder_id  text not null references elder(id) on delete cascade,
  day       int not null,
  date      date not null,
  light     text not null check (light in ('green','yellow','red','gray')),
  reasons   jsonb not null default '[]'::jsonb,
  z         jsonb not null default '{}'::jsonb,
  baseline_ready boolean not null,
  explanation_vi text, explanation_en text,
  primary key (elder_id, day)
);

create table alert (
  id            bigserial primary key,
  elder_id      text not null references elder(id) on delete cascade,
  day           int, date date,
  type          text not null,                         -- metric_trend | emergency | opt_out | scam_topic | ...
  severity      text not null check (severity in ('yellow','red')),
  explanation_vi text, explanation_en text,
  acknowledged  boolean not null default false,
  acknowledged_by uuid,
  call_id       text references call_session(id),
  created_at    timestamptz not null default now()
);

create table dmaic_cycle (
  id               bigserial primary key,
  elder_id         text not null references elder(id) on delete cascade,
  define           jsonb not null default '{}'::jsonb,
  intervention_day int,
  rebaseline_days  jsonb not null default '[]'::jsonb,
  result           jsonb,                              -- compute_cycle output
  updated_at       timestamptz not null default now()
);

create table family_note (
  id         bigserial primary key,
  elder_id   text not null references elder(id) on delete cascade,
  day        int,
  author_id  uuid,
  author     text not null,
  text       text not null,
  to_elder   boolean not null default false,           -- read to the elder at the end of the next call
  simulated  boolean not null default false,
  created_at timestamptz not null default now()
);

create table access_log (
  id        bigserial primary key,
  elder_id  text references elder(id) on delete cascade,
  actor_id  uuid,
  actor     text not null,
  role      text,
  action    text not null,
  resource  text,
  ts        timestamptz not null default now()
);

create index on alert (elder_id, day desc);
create index on access_log (elder_id, ts desc);
create index on call_session (transcript_expires_at) where transcript is not null;

-- ---------------------------------------------------------------- helper functions for RLS
create or replace function app_role(e text) returns text language sql stable security definer as $$
  select case
    when exists (select 1 from elder where id = e and auth_user_id = auth.uid()) then 'elder_self'
    else (select role from family_member where elder_id = e and auth_user_id = auth.uid() limit 1)
  end
$$;

create or replace function can_read(e text) returns boolean language sql stable as $$
  select app_role(e) in ('primary','viewer','elder_self','clinician')
$$;

create or replace function clinician_shared(e text) returns boolean language sql stable security definer as $$
  select coalesce((select granted from consent where elder_id = e and kind = 'clinician_sharing'
                   order by ts desc limit 1), false)
$$;

-- ---------------------------------------------------------------- RLS
alter table elder          enable row level security;
alter table family_member  enable row level security;
alter table consent        enable row level security;
alter table call_session   enable row level security;
alter table call_analysis  enable row level security;
alter table memory_fact    enable row level security;
alter table metric_daily   enable row level security;
alter table baseline       enable row level security;
alter table daily_light    enable row level security;
alter table alert          enable row level security;
alter table dmaic_cycle    enable row level security;
alter table family_note    enable row level security;
alter table access_log     enable row level security;

-- Elder profile: everyone linked can read; only primary carer (or the elder) can update.
create policy elder_read   on elder for select using (can_read(id) and (app_role(id) <> 'clinician' or clinician_shared(id)));
create policy elder_update on elder for update using (app_role(id) in ('primary','elder_self'));

create policy fm_read   on family_member for select using (can_read(elder_id));
create policy fm_manage on family_member for all using (app_role(elder_id) = 'primary');

-- Consent: readable by all linked roles; only the elder or primary carer can record consent changes.
create policy consent_read  on consent for select using (can_read(elder_id));
create policy consent_write on consent for insert with check (app_role(elder_id) in ('primary','elder_self'));

-- Transcripts: only primary carer and the elder; viewers and clinicians see summaries/metrics, not transcripts.
create policy call_read on call_session for select using (app_role(elder_id) in ('primary','elder_self'));

-- Derived data (summaries, metrics, lights, baselines, DMAIC): all linked roles; clinicians only with consent.
create policy ca_read on call_analysis for select
  using (can_read(elder_id) and (app_role(elder_id) <> 'clinician' or clinician_shared(elder_id)));
create policy mf_read on memory_fact for select using (app_role(elder_id) in ('primary','elder_self'));
create policy md_read on metric_daily for select
  using (can_read(elder_id) and (app_role(elder_id) <> 'clinician' or clinician_shared(elder_id)));
create policy bl_read on baseline for select
  using (can_read(elder_id) and (app_role(elder_id) <> 'clinician' or clinician_shared(elder_id)));
create policy dl_read on daily_light for select using (can_read(elder_id));
create policy dm_read on dmaic_cycle for select
  using (can_read(elder_id) and (app_role(elder_id) <> 'clinician' or clinician_shared(elder_id)));
create policy dm_write on dmaic_cycle for all using (app_role(elder_id) in ('primary','clinician'));

-- Alerts: everyone linked reads; primary and viewer can acknowledge.
create policy alert_read on alert for select using (can_read(elder_id));
create policy alert_ack  on alert for update using (app_role(elder_id) in ('primary','viewer'))
  with check (app_role(elder_id) in ('primary','viewer'));

-- Notes: family + clinician read/write their own; the elder can read notes addressed to them.
create policy note_read  on family_note for select
  using (app_role(elder_id) in ('primary','viewer','clinician') or (app_role(elder_id) = 'elder_self' and to_elder));
create policy note_write on family_note for insert
  with check (app_role(elder_id) in ('primary','viewer','clinician') and author_id = auth.uid());

-- Access log: append by any linked role (server writes with service key); read by primary and the elder.
create policy al_read   on access_log for select using (app_role(elder_id) in ('primary','elder_self'));
create policy al_insert on access_log for insert with check (can_read(elder_id));

-- ---------------------------------------------------------------- retention (pg_cron, daily)
-- select cron.schedule('purge-transcripts', '15 3 * * *',
--   $$ update call_session set transcript = null where transcript_expires_at < now() and transcript is not null $$);
