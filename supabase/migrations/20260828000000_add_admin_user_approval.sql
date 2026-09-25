create table public.user_access (
  user_id uuid primary key references auth.users (id) on delete cascade,
  email text not null,
  status text not null default 'pending'
    check (status in ('pending', 'approved', 'rejected')),
  requested_at timestamptz not null default now(),
  reviewed_at timestamptz,
  reviewed_by uuid,
  constraint user_access_review_consistency check (
    (status = 'pending' and reviewed_at is null and reviewed_by is null)
    or (status in ('approved', 'rejected') and reviewed_at is not null and reviewed_by is not null)
  )
);

create table public.signup_allowlist (
  email text primary key,
  permitted_at timestamptz not null default now(),
  permitted_by uuid not null references auth.users (id),
  constraint signup_allowlist_normalized_email check (email = lower(trim(email))),
  constraint signup_allowlist_valid_email check (email ~ '^[^[:space:]@]+@[^[:space:]@]+\.[^[:space:]@]+$')
);

create index signup_allowlist_permitted_by_idx
  on public.signup_allowlist (permitted_by);

create table public.user_activity_events (
  id bigint generated always as identity primary key,
  user_id uuid not null references auth.users (id) on delete cascade,
  event_type text not null check (event_type in ('login', 'page_view', 'logout')),
  page_path text check (page_path is null or char_length(page_path) <= 500),
  occurred_at timestamptz not null default now()
);

create index user_activity_events_user_time_idx
  on public.user_activity_events (user_id, occurred_at desc);

create index user_activity_events_type_time_idx
  on public.user_activity_events (event_type, occurred_at desc);

create table public.user_presence (
  user_id uuid primary key references auth.users (id) on delete cascade,
  last_seen_at timestamptz not null default now(),
  signed_out_at timestamptz,
  last_page text check (last_page is null or char_length(last_page) <= 500)
);

create table public.user_exceptions (
  id bigint generated always as identity primary key,
  user_id uuid not null references auth.users (id) on delete cascade,
  symbol text not null,
  reason text,
  date_from date not null default current_date,
  date_to date not null default (current_date + 30),
  created_at timestamptz not null default now(),
  constraint user_exceptions_normalized_symbol
    check (symbol = upper(trim(symbol)) and symbol ~ '^[A-Z0-9][A-Z0-9.-]{0,14}$'),
  constraint user_exceptions_reason_length
    check (reason is null or char_length(reason) <= 500),
  constraint user_exceptions_date_order check (date_to >= date_from),
  constraint user_exceptions_user_symbol_unique unique (user_id, symbol)
);

create table public.user_bought_selections (
  id bigint generated always as identity primary key,
  user_id uuid not null references auth.users (id) on delete cascade,
  symbol text not null,
  quantity numeric(18, 6) not null default 1,
  buy_price numeric(18, 6),
  bought_on date,
  notes text,
  created_at timestamptz not null default now(),
  constraint user_bought_selections_normalized_symbol
    check (symbol = upper(trim(symbol)) and symbol ~ '^[A-Z0-9][A-Z0-9.-]{0,14}$'),
  constraint user_bought_selections_positive_quantity check (quantity > 0),
  constraint user_bought_selections_positive_price check (buy_price is null or buy_price >= 0),
  constraint user_bought_selections_notes_length
    check (notes is null or char_length(notes) <= 500),
  constraint user_bought_selections_user_symbol_unique unique (user_id, symbol)
);

alter table public.user_access enable row level security;
alter table public.signup_allowlist enable row level security;
alter table public.user_activity_events enable row level security;
alter table public.user_presence enable row level security;
alter table public.user_exceptions enable row level security;
alter table public.user_bought_selections enable row level security;

revoke all on table public.user_access from anon, authenticated;
grant select on table public.user_access to authenticated;
grant update (status) on table public.user_access to authenticated;
grant all on table public.user_access to service_role;

revoke all on table public.signup_allowlist from anon, authenticated;
grant select, insert, delete on table public.signup_allowlist to authenticated;
grant select on table public.signup_allowlist to supabase_auth_admin;
grant all on table public.signup_allowlist to service_role;

revoke all on table public.user_activity_events from anon, authenticated;
grant insert on table public.user_activity_events to authenticated;
grant select on table public.user_activity_events to authenticated;
grant all on table public.user_activity_events to service_role;
grant usage on sequence public.user_activity_events_id_seq to authenticated;
grant all on sequence public.user_activity_events_id_seq to service_role;

