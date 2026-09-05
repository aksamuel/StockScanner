from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MIGRATION = ROOT / "supabase/migrations/20260828000000_add_admin_user_approval.sql"
PORTFOLIO_MIGRATION = ROOT / "supabase/migrations/20260828120000_add_user_portfolio_imports.sql"
EDIT_MIGRATION = ROOT / "supabase/migrations/20260828123000_enable_personal_exception_updates.sql"


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
    source = (
        read("personal-lists.js") + read("my-exceptions.html")
        + read("my-bought-selection.html") + read("portfolio-analysis.html")
        + read("portfolio-analysis.js")
    )
    assert "SUPABASE_SERVICE_ROLE_KEY" not in source
    assert "SUPABASE_SECRET_KEY" not in source
    assert "sb_secret_" not in source


def test_personal_list_tables_expand_to_the_viewport_and_scroll_on_mobile():
    styles = read("personal-lists.css")

    assert "width: calc(100vw - 48px);" in styles
    assert "margin-left: calc(50% - 50vw + 24px);" in styles
    assert "width: calc(100vw - 28px);" in styles
    assert "overflow-x: auto;" in styles
    for page in (
        "my-exceptions.html",
        "my-bought-selection.html",
        "portfolio-analysis.html",
    ):
        assert 'class="table-wrap"' in read(page)


def test_personal_list_headers_use_the_compact_single_navigation_pattern():
    styles = read("personal-lists.css")
    auth = read("auth.js")

    assert "padding: 62px 24px 40px;" in styles
    assert "margin-bottom: 14px;" in styles
    assert "padding-top: 12px !important;" in auth
    assert "padding-left: 94px;" in auth
    assert ".stockscanner-menu-toggle > span:last-child { display: none; }" in auth
    assert auth.count('["Scanner", "Bought candidates", "bought-selection.html"]') == 1


