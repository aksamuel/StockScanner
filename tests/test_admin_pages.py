from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ADMIN_EMAIL = "aaksamuel@zohomail.com"


def read(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


def test_admin_pages_are_marked_for_admin_only_guard():
    for page in ("admin.html", "users.html"):
        source = read(page)
        assert '<html lang="en" data-admin-only>' in source
        assert ADMIN_EMAIL in source
        assert 'src="/StockScanner/auth.js"' in source


def test_auth_guard_redirects_non_admin_before_showing_admin_page():
    source = read("auth.js")
    admin_check = source.index('hasAttribute("data-admin-only")')
    redirect = source.index('window.location.replace(`${APP_ROOT}index.html`)', admin_check)
    show_page = source.index("showPage();", redirect)
    assert admin_check < redirect < show_page


def test_admin_dashboard_contains_activity_metrics():
    source = read("admin.html")
    for metric in (
        "Registered users",
        "Approved users",
        "Active now",
        "Total logins",
        "Total page hits",
    ):
        assert metric in source


def test_admin_dashboard_can_request_manual_scanner_runs():
    source = read("admin.html")
    assert 'id="runDaily"' in source
    assert 'id="runHourly"' in source
    assert 'supabase.functions.invoke("trigger-scanner"' in source
    assert 'triggerWorkflow("daily"' in source
    assert 'triggerWorkflow("hourly"' in source


def test_scanner_trigger_function_verifies_admin_and_keeps_github_token_server_side():
    source = read("supabase/functions/trigger-scanner/index.ts")
    verified_user = source.index("userClient.auth.getUser()")
    admin_email_check = source.index("!== ADMIN_EMAIL", verified_user)
    github_token = source.index('Deno.env.get("GITHUB_ACTIONS_TOKEN")', admin_email_check)
    assert verified_user < admin_email_check < github_token
    assert 'file: "scan.yml"' in source
    assert 'file: "price-snapshot.yml"' in source
    assert 'inputs: { mode: "universe"' in source
    assert 'inputs: { mode: "hourly"' in source
    assert "github_pat_" not in source
    assert "ghp_" not in source


def test_user_management_offers_requested_actions():
    source = read("users.html")
    for action in ("accept", "block", "delete"):
        assert f'"{action}"' in source
    assert "Protected administrator" in source


def test_edge_function_verifies_admin_before_using_admin_api():
    source = read("supabase/functions/manage-user/index.ts")
    verified_user = source.index("userClient.auth.getUser()")
    admin_email_check = source.index("!== ADMIN_EMAIL", verified_user)
    admin_client = source.index("const adminClient", admin_email_check)
    assert verified_user < admin_email_check < admin_client
    assert 'defaultKey("SUPABASE_SECRET_KEYS", "SUPABASE_SERVICE_ROLE_KEY")' in source
    assert "sb_secret_" not in source


def test_presence_heartbeat_does_not_increment_page_hits():
    source = read("auth.js")
    interval = source[source.index("window.setInterval("):]
    assert "updatePresence(data.user)" in interval
    assert 'recordActivity(data.user, "page_view")' not in interval


def test_navigation_drawer_displays_user_identity():
    source = read("auth.js")
    assert "user.user_metadata?.full_name" in source
    assert "user.email" in source
    assert "identity.textContent = displayName" in source
    assert 'identity.className = "stockscanner-drawer-user"' in source
    assert "identity.title = user.email || displayName" in source


def test_login_actions_stack_on_narrow_mobile_screens():
    source = read("login.html")
    assert "@media (max-width: 480px)" in source
    assert ".actions { grid-template-columns: 1fr; }" in source


def test_admin_tables_use_full_viewport_width_with_mobile_gutters():
    for page in ("admin.html", "users.html"):
        source = read(page)
        assert "width: calc(100vw - 48px)" in source
        assert "margin-left: calc(50% - 50vw + 24px)" in source
        assert "width: calc(100vw - 28px)" in source
        assert "overflow-x: auto" in source


def test_admin_pages_use_one_compact_header_pattern():
    for page in ("admin.html", "users.html"):
        source = read(page)
        assert "padding: 62px 24px 40px" in source
        assert "font-size: 1.45rem" in source
        assert ".stockscanner-account" not in source
