from __future__ import annotations

from datetime import date, datetime, timezone
from pathlib import Path
import re

import pytest

from stockscanner.pip.approval_workflow import (
    ApprovalStatus,
    ApprovalWorkflow,
    InvalidApprovalTransition,
)
from stockscanner.pip.config import order_transmission_enabled
from stockscanner.pip.dead_money import DeadMoneyDetector
from stockscanner.pip.dividend_analysis import DividendAnalysisEngine
from stockscanner.pip.forward_looking import ForwardLookingAnalyzer
from stockscanner.pip.growth_analysis import GrowthAnalysisEngine
from stockscanner.pip.ibkr_sync import (
    CSVPortfolioDataSource,
    FixturePortfolioDataSource,
    IBKRPortfolioSyncService,
)
from stockscanner.pip.position_lifecycle import PositionLifecycleAnalyzer
from stockscanner.pip.replacement_engine import ReplacementCandidateEngine
from stockscanner.pip.repository import SupabaseAuditLogSink, SupabasePortfolioRepository
from stockscanner.pip.sell_advisor import SellAdvisor
from stockscanner.pip.scoring import (
    CPS_WEIGHTS,
    SELL_SCORE_WEIGHTS,
    calculate_cps_result,
    calculate_sell_score_result,
)


def test_scoring_preserves_weights_and_normalizes_sell_score():
    assert sum(CPS_WEIGHTS.values()) == 100
    assert sum(SELL_SCORE_WEIGHTS.values()) == 115
    result = calculate_sell_score_result({name: 100 for name in SELL_SCORE_WEIGHTS})
    assert result.score == 100
    assert result.confidence == 1

    one_factor = calculate_sell_score_result(
        {name: (100 if name == "opportunity_cost" else 0) for name in SELL_SCORE_WEIGHTS}
    )
    assert one_factor.score == pytest.approx(15 / 115 * 100)


def test_scoring_reports_missing_data_and_reduces_confidence():
    result = calculate_cps_result({
        "tsr": 80,
        "relative_performance": 80,
        "dividend_growth": 80,
        "earnings_growth": 80,
        "analyst_revisions": None,
    })
    assert result.score == 80
    assert result.confidence == pytest.approx(0.9)
    assert result.reasons == ("Analyst Revisions data is missing.",)

    empty = calculate_cps_result({})
    assert empty.score is None
    assert empty.confidence == 0
    assert len(empty.reasons) == len(CPS_WEIGHTS)


def test_fixture_sync_normalizes_records_and_masks_account_identifier():
    service = IBKRPortfolioSyncService(clock=lambda: datetime(2026, 1, 2, tzinfo=timezone.utc))
    fixture = FixturePortfolioDataSource({
        "accounts": [{"account_name": "Broker", "account_id": "U12345678"}],
        "positions": [{
            "symbol": "aapl",
            "account_id": "U12345678",
            "quantity": "2",
            "average_cost": "100",
            "market_price": "110",
        }],
        "transactions": [{
            "symbol": "AAPL", "type": "buy", "quantity": 2, "price": 100, "trade_date": "2025-01-01",
        }],
        "dividends": [{"symbol": "aapl", "amount": 1.25, "pay_date": "2025-04-01"}],
    })

    result = service.sync(fixture, "portfolio-id")
    assert result["accounts"][0]["masked_account_id"] == "***5678"
    assert result["positions"][0].symbol == "AAPL"
    assert result["positions"][0].market_value == 220
    assert result["positions"][0].cost_basis == 200
    assert result["positions"][0].portfolio_id == "portfolio-id"
    assert result["transactions"][0]["trade_date"] == "2025-01-01"
    assert result["dividends"][0]["pay_date"] == date(2025, 4, 1)
    assert "U12345678" not in repr(result)


def test_csv_flex_source_reads_existing_export_without_network(tmp_path: Path):
    path = tmp_path / "holdings.csv"
    path.write_text(
        "ClientAccountID,Symbol,Quantity,CostBasisPrice,OpenDateTime,Currency,CurrentPrice\n"
        "U99990000,msft,3,100,20250102,USD,125\n",
        encoding="utf-8",
    )
    source = CSVPortfolioDataSource(path)
    records = IBKRPortfolioSyncService().sync(source, "p1")
    assert records["accounts"][0]["masked_account_id"] == "***0000"
    assert records["positions"][0].symbol == "MSFT"
    assert records["positions"][0].market_value == 375
    assert records["positions"][0].account_id == "***0000"
    assert "U99990000" not in repr(records)


