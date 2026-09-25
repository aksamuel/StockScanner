-- Schema for daily seed / hourly snapshot persistence.
create extension if not exists pgcrypto;

create table if not exists scan_runs (
    id uuid primary key default gen_random_uuid(),
    run_kind text not null,
    slot_key text not null,
    status text not null default 'pending',
    total_tickers integer not null default 0,
    collected_tickers integer not null default 0,
    remaining_tickers integer not null default 0,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    completed_at timestamptz,
    unique (run_kind, slot_key)
);

create table if not exists scan_tickers (
    id uuid primary key default gen_random_uuid(),
    slot_key text not null,
    ticker text not null,
    status text not null default 'pending',
    attempt_count integer not null default 0,
    claimed_by text,
    claimed_at timestamptz,
    collected_at timestamptz,
    last_price numeric,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    unique (slot_key, ticker)
);

create table if not exists price_snapshots (
    id uuid primary key default gen_random_uuid(),
    slot_key text not null,
    ticker text not null,
    price numeric not null,
    snapshot_time timestamptz not null default now(),
    source text not null default 'yfinance',
    created_at timestamptz not null default now(),
    unique (slot_key, ticker)
);

create index if not exists scan_runs_status_idx on scan_runs (status, run_kind, slot_key);
create index if not exists scan_tickers_slot_status_idx on scan_tickers (slot_key, status, ticker);
create index if not exists price_snapshots_slot_idx on price_snapshots (slot_key, ticker);
