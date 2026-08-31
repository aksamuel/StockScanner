create table if not exists public.scanner_run_state (
    singleton_id smallint primary key default 1 check (singleton_id = 1),
    market_date date not null,
    status text not null check (status in ('running', 'completed', 'failed')),
    workflow_run_id bigint not null,
    trigger_source text not null default 'unknown',
    started_at timestamptz not null default now(),
    completed_at timestamptz,
    last_error text
);

alter table public.scanner_run_state enable row level security;

revoke all on table public.scanner_run_state from public, anon, authenticated;
grant select, insert, update on table public.scanner_run_state to service_role;

create or replace function public.acquire_daily_scanner_run(
    p_market_date date,
    p_workflow_run_id bigint,
    p_trigger_source text default 'unknown',
    p_force boolean default false
)
returns boolean
language plpgsql
security invoker
set search_path = ''
as $$
declare
    affected_rows integer;
begin
    insert into public.scanner_run_state (
        singleton_id,
        market_date,
        status,
        workflow_run_id,
        trigger_source,
        started_at,
        completed_at,
        last_error
    )
    values (
        1,
        p_market_date,
        'running',
        p_workflow_run_id,
        coalesce(nullif(p_trigger_source, ''), 'unknown'),
        now(),
        null,
        null
    )
    on conflict (singleton_id) do update
    set market_date = excluded.market_date,
        status = 'running',
        workflow_run_id = excluded.workflow_run_id,
        trigger_source = excluded.trigger_source,
        started_at = now(),
        completed_at = null,
        last_error = null
    where p_force
       or public.scanner_run_state.market_date < excluded.market_date
       or public.scanner_run_state.status = 'failed'
       or (
           public.scanner_run_state.status = 'running'
           and public.scanner_run_state.started_at < now() - interval '2 hours'
       );

    get diagnostics affected_rows = row_count;
    return affected_rows = 1;
end;
$$;

create or replace function public.finish_daily_scanner_run(
    p_market_date date,
    p_workflow_run_id bigint,
    p_status text,
    p_error text default null
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
        raise exception 'Invalid scanner completion status: %', p_status;
    end if;

    update public.scanner_run_state
    set status = p_status,
        completed_at = now(),
        last_error = case when p_status = 'failed' then left(p_error, 2000) else null end
    where singleton_id = 1
      and market_date = p_market_date
      and workflow_run_id = p_workflow_run_id
      and status = 'running';

    get diagnostics affected_rows = row_count;
    return affected_rows = 1;
end;
$$;

revoke all on function public.acquire_daily_scanner_run(date, bigint, text, boolean)
    from public, anon, authenticated;
revoke all on function public.finish_daily_scanner_run(date, bigint, text, text)
    from public, anon, authenticated;
grant execute on function public.acquire_daily_scanner_run(date, bigint, text, boolean)
    to service_role;
grant execute on function public.finish_daily_scanner_run(date, bigint, text, text)
    to service_role;
