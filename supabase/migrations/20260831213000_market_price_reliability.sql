alter table public.price_snapshots
  add column if not exists previous_close_prices jsonb not null default '{}'::jsonb,
  add column if not exists market_close_prices jsonb not null default '{}'::jsonb,
  add column if not exists requested_symbol_count integer not null default 0,
  add column if not exists portfolio_symbol_count integer not null default 0,
  add column if not exists portfolio_updated_count integer not null default 0,
  add column if not exists portfolio_missing_symbols jsonb not null default '[]'::jsonb,
  add column if not exists portfolio_coverage_percent numeric(6,2) not null default 100,
  add column if not exists provider_counts jsonb not null default '{}'::jsonb,
  add column if not exists provider_by_symbol jsonb not null default '{}'::jsonb,
  add column if not exists stale_symbols jsonb not null default '[]'::jsonb,
  add column if not exists collection_kind text not null default 'intraday';

update public.price_snapshots
set previous_close_prices = daily_prices
where previous_close_prices = '{}'::jsonb
  and daily_prices <> '{}'::jsonb;

alter table public.price_snapshots
  drop constraint if exists price_snapshots_previous_close_object_check,
  add constraint price_snapshots_previous_close_object_check
    check (jsonb_typeof(previous_close_prices) = 'object'),
  drop constraint if exists price_snapshots_market_close_object_check,
  add constraint price_snapshots_market_close_object_check
    check (jsonb_typeof(market_close_prices) = 'object'),
  drop constraint if exists price_snapshots_portfolio_missing_array_check,
  add constraint price_snapshots_portfolio_missing_array_check
    check (jsonb_typeof(portfolio_missing_symbols) = 'array'),
  drop constraint if exists price_snapshots_stale_symbols_array_check,
  add constraint price_snapshots_stale_symbols_array_check
    check (jsonb_typeof(stale_symbols) = 'array'),
  drop constraint if exists price_snapshots_collection_kind_check,
  add constraint price_snapshots_collection_kind_check
    check (collection_kind in ('intraday', 'market_close')),
  drop constraint if exists price_snapshots_coverage_check,
  add constraint price_snapshots_coverage_check
    check (portfolio_coverage_percent between 0 and 100);

comment on column public.price_snapshots.previous_close_prices is
  'Official previous trading-day close by symbol.';
comment on column public.price_snapshots.market_close_prices is
  'Current market-date closing snapshot collected after 16:00 New York time.';
comment on column public.price_snapshots.portfolio_missing_symbols is
  'Purchased symbols not refreshed in the latest provider pass.';

create table public.price_collection_runs (
  slot text primary key,
  market_date date not null,
  workflow_run_id bigint not null,
  status text not null check (status in ('running', 'completed', 'failed')),
  started_at timestamptz not null default now(),
  completed_at timestamptz
);

alter table public.price_collection_runs enable row level security;
revoke all on table public.price_collection_runs from public, anon, authenticated;
grant select, insert, update, delete on table public.price_collection_runs to service_role;

create or replace function public.acquire_price_collection_slot(
  p_slot text,
  p_market_date date,
  p_workflow_run_id bigint
)
returns boolean
language plpgsql
security invoker
set search_path = ''
as $$
declare
  affected_rows integer;
begin
  delete from public.price_collection_runs
  where market_date < p_market_date;

  insert into public.price_collection_runs (
    slot, market_date, workflow_run_id, status, started_at, completed_at
  ) values (
    p_slot, p_market_date, p_workflow_run_id, 'running', now(), null
  )
  on conflict (slot) do update
  set workflow_run_id = excluded.workflow_run_id,
      status = 'running',
      started_at = now(),
      completed_at = null
  where public.price_collection_runs.status = 'failed'
     or (
       public.price_collection_runs.status = 'running'
       and public.price_collection_runs.started_at < now() - interval '45 minutes'
     );

  get diagnostics affected_rows = row_count;
  return affected_rows = 1;
end;
$$;

create or replace function public.finish_price_collection_slot(
  p_slot text,
  p_workflow_run_id bigint,
  p_status text
)
returns boolean
language plpgsql
security invoker
set search_path = ''
as $$
declare
  affected_rows integer;
begin
  if p_status not in ('completed', 'failed') then
    raise exception 'Invalid price collection status: %', p_status;
  end if;
  update public.price_collection_runs
  set status = p_status,
      completed_at = now()
  where slot = p_slot
    and workflow_run_id = p_workflow_run_id
    and status = 'running';
  get diagnostics affected_rows = row_count;
  return affected_rows = 1;
end;
$$;

revoke all on function public.acquire_price_collection_slot(text, date, bigint)
  from public, anon, authenticated;
revoke all on function public.finish_price_collection_slot(text, bigint, text)
  from public, anon, authenticated;
grant execute on function public.acquire_price_collection_slot(text, date, bigint)
  to service_role;
grant execute on function public.finish_price_collection_slot(text, bigint, text)
  to service_role;
