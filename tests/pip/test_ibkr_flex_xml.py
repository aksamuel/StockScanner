import io

import pytest

from stockscanner.pip.ibkr_sync import (
    CSVPortfolioDataSource,
    FlexXMLPortfolioDataSource,
    IBKRPortfolioSyncService,
    MAX_FLEX_XML_BYTES,
    mask_account_identifier,
)
from stockscanner.pip.repository import SupabasePortfolioRepository


PORTFOLIO_ID = "22222222-2222-4222-8222-222222222222"
ACCOUNT_ONE = "U1234567"
ACCOUNT_TWO = "U7654321"

FLEX_XML = f"""<?xml version="1.0" encoding="UTF-8"?>
<FlexQueryResponse queryName="PIP" type="AF">
  <FlexStatements count="2">
    <FlexStatement accountId="{ACCOUNT_ONE}" currency="USD">
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
    <FlexStatement accountId="{ACCOUNT_TWO}" currency="EUR">
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
    assert ACCOUNT_ONE not in repr(repository.saved)
    assert ACCOUNT_TWO not in repr(repository.saved)


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
        <FlexStatement accountId="U1234567" currency="USD">
          <OpenPositions><OpenPosition assetCategory="STK" accountId="U1234567"
            currency="USD" symbol="AAPL" conid="1" position="1" /></OpenPositions>
        </FlexStatement>
        <FlexStatement accountId="U9874567" currency="USD">
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
