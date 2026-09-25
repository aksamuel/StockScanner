from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def read(path):
    return (ROOT / path).read_text(encoding="utf-8")


def test_market_price_page_is_approved_user_only_and_reads_singleton():
    page = read("market-prices.html")

    assert 'src="/StockScanner/auth.js"' in page
    assert "requireApprovedUser()" in page
    assert '.from("price_snapshots")' in page
    assert '.eq("source", "hourly_yahoo")' in page
    assert "previous_close_prices" in page
    assert "market_close_prices" in page
    assert "intraday_series" in page
    assert "SUPABASE_SECRET_KEY" not in page
    assert "sb_secret_" not in page


def test_market_price_page_has_accessible_table_and_spike_chart():
    page = read("market-prices.html")
    logic = read("market-prices.js")

    assert "Current price" in page
    assert "Previous close" in page
    assert "Today's market close" in page
    assert 'id="spikeChart"' in page
    assert 'role="img"' in page
    assert 'aria-label="Intraday price points"' in page
    assert "spike-positive" in page
    assert "spike-negative" in page
    assert 'setAttribute("aria-selected"' in page
    assert 'event.key === "Enter"' in page
    assert "percentage move from the previous trading-day close" in page
    assert "Math.abs(value)" in logic


def test_market_data_schema_retains_only_bounded_current_day_points():
    migration = read("supabase/migrations/20260829160000_add_intraday_price_comparison.sql")
    snapshot = read("stockscanner/price_snapshot.py")

    assert "daily_prices jsonb" in migration
    assert "intraday_series jsonb" in migration
    assert "market_date date not null" in migration
    assert "jsonb_typeof(daily_prices) = 'object'" in migration
    assert "jsonb_typeof(intraday_series) = 'object'" in migration
    assert 'points[-16:]' in snapshot or '[-16:]' in snapshot
    assert "timestamp.date() == local.date()" in snapshot


def test_market_page_is_in_navigation_and_deployment_paths():
    auth = read("auth.js")
    scan_workflow = read(".github/workflows/scan.yml")
    price_workflow = read(".github/workflows/price-snapshot.yml")

    assert '["Market data", "Hourly & daily prices", "market-prices.html"]' in auth
    assert '- "market-prices.html"' in scan_workflow
    assert '- "market-prices.js"' in scan_workflow
    assert '- "stockscanner/price_providers.py"' in price_workflow
    assert '- "stockscanner/market_data.py"' in price_workflow
