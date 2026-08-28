-- Keep only the most recent hourly price payload.
delete from public.price_snapshots
where source <> 'hourly_yahoo';

with ranked_snapshots as (
  select
    id,
    row_number() over (
      partition by source
      order by generated_at desc, id desc
    ) as row_number
  from public.price_snapshots
)
delete from public.price_snapshots
where id in (
  select id
  from ranked_snapshots
  where row_number > 1
);

alter table public.price_snapshots
  drop constraint if exists price_snapshots_generated_source_key;
drop index if exists public.price_snapshots_generated_at_idx;

alter table public.price_snapshots
  add constraint price_snapshots_hourly_source_check
  check (source = 'hourly_yahoo');

create unique index price_snapshots_source_key
  on public.price_snapshots (source);

comment on table public.price_snapshots is
  'Singleton latest hourly Yahoo price payload written by backend automation.';

-- Keep only the current NYSE ticker universe, with no historical copies.
create table public.nyse_tickers (
  symbol text primary key,
  security_name text not null default '',
  exchange text not null,
  market_cap bigint not null default 0 check (market_cap >= 0),
  source text not null default 'yahoo_screener',
  refreshed_at timestamptz not null,
  constraint nyse_tickers_symbol_check
    check (
      symbol = upper(trim(symbol))
      and symbol ~ '^[A-Z0-9][A-Z0-9.-]{0,14}$'
    ),
  constraint nyse_tickers_exchange_check
    check (char_length(trim(exchange)) between 1 and 20),
  constraint nyse_tickers_source_check
    check (source in ('yahoo_screener', 'nasdaqtrader'))
);

comment on table public.nyse_tickers is
  'Current NYSE ticker universe; each daily refresh atomically replaces all rows.';

create index nyse_tickers_refreshed_at_idx
  on public.nyse_tickers (refreshed_at desc);

alter table public.nyse_tickers enable row level security;

revoke all on table public.nyse_tickers from public, anon, authenticated;
grant select, insert, update, delete on table public.nyse_tickers to service_role;

create or replace function public.replace_nyse_tickers(
  p_refreshed_at timestamptz,
  p_source text,
  p_tickers jsonb
)
returns table (symbol_count integer, refreshed_at timestamptz)
language plpgsql
security invoker
set search_path = ''
as $$
declare
  v_expected_count integer;
  v_stored_count integer;
begin
  if p_refreshed_at is null then
    raise exception 'refreshed_at is required';
  end if;

  if p_source not in ('yahoo_screener', 'nasdaqtrader') then
    raise exception 'unsupported NYSE ticker source: %', p_source;
  end if;

  if jsonb_typeof(p_tickers) is distinct from 'array' then
    raise exception 'tickers must be a JSON array';
  end if;

  v_expected_count := jsonb_array_length(p_tickers);
  if v_expected_count = 0 then
    raise exception 'ticker list cannot be empty';
  end if;

  delete from public.nyse_tickers;

  insert into public.nyse_tickers (
    symbol,
    security_name,
    exchange,
    market_cap,
    source,
    refreshed_at
  )
  select
    upper(trim(ticker.symbol)),
    coalesce(ticker.security_name, ''),
    upper(trim(ticker.exchange)),
    coalesce(ticker.market_cap, 0),
    p_source,
    p_refreshed_at
  from jsonb_to_recordset(p_tickers) as ticker (
    symbol text,
    security_name text,
    exchange text,
    market_cap bigint
  );

  get diagnostics v_stored_count = row_count;
  if v_stored_count <> v_expected_count then
    raise exception
      'stored ticker count % does not match requested count %',
      v_stored_count,
      v_expected_count;
  end if;

  return query select v_stored_count, p_refreshed_at;
end;
$$;

comment on function public.replace_nyse_tickers(timestamptz, text, jsonb) is
  'Atomically replaces the current NYSE ticker universe for backend automation.';

revoke all on function public.replace_nyse_tickers(timestamptz, text, jsonb)
  from public, anon, authenticated;
grant execute on function public.replace_nyse_tickers(timestamptz, text, jsonb)
  to service_role;
