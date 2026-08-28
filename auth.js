import { createClient } from "https://cdn.jsdelivr.net/npm/@supabase/supabase-js@2.112.3/+esm";

const SUPABASE_URL = "https://cszzbkssxxgwgafwuonc.supabase.co";
const SUPABASE_PUBLISHABLE_KEY = "sb_publishable_VnhkG4H4acjm2Hp1k5tzyw_I9xtUrGI";
const APP_ROOT = "/StockScanner/";
const ADMIN_EMAIL = "aaksamuel@zohomail.com";

const supabase = createClient(SUPABASE_URL, SUPABASE_PUBLISHABLE_KEY, {
  auth: {
    persistSession: true,
    autoRefreshToken: true,
    detectSessionInUrl: true,
  },
});

function loginUrl() {
  const next = `${window.location.pathname}${window.location.search}${window.location.hash}`;
  return `${APP_ROOT}login.html?next=${encodeURIComponent(next)}`;
}

function showPage() {
  document.documentElement.classList.add("auth-ready");
}

async function updatePresence(user, signedOut = false) {
  const now = new Date().toISOString();
  const pagePath = `${window.location.pathname}${window.location.search}`.slice(0, 500);

  return supabase.from("user_presence").upsert({
    user_id: user.id,
    last_seen_at: now,
    signed_out_at: signedOut ? now : null,
    last_page: pagePath,
  }, { onConflict: "user_id" });
}

async function recordActivity(user, eventType) {
  const pagePath = `${window.location.pathname}${window.location.search}`.slice(0, 500);

  await Promise.all([
    supabase.from("user_activity_events").insert({
      user_id: user.id,
      event_type: eventType,
      page_path: pagePath,
    }),
    updatePresence(user, eventType === "logout"),
  ]);
}

function addAccountControls(user) {
  const controls = document.createElement("div");
  controls.className = "stockscanner-account";
  controls.setAttribute("aria-label", "Account controls");

  const identity = document.createElement("span");
  const displayName = user.user_metadata?.full_name
    || user.user_metadata?.name
    || user.email
    || "Signed in user";
  identity.textContent = `User: ${displayName}`;
  identity.title = user.email || displayName;

  const exceptions = document.createElement("a");
  exceptions.href = `${APP_ROOT}my-exceptions.html`;
  exceptions.textContent = "My exceptions";
  const bought = document.createElement("a");
  bought.href = `${APP_ROOT}my-bought-selection.html`;
  bought.textContent = "My bought list";
  for (const link of [exceptions, bought]) {
    link.style.color = "#81d4fa";
    link.style.whiteSpace = "nowrap";
  }
  controls.append(identity, exceptions, bought);

  if ((user.email || "").toLowerCase() === ADMIN_EMAIL) {
    const dashboard = document.createElement("a");
    dashboard.href = `${APP_ROOT}admin.html`;
    dashboard.textContent = "Admin dashboard";
    const users = document.createElement("a");
    users.href = `${APP_ROOT}users.html`;
    users.textContent = "Manage users";
    controls.append(dashboard, users);
  }

  const signOut = document.createElement("button");
  signOut.type = "button";
  signOut.textContent = "Sign out";
  signOut.addEventListener("click", async () => {
    signOut.disabled = true;
    await recordActivity(user, "logout").catch(() => {});
    await supabase.auth.signOut({ scope: "local" });
    window.location.replace(`${APP_ROOT}login.html`);
  });

  controls.append(signOut);
  controls.style.flexWrap = "wrap";
  controls.style.maxWidth = "min(95vw, 900px)";
  controls.style.top = "10px";
  controls.style.right = "12px";
  controls.style.bottom = "auto";
  document.body.appendChild(controls);
}

async function protectPage() {
  const { data, error } = await supabase.auth.getUser();

  if (error || !data.user) {
    window.location.replace(loginUrl());
    return;
  }

  const { data: access, error: accessError } = await supabase
    .from("user_access")
    .select("status")
    .eq("user_id", data.user.id)
    .maybeSingle();

  if (accessError || access?.status !== "approved") {
    await supabase.auth.signOut({ scope: "local" });
    window.location.replace(`${APP_ROOT}login.html?approval=pending`);
    return;
  }

  const isAdmin = (data.user.email || "").toLowerCase() === ADMIN_EMAIL;
  if (document.documentElement.hasAttribute("data-admin-only") && !isAdmin) {
    window.location.replace(`${APP_ROOT}index.html`);
    return;
  }

  addAccountControls(data.user);
  showPage();
  await recordActivity(data.user, "page_view").catch(() => {});
  window.setInterval(
    () => updatePresence(data.user).catch(() => {}),
    5 * 60 * 1000,
  );
}

supabase.auth.onAuthStateChange((event) => {
  if (event === "SIGNED_OUT") {
    window.location.replace(`${APP_ROOT}login.html`);
  }
});

protectPage().catch(() => window.location.replace(loginUrl()));
