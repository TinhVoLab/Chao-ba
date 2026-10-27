-- Chào Bà: table privileges for the `authenticated` role (Supabase grants these by default).
-- Privileges only open the door; the RLS policies in schema.sql decide which rows each user sees or changes.
grant usage on schema public to authenticated;
grant select, insert, update on all tables in schema public to authenticated;
grant usage, select on all sequences in schema public to authenticated;
grant execute on all functions in schema public to authenticated;