def test_csv_import_accepts_workbench_day_month_year_buy_date():
    from io import StringIO

    source = CSVPortfolioDataSource(
        StringIO(
            "Account,Symbol,Quantity,CostBasisPrice,BuyDate,Currency\n"
            "U12345678,AAPL,2,100,02/Jan/2025,USD\n"
        )
    )
    records = IBKRPortfolioSyncService().sync(source, "portfolio-id")
    assert records["positions"][0].entry_date == datetime(2025, 1, 2, tzinfo=timezone.utc)


def test_csv_import_keeps_duplicate_symbol_lots_distinct_in_supabase():
    from io import StringIO

    class Response:
        error = None
        data = []

        def execute(self):
            return self

    class Query:
        def __init__(self, client, table):
            self.client, self.table = client, table

        def upsert(self, rows, on_conflict):
            self.client.position_rows = rows
            return Response()

    class Client:
        def table(self, table):
            return Query(self, table)

    source = CSVPortfolioDataSource(
        StringIO(
            "Symbol,Quantity,CostBasisPrice,BuyDate,Currency\n"
            "AAPL,2,100,02/Jan/2025,USD\n"
            "AAPL,1,110,15/Jan/2025,USD\n"
        )
    )
    client = Client()
    IBKRPortfolioSyncService(SupabasePortfolioRepository(client)).sync(source, "portfolio-id")

    rows = client.position_rows
    assert len(rows) == 2
    assert {row["symbol"] for row in rows} == {"AAPL"}
    assert len({row["source_key"] for row in rows}) == 2


def test_csv_import_applies_explicit_default_currency_to_positions():
    from io import StringIO

    source = CSVPortfolioDataSource(
        StringIO("Account,Symbol,Quantity,AverageCost\nU12345678,AAPL,2,100\n"),
        default_currency="GBP",
    )
    records = IBKRPortfolioSyncService().sync(source, "portfolio-id")
    assert records["positions"][0].currency == "GBP"


def test_sync_rejects_invalid_position_rows():
    service = IBKRPortfolioSyncService()
    with pytest.raises(ValueError, match="Invalid symbol"):
        service.normalize_position({"symbol": "not a ticker", "quantity": 1})
    with pytest.raises(ValueError, match="quantity"):
        service.normalize_position({"symbol": "AAPL"})


def test_lifecycle_growth_forward_and_dead_money_outputs_handle_missing_data():
    lifecycle = PositionLifecycleAnalyzer().summarize_position(
        "AAPL",
        entry_date="2025-01-01",
        cost_basis=100,
        market_value=90,
        dividends=2,
    )
    assert lifecycle.days_held is not None
    assert lifecycle.total_return_percent == pytest.approx(-8)

    no_growth = GrowthAnalysisEngine().analyze()
    assert no_growth.score is None
    assert no_growth.confidence == 0
    partial_growth = GrowthAnalysisEngine().analyze(earnings_growth_percent=10)
    assert partial_growth.score == 75
    assert partial_growth.confidence == 0.5

    forward = ForwardLookingAnalyzer().analyze(target_upside_percent=10)
    assert forward.score == 60
    assert forward.confidence == 0.6
    assert any("revisions data is missing" in reason.lower() for reason in forward.reasons)

    assessment = DeadMoneyDetector().assess("AAPL", cps=30, total_return_percent=-10)
    assert assessment.is_dead_money is True
    assert assessment.confidence == pytest.approx(2 / 3)
    assert DeadMoneyDetector().assess("AAPL", cps=None).is_dead_money is None
    assert DividendAnalysisEngine().analyze([], None, None, None, None)["confidence"] == 0


def test_replacement_engine_excludes_held_symbols_and_concentration_breaches():
    candidates = ReplacementCandidateEngine().generate_candidates(
        symbol="AAPL",
        current_score=50,
        peer_scores=[("MSFT", 90), ("NVDA", 85), ("TSLA", 80)],
        candidate_cps={"MSFT": 80, "NVDA": 70, "TSLA": 90},
        held_symbols={"NVDA"},
        concentrations={"TSLA": 25},
        max_concentration_percent=20,
    )
    assert [candidate.symbol for candidate in candidates] == ["MSFT"]
    assert candidates[0].score == 85
    assert any("CPS" in reason for reason in candidates[0].rationale)


