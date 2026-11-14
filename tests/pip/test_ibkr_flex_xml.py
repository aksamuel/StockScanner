import io
from datetime import date, datetime, timezone

import pytest

from stockscanner.pip.ibkr_sync import (
    account_fingerprint,
    CSVPortfolioDataSource,
    FixturePortfolioDataSource,
    FlexXMLPortfolioDataSource,
    IBKRPortfolioSyncService,
    MAX_FLEX_XML_BYTES,
    mask_account_identifier,
)
from stockscanner.pip.repository import InMemoryPortfolioRepository, SupabasePortfolioRepository


PORTFOLIO_ID = "22222222-2222-4222-8222-222222222222"
ACCOUNT_ONE = "U1234567"
ACCOUNT_TWO = "U7654321"

FLEX_XML = f"""<?xml version="1.0" encoding="UTF-8"?>
<FlexQueryResponse queryName="PIP" type="AF">
  <FlexStatements count="2">
    <FlexStatement accountId="{ACCOUNT_ONE}" currency="USD" toDate="20250131">
      <AccountInformation accountId="{ACCOUNT_ONE}" baseCurrency="USD" />
      <OpenPositions>
        <OpenPosition assetCategory="STK" accountId="{ACCOUNT_ONE}" currency="USD"
          symbol="AAPL" conid="265598" position="5" costBasisPrice="100"
          markPrice="120" positionValue="600" openDateTime="20250102" />
        <OpenPosition assetCategory="OPT" accountId="{ACCOUNT_ONE}" currency="USD"
          symbol="AAPL 20261218 C250" position="1" />
      </OpenPositions>
      <Trades>
        <Trade assetCategory="STK" accountId="{ACCOUNT_ONE}" currency="USD"
          symbol="AAPL" tradeID="trade-1" tradeDate="20260806;112923"
          buySell="BUY" quantity="1" tradePrice="120" />
      </Trades>
      <CashTransactions>
        <CashTransaction accountId="{ACCOUNT_ONE}" currency="USD" symbol="AAPL"
          type="Dividends" transactionID="div-1" dateTime="20260806"
          exDate="20260801" payDate="20260806" amount="2.5" />
        <CashTransaction accountId="{ACCOUNT_ONE}" currency="USD" symbol="AAPL"
          type="Deposits" dateTime="20260806" amount="100" />
      </CashTransactions>
    </FlexStatement>
    <FlexStatement accountId="{ACCOUNT_TWO}" currency="EUR" toDate="20250131">
      <AccountInformation accountId="{ACCOUNT_TWO}" baseCurrency="EUR" />
      <OpenPositions>
        <OpenPosition assetCategory="STK" accountId="{ACCOUNT_TWO}" currency="EUR"
          symbol="MSFT" conid="272093" position="2" costBasisMoney="500"
          markPrice="300" positionValue="600" openDateTime="20250203" />
      </OpenPositions>
    </FlexStatement>
  </FlexStatements>
</FlexQueryResponse>
"""


class CapturingRepository:
    def __init__(self):
        self.saved = {}

    def upsert_accounts(self, portfolio_id, accounts):
        self.saved["accounts"] = accounts
        return accounts

    def upsert_positions(self, portfolio_id, positions):
        self.saved["positions"] = positions
        return positions

    def replace_flex_positions(self, portfolio_id, positions, snapshot_accounts, started_at):
        self.saved["positions"] = positions
        self.saved["snapshot_accounts"] = snapshot_accounts
        return positions

    def upsert_transactions(self, portfolio_id, transactions):
        self.saved["transactions"] = transactions
        return transactions

    def upsert_dividends(self, portfolio_id, dividends):
        self.saved["dividends"] = dividends
        return dividends


class AccountPersistenceQuery:
    def __init__(self, client, table):
        self.client = client
        self.table = table
        self.rows = []

    def upsert(self, rows, on_conflict):
        self.client.conflicts.append((self.table, on_conflict))
        self.rows = rows
        return self

    def select(self, columns):
        return self

    def execute(self):
        if self.table == "ibkr_accounts":
            data = [
                {
                    "id": f"account-{index}",
                    "masked_account_id": row["masked_account_id"],
                    "account_fingerprint": row["account_fingerprint"],
                }
                for index, row in enumerate(self.rows)
            ]
        else:
            data = list(self.rows)
        self.client.writes.append((self.table, data))
        return type("Response", (), {"data": data, "error": None})()