revoke all on table public.user_presence from anon, authenticated;
grant select, insert, update on table public.user_presence to authenticated;
grant all on table public.user_presence to service_role;

revoke all on table public.user_exceptions from anon, authenticated;
grant select, insert, delete on table public.user_exceptions to authenticated;
grant all on table public.user_exceptions to service_role;
grant usage on sequence public.user_exceptions_id_seq to authenticated;
grant all on sequence public.user_exceptions_id_seq to service_role;

revoke all on table public.user_bought_selections from anon, authenticated;
grant select, insert, delete on table public.user_bought_selections to authenticated;
grant all on table public.user_bought_selections to service_role;
grant usage on sequence public.user_bought_selections_id_seq to authenticated;
grant all on sequence public.user_bought_selections_id_seq to service_role;

create policy "Users or admin can read access status"
  on public.user_access
  for select
  to authenticated
  using (
    (select auth.uid()) = user_id
    or lower(coalesce((select auth.jwt()) ->> 'email', '')) = 'aaksamuel@zohomail.com'
  );

create policy "StockScanner admin can review access requests"
  on public.user_access
  for update
  to authenticated
  using (lower(coalesce((select auth.jwt()) ->> 'email', '')) = 'aaksamuel@zohomail.com')
  with check (lower(coalesce((select auth.jwt()) ->> 'email', '')) = 'aaksamuel@zohomail.com');

create policy "StockScanner admin can view signup permissions"
  on public.signup_allowlist
  for select
  to authenticated
  using (lower(coalesce((select auth.jwt()) ->> 'email', '')) = 'aaksamuel@zohomail.com');

create policy "StockScanner admin can grant signup permission"
  on public.signup_allowlist
  for insert
  to authenticated
  with check (
    lower(coalesce((select auth.jwt()) ->> 'email', '')) = 'aaksamuel@zohomail.com'
    and permitted_by = (select auth.uid())
  );

create policy "StockScanner admin can revoke signup permission"
  on public.signup_allowlist
  for delete
  to authenticated
  using (lower(coalesce((select auth.jwt()) ->> 'email', '')) = 'aaksamuel@zohomail.com');

create policy "Supabase Auth can check signup permissions"
  on public.signup_allowlist
  for select
  to supabase_auth_admin
  using (true);

create policy "Users can record their own activity"
  on public.user_activity_events
  for insert
  to authenticated
  with check (
    (select auth.uid()) = user_id
    and exists (
      select 1
      from public.user_access
      where user_id = (select auth.uid())
        and status = 'approved'
    )
  );

create policy "StockScanner admin can read activity"
  on public.user_activity_events
  for select
  to authenticated
  using (lower(coalesce((select auth.jwt()) ->> 'email', '')) = 'aaksamuel@zohomail.com');

create policy "Users or admin can read presence"
  on public.user_presence
  for select
  to authenticated
  using (
    (select auth.uid()) = user_id
    or lower(coalesce((select auth.jwt()) ->> 'email', '')) = 'aaksamuel@zohomail.com'
  );

create policy "Users can create their own presence"
  on public.user_presence
  for insert
  to authenticated
  with check (
    (select auth.uid()) = user_id
    and exists (
      select 1
      from public.user_access
      where user_id = (select auth.uid())
        and status = 'approved'
    )
  );

create policy "Users can update their own presence"
  on public.user_presence
  for update
  to authenticated
  using ((select auth.uid()) = user_id)
  with check ((select auth.uid()) = user_id);

create policy "Approved users can read their own exceptions"
  on public.user_exceptions
  for select
  to authenticated
  using (
    (select auth.uid()) = user_id
    and exists (
      select 1 from public.user_access
      where user_id = (select auth.uid()) and status = 'approved'
    )
  );

create policy "Approved users can add their own exceptions"
  on public.user_exceptions
  for insert
  to authenticated
  with check (
    (select auth.uid()) = user_id
    and exists (
      select 1 from public.user_access
      where user_id = (select auth.uid()) and status = 'approved'
    )
  );

create policy "Approved users can delete their own exceptions"
  on public.user_exceptions
  for delete
  to authenticated
  using (
    (select auth.uid()) = user_id
    and exists (
      select 1 from public.user_access
      where user_id = (select auth.uid()) and status = 'approved'
    )
  );

create policy "Approved users can read their own bought selections"
  on public.user_bought_selections
  for select
  to authenticated
  using (
    (select auth.uid()) = user_id
    and exists (
      select 1 from public.user_access
      where user_id = (select auth.uid()) and status = 'approved'
    )
  );

