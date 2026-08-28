from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MIGRATION = ROOT / "supabase/migrations/20260828000000_add_admin_user_approval.sql"


def read(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


def test_personal_list_pages_use_auth_and_owner_filters():
    for page, table in (
        ("my-exceptions.html", "user_exceptions"),
        ("my-bought-selection.html", "user_bought_selections"),
    ):
        source = read(page)
        assert 'src="/StockScanner/auth.js"' in source
        assert "requireApprovedUser()" in source
        assert f'.from("{table}")' in source
        assert '.eq("user_id", user.id)' in source
        assert "user_id: user.id" in source


def test_personal_lists_are_auth_owned_and_cascade_on_user_delete():
    source = MIGRATION.read_text(encoding="utf-8")
    for table in ("user_exceptions", "user_bought_selections"):
        table_start = source.index(f"create table public.{table}")
        table_end = source.index(");", table_start)
        definition = source[table_start:table_end]
        assert "references auth.users (id) on delete cascade" in definition
        assert f"alter table public.{table} enable row level security" in source
        assert f"grant select, insert, delete on table public.{table} to authenticated" in source


def test_personal_list_rls_requires_approved_owner():
    source = MIGRATION.read_text(encoding="utf-8")
    for policy_name in (
        "Approved users can read their own exceptions",
        "Approved users can add their own exceptions",
        "Approved users can delete their own exceptions",
        "Approved users can read their own bought selections",
        "Approved users can add their own bought selections",
        "Approved users can delete their own bought selections",
    ):
        start = source.index(f'create policy "{policy_name}"')
        policy = source[start:source.index(";", start)]
        assert "(select auth.uid()) = user_id" in policy
        assert "status = 'approved'" in policy


def test_personal_list_client_contains_no_server_secret():
    source = read("personal-lists.js") + read("my-exceptions.html") + read("my-bought-selection.html")
    assert "SUPABASE_SERVICE_ROLE_KEY" not in source
    assert "SUPABASE_SECRET_KEY" not in source
    assert "sb_secret_" not in source


def test_pages_deploy_when_personal_list_files_change():
    workflow = read(".github/workflows/scan.yml")
    for path in (
        "my-exceptions.html",
        "my-bought-selection.html",
        "personal-lists.css",
        "personal-lists.js",
    ):
        assert f'- "{path}"' in workflow


def test_bought_page_calculates_latest_profit_and_loss_percentage():
    page = read("my-bought-selection.html")
    styles = read("personal-lists.css")

    assert "<th>Symbol</th><th>Profit / Loss %</th>" in page
    assert '.from("price_snapshots")' in page
    assert '.eq("source", "hourly_yahoo")' in page
    assert "((currentPrice - purchasedPrice) / purchasedPrice) * 100" in page
    assert 'profitLoss > 0 ? "pl-profit"' in page
    assert 'profitLoss < 0 ? "pl-loss"' in page
    assert "td.pl-profit" in styles
    assert "td.pl-loss" in styles
