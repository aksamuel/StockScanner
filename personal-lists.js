import { createClient } from "https://cdn.jsdelivr.net/npm/@supabase/supabase-js@2.112.3/+esm";

export const APP_ROOT = "/StockScanner/";
export const supabase = createClient(
  "https://cszzbkssxxgwgafwuonc.supabase.co",
  "sb_publishable_VnhkG4H4acjm2Hp1k5tzyw_I9xtUrGI",
  { auth: { persistSession: true, autoRefreshToken: true, detectSessionInUrl: true } },
);

export async function requireApprovedUser() {
  const { data: { user }, error } = await supabase.auth.getUser();
  if (error || !user) {
    window.location.replace(`${APP_ROOT}login.html`);
    return null;
  }
  const { data: access, error: accessError } = await supabase
    .from("user_access")
    .select("status")
    .eq("user_id", user.id)
    .maybeSingle();
  if (accessError || access?.status !== "approved") {
    window.location.replace(`${APP_ROOT}login.html?approval=pending`);
    return null;
  }
  return user;
}

export function localDateValue(date = new Date()) {
  const local = new Date(date.getTime() - date.getTimezoneOffset() * 60_000);
  return local.toISOString().slice(0, 10);
}

export { formatDate } from "./date-format.js";

export function setMessage(element, text, success = false) {
  element.textContent = text;
  element.classList.toggle("success", success);
}

export function setFormBusy(form, busy) {
  for (const control of form.elements) control.disabled = busy;
}

export function tableCell(value, className = "") {
  const cell = document.createElement("td");
  cell.textContent = value;
  if (className) cell.className = className;
  return cell;
}