class AccountPersistenceClient:
    def __init__(self):
        self.conflicts = []
        self.writes = []

    def table(self, name):
        return AccountPersistenceQuery(self, name)

    def rpc(self, name, params):
        assert name == "pip_replace_flex_positions"
        self.writes.append(("positions", params["p_positions"]))
        return type("Response", (), {
            "execute": lambda self: type("Result", (), {
                "data": len(params["p_positions"]), "error": None,
            })(),
        })()


def test_flex_xml_sync_masks_accounts_and_normalizes_stock_records():
    repository = CapturingRepository()
    result = IBKRPortfolioSyncService(repository).sync(
        FlexXMLPortfolioDataSource(FLEX_XML),
        PORTFOLIO_ID,
    )

    assert len(result["positions"]) == 2
    assert [row["masked_account_id"] for row in repository.saved["accounts"]] == [
        "***4567",
        "***4321",
    ]
    assert [position.account_id for position in repository.saved["positions"]] == [
        "***4567",
        "***4321",
    ]
    assert [position.symbol for position in repository.saved["positions"]] == ["AAPL", "MSFT"]
    assert repository.saved["positions"][1].average_cost == 250
    assert len(repository.saved["transactions"]) == 1
    assert repository.saved["transactions"][0]["metadata"]["account_id"] == "***4567"
    assert len(repository.saved["dividends"]) == 1
    assert repository.saved["dividends"][0]["account_id"] == "***4567"
    assert repository.saved["dividends"][0]["metadata"]["source_key"]
    assert repository.saved["snapshot_accounts"] == {
        account_fingerprint(ACCOUNT_ONE): date(2025, 1, 31),
        account_fingerprint(ACCOUNT_TWO): date(2025, 1, 31),
    }
    assert ACCOUNT_ONE not in repr(repository.saved)
    assert ACCOUNT_TWO not in repr(repository.saved)


@pytest.mark.parametrize(
    ("sections", "expected"),
    [
        ("<Trades /><CashTransactions />", []),
        ("", ["Trades", "Cash Transactions"]),
        ("<Trades />", ["Cash Transactions"]),
        ("<CashTransactions />", ["Trades"]),
    ],
)
def test_flex_xml_warns_about_missing_history_sections_without_rejecting_positions(sections, expected):
    xml = (
        f'<FlexQueryResponse><FlexStatement accountId="{ACCOUNT_ONE}" '
        f'currency="USD" toDate="20250131"><OpenPositions />{sections}'
        "</FlexStatement></FlexQueryResponse>"
    )
    repository = CapturingRepository()

    result = IBKRPortfolioSyncService(repository).sync(
        FlexXMLPortfolioDataSource(xml), PORTFOLIO_ID,
    )

    assert len(result["warnings"]) == len(expected)
    for warning, section in zip(result["warnings"], expected):
        assert f"No {section} section" in warning
        assert "report period" in warning
        assert ACCOUNT_ONE not in warning
    assert repository.saved["snapshot_accounts"] == {
        account_fingerprint(ACCOUNT_ONE): date(2025, 1, 31),
    }


def test_flex_xml_warns_once_if_any_account_lacks_a_history_section():
    xml = (
        "<FlexQueryResponse>"
        f'<FlexStatement accountId="{ACCOUNT_ONE}" currency="USD" toDate="20250131">'
        "<OpenPositions /><Trades /><CashTransactions /></FlexStatement>"
        f'<FlexStatement accountId="{ACCOUNT_TWO}" currency="USD" toDate="20250131">'
        "<OpenPositions /><Trades /></FlexStatement>"
        "</FlexQueryResponse>"
    )

    data = FlexXMLPortfolioDataSource(xml).load_portfolio()

    assert len(data.warnings) == 1
    assert "Cash Transactions" in data.warnings[0]
    assert ACCOUNT_ONE not in data.warnings[0]
    assert ACCOUNT_TWO not in data.warnings[0]