create policy "Approved users can add their own bought selections"
  on public.user_bought_selections
  for insert
  to authenticated
  with check (
    (select auth.uid()) = user_id
    and exists (
      select 1 from public.user_access
      where user_id = (select auth.uid()) and status = 'approved'
    )
  );

create policy "Approved users can delete their own bought selections"
  on public.user_bought_selections
  for delete
  to authenticated
  using (
    (select auth.uid()) = user_id
    and exists (
      select 1 from public.user_access
      where user_id = (select auth.uid()) and status = 'approved'
    )
  );

create schema if not exists private;

create function private.hook_require_admin_permission(event jsonb)
returns jsonb
language plpgsql
set search_path = ''
as $$
declare
  signup_email text := lower(trim(event -> 'user' ->> 'email'));
begin
  if signup_email = 'aaksamuel@zohomail.com'
     or exists (
       select 1
       from public.signup_allowlist
       where email = signup_email
     ) then
    return '{}'::jsonb;
  end if;

  return jsonb_build_object(
    'error', jsonb_build_object(
      'http_code', 403,
      'message', 'Administrator permission is required before creating an account.'
    )
  );
end;
$$;

revoke all on function private.hook_require_admin_permission(jsonb)
  from public, anon, authenticated;
grant usage on schema private to supabase_auth_admin;
grant execute on function private.hook_require_admin_permission(jsonb)
  to supabase_auth_admin;

create function private.sync_user_access()
returns trigger
language plpgsql
security definer
set search_path = ''
as $$
begin
  insert into public.user_access (user_id, email, status, reviewed_at, reviewed_by)
  values (
    new.id,
    lower(new.email),
    case
      when lower(new.email) = 'aaksamuel@zohomail.com'
        or exists (select 1 from public.signup_allowlist where email = lower(new.email))
      then 'approved'
      else 'pending'
    end,
    case
      when lower(new.email) = 'aaksamuel@zohomail.com'
        or exists (select 1 from public.signup_allowlist where email = lower(new.email))
      then now()
      else null
    end,
    case
      when lower(new.email) = 'aaksamuel@zohomail.com' then new.id
      else (select permitted_by from public.signup_allowlist where email = lower(new.email))
    end
  )
  on conflict (user_id) do update set email = excluded.email;
  return new;
end;
$$;

revoke all on function private.sync_user_access() from public, anon, authenticated;

create trigger sync_user_access_after_auth_change
  after insert or update of email on auth.users
  for each row execute function private.sync_user_access();

create function private.record_access_review()
returns trigger
language plpgsql
set search_path = ''
as $$
begin
  if new.status is distinct from old.status then
    new.reviewed_at := case when new.status = 'pending' then null else now() end;
    new.reviewed_by := case when new.status = 'pending' then null else auth.uid() end;
  end if;
  return new;
end;
$$;

revoke all on function private.record_access_review() from public, anon, authenticated;

create trigger record_user_access_review
  before update of status on public.user_access
  for each row execute function private.record_access_review();

insert into public.user_access (user_id, email, status, reviewed_at, reviewed_by)
select
  id,
  lower(email),
  case when lower(email) = 'aaksamuel@zohomail.com' then 'approved' else 'pending' end,
  case when lower(email) = 'aaksamuel@zohomail.com' then now() else null end,
  case when lower(email) = 'aaksamuel@zohomail.com' then id else null end
from auth.users
on conflict (user_id) do nothing;

drop policy if exists "Authenticated users can read price snapshots"
  on public.price_snapshots;

create policy "Approved users can read price snapshots"
  on public.price_snapshots
  for select
  to authenticated
  using (
    exists (
      select 1
      from public.user_access
      where user_id = (select auth.uid())
        and status = 'approved'
    )
  );

comment on table public.user_access is
  'Admin-reviewed access status for StockScanner users; no passwords are stored here.';

comment on table public.signup_allowlist is
  'Email addresses permitted by the StockScanner administrator before account creation.';

comment on function private.hook_require_admin_permission(jsonb) is
  'Configure as the Supabase Before User Created hook to enforce invite-only signup.';

comment on table public.user_activity_events is
  'Append-only login, page-view, and logout events for the admin activity dashboard.';

comment on table public.user_presence is
  'Most recent approved-user activity used to estimate currently active sessions.';

comment on table public.user_exceptions is
  'Personal StockScanner exception tickers; rows cascade-delete with the owning Auth user.';

comment on table public.user_bought_selections is
  'Personal bought-stock selections; rows cascade-delete with the owning Auth user.';
