-- Additive beta only. Production scanner tables and recommendations are unchanged.
create table public.catalyst_beta_cache (
  symbol text primary key check (symbol ~ '^[A-Z0-9][A-Z0-9.-]{0,14}$'),
  collected_at timestamptz not null,
  payload jsonb not null check (jsonb_typeof(payload) = 'object')
);
alter table public.catalyst_beta_cache enable row level security;
revoke all on public.catalyst_beta_cache from public, anon, authenticated;
grant select on public.catalyst_beta_cache to authenticated;
grant all on public.catalyst_beta_cache to service_role;
create policy "Approved users read beta evidence" on public.catalyst_beta_cache
  for select to authenticated using (exists (
    select 1 from public.user_access a where a.user_id = (select auth.uid()) and a.status = 'approved'
  ));

create table public.catalyst_beta_reviews (
  user_id uuid not null references auth.users(id) on delete cascade,
  symbol text not null references public.catalyst_beta_cache(symbol) on delete cascade,
  event_id text not null check (event_id ~ '^[0-9]{10}-[0-9]{2}-[0-9]{6}$'),
  category text not null check (category in ('guidance_raise','earnings_improvement','contract_approval',
    'acquisition_disposal','capital_return','insider_purchase','negative_guidance','dilution','accounting_regulatory','neutral')),
  note text not null check (length(trim(note)) between 1 and 1000),
  confirmed boolean not null default false,
  updated_at timestamptz not null default now(),
  primary key (user_id, symbol, event_id)
);
create index catalyst_beta_reviews_symbol_idx on public.catalyst_beta_reviews(symbol);
alter table public.catalyst_beta_reviews enable row level security;
revoke all on public.catalyst_beta_reviews from public, anon, authenticated;
grant select, insert, update, delete on public.catalyst_beta_reviews to authenticated;
grant all on public.catalyst_beta_reviews to service_role;
create policy "Approved owners manage beta reviews" on public.catalyst_beta_reviews
  for all to authenticated using (user_id = (select auth.uid()) and exists (
    select 1 from public.user_access a where a.user_id = (select auth.uid()) and a.status = 'approved'
  )) with check (user_id = (select auth.uid()) and exists (
    select 1 from public.user_access a where a.user_id = (select auth.uid()) and a.status = 'approved'
  ));

create table public.catalyst_beta_throttle (
  key text primary key,
  attempted_at timestamptz not null
);
alter table public.catalyst_beta_throttle enable row level security;
revoke all on public.catalyst_beta_throttle from public, anon, authenticated;
grant all on public.catalyst_beta_throttle to service_role;
comment on table public.catalyst_beta_throttle is 'Backend-only global SEC throttle; no client policies by design.';
insert into public.catalyst_beta_throttle(key,attempted_at) values ('global','2000-01-01');
create function public.claim_catalyst_beta_refresh(p_user uuid) returns boolean
language plpgsql security invoker set search_path = '' as $$
declare global_time timestamptz; user_time timestamptz;
begin
  if p_user is null then return false; end if;
  select attempted_at into global_time from public.catalyst_beta_throttle where key = 'global' for update;
  if global_time > clock_timestamp() - interval '5 seconds' then return false; end if;
  select attempted_at into user_time from public.catalyst_beta_throttle where key = p_user::text;
  if user_time > clock_timestamp() - interval '15 seconds' then return false; end if;
  update public.catalyst_beta_throttle set attempted_at = clock_timestamp() where key = 'global';
  insert into public.catalyst_beta_throttle(key,attempted_at) values(p_user::text,clock_timestamp())
    on conflict(key) do update set attempted_at = excluded.attempted_at;
  return true;
end;
$$;
revoke all on function public.claim_catalyst_beta_refresh(uuid) from public, anon, authenticated;
grant execute on function public.claim_catalyst_beta_refresh(uuid) to service_role;
