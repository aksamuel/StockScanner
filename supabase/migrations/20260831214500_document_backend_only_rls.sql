create policy "Deny client access to NYSE universe"
on public.nyse_tickers
for all
to anon, authenticated
using (false)
with check (false);

create policy "Deny client access to scanner run state"
on public.scanner_run_state
for all
to anon, authenticated
using (false)
with check (false);

create policy "Deny client access to price collection runs"
on public.price_collection_runs
for all
to anon, authenticated
using (false)
with check (false);