def test_flex_positions_only_skips_invalid_optional_history():
    xml = (
        f'<FlexQueryResponse><FlexStatement accountId="{ACCOUNT_ONE}" '
        'currency="USD" toDate="20250131"><OpenPositions>'
        '<OpenPosition assetCategory="STK" currency="USD" symbol="AAPL" '
        'position="2" costBasisPrice="100" openDateTime="20250102;090000" '
        'levelOfDetail="LOT" /></OpenPositions>'
        '<Trades><Trade assetCategory="STK" /></Trades>'
        '<CashTransactions><CashTransaction type="Dividends" /></CashTransactions>'
        "</FlexStatement></FlexQueryResponse>"
    )
    with pytest.raises(ValueError, match="invalid stock symbol"):
        FlexXMLPortfolioDataSource(xml).load_portfolio()

    data = FlexXMLPortfolioDataSource(xml, positions_only=True).load_portfolio()

    assert len(data.positions) == 1
    assert data.positions[0]["entry_date"] == "20250102;090000"
    assert data.transactions == []
    assert data.dividends == []
    assert len(data.warnings) == 1
    assert "Positions-only" in data.warnings[0]
    assert "retained" in data.warnings[0]
    assert "incomplete" in data.warnings[0]
    assert ACCOUNT_ONE not in data.warnings[0]


def test_flex_positions_only_still_rejects_invalid_open_positions_before_writing():
    xml = (
        f'<FlexQueryResponse><FlexStatement accountId="{ACCOUNT_ONE}" '
        'currency="USD" toDate="20250131"><OpenPositions>'
        '<OpenPosition assetCategory="STK" currency="USD" position="1" />'
        "</OpenPositions></FlexStatement></FlexQueryResponse>"
    )
    repository = CapturingRepository()

    with pytest.raises(ValueError, match="invalid stock symbol"):
        IBKRPortfolioSyncService(repository).sync(
            FlexXMLPortfolioDataSource(xml, positions_only=True), PORTFOLIO_ID,
        )
    assert repository.saved == {}


@pytest.mark.parametrize(
    ("content", "message"),
    [
        ("<FlexQueryResponse><FlexStatements /></FlexQueryResponse>", "no account statements"),
        ("<FlexStatementResponse><Status>Fail</Status></FlexStatementResponse>", "not a Flex Query XML"),
        ("<FlexQueryResponse><!DOCTYPE invalid></FlexQueryResponse>", "invalid or unsafe"),
    ],
)
def test_flex_xml_rejects_invalid_or_unsafe_statements(content, message):
    with pytest.raises(ValueError, match=message):
        FlexXMLPortfolioDataSource(content).load_portfolio()


def test_flex_xml_rejects_external_entities_and_oversized_statements():
    unsafe = """<!DOCTYPE FlexQueryResponse [
      <!ENTITY file SYSTEM "file:///etc/passwd">
    ]><FlexQueryResponse>&file;</FlexQueryResponse>"""
    with pytest.raises(ValueError, match="invalid or unsafe"):
        FlexXMLPortfolioDataSource(unsafe).load_portfolio()
    with pytest.raises(ValueError, match="limited to 5 MB"):
        FlexXMLPortfolioDataSource(b"x" * (MAX_FLEX_XML_BYTES + 1))


def test_mask_account_identifier_is_idempotent_for_imported_masks():
    assert mask_account_identifier("U1234567") == "***4567"
    assert mask_account_identifier("***4567") == "***4567"


def test_distinct_accounts_with_the_same_masked_suffix_remain_separate():
    xml = """<FlexQueryResponse>
      <FlexStatements>
        <FlexStatement accountId="U1234567" currency="USD" toDate="20250131">
          <OpenPositions><OpenPosition assetCategory="STK" accountId="U1234567"
            currency="USD" symbol="AAPL" conid="1" position="1" /></OpenPositions>
        </FlexStatement>
        <FlexStatement accountId="U9874567" currency="USD" toDate="20250131">
          <OpenPositions><OpenPosition assetCategory="STK" accountId="U9874567"
            currency="USD" symbol="MSFT" conid="2" position="2" /></OpenPositions>
        </FlexStatement>
      </FlexStatements>
    </FlexQueryResponse>"""
    client = AccountPersistenceClient()
    result = IBKRPortfolioSyncService(
        SupabasePortfolioRepository(client)
    ).sync(FlexXMLPortfolioDataSource(xml), PORTFOLIO_ID)

    accounts = client.writes[0][1]
    positions = next(rows for table, rows in client.writes if table == "positions")
    assert len(result["accounts"]) == 2
    assert {account["masked_account_id"] for account in result["accounts"]} == {"***4567"}
    assert len({account["account_fingerprint"] for account in accounts}) == 2
    assert [row["account_id"] for row in positions] == ["account-0", "account-1"]
    assert ("ibkr_accounts", "portfolio_id,account_fingerprint") in client.conflicts
    assert "U1234567" not in repr(client.writes)
    assert "U9874567" not in repr(client.writes)


