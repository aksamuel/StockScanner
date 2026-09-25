-- Supabase's safe-update guard rejects DELETE statements without a predicate.
-- Replace the function from the preceding migration with an equivalent,
-- explicitly bounded delete that remains atomic with the insert.
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

  delete from public.nyse_tickers
  where symbol is not null;

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

revoke all on function public.replace_nyse_tickers(timestamptz, text, jsonb)
  from public, anon, authenticated;
grant execute on function public.replace_nyse_tickers(timestamptz, text, jsonb)
  to service_role;
