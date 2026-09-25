create table public.user_portfolio_holdings (
  id bigint generated always as identity primary key,
  user_id uuid not null references auth.users (id) on delete cascade,
  broker text not null,
  position_key text not null,
  symbol text not null,
  description text,
  asset_class text not null default 'STK',
  currency text not null default 'USD',
  quantity numeric(22, 8) not null,
  buy_price numeric(22, 8),
  bought_on date,
  current_price numeric(22, 8),
  current_price_at timestamptz,
  market_value numeric(24, 8),
  unrealized_pnl numeric(24, 8),
  target_price numeric(22, 8),
  stop_loss numeric(22, 8),
  notes text,
  import_source text not null check (import_source in ('ibkr_flex', 'csv')),
  imported_at timestamptz not null default now(),
  constraint user_portfolio_holdings_broker_length
    check (char_length(trim(broker)) between 1 and 80),
  constraint user_portfolio_holdings_position_key_length
    check (char_length(position_key) between 1 and 160),
  constraint user_portfolio_holdings_normalized_symbol
    check (symbol = upper(trim(symbol)) and symbol ~ '^[A-Z0-9][A-Z0-9.-]{0,29}$'),
  constraint user_portfolio_holdings_asset_class_length
    check (char_length(asset_class) between 1 and 20),
  constraint user_portfolio_holdings_currency_format
    check (currency = upper(currency) and currency ~ '^[A-Z]{3}$'),
  constraint user_portfolio_holdings_nonzero_quantity check (quantity <> 0),
  constraint user_portfolio_holdings_nonnegative_prices check (
    (buy_price is null or buy_price >= 0)
    and (current_price is null or current_price >= 0)
    and (target_price is null or target_price >= 0)
    and (stop_loss is null or stop_loss >= 0)
  ),
  constraint user_portfolio_holdings_description_length
    check (description is null or char_length(description) <= 300),
  constraint user_portfolio_holdings_notes_length
    check (notes is null or char_length(notes) <= 500),
  constraint user_portfolio_holdings_owner_position_unique
    unique (user_id, broker, position_key)
);

create index user_portfolio_holdings_owner_symbol_idx
  on public.user_portfolio_holdings (user_id, symbol);

create table public.user_portfolio_imports (
  user_id uuid not null references auth.users (id) on delete cascade,
  broker text not null,
  import_source text not null check (import_source in ('ibkr_flex', 'csv')),
  downloaded_at timestamptz not null,
  row_count integer not null check (row_count >= 0),
  primary key (user_id, broker),
  constraint user_portfolio_imports_broker_length
    check (char_length(trim(broker)) between 1 and 80)
);

alter table public.user_portfolio_holdings enable row level security;
alter table public.user_portfolio_imports enable row level security;

revoke all on table public.user_portfolio_holdings from anon, authenticated;
grant select, insert, update, delete on table public.user_portfolio_holdings to authenticated;
grant all on table public.user_portfolio_holdings to service_role;
grant usage on sequence public.user_portfolio_holdings_id_seq to authenticated;
grant all on sequence public.user_portfolio_holdings_id_seq to service_role;

revoke all on table public.user_portfolio_imports from anon, authenticated;
grant select, insert, update, delete on table public.user_portfolio_imports to authenticated;
grant all on table public.user_portfolio_imports to service_role;

create policy "Approved users can read their own portfolio holdings"
  on public.user_portfolio_holdings
  for select
  to authenticated
  using (
    (select auth.uid()) = user_id
    and exists (
      select 1 from public.user_access
      where user_id = (select auth.uid()) and status = 'approved'
    )
  );

create policy "Approved users can add their own portfolio holdings"
  on public.user_portfolio_holdings
  for insert
  to authenticated
  with check (
    (select auth.uid()) = user_id
    and exists (
      select 1 from public.user_access
      where user_id = (select auth.uid()) and status = 'approved'
    )
  );

create policy "Approved users can update their own portfolio holdings"
  on public.user_portfolio_holdings
  for update
  to authenticated
  using ((select auth.uid()) = user_id)
  with check (
    (select auth.uid()) = user_id
    and exists (
      select 1 from public.user_access
      where user_id = (select auth.uid()) and status = 'approved'
    )
  );

create policy "Approved users can delete their own portfolio holdings"
  on public.user_portfolio_holdings
  for delete
  to authenticated
  using (
    (select auth.uid()) = user_id
    and exists (
      select 1 from public.user_access
      where user_id = (select auth.uid()) and status = 'approved'
    )
  );

create policy "Approved users can read their own portfolio imports"
  on public.user_portfolio_imports
  for select
  to authenticated
  using (
    (select auth.uid()) = user_id
    and exists (
      select 1 from public.user_access
      where user_id = (select auth.uid()) and status = 'approved'
    )
  );