def test_supabase_sync_adapter_upserts_only_masked_data():
    class Response:
        error = None

        def __init__(self, data=None):
            self.data = data or []

    class Query:
        def __init__(self, client, table):
            self.client, self.table_name = client, table

        def upsert(self, rows, on_conflict):
            self.client.calls.append((self.table_name, "upsert", rows, on_conflict))
            data = rows
            if self.table_name == "ibkr_accounts":
                data = [{**rows[0], "id": "account-uuid"}]
            return ResponseQuery(self.client, self.table_name, data)

        def insert(self, row):
            self.client.calls.append((self.table_name, "insert", row))
            return ResponseQuery(self.client, self.table_name, [row])

        def update(self, row):
            self.client.calls.append((self.table_name, "update", row))
            return ResponseQuery(self.client, self.table_name, [])

        def eq(self, key, value):
            self.client.calls.append((self.table_name, "eq", key, value))
            return self

        def execute(self):
            return Response()

    class ResponseQuery:
        def __init__(self, client, table, data):
            self.client, self.table, self.data = client, table, data

        def execute(self):
            return Response(self.data)

        def select(self, columns):
            self.client.calls.append((self.table, "select", columns))
            return self

        def eq(self, key, value):
            self.client.calls.append((self.table, "eq", key, value))
            return self

    class Client:
        def __init__(self):
            self.calls = []

        def table(self, table):
            return Query(self, table)

    client = Client()
    repository = SupabasePortfolioRepository(client)
    result = IBKRPortfolioSyncService(repository).sync(FixturePortfolioDataSource({
        "accounts": [{"account_id": "U12345678"}],
        "positions": [{"symbol": "AAPL", "account_id": "U12345678", "quantity": 1}],
        "transactions": [{"symbol": "AAPL", "type": "buy", "trade_date": "2026-01-01"}],
        "dividends": [{"symbol": "AAPL", "amount": 1, "pay_date": "2026-02-01"}],
    }), "portfolio-uuid")
    assert len(result["positions"]) == 1
    assert {call[0] for call in client.calls} >= {
        "ibkr_accounts", "positions", "transactions", "dividends",
    }
    assert "U12345678" not in repr(client.calls)
    position_call = next(call for call in client.calls if call[0] == "positions")
    assert position_call[2][0]["account_id"] == "account-uuid"


def test_supabase_audit_sink_records_transition_and_state_without_raw_ids():
    class Response:
        error = None
        data = []

        def execute(self):
            return self

    class Query:
        def __init__(self, client, table):
            self.client, self.table_name = client, table

        def insert(self, row):
            self.client.calls.append((self.table_name, "insert", row))
            return self

        def update(self, row):
            self.client.calls.append((self.table_name, "update", row))
            return self

        def eq(self, key, value):
            self.client.calls.append((self.table_name, "eq", key, value))
            return self

        def execute(self):
            return Response()

    class Client:
        def __init__(self):
            self.calls = []

        def table(self, table):
            return Query(self, table)

        def rpc(self, name, params):
            self.calls.append((name, params))
            return Response()

    client = Client()
    recommendation_id = "11111111-1111-4111-8111-111111111111"
    sink = SupabaseAuditLogSink(
        client,
        "22222222-2222-4222-8222-222222222222",
        "33333333-3333-4333-8333-333333333333",
    )
    workflow = ApprovalWorkflow(audit_sink=sink)
    workflow.propose(recommendation_id)
    workflow.begin_review(recommendation_id, "reviewer")
    workflow.approve(recommendation_id, "reviewer", "Reviewed.")
    transition_calls = [call for call in client.calls if call[0] == "pip_transition_sell_recommendation"]
    assert len(transition_calls) == 3
    assert transition_calls[-1][1]["p_expected_status"] == "under_review"
    assert transition_calls[-1][1]["p_next_status"] == "approved"
    assert transition_calls[-1][1]["p_actor"] == "reviewer"