def _position_statement(account: str, statement_date: str, position_rows: str) -> str:
    return (
        f'<FlexQueryResponse><FlexStatements><FlexStatement accountId="{account}" '
        f'currency="USD" toDate="{statement_date}"><OpenPositions>{position_rows}'
        "</OpenPositions></FlexStatement></FlexStatements></FlexQueryResponse>"
    )


def _position(symbol: str, quantity: int, cost: int = 100, account: str = ACCOUNT_ONE) -> str:
    return (
        f'<OpenPosition assetCategory="STK" accountId="{account}" currency="USD" '
        f'symbol="{symbol}" conid="{symbol}" position="{quantity}" costBasisPrice="{cost}" />'
    )


def test_flex_snapshots_replace_changed_and_closed_positions_only_for_included_accounts():
    repository = InMemoryPortfolioRepository()
    service = IBKRPortfolioSyncService(
        repository,
        clock=lambda: datetime(2025, 2, 1, tzinfo=timezone.utc),
    )
    csv_position = service.normalize_position({
        "symbol": "CSV",
        "account_id": ACCOUNT_ONE,
        "quantity": 3,
        "currency": "USD",
    })
    repository.upsert_positions(PORTFOLIO_ID, [csv_position])
    service.sync(FlexXMLPortfolioDataSource(_position_statement(
        ACCOUNT_ONE, "20250130", _position("AAPL", 5) + _position("MSFT", 2),
    )), PORTFOLIO_ID)
    service.sync(FlexXMLPortfolioDataSource(_position_statement(
        ACCOUNT_TWO, "20250130", _position("AAPL", 4, account=ACCOUNT_TWO),
    )), PORTFOLIO_ID)
    service.sync(FlexXMLPortfolioDataSource(_position_statement(
        ACCOUNT_ONE, "20250131", _position("AAPL", 6, 105),
    )), PORTFOLIO_ID)

    positions = repository.positions[PORTFOLIO_ID]
    assert sorted((position.symbol, position.quantity) for position in positions) == [
        ("AAPL", 4.0),
        ("AAPL", 6.0),
        ("CSV", 3.0),
    ]
    assert next(position for position in positions if position.quantity == 6).average_cost == 105

    service.sync(FlexXMLPortfolioDataSource(_position_statement(
        ACCOUNT_ONE, "20250201", "",
    )), PORTFOLIO_ID)
    assert sorted((position.symbol, position.quantity) for position in repository.positions[PORTFOLIO_ID]) == [
        ("AAPL", 4.0),
        ("CSV", 3.0),
    ]


def test_flex_snapshot_rejects_an_older_statement_or_earlier_concurrent_request():
    repository = InMemoryPortfolioRepository()
    service = IBKRPortfolioSyncService(repository)
    source = lambda day, quantity: FlexXMLPortfolioDataSource(
        _position_statement(ACCOUNT_ONE, day, _position("AAPL", quantity))
    )
    newer_request = datetime(2025, 2, 1, 12, 0, tzinfo=timezone.utc)
    older_request = datetime(2025, 2, 1, 11, 0, tzinfo=timezone.utc)
    service.sync(source("20250131", 6), PORTFOLIO_ID, snapshot_started_at=newer_request)

    with pytest.raises(RuntimeError, match="newer Flex"):
        service.sync(source("20250130", 5), PORTFOLIO_ID, snapshot_started_at=newer_request)
    with pytest.raises(RuntimeError, match="newer Flex"):
        service.sync(source("20250131", 5), PORTFOLIO_ID, snapshot_started_at=older_request)
    assert repository.positions[PORTFOLIO_ID][0].quantity == 6


