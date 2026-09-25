grant update (reason, date_from, date_to) on table public.user_exceptions to authenticated;

create policy "Approved users can update their own exceptions"
  on public.user_exceptions
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

comment on policy "Approved users can update their own exceptions"
  on public.user_exceptions is
  'Allows an approved owner to extend or edit only their own exception row.';

grant update (quantity, buy_price, bought_on, notes)
  on table public.user_bought_selections to authenticated;

create policy "Approved users can update their own bought selections"
  on public.user_bought_selections
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

comment on policy "Approved users can update their own bought selections"
  on public.user_bought_selections is
  'Allows an approved owner to edit only their own bought-selection row.';
