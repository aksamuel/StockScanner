from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def read(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


def test_database_page_is_authenticated_and_in_navigation():
    page = read("database.html")
    auth = read("auth.js")
    workflow = read(".github/workflows/scan.yml")

    assert 'src="/StockScanner/auth.js"' in page
    assert '["Market data", "Database overview", "database.html"]' in auth
    assert '- "database.html"' in workflow


def test_database_page_uses_rls_scoped_queries_and_no_secret():
    page = read("database.html")

    for table in (
        "price_snapshots",
        "user_portfolio_holdings",
        "user_portfolio_imports",
        "user_exceptions",
        "user_bought_selections",
    ):
        assert f'"{table}"' in page
    assert "sb_publishable_" in page
    assert "sb_secret_" not in page
    assert "SUPABASE_SECRET_KEY" not in page


def test_application_logs_are_restricted_to_the_named_admin():
    page = read("database.html")

    assert 'const ADMIN_EMAIL = "aaksamuel@zohomail.com"' in page
    admin_check = page.index('toLowerCase() === ADMIN_EMAIL')
    log_query = page.index('supabase.from("user_activity_events")')
    assert admin_check < log_query
    assert "logs/explorer" in page


def test_database_tables_use_full_viewport_width():
    page = read("database.html")

    assert "width: calc(100vw - 48px)" in page
    assert "width: calc(100vw - 28px)" in page
    assert "overflow-x: auto" in page