@pytest.mark.parametrize(
    "statement",
    [
        '<FlexStatement accountId="U1234567" toDate="20250131" />',
        '<FlexStatement accountId="U1234567"><OpenPositions /></FlexStatement>',
        '<FlexStatement toDate="20250131"><OpenPositions /></FlexStatement>',
        '<FlexStatement accountId="U1234567" toDate="20250131"><OpenPositions /></FlexStatement>',
        (
            '<FlexStatement accountId="U1234567" currency="USD" toDate="20250131">'
            '<AccountInformation accountId="U7654321" currency="USD" />'
            "<OpenPositions /></FlexStatement>"
        ),
        (
            '<FlexStatement accountId="U1234567" currency="USD" toDate="20250131">'
            '<OpenPositions><OpenPosition currency="USD" symbol="AAPL" position="1" />'
            "</OpenPositions></FlexStatement>"
        ),
        (
            '<FlexStatement accountId="U1234567" currency="USD" toDate="20250131">'
            '<OpenPositions /><Trades><Trade accountId="U7654321" assetCategory="STK" '
            'currency="USD" symbol="AAPL" tradeDate="20250101" buySell="BUY" />'
            "</Trades></FlexStatement>"
        ),
        (
            '<FlexStatement accountId="U1234567" currency="USD" toDate="20250131">'
            '<OpenPositions /><CashTransactions><CashTransaction accountId="U7654321" '
            'currency="USD" symbol="AAPL" type="Dividends" amount="1" />'
            "</CashTransactions></FlexStatement>"
        ),
        (
            '<FlexStatement accountId="U1234567" toDate="20250131"><OpenPositions>'
            + _position("AAPL", 1, account=ACCOUNT_TWO)
            + "</OpenPositions></FlexStatement>"
        ),
    ],
)
def test_flex_rejects_incomplete_or_mismatched_account_snapshots_before_writing(statement):
    repository = CapturingRepository()
    source = FlexXMLPortfolioDataSource(f"<FlexQueryResponse>{statement}</FlexQueryResponse>")
    with pytest.raises(ValueError):
        IBKRPortfolioSyncService(repository).sync(source, PORTFOLIO_ID)
    assert repository.saved == {}


def test_flex_uses_account_information_base_currency_when_statement_omits_it():
    xml = (
        '<FlexQueryResponse><FlexStatement accountId="U1234567" toDate="20250131">'
        '<AccountInformation accountId="U1234567" currency="EUR" />'
        '<OpenPositions><OpenPosition assetCategory="STK" currency="EUR" '
        'symbol="AAPL" position="1" /></OpenPositions></FlexStatement></FlexQueryResponse>'
    )
    data = FlexXMLPortfolioDataSource(xml).load_portfolio()
    assert data.accounts[0]["currency"] == "EUR"


def test_flex_keeps_identical_lots_distinct_and_rejects_mixed_summary_and_lots():
    identical = _position("AAPL", 2)
    lot = identical.replace("<OpenPosition ", '<OpenPosition levelOfDetail="LOT" ')
    data = FlexXMLPortfolioDataSource(
        _position_statement(ACCOUNT_ONE, "20250131", lot + lot)
    ).load_portfolio()
    assert len({position["source_key"] for position in data.positions}) == 2

    summary = identical.replace("<OpenPosition ", '<OpenPosition levelOfDetail="SUMMARY" ')
    with pytest.raises(ValueError, match="Summary and Lot"):
        FlexXMLPortfolioDataSource(
            _position_statement(ACCOUNT_ONE, "20250131", summary + lot)
        ).load_portfolio()
    with pytest.raises(ValueError, match="ambiguous"):
        FlexXMLPortfolioDataSource(
            _position_statement(ACCOUNT_ONE, "20250131", identical + identical)
        ).load_portfolio()


