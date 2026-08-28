create index if not exists signup_allowlist_permitted_by_idx
  on public.signup_allowlist (permitted_by);

drop policy if exists "Users can read their own access status" on public.user_access;
drop policy if exists "StockScanner admin can read access requests" on public.user_access;
create policy "Users or admin can read access status"
  on public.user_access
  for select
  to authenticated
  using (
    (select auth.uid()) = user_id
    or lower(coalesce((select auth.jwt()) ->> 'email', '')) = 'aaksamuel@zohomail.com'
  );

drop policy if exists "StockScanner admin can review access requests" on public.user_access;
create policy "StockScanner admin can review access requests"
  on public.user_access
  for update
  to authenticated
  using (lower(coalesce((select auth.jwt()) ->> 'email', '')) = 'aaksamuel@zohomail.com')
  with check (lower(coalesce((select auth.jwt()) ->> 'email', '')) = 'aaksamuel@zohomail.com');

drop policy if exists "StockScanner admin can view signup permissions" on public.signup_allowlist;
create policy "StockScanner admin can view signup permissions"
  on public.signup_allowlist
  for select
  to authenticated
  using (lower(coalesce((select auth.jwt()) ->> 'email', '')) = 'aaksamuel@zohomail.com');

drop policy if exists "StockScanner admin can grant signup permission" on public.signup_allowlist;
create policy "StockScanner admin can grant signup permission"
  on public.signup_allowlist
  for insert
  to authenticated
  with check (
    lower(coalesce((select auth.jwt()) ->> 'email', '')) = 'aaksamuel@zohomail.com'
    and permitted_by = (select auth.uid())
  );

drop policy if exists "StockScanner admin can revoke signup permission" on public.signup_allowlist;
create policy "StockScanner admin can revoke signup permission"
  on public.signup_allowlist
  for delete
  to authenticated
  using (lower(coalesce((select auth.jwt()) ->> 'email', '')) = 'aaksamuel@zohomail.com');

drop policy if exists "StockScanner admin can read activity" on public.user_activity_events;
create policy "StockScanner admin can read activity"
  on public.user_activity_events
  for select
  to authenticated
  using (lower(coalesce((select auth.jwt()) ->> 'email', '')) = 'aaksamuel@zohomail.com');

drop policy if exists "Users can read their own presence" on public.user_presence;
drop policy if exists "StockScanner admin can read presence" on public.user_presence;
create policy "Users or admin can read presence"
  on public.user_presence
  for select
  to authenticated
  using (
    (select auth.uid()) = user_id
    or lower(coalesce((select auth.jwt()) ->> 'email', '')) = 'aaksamuel@zohomail.com'
  );
