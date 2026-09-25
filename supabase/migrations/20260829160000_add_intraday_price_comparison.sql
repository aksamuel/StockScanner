alter table public.price_snapshots
  add column if not exists market_date date not null
    default ((now() at time zone 'America/New_York')::date),
  add column if not exists daily_prices jsonb not null default '{}'::jsonb,
  add column if not exists intraday_series jsonb not null default '{}'::jsonb;

-- Backfill the singleton from its actual collection time rather than the
-- migration date, which may be a weekend or a later trading day.
update public.price_snapshots
set market_date = (generated_at at time zone timezone)::date;

alter table public.price_snapshots
  drop constraint if exists price_snapshots_daily_prices_object_check,
  add constraint price_snapshots_daily_prices_object_check
    check (jsonb_typeof(daily_prices) = 'object'),
  drop constraint if exists price_snapshots_intraday_series_object_check,
  add constraint price_snapshots_intraday_series_object_check
    check (jsonb_typeof(intraday_series) = 'object');

comment on column public.price_snapshots.daily_prices is
  'Latest completed daily close by symbol, stored in the singleton hourly payload.';
comment on column public.price_snapshots.market_date is
  'New York trading date represented by the singleton payload; prior-day data is replaced.';
comment on column public.price_snapshots.intraday_series is
  'Bounded current-trading-day price points by symbol; reset each New York trading day.';