def test_csv_positions_from_accounts_with_the_same_mask_remain_distinct():
    first = CSVPortfolioDataSource(
        io.StringIO("AccountId,Symbol,Quantity,Currency\nU1234567,AAPL,1,USD"),
    ).load_portfolio()
    second = CSVPortfolioDataSource(
        io.StringIO("AccountId,Symbol,Quantity,Currency\nU9874567,AAPL,1,USD"),
    ).load_portfolio()

    assert first.accounts[0]["masked_account_id"] == second.accounts[0]["masked_account_id"]
    assert first.positions[0]["source_key"] != second.positions[0]["source_key"]
    assert first.positions[0]["account_fingerprint"] != second.positions[0]["account_fingerprint"]


def _sync_warnings(source) -> list[str]:
    return IBKRPortfolioSyncService().sync(source, PORTFOLIO_ID)["warnings"]


def test_a_sync_counts_positions_without_a_market_value_and_names_none_of_them():
    csv_text = (
        "Symbol,Quantity,AverageCost,MarketValue,Currency\n"
        "AAA,10,5,60,USD\n"
        "BBB,2,7,,USD\n"
        "CCC,3,9,,USD\n"
    )

    warnings = _sync_warnings(CSVPortfolioDataSource(io.StringIO(csv_text)))

    assert len(warnings) == 1
    assert warnings[0].startswith("Market value is missing for 2 of 3 positions;")
    assert "Mark Price and Position Value" in warnings[0]
    assert "Market Price or Market Value" in warnings[0]
    assert all(symbol not in warnings[0] for symbol in ("AAA", "BBB", "CCC"))


@pytest.mark.parametrize(
    "csv_text",
    [
        "Symbol,Quantity,AverageCost,MarketPrice,Currency\nAAA,10,5,6,USD\n",
        "Symbol,Quantity,AverageCost,MarketValue,Currency\nAAA,10,5,60,USD\n",
        "Symbol,Quantity,AverageCost,MarketValue,Currency\nAAA,10,5,0,USD\n",
    ],
)
def test_a_market_price_or_a_market_value_is_enough_to_raise_no_warning(csv_text):
    assert _sync_warnings(CSVPortfolioDataSource(io.StringIO(csv_text))) == []


def test_the_missing_market_value_warning_is_singular_for_one_position():
    csv_text = "Symbol,Quantity,AverageCost,Currency\nAAA,10,5,USD\n"

    [warning] = _sync_warnings(CSVPortfolioDataSource(io.StringIO(csv_text)))

    assert warning.startswith("Market value is missing for 1 of 1 position;")


def test_closed_positions_are_not_counted_as_missing_a_market_value():
    source = FixturePortfolioDataSource({"positions": [
        {"symbol": "AAA", "quantity": 10, "market_value": 60},
        {"symbol": "BBB", "quantity": 0},
    ]})

    assert _sync_warnings(source) == []


def test_a_short_position_without_a_market_value_counts_as_held_and_missing():
    csv_text = "Symbol,Quantity,AverageCost,Currency\nAAA,-5,10,USD\n"

    [warning] = _sync_warnings(CSVPortfolioDataSource(io.StringIO(csv_text)))

    assert warning.startswith("Market value is missing for 1 of 1 position;")


def test_a_flex_sync_adds_the_missing_market_value_warning_after_the_history_warnings():
    priced = _position("BBB", 1).replace(" />", ' markPrice="12" />')
    xml = (
        f'<FlexQueryResponse><FlexStatement accountId="{ACCOUNT_ONE}" currency="USD" '
        'toDate="20250131"><OpenPositions>'
        + _position("AAA", 5)
        + priced
        + "</OpenPositions><CashTransactions /></FlexStatement></FlexQueryResponse>"
    )

    warnings = _sync_warnings(FlexXMLPortfolioDataSource(xml))

    assert len(warnings) == 2
    assert "No Trades section" in warnings[0]
    assert warnings[1].startswith("Market value is missing for 1 of 2 positions;")
    assert ACCOUNT_ONE not in " ".join(warnings)


def test_a_positions_only_flex_sync_also_reports_missing_market_values():
    xml = _position_statement(ACCOUNT_ONE, "20250131", _position("AAA", 5))

    warnings = _sync_warnings(FlexXMLPortfolioDataSource(xml, positions_only=True))

    assert len(warnings) == 2
    assert "Positions-only" in warnings[0]
    assert warnings[1].startswith("Market value is missing for 1 of 1 position;")
