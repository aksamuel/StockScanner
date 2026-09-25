import { createClient } from "@supabase/supabase-js";

const email = (process.env.ADMIN_EMAIL || "").trim().toLowerCase();
const supabaseUrl = (process.env.SUPABASE_URL || "").trim();
const secretKey = (process.env.SUPABASE_SECRET_KEY || "").trim();
const redirectTo = (process.env.ADMIN_REDIRECT_URL || "").trim();

if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) {
  throw new Error("ADMIN_EMAIL must be a valid email address.");
}
if (!supabaseUrl) {
  throw new Error("SUPABASE_URL is required.");
}
if (!secretKey) {
  throw new Error("SUPABASE_SECRET_KEY is required.");
}

const supabase = createClient(supabaseUrl, secretKey, {
  auth: {
    autoRefreshToken: false,
    detectSessionInUrl: false,
    persistSession: false,
  },
});

async function findUserByEmail(targetEmail) {
  const perPage = 1000;
  for (let page = 1; page <= 100; page += 1) {
    const { data, error } = await supabase.auth.admin.listUsers({ page, perPage });
    if (error) throw error;

    const users = data?.users || [];
    const match = users.find(
      (user) => (user.email || "").trim().toLowerCase() === targetEmail,
    );
    if (match) return match;
    if (users.length < perPage) return null;
  }
  throw new Error("User lookup exceeded the safe pagination limit.");
}

let user = await findUserByEmail(email);
let invited = false;

if (!user) {
  const options = redirectTo ? { redirectTo } : undefined;
  const { data, error } = await supabase.auth.admin.inviteUserByEmail(email, options);
  if (error) throw error;
  user = data?.user;
  invited = true;
}

if (!user?.id) {
  throw new Error("Supabase did not return an administrator user ID.");
}

const appMetadata = {
  ...(user.app_metadata || {}),
  role: "admin",
};
const { error: updateError } = await supabase.auth.admin.updateUserById(user.id, {
  app_metadata: appMetadata,
});
if (updateError) throw updateError;

console.log(
  invited
    ? "Administrator invitation sent and admin role assigned."
    : "Existing user promoted to administrator.",
);
