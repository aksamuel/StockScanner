import { createClient } from "https://cdn.jsdelivr.net/npm/@supabase/supabase-js@2.112.3/+esm";

const SUPABASE_URL = "https://cszzbkssxxgwgafwuonc.supabase.co";
const SUPABASE_PUBLISHABLE_KEY = "sb_publishable_VnhkG4H4acjm2Hp1k5tzyw_I9xtUrGI";
const APP_ROOT = "/StockScanner/";

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

function addAccountControls(user) {
  const controls = document.createElement("div");
  controls.className = "stockscanner-account";
  controls.setAttribute("aria-label", "Account controls");

  const identity = document.createElement("span");
  identity.textContent = user.email || "Signed in";

  const signOut = document.createElement("button");
  signOut.type = "button";
  signOut.textContent = "Sign out";
  signOut.addEventListener("click", async () => {
    signOut.disabled = true;
    await supabase.auth.signOut();
    window.location.replace(`${APP_ROOT}login.html`);
  });

  controls.append(identity, signOut);
  document.body.appendChild(controls);
}

async function protectPage() {
  const { data, error } = await supabase.auth.getUser();

  if (error || !data.user) {
    window.location.replace(loginUrl());
    return;
  }

  addAccountControls(data.user);
  showPage();
}

supabase.auth.onAuthStateChange((event) => {
  if (event === "SIGNED_OUT") {
    window.location.replace(`${APP_ROOT}login.html`);
  }
});

protectPage().catch(() => window.location.replace(loginUrl()));