def test_sell_advisor_can_recommend_partial_review():
    recommendation = SellAdvisor().build_recommendation(
        portfolio_id="portfolio-1",
        symbol="AAPL",
        sell_score=55,
        cps=55,
        opportunity_cost=75,
        technical_health=60,
        relative_performance=50,
    )
    assert recommendation.recommendation == "partial-sell"


def test_approval_workflow_validates_transitions_and_audits_every_transition():
    sink_events = []
    workflow = ApprovalWorkflow(audit_sink=sink_events.append)
    with pytest.raises(InvalidApprovalTransition):
        workflow.approve("rec-1", "reviewer", "Not proposed")

    assert workflow.propose("rec-1").status is ApprovalStatus.PROPOSED
    workflow.begin_review("rec-1", "reviewer")
    with pytest.raises(ValueError, match="human approval"):
        workflow.approve("rec-1", "", "")
    approved = workflow.approve("rec-1", "reviewer", "Score reviewed.")
    assert approved.status is ApprovalStatus.APPROVED
    workflow.mark_submitted("rec-1", "reviewer", "Manually submitted outside PIP.")
    assert workflow.latest("rec-1").status is ApprovalStatus.SUBMITTED
    assert len(workflow.audit_logs) == len(sink_events) == 4
    assert workflow.audit_logs[-1]["to_status"] == "submitted"

    with pytest.raises(InvalidApprovalTransition):
        workflow.cancel("rec-1", "reviewer", "Already terminal.")


def test_approval_audit_redacts_secrets_and_numeric_account_ids():
    workflow = ApprovalWorkflow()
    workflow.submit("rec-2")
    event = workflow.audit_logs[0]
    assert "U12345678" not in repr(event)
    workflow.approve("rec-2", "account U12345678", "token=supersecret approved")
    assert "U12345678" not in repr(workflow.audit_logs)
    assert "supersecret" not in repr(workflow.audit_logs)


def test_order_transmission_is_disabled_by_default_and_in_ci():
    assert not order_transmission_enabled({})
    assert not order_transmission_enabled({"PIP_IBKR_ORDER_TRANSMISSION_ENABLED": "true", "CI": "true"})
    assert not order_transmission_enabled({
        "PIP_IBKR_ORDER_TRANSMISSION_ENABLED": "true",
        "PYTEST_CURRENT_TEST": "test_order_transmission_is_disabled",
    })


def test_pip_migration_has_rls_and_append_only_audit_logs():
    migration = Path(__file__).parents[1] / "supabase/migrations/20261023_pip_core_schema.sql"
    approval_migration = Path(__file__).parents[1] / "supabase/migrations/20261024_pip_approval_rpc.sql"
    sql = migration.read_text(encoding="utf-8").lower()
    approval_sql = approval_migration.read_text(encoding="utf-8").lower()
    tables = (
        "pip_profiles", "portfolios", "ibkr_accounts", "positions", "transactions",
        "dividends", "daily_snapshots", "analyst_signals", "stock_scores",
        "sell_recommendations", "replacement_candidates", "audit_logs",
    )
    for table in tables:
        match = re.search(
            rf"create table if not exists public\.{table}\s*\((.*?)\n\);",
            sql,
            re.DOTALL,
        )
        assert match
        assert "created_at timestamptz not null default now()" in match.group(1)
        assert "updated_at timestamptz not null default now()" in match.group(1)
        assert f"alter table public.{table} enable row level security" in sql
    assert "references auth.users(id)" in sql
    assert "public.user_access" in sql
    assert "masked_account_id" in sql
    assert "account_number text" not in sql
    assert "grant select, insert on public.audit_logs to authenticated" in sql
    assert "for update to authenticated" not in sql.split("create policy \"pip owners read audit logs\"", 1)[1]
    assert "for delete to authenticated" not in sql.split("create policy \"pip owners read audit logs\"", 1)[1]
    assert "security definer" in approval_sql
    assert "auth.uid()" in approval_sql
    assert "revoke update, delete on public.sell_recommendations from anon, authenticated" in approval_sql
    assert "pip_transition_sell_recommendation" in approval_sql
    assert "revoke insert on public.audit_logs from anon, authenticated" in approval_sql
    assert "approved_by is null" in approval_sql
