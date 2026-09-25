from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_shared_sorting_enhances_tables_after_authentication():
    source = read("auth.js")
    install = source.index("function installSharedTableSorting()")
    auth = source.index("async function protectPage()", install)
    call = source.index("installSharedTableSorting();", auth)
    show = source.index("showPage();", call)
    assert install < auth < call < show
    assert 'document.querySelectorAll("table").forEach(enhanceTable)' in source
    assert "new MutationObserver" in source
    assert 'header.setAttribute("aria-sort", direction)' in source
    assert "dataset.sortValue" in source


def test_market_price_table_gets_all_column_sorting_from_shared_guard():
    page = read("market-prices.html")
    assert page.count("<th>") == 6
    assert 'src="/StockScanner/auth.js"' in page
    assert "no-sort" not in page


def test_generated_report_pages_keep_their_existing_all_column_sorting():
    generator = read("stockscanner/html_report.py")
    assert "window.stockscannerNativeTableSorting = true;" in generator
    assert "document.querySelectorAll('th:not(.no-sort)')" in generator
    for filename in ("index.html", "technical.html", "analysts.html", "bought-selection.html"):
        page = read(filename)
        assert "document.querySelectorAll('th:not(.no-sort)')" in page


def test_existing_technical_page_is_reordered_before_display():
    source = read("auth.js")
    reorder = source.index("function reorderTechnicalAnalysisColumns()")
    call = source.index("reorderTechnicalAnalysisColumns();", reorder)
    show = source.index("showPage();", call)
    assert reorder < call < show
    assert 'const desired = ["Rank", "Symbol", "Entry", "Target 1", "Target 2", "Target 3"]' in source
