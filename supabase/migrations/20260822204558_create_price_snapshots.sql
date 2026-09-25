create table public.price_snapshots (
  id bigint generated always as identity primary key,
  generated_at timestamptz not null,
  price_timestamp timestamptz,
  timezone text not null default 'America/New_York',
  source text not null,
  symbol_count integer not null check (symbol_count >= 0),
  updated_count integer not null default 0 check (updated_count >= 0),
  failed_count integer not null default 0 check (failed_count >= 0),
  prices jsonb not null check (jsonb_typeof(prices) = 'object'),
  failures jsonb not null default '{}'::jsonb check (jsonb_typeof(failures) = 'object'),
  created_at timestamptz not null default now(),
  constraint price_snapshots_generated_source_key unique (generated_at, source)
);

create index price_snapshots_generated_at_idx
  on public.price_snapshots (generated_at desc);

alter table public.price_snapshots enable row level security;

revoke all on table public.price_snapshots from anon, authenticated;
grant select on table public.price_snapshots to authenticated;
grant all on table public.price_snapshots to service_role;
grant usage, select on sequence public.price_snapshots_id_seq to service_role;

create policy "Authenticated users can read price snapshots"
  on public.price_snapshots
  for select
  to authenticated
  using (true);

comment on table public.price_snapshots is
  'Append-only hourly and full-scan market price snapshots written by backend automation.';