create policy "Approved users can add their own portfolio imports"
  on public.user_portfolio_imports
  for insert
  to authenticated
  with check (
    (select auth.uid()) = user_id
    and exists (
      select 1 from public.user_access
      where user_id = (select auth.uid()) and status = 'approved'
    )
  );

create policy "Approved users can update their own portfolio imports"
  on public.user_portfolio_imports
  for update
  to authenticated
  using ((select auth.uid()) = user_id)
  with check (
    (select auth.uid()) = user_id
    and exists (
      select 1 from public.user_access
      where user_id = (select auth.uid()) and status = 'approved'
    )
  );

create policy "Approved users can delete their own portfolio imports"
  on public.user_portfolio_imports
  for delete
  to authenticated
  using (
    (select auth.uid()) = user_id
    and exists (
      select 1 from public.user_access
      where user_id = (select auth.uid()) and status = 'approved'
    )
  );

create function public.replace_my_portfolio_holdings(
  p_broker text,
  p_source text,
  p_holdings jsonb
)
returns table (replaced_count integer, downloaded_at timestamptz)
language plpgsql
security invoker
set search_path = ''
as $$
declare
  v_user_id uuid := auth.uid();
  v_broker text := upper(trim(p_broker));
  v_source text := lower(trim(p_source));
  v_downloaded_at timestamptz := now();
  v_count integer;
begin
  if v_user_id is null then
    raise exception 'Authentication required';
  end if;
  if not exists (
    select 1 from public.user_access
    where user_id = v_user_id and status = 'approved'
  ) then
    raise exception 'Approved user access required';
  end if;
  if char_length(v_broker) not between 1 and 80 then
    raise exception 'Broker must contain between 1 and 80 characters';
  end if;
  if v_source not in ('ibkr_flex', 'csv') then
    raise exception 'Unsupported portfolio import source';
  end if;
  if jsonb_typeof(p_holdings) <> 'array' then
    raise exception 'Holdings must be a JSON array';
  end if;
  if jsonb_array_length(p_holdings) > 1000 then
    raise exception 'A portfolio import is limited to 1000 rows';
  end if;

  delete from public.user_portfolio_holdings
  where user_id = v_user_id and broker = v_broker;
  delete from public.user_portfolio_imports
  where user_id = v_user_id and broker = v_broker;

  insert into public.user_portfolio_holdings (
    user_id, broker, position_key, symbol, description, asset_class, currency,
    quantity, buy_price, bought_on, current_price, current_price_at,
    market_value, unrealized_pnl, target_price, stop_loss, notes,
    import_source, imported_at
  )
  select
    v_user_id,
    v_broker,
    left(coalesce(nullif(trim(item ->> 'position_key'), ''), trim(item ->> 'symbol')), 160),
    upper(trim(item ->> 'symbol')),
    left(nullif(trim(item ->> 'description'), ''), 300),
    left(upper(coalesce(nullif(trim(item ->> 'asset_class'), ''), 'STK')), 20),
    upper(coalesce(nullif(trim(item ->> 'currency'), ''), 'USD')),
    (item ->> 'quantity')::numeric,
    nullif(item ->> 'buy_price', '')::numeric,
    nullif(item ->> 'bought_on', '')::date,
    nullif(item ->> 'current_price', '')::numeric,
    nullif(item ->> 'current_price_at', '')::timestamptz,
    nullif(item ->> 'market_value', '')::numeric,
    nullif(item ->> 'unrealized_pnl', '')::numeric,
    nullif(item ->> 'target_price', '')::numeric,
    nullif(item ->> 'stop_loss', '')::numeric,
    left(nullif(trim(item ->> 'notes'), ''), 500),
    v_source,
    v_downloaded_at
  from jsonb_array_elements(p_holdings) as item;

  get diagnostics v_count = row_count;
  insert into public.user_portfolio_imports (
    user_id, broker, import_source, downloaded_at, row_count
  ) values (
    v_user_id, v_broker, v_source, v_downloaded_at, v_count
  );

  return query select v_count, v_downloaded_at;
end;
$$;

revoke all on function public.replace_my_portfolio_holdings(text, text, jsonb)
  from public, anon;
grant execute on function public.replace_my_portfolio_holdings(text, text, jsonb)
  to authenticated;

comment on table public.user_portfolio_holdings is
  'Current broker portfolio holdings owned by one approved StockScanner user; broker imports replace prior rows.';
comment on table public.user_portfolio_imports is
  'Latest on-demand portfolio import time and row count for each user and broker.';
comment on function public.replace_my_portfolio_holdings(text, text, jsonb) is
  'Atomically replaces the authenticated approved user portfolio for one broker.';
