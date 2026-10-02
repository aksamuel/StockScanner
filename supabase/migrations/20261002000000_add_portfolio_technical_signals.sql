create table public.portfolio_technical_signals (
  symbol text primary key,
  score numeric(6,2),
  recommendation text,
  scanner_price numeric,
  technical_target numeric,
  resistance_target numeric,
  analyst_target_upside numeric,
  market_date date not null,
  calculated_at timestamptz,
  last_success_at timestamptz,
  last_attempt_at timestamptz not null default now(),
  status text not null default 'unavailable'
    check (status in ('available', 'stale', 'unavailable')),
  failure_reason text,
  updated_at timestamptz not null default now(),
  constraint portfolio_technical_signals_symbol_check
    check (symbol = upper(symbol) and symbol ~ '^[A-Z0-9][A-Z0-9.-]{0,14}$'),
  constraint portfolio_technical_signals_score_check
    check (score is null or score between 0 and 100)
);

alter table public.portfolio_technical_signals enable row level security;
revoke all on table public.portfolio_technical_signals from public, anon, authenticated;
grant select, insert, update, delete on table public.portfolio_technical_signals to service_role;

create or replace function public.record_portfolio_technical_signal_attempts(
  p_market_date date,
  p_attempts jsonb
)
returns integer
language plpgsql
security invoker
set search_path = ''
as $$
declare
  item jsonb;
  normalized_symbol text;
  recorded integer := 0;
begin
  if jsonb_typeof(p_attempts) <> 'array' then
    raise exception 'Technical signal attempts must be a JSON array';
  end if;

  for item in select value from jsonb_array_elements(p_attempts)
  loop
    normalized_symbol := upper(trim(item ->> 'symbol'));
    if normalized_symbol !~ '^[A-Z0-9][A-Z0-9.-]{0,14}$' then
      raise exception 'Invalid technical signal symbol';
    end if;

    if coalesce((item ->> 'success')::boolean, false) then
      insert into public.portfolio_technical_signals (
        symbol, score, recommendation, scanner_price, technical_target,
        resistance_target, analyst_target_upside, market_date, calculated_at,
        last_success_at, last_attempt_at, status, failure_reason, updated_at
      ) values (
        normalized_symbol,
        nullif(item ->> 'score', '')::numeric,
        nullif(item ->> 'recommendation', ''),
        nullif(item ->> 'scanner_price', '')::numeric,
        nullif(item ->> 'technical_target', '')::numeric,
        nullif(item ->> 'resistance_target', '')::numeric,
        nullif(item ->> 'analyst_target_upside', '')::numeric,
        p_market_date, now(), now(), now(), 'available', null, now()
      )
      on conflict (symbol) do update
      set score = excluded.score,
          recommendation = excluded.recommendation,
          scanner_price = excluded.scanner_price,
          technical_target = excluded.technical_target,
          resistance_target = excluded.resistance_target,
          analyst_target_upside = excluded.analyst_target_upside,
          market_date = excluded.market_date,
          calculated_at = excluded.calculated_at,
          last_success_at = excluded.last_success_at,
          last_attempt_at = excluded.last_attempt_at,
          status = 'available',
          failure_reason = null,
          updated_at = now();
    else
      insert into public.portfolio_technical_signals (
        symbol, market_date, last_attempt_at, status, failure_reason, updated_at
      ) values (
        normalized_symbol, p_market_date, now(), 'unavailable',
        left(coalesce(nullif(item ->> 'failure_reason', ''), 'analysis_failure'), 120),
        now()
      )
      on conflict (symbol) do update
      set last_attempt_at = excluded.last_attempt_at,
          status = case
            when public.portfolio_technical_signals.last_success_at is null
              then 'unavailable'
            else 'stale'
          end,
          failure_reason = excluded.failure_reason,
          updated_at = now();
    end if;
    recorded := recorded + 1;
  end loop;

  return recorded;
end;
$$;

revoke all on function public.record_portfolio_technical_signal_attempts(date, jsonb)
  from public, anon, authenticated;
grant execute on function public.record_portfolio_technical_signal_attempts(date, jsonb)
  to service_role;

create or replace function public.get_my_portfolio_technical_signals()
returns table (
  symbol text,
  score numeric,
  recommendation text,
  scanner_price numeric,
  technical_target numeric,
  resistance_target numeric,
  analyst_target_upside numeric,
  market_date date,
  calculated_at timestamptz,
  last_success_at timestamptz,
  last_attempt_at timestamptz,
  status text,
  failure_reason text,
  scanner_market_date date,
  scanner_status text
)
language sql
stable
security definer
set search_path = ''
as $$
  select distinct
    signal.symbol,
    signal.score,
    signal.recommendation,
    signal.scanner_price,
    signal.technical_target,
    signal.resistance_target,
    signal.analyst_target_upside,
    signal.market_date,
    signal.calculated_at,
    signal.last_success_at,
    signal.last_attempt_at,
    signal.status,
    signal.failure_reason,
    run.market_date,
    run.status
  from public.user_portfolio_holdings as holding
  join public.user_access as access
    on access.user_id = holding.user_id and access.status = 'approved'
  left join public.portfolio_technical_signals as signal
    on signal.symbol = holding.symbol
  left join public.scanner_run_state as run
    on run.singleton_id = 1
  where holding.user_id = auth.uid()
    and signal.symbol is not null
  order by signal.symbol;
$$;

revoke all on function public.get_my_portfolio_technical_signals()
  from public, anon;
grant execute on function public.get_my_portfolio_technical_signals()
  to authenticated;

comment on table public.portfolio_technical_signals is
  'Latest successful daily technical evidence for held symbols; direct client access is denied.';
comment on function public.get_my_portfolio_technical_signals() is
  'Returns technical evidence only for the authenticated approved user current portfolio symbols.';