def test_pages_deploy_when_personal_list_files_change():
    workflow = read(".github/workflows/scan.yml")
    for path in (
        "my-exceptions.html",
        "my-bought-selection.html",
        "personal-lists.css",
        "personal-lists.js",
        "portfolio-analysis.html",
        "portfolio-analysis.js",
        "portfolio-holdings-template.csv",
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


def test_bought_page_estimates_breakeven_from_equal_weight_top_twenty():
    page = read("my-bought-selection.html")
    logic = read("portfolio-analysis.js")
    report = read("stockscanner/html_report.py")

    assert "Time-to-profit status" in page
    assert "Est. breakeven days" in page
    assert 'querySelector("#kpiBenchmarkData")' in page
    assert "equalWeightTopTwentyMetrics" in page
    assert "estimatedBreakevenDays" in page
    assert "Math.log(purchased / current) / Math.log(1 + dailyReturn)" in logic
    assert "annualizedReturnPercent" in logic
    assert 'id="kpiBenchmarkData" type="application/json"' in report
    assert "not a forecast or a guaranteed recovery date" in page


def test_top_twenty_filters_use_only_the_authenticated_users_personal_rows():
    source = read("auth.js")

    assert '.from("user_bought_selections")' in source
    assert '.from("user_portfolio_holdings")' in source
    assert '.from("user_exceptions")' in source
    assert source.count('.eq("user_id", user.id)') >= 2
    assert '.lte("date_from", today)' in source
    assert '.gte("date_to", today)' in source
    assert '"#topTable tbody tr, #top20DetailsTable tbody tr"' in source
    assert "#allTable tbody tr" not in source


def test_personal_top_twenty_filters_hide_rows_by_default_and_offer_toggles():
    source = read("auth.js")

    assert "showAlreadyBought: false" in source
    assert "showExceptions: false" in source
    assert "row.hidden = hideBought || hideException" in source
    assert 'showLabel: "Show Already Bought"' in source
    assert 'hideLabel: "Hide Already Bought"' in source
    assert 'showLabel: "Show My Exceptions"' in source
    assert 'hideLabel: "Hide My Exceptions"' in source
    assert 'badge.textContent = "Already Bought"' in source
    assert 'badge.textContent = "My Exception"' in source


def test_personal_filters_are_applied_before_protected_page_is_shown():
    source = read("auth.js")
    filter_call = source.index("await applyPersonalTopTwentyFilters(data.user)")
    show_page = source.index("showPage();", filter_call)
    assert filter_call < show_page


def test_protected_pages_use_a_responsive_accessible_navigation_drawer():
    source = read("auth.js")

    assert "addNavigationDrawer(data.user)" in source
    assert 'className = "stockscanner-menu-toggle"' in source
    assert 'className = "stockscanner-navigation-drawer"' in source
    assert 'className = "stockscanner-drawer-overlay"' in source
    assert 'setAttribute("aria-expanded", "false")' in source
    assert 'setAttribute("aria-hidden", "true")' in source
    assert 'event.key === "Escape"' in source
    assert 'overlay.addEventListener("click"' in source
    assert ".dashboard-nav," in source
    assert ".page-nav," in source
    for filename in (
        "index.html",
        "technical.html",
        "analysts.html",
        "bought-selection.html",
        "my-exceptions.html",
        "my-bought-selection.html",
        "portfolio-analysis.html",
        "admin.html",
        "users.html",
    ):
        assert filename in source


def test_portfolio_tables_are_user_owned_and_cascade_deleted():
    source = PORTFOLIO_MIGRATION.read_text(encoding="utf-8")
    for table in ("user_portfolio_holdings", "user_portfolio_imports"):
        assert f"create table public.{table}" in source
        assert "references auth.users (id) on delete cascade" in source
        assert f"alter table public.{table} enable row level security" in source
        assert f"Approved users can read their own portfolio" in source
    assert "security invoker" in source.lower()
    assert "v_user_id uuid := auth.uid()" in source
    assert "where user_id = v_user_id and broker = v_broker" in source
    assert "A portfolio import is limited to 1000 rows" in source


def test_portfolio_csv_atomically_replaces_only_the_current_users_broker():
    migration = PORTFOLIO_MIGRATION.read_text(encoding="utf-8")
    page = read("portfolio-analysis.html")
    function_start = migration.index("create function public.replace_my_portfolio_holdings")
    function_end = migration.index("$$;", function_start)
    function = migration[function_start:function_end]

    scoped_delete = (
        "delete from public.user_portfolio_holdings\n"
        "  where user_id = v_user_id and broker = v_broker;"
    )
    assert scoped_delete in function
    assert function.index(scoped_delete) < function.index(
        "insert into public.user_portfolio_holdings"
    )
    assert "truncate" not in function.lower()
    assert 'await supabase.rpc("replace_my_portfolio_holdings"' in page
    assert "Previous ${broker} holdings replaced" in page
    assert page.index('await supabase.rpc("replace_my_portfolio_holdings"') < page.index(
        "await loadPortfolio();", page.index('await supabase.rpc("replace_my_portfolio_holdings"')
    )


def test_portfolio_page_supports_ibkr_csv_and_rule_based_analysis():
    page = read("portfolio-analysis.html")
    logic = read("portfolio-analysis.js")
    template = read("portfolio-holdings-template.csv")

    assert 'id="ibkrImport"' not in page
    assert 'supabase.functions.invoke("import-ibkr-portfolio"' not in page
    assert 'id="csvFile"' in page
    assert 'href="/StockScanner/portfolio-holdings-template.csv"' in page
    assert '.rpc("replace_my_portfolio_holdings"' in page
    assert page.count('.eq("user_id", user.id)') >= 4
    assert "symbol,quantity,buy_price,buy_date" in template
    assert 'buy_price: ["buy_price", "costbasisprice", "cost_basis_price"]' in logic
    assert 'buy_date: ["buy_date", "opendatetime", "open_date_time", "trade_date"]' in logic
    assert '.toUpperCase().replace(/\\s+/g, "-")' in logic
    assert "Native IBKR exports using Symbol, Quantity, CostBasisPrice, and OpenDateTime" in page
    assert "holdingReturnPercent" in logic
    assert "profitTimingLabel" in logic
    assert 'return decision("sell", "Sell review"' in logic
    assert 'return decision("partial-sell", "Partial sell review"' in logic
    assert "Hold / monitor" in logic
    assert "loadDailyScannerSignals" in page
    assert "const recommendationText = cells[4]?.textContent" in page
    assert "portfolioConcentrationPercent" in page
    assert "portfolioActionDecision" in page


def test_portfolio_uses_seven_percent_review_and_conservative_automatic_target():
    page = read("portfolio-analysis.html")
    logic = read("portfolio-analysis.js")

    assert "DEFAULT_PROFIT_REVIEW_PERCENT = 7" in logic
    assert "recommendedTargetPrice" in logic
    assert 'source: "7% return objective"' not in logic
    assert '`${DEFAULT_PROFIT_REVIEW_PERCENT}% return objective`' in logic
    assert 'source: "Technical Target 1"' in logic
    assert 'source: "Technical resistance"' in logic
    assert 'source: "Analyst target proxy"' in logic
    assert "Math.min(...candidates.map" in logic
    assert 'targetDetails?.type === "manual"' in logic
    assert 'fetchDocument("/StockScanner/technical.html")' in page
    assert 'fetchDocument("/StockScanner/analysts.html")' in page
    assert "scanner.scannerPrice * (1 + scanner.analystTargetUpside / 100)" in page
    assert 'data-sort-key="target"' in page
    assert "gain of at least 7%" in page


def test_portfolio_table_headers_sort_visible_user_holdings():
    page = read("portfolio-analysis.html")

    for key in (
        "symbol", "quantity", "buy_price", "bought_on",
        "present_price", "return_percent", "target", "concentration",
        "held_days", "action", "price_updated",
    ):
        assert f'data-sort-key="{key}"' in page
        assert f'data-sort-column="{key}"' in page
    assert 'let sortKey = "symbol"' in page
    assert 'let sortDirection = "ascending"' in page
    assert "visible.sort(compareHoldings)" in page
    assert "updateSortHeaders()" in page
    assert 'header.setAttribute("aria-sort", active ? sortDirection : "none")' in page


def test_portfolio_kpis_filter_the_holdings_table_accessibly():
    page = read("portfolio-analysis.html")

    for filter_name in ("all", "profitable", "sell", "partial-sell", "hold"):
        assert f'data-portfolio-filter="{filter_name}"' in page
    assert page.count('class="metric metric-filter"') == 5
    assert page.count('aria-controls="brokerTables"') == 6
    assert 'let portfolioFilter = "all"' in page
    assert "analyzed.filter(matchesPortfolioFilter).filter" in page
    assert 'holding.returnPercent > 0' in page
    assert 'holding.decision.code === portfolioFilter' in page
    assert 'button.setAttribute("aria-pressed", active ? "true" : "false")' in page
    assert 'portfolioFilter === selectedFilter && selectedFilter !== "all"' in page
    assert "No holdings from this broker match the selected filters." in page


def test_portfolio_renders_each_broker_in_a_separate_kpi_filtered_table():
    page = read("portfolio-analysis.html")

    assert 'id="brokerTables"' in page
    assert 'id="portfolioTableTemplate"' in page
    assert 'class="broker-group"' in page
    assert "renderBrokerTables(analyzed, visible)" in page
    assert "new Set(analyzed.map((holding) => holding.broker))" in page
    assert "visible.filter((holding) => holding.broker === broker)" in page
    assert "No holdings from this broker match the selected filters." in page
    assert "brokerTables.replaceChildren(...sections)" in page
    assert 'brokerTables.addEventListener("click"' in page
    assert '.eq("user_id", user.id)' in page


def test_manual_broker_name_overrides_detection_and_form_resets_after_upload():
    page = read("portfolio-analysis.html")
    manual_broker = 'document.querySelector("#broker").value.trim().toUpperCase()'
    detection = "detectedPortfolioBroker(csvSource)"
    upload = page[page.index("csvForm.addEventListener"):page.index("async function loadPortfolio")]

    assert upload.index(manual_broker) < upload.index(detection)
    assert "csvForm.reset();" in upload


def test_portfolio_table_places_action_after_symbol_without_broker_column():
    page = read("portfolio-analysis.html")
    header = page[page.index("<thead>"):page.index("</thead>")]
    holding_row = page.index("function holdingRow")
    row_append_start = page.index("row.append(", holding_row)
    row_append = page[row_append_start:page.index("return row;", row_append_start)]

    assert header.index('data-sort-key="symbol"') < header.index('data-sort-key="action"')
    assert header.index('data-sort-key="action"') < header.index('data-sort-key="quantity"')
    assert 'data-sort-key="broker"' not in header
    assert row_append.index("symbolCell") < row_append.index("decisionCell")
    assert row_append.index("decisionCell") < row_append.index("Number(holding.quantity)")
    assert "tableCell(holding.broker)" not in row_append


def test_personal_lists_are_directly_editable_without_github_issues():
    auth = read("auth.js")
    exception_page = read("my-exceptions.html")
    bought_page = read("my-bought-selection.html")
    legacy_page = read("exceptions.html")
    migration = EDIT_MIGRATION.read_text(encoding="utf-8")

    assert 'window.stockscannerPersonalExceptions' in auth
    assert 'window.stockscannerBoughtSelections' in auth
    assert '.upsert(records, { onConflict: "user_id,symbol" })' in auth
    assert '.from("user_exceptions").update(values)' in exception_page
    assert '.from("user_bought_selections").update(values)' in bought_page
    assert 'window.location.replace("my-exceptions.html")' in legacy_page
    assert "github.com/aksamuel/StockScanner/issues" not in legacy_page
    assert "Approved users can update their own exceptions" in migration
    assert "Approved users can update their own bought selections" in migration
