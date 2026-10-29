from __future__ import annotations

import csv
import io
import os
import re
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any, Callable
from uuid import UUID

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request, status
from fastapi.concurrency import run_in_threadpool
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, ConfigDict, Field, field_validator
from fastapi.responses import JSONResponse
import httpx
from supabase import create_client
from postgrest.exceptions import APIError
try:
    from supabase_auth.errors import AuthApiError
except ImportError:
    from gotrue.errors import AuthApiError

from .approval_workflow import ApprovalDecision, ApprovalStatus, ApprovalWorkflow
from .dead_money import DeadMoneyDetector
from .decision_engine import DecisionEngine
from .dividend_analysis import DividendAnalysisEngine, DividendRecord
from .forward_looking import ForwardLookingAnalyzer
from .growth_analysis import GrowthAnalysisEngine
from .ibkr_sync import CSVPortfolioDataSource, IBKRPortfolioSyncService
from .opportunity_cost import OpportunityCostEngine
from .position_lifecycle import PositionLifecycleAnalyzer
from .repository import SupabaseAuditLogSink, SupabasePortfolioRepository
from .research import ResearchDataUnavailable, collect_research_data
from .scoring import calculate_cps_result


MAX_CSV_BYTES = 1_000_000
MAX_CSV_ROWS = 1_000
SYMBOL_PATTERN = re.compile(r"^[A-Z0-9][A-Z0-9.-]{0,29}$")


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class PortfolioCreate(StrictModel):
    name: str = Field(min_length=1, max_length=100)
    currency: str = Field(default="USD", min_length=3, max_length=3)

    @field_validator("name")
    @classmethod
    def clean_name(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Portfolio name cannot be blank")
        return value

    @field_validator("currency")
    @classmethod
    def normalize_currency(cls, value: str) -> str:
        value = value.strip().upper()
        if not value.isalpha():
            raise ValueError("Currency must be a three-letter code")
        return value


class ScoreInputs(StrictModel):
    tsr: float | None = Field(default=None, ge=0, le=100)
    relative_performance: float | None = Field(default=None, ge=0, le=100)
    dividend_growth: float | None = Field(default=None, ge=0, le=100)
    earnings_growth: float | None = Field(default=None, ge=0, le=100)
    analyst_revisions: float | None = Field(default=None, ge=0, le=100)
    revisions: float | None = Field(default=None, ge=0, le=100)
    dividend_quality: float | None = Field(default=None, ge=0, le=100)
    technical_health: float | None = Field(default=None, ge=0, le=100)
    opportunity_cost: float | None = Field(default=None, ge=0, le=100)


class PositionInputs(StrictModel):
    entry_date: date | None = None
    cost_basis: float | None = None
    market_value: float | None = None
    market_price: float | None = Field(default=None, gt=0)
    dividends_received: float | None = None


class DividendInput(StrictModel):
    symbol: str
    amount: float
    ex_date: date | None = None
    pay_date: date | None = None
    currency: str = "USD"


class DividendInputs(StrictModel):
    records: list[DividendInput] = Field(default_factory=list, max_length=2_000)
    current_price: float | None = Field(default=None, gt=0)
    payout_ratio: float | None = None
    dividend_growth_rate: float | None = None
    consistency_score: float | None = None


class GrowthInputs(StrictModel):
    earnings_growth_percent: float | None = None
    revenue_growth_percent: float | None = None


class ForwardInputs(StrictModel):
    target_price: float | None = Field(default=None, gt=0)
    target_upside_percent: float | None = None
    analyst_revisions_score: float | None = Field(default=None, ge=0, le=100)


class PeerScore(StrictModel):
    symbol: str
    score: float

    @field_validator("symbol")
    @classmethod
    def normalize_symbol(cls, value: str) -> str:
        value = value.strip().upper()
        if not SYMBOL_PATTERN.fullmatch(value):
            raise ValueError("Invalid replacement candidate symbol")
        return value


class AnalysisRequest(StrictModel):
    portfolio_id: UUID
    symbol: str
    scores: ScoreInputs = Field(default_factory=ScoreInputs)
    position: PositionInputs = Field(default_factory=PositionInputs)
    dividends: DividendInputs = Field(default_factory=DividendInputs)
    growth: GrowthInputs = Field(default_factory=GrowthInputs)
    forward: ForwardInputs = Field(default_factory=ForwardInputs)
    peer_scores: list[PeerScore] = Field(default_factory=list, max_length=500)
    candidate_cps: dict[str, float] = Field(default_factory=dict, max_length=500)
    held_symbols: list[str] = Field(default_factory=list, max_length=1_000)

    @field_validator("symbol")
    @classmethod
    def normalize_symbol(cls, value: str) -> str:
        value = value.strip().upper()
        if not SYMBOL_PATTERN.fullmatch(value):
            raise ValueError("Invalid symbol")
        return value


class ResearchRequest(StrictModel):
    symbol: str

    @field_validator("symbol")
    @classmethod
    def normalize_symbol(cls, value: str) -> str:
        value = value.strip().upper()
        if not SYMBOL_PATTERN.fullmatch(value):
            raise ValueError("Invalid symbol")
        return value


class ApprovalTransitionRequest(StrictModel):
    status: ApprovalStatus
    actor: str | None = Field(default=None, max_length=80)
    reason: str | None = Field(default=None, max_length=300)


@dataclass(frozen=True)
class AuthenticatedUser:
    client: Any
    user_id: str
    email: str | None


def _response_data(response: Any, message: str) -> Any:
    if getattr(response, "error", None):
        raise HTTPException(status_code=502, detail=message)
    return getattr(response, "data", None)


def _one_row(data: Any) -> dict[str, Any] | None:
    if isinstance(data, dict):
        return data
    if isinstance(data, list) and data:
        return data[0]
    return None


def create_app(
    *,
    client_factory: Callable[[str, str], Any] = create_client,
    environ: dict[str, str] | None = None,
    research_fetcher: Callable[..., dict[str, Any]] | None = None,
) -> FastAPI:
    settings = os.environ if environ is None else environ
    fetch_research = research_fetcher or collect_research_data
    app = FastAPI(
        title="StockScanner Portfolio Intelligence API",
        version="1.0.0",
        description="Authenticated portfolio analytics and human approval workflow. No order transmitter is available.",
    )
    origins = [
        origin.strip()
        for origin in settings.get(
            "PIP_CORS_ORIGINS",
            "http://localhost:8000,http://127.0.0.1:8000",
        ).split(",")
        if origin.strip()
    ]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=False,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type"],
    )

    @app.exception_handler(APIError)
    @app.exception_handler(httpx.HTTPError)
    def data_service_error_handler(request: Request, exc: Exception) -> JSONResponse:
        return JSONResponse(
            status_code=502,
            content={"detail": "The PIP data service request failed."},
        )

    def require_user(authorization: str | None = Header(default=None)) -> AuthenticatedUser:
        if not authorization or not authorization.startswith("Bearer "):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="A valid Supabase access token is required.",
                headers={"WWW-Authenticate": "Bearer"},
            )
        token = authorization.removeprefix("Bearer ").strip()
        if not token:
            raise HTTPException(status_code=401, detail="A valid Supabase access token is required.")

        supabase_url = settings.get("SUPABASE_URL", "").strip()
        publishable_key = settings.get("SUPABASE_PUBLISHABLE_KEY", "").strip()
        if not supabase_url or not publishable_key:
            raise HTTPException(status_code=503, detail="PIP Supabase configuration is incomplete.")
        client = client_factory(supabase_url, publishable_key)
        try:
            auth_response = client.auth.get_user(token)
        except AuthApiError as exc:
            raise HTTPException(status_code=401, detail="The Supabase access token is invalid or expired.") from exc
        user = getattr(auth_response, "user", None)
        if user is None or not getattr(user, "id", None):
            raise HTTPException(status_code=401, detail="The Supabase access token is invalid or expired.")

        client.postgrest.auth(token)
        access_response = client.table("user_access").select("status").eq("user_id", str(user.id)).maybe_single().execute()
        access = _one_row(_response_data(access_response, "Unable to verify PIP account access."))
        if not access or access.get("status") != "approved":
            raise HTTPException(status_code=403, detail="An approved StockScanner account is required.")
        return AuthenticatedUser(client, str(user.id), getattr(user, "email", None))

    def owned_portfolio(user: AuthenticatedUser, portfolio_id: UUID) -> None:
        result = user.client.table("portfolios").select("id").eq(
            "id", str(portfolio_id)
        ).eq("user_id", user.user_id).maybe_single().execute()
        if not _one_row(_response_data(result, "Unable to load the requested portfolio.")):
            raise HTTPException(status_code=404, detail="Portfolio not found.")

    @app.get("/healthz")
    def health() -> dict[str, str]:
        return {"status": "ok", "service": "pip"}

    @app.get("/api/pip/portfolios")
    def list_portfolios(user: AuthenticatedUser = Depends(require_user)) -> list[dict[str, Any]]:
        result = user.client.table("portfolios").select(
            "id,name,currency,created_at,updated_at"
        ).eq("user_id", user.user_id).order("created_at", desc=True).execute()
        return _response_data(result, "Unable to load portfolios.") or []

    @app.post("/api/pip/portfolios", status_code=status.HTTP_201_CREATED)
    def create_portfolio(
        body: PortfolioCreate,
        user: AuthenticatedUser = Depends(require_user),
    ) -> dict[str, Any]:
        result = user.client.table("portfolios").insert({
            "user_id": user.user_id,
            "name": body.name,
            "currency": body.currency,
        }).select("id,name,currency,created_at,updated_at").single().execute()
        row = _one_row(_response_data(result, "Unable to create portfolio."))
        if row is None:
            raise HTTPException(status_code=502, detail="Unable to create portfolio.")
        return row

    @app.post("/api/pip/portfolios/{portfolio_id}/sync/csv")
    async def sync_csv(
        portfolio_id: UUID,
        request: Request,
        default_currency: str | None = Query(default=None, min_length=3, max_length=3, pattern=r"^[A-Za-z]{3}$"),
        user: AuthenticatedUser = Depends(require_user),
    ) -> dict[str, Any]:
        await run_in_threadpool(owned_portfolio, user, portfolio_id)
        content_length = request.headers.get("content-length")
        if content_length:
            try:
                if int(content_length) > MAX_CSV_BYTES:
                    raise HTTPException(status_code=413, detail="CSV import is limited to 1 MB.")
            except ValueError as exc:
                raise HTTPException(status_code=400, detail="Invalid content length.") from exc
        content = bytearray()
        async for chunk in request.stream():
            content.extend(chunk)
            if len(content) > MAX_CSV_BYTES:
                raise HTTPException(status_code=413, detail="CSV import is limited to 1 MB.")
        try:
            csv_text = content.decode("utf-8-sig")
        except UnicodeDecodeError as exc:
            raise HTTPException(status_code=400, detail="CSV must use UTF-8 encoding.") from exc
        if not csv_text.strip():
            raise HTTPException(status_code=400, detail="CSV file is empty.")
        if request.headers.get("content-type", "").split(";", 1)[0].strip().lower() != "text/csv":
            raise HTTPException(status_code=415, detail="Send the portfolio export as text/csv.")

        try:
            row_count = sum(1 for _ in csv.DictReader(io.StringIO(csv_text)))
        except csv.Error as exc:
            raise HTTPException(status_code=400, detail="CSV could not be parsed.") from exc
        if row_count > MAX_CSV_ROWS:
            raise HTTPException(status_code=413, detail="CSV import is limited to 1,000 rows.")

        def persist_import() -> dict[str, Any]:
            repository = SupabasePortfolioRepository(user.client)
            result = IBKRPortfolioSyncService(repository).sync(
                CSVPortfolioDataSource(io.StringIO(csv_text), default_currency=default_currency),
                str(portfolio_id),
            )
            return {
                "accounts": result["accounts"],
                "positions": [asdict(position) for position in result["positions"]],
                "transactions": result["transactions"],
                "dividends": result["dividends"],
                "counts": {
                    "accounts": len(result["accounts"]),
                    "positions": len(result["positions"]),
                    "transactions": len(result["transactions"]),
                    "dividends": len(result["dividends"]),
                },
            }

        try:
            return await run_in_threadpool(persist_import)
        except (ValueError, csv.Error) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.post("/api/pip/portfolios/{portfolio_id}/research")
    def research(
        portfolio_id: UUID,
        body: ResearchRequest,
        user: AuthenticatedUser = Depends(require_user),
    ) -> dict[str, Any]:
        owned_portfolio(user, portfolio_id)
        position_result = user.client.table("positions").select(
            "symbol"
        ).eq("portfolio_id", str(portfolio_id)).eq(
            "symbol", body.symbol
        ).limit(1).execute()
        if not _response_data(
            position_result,
            "Unable to verify the selected holding.",
        ):
            raise HTTPException(
                status_code=422,
                detail="Import this holding into the selected portfolio before loading research.",
            )

        snapshot_result = user.client.table("price_snapshots").select(
            "generated_at,prices,price_timestamps,provider_by_symbol,stale_symbols"
        ).eq("source", "hourly_yahoo").order(
            "generated_at", desc=True
        ).limit(1).execute()
        snapshots = _response_data(
            snapshot_result,
            "Unable to load the shared market-price snapshot.",
        ) or []
        try:
            return fetch_research(
                body.symbol,
                market_snapshot=snapshots[0] if snapshots else None,
            )
        except ResearchDataUnavailable as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

    @app.post("/api/pip/analysis")
    def analyze(
        body: AnalysisRequest,
        user: AuthenticatedUser = Depends(require_user),
    ) -> dict[str, Any]:
        owned_portfolio(user, body.portfolio_id)

        position_result = user.client.table("positions").select(
            "quantity,average_cost,market_price,market_value,cost_basis,entry_date,currency"
        ).eq("portfolio_id", str(body.portfolio_id)).eq("symbol", body.symbol).execute()
        position_rows = _response_data(position_result, "Unable to load the selected holding.") or []
        if not position_rows:
            raise HTTPException(
                status_code=422,
                detail="Import this holding into the selected portfolio before analyzing it.",
            )
        currencies = {str(row.get("currency") or "").strip().upper() for row in position_rows}
        if "" in currencies or len(currencies) != 1:
            raise HTTPException(
                status_code=422,
                detail="Analyze positions in one currency at a time; PIP does not convert currencies.",
            )
        currency = next(iter(currencies))
        total_quantity = sum(float(row.get("quantity") or 0) for row in position_rows)
        cost_values = [
            row.get("cost_basis")
            if row.get("cost_basis") is not None
            else float(row["average_cost"]) * float(row.get("quantity") or 0)
            if row.get("average_cost") is not None
            else None
            for row in position_rows
        ]
        market_values = [
            row.get("market_value")
            if row.get("market_value") is not None
            else float(row["market_price"]) * float(row.get("quantity") or 0)
            if row.get("market_price") is not None
            else None
            for row in position_rows
        ]
        complete_cost = all(value is not None for value in cost_values)
        complete_market_value = all(value is not None for value in market_values)
        stored_cost_basis = (
            sum(float(value) for value in cost_values) if complete_cost else None
        )
        stored_market_value = (
            sum(float(value) for value in market_values) if complete_market_value else None
        )
        entry_dates = [str(row["entry_date"])[:10] for row in position_rows if row.get("entry_date")]
        stored_entry_date = min(entry_dates) if entry_dates else None
        stored_market_price = (
            stored_market_value / total_quantity
            if stored_market_value is not None and total_quantity
            else next((row["market_price"] for row in position_rows if row.get("market_price")), None)
        )
        current_price = (
            body.dividends.current_price
            or body.position.market_price
            or stored_market_price
        )
        market_value = body.position.market_value
        if market_value is None:
            market_value = (
                current_price * total_quantity
                if current_price is not None and total_quantity
                else stored_market_value
            )

        stored_score_result = user.client.table("stock_scores").select(
            "tsr,relative_performance,dividend_growth,earnings_growth,analyst_revisions,"
            "dividend_quality,technical_health,opportunity_cost,revisions"
        ).eq("portfolio_id", str(body.portfolio_id)).eq("symbol", body.symbol).maybe_single().execute()
        stored_scores = _one_row(_response_data(stored_score_result, "Unable to load saved score inputs.")) or {}

        signals_result = user.client.table("analyst_signals").select(
            "target_price,target_upside,revisions,signal_date"
        ).eq("portfolio_id", str(body.portfolio_id)).eq(
            "symbol", body.symbol
        ).order("signal_date", desc=True).limit(1).execute()
        latest_signal = next(iter(_response_data(signals_result, "Unable to load analyst signals.") or []), {})

        growth = GrowthAnalysisEngine().analyze(
            earnings_growth_percent=body.growth.earnings_growth_percent,
            revenue_growth_percent=body.growth.revenue_growth_percent,
        )
        dividend_records = [
            DividendRecord(
                symbol=record.symbol,
                amount=record.amount,
                ex_date=record.ex_date.isoformat() if record.ex_date else None,
                pay_date=record.pay_date.isoformat() if record.pay_date else None,
                currency=record.currency,
            )
            for record in body.dividends.records
        ]
        if not dividend_records:
            cutoff = datetime.now(timezone.utc).date() - timedelta(days=365)
            dividend_result = user.client.table("dividends").select(
                "symbol,dividend_amount,ex_date,pay_date,metadata"
            ).eq("portfolio_id", str(body.portfolio_id)).eq(
                "symbol", body.symbol
            ).or_(
                f"pay_date.gte.{cutoff.isoformat()},ex_date.gte.{cutoff.isoformat()}"
            ).limit(2_000).execute()
            dividend_records = [
                DividendRecord(
                    symbol=row["symbol"],
                    amount=float(row["dividend_amount"]),
                    ex_date=row.get("ex_date"),
                    pay_date=row.get("pay_date"),
                    currency=(row.get("metadata") or {}).get("currency", "USD"),
                )
                for row in (_response_data(dividend_result, "Unable to load dividend history.") or [])
            ]
        if any(record.currency.strip().upper() != currency for record in dividend_records):
            raise HTTPException(
                status_code=422,
                detail="Dividend history must use the holding's currency; PIP does not convert currencies.",
            )
        dividend = DividendAnalysisEngine().analyze(
            dividend_records=dividend_records,
            current_price=current_price,
            payout_ratio=body.dividends.payout_ratio,
            dividend_growth_rate=body.dividends.dividend_growth_rate,
            consistency_score=body.dividends.consistency_score,
            current_market_value=abs(market_value) if market_value is not None else None,
        )
        forward_target_upside = body.forward.target_upside_percent
        if forward_target_upside is None:
            target_price = body.forward.target_price or latest_signal.get("target_price")
            if target_price is None:
                forward_target_upside = latest_signal.get("target_upside")
            elif current_price is not None:
                forward_target_upside = (float(target_price) / float(current_price) - 1) * 100
        forward_revision_score = body.forward.analyst_revisions_score
        if forward_revision_score is None:
            forward_revision_score = stored_scores.get("analyst_revisions")
        if forward_revision_score is None:
            forward_revision_score = latest_signal.get("revisions")
        forward = ForwardLookingAnalyzer().analyze(
            target_upside_percent=forward_target_upside,
            analyst_revisions_score=forward_revision_score,
        )

        components = body.scores.model_dump()
        for component, stored_value in stored_scores.items():
            if components.get(component) is None:
                components[component] = stored_value
        if components["earnings_growth"] is None:
            components["earnings_growth"] = growth.score
        if components["dividend_growth"] is None:
            components["dividend_growth"] = DividendAnalysisEngine().growth_score(
                body.dividends.dividend_growth_rate
            )
        if components["dividend_quality"] is None:
            components["dividend_quality"] = dividend["dividend_quality_score"]
        if components["analyst_revisions"] is None:
            components["analyst_revisions"] = forward_revision_score
        if components["revisions"] is None:
            components["revisions"] = forward_revision_score

        entry_date = body.position.entry_date or stored_entry_date
        cost_basis = body.position.cost_basis if body.position.cost_basis is not None else stored_cost_basis
        cps_result = calculate_cps_result(components)
        lifecycle = PositionLifecycleAnalyzer().summarize_position(
            body.symbol,
            entry_date=entry_date,
            cost_basis=cost_basis,
            market_value=market_value,
            dividends=body.position.dividends_received,
        )
        dead_money = DeadMoneyDetector().assess(
            body.symbol,
            cps=cps_result.score,
            total_return_percent=lifecycle.total_return_percent,
            opportunity_cost_score=components["opportunity_cost"],
        )
        alternatives = [
            (
                peer.symbol,
                body.candidate_cps.get(peer.symbol, peer.score),
                market_value or 0.0,
            )
            for peer in body.peer_scores
        ]
        opportunity_cost_items = (
            OpportunityCostEngine().compare(
                body.symbol,
                market_value or 0.0,
                cps_result.score,
                alternatives,
            )
            if cps_result.score is not None
            else []
        )
        module_assessments = {
            "lifecycle": asdict(lifecycle),
            "dead_money": asdict(dead_money),
            "dividends": dividend,
            "growth": asdict(growth),
            "forward_looking": asdict(forward),
            "opportunity_cost": {
                "available": cps_result.score is not None,
                "items": [asdict(item) for item in opportunity_cost_items],
                "reasons": (
                    []
                    if cps_result.score is not None
                    else ["Current holding CPS is unavailable."]
                ),
            },
        }

        held_result = user.client.table("positions").select(
            "symbol,quantity"
        ).eq("portfolio_id", str(body.portfolio_id)).execute()
        held_rows = _response_data(held_result, "Unable to load current portfolio holdings.") or []
        held_symbols = set()
        for row in held_rows:
            try:
                quantity = float(row.get("quantity") or 0)
            except (TypeError, ValueError):
                continue
            held_symbol = str(row.get("symbol") or "").strip().upper()
            if quantity != 0 and SYMBOL_PATTERN.fullmatch(held_symbol):
                held_symbols.add(held_symbol)
        held_symbols.update(
            symbol.strip().upper()
            for symbol in body.held_symbols
            if SYMBOL_PATTERN.fullmatch(symbol.strip().upper())
        )

        repository = SupabasePortfolioRepository(user.client)
        engine = DecisionEngine(repository=repository)
        result = engine.analyze_position(
            portfolio_id=str(body.portfolio_id),
            symbol=body.symbol,
            **components,
            peer_scores=[(peer.symbol, peer.score) for peer in body.peer_scores],
            candidate_cps=body.candidate_cps,
            held_symbols=held_symbols,
            additional_metadata={"modules": module_assessments},
        )
        recommendation = engine.last_recommendation
        if recommendation is None:
            raise HTTPException(status_code=500, detail="Unable to create analysis recommendation.")
        workflow = ApprovalWorkflow(
            audit_sink=SupabaseAuditLogSink(
                user.client,
                str(body.portfolio_id),
                user.user_id,
            )
        )
        workflow.propose(recommendation.id)
        recommendation.status = ApprovalStatus.PROPOSED.value

        if (
            body.forward.target_price is not None
            or                         body.forward.target_price is not None
            or body.forward.target_upside_percent is not None
            or body.forward.analyst_revisions_score is not None
        ):
            signal_result = user.client.table("analyst_signals").insert({
                "portfolio_id": str(body.portfolio_id),
                "symbol": body.symbol,
                "target_price": body.forward.target_price,
                "target_upside": forward_target_upside,
                "revisions": forward_revision_score,
                "signal_date": datetime.now(timezone.utc).isoformat(),
                "metadata": {"source": "user_supplied"},
            }).execute()
            _response_data(signal_result, "Unable to persist analyst inputs.")

        snapshot_result = user.client.table("daily_snapshots").upsert(
            [{
                "portfolio_id": str(body.portfolio_id),
                "symbol": body.symbol,
                "snapshot_date": datetime.now(timezone.utc).date().isoformat(),
                "price": current_price,
                "market_value": market_value,
                "score": result.cps,
                "metadata": {
                    "score_type": "cps",
                    "sell_score": result.sell_score,
                    "currency": currency,
                    "source": "pip_analysis",
                },
            }],
            on_conflict="portfolio_id,symbol,snapshot_date",
        ).execute()
        _response_data(snapshot_result, "Unable to persist daily portfolio snapshot.")
        return {
            "analysis": asdict(result),
            "modules": module_assessments,
            "recommendation": asdict(recommendation),
        }

    @app.get("/api/pip/portfolios/{portfolio_id}/recommendations")
    def list_recommendations(
        portfolio_id: UUID,
        user: AuthenticatedUser = Depends(require_user),
    ) -> list[dict[str, Any]]:
        owned_portfolio(user, portfolio_id)
        result = user.client.table("sell_recommendations").select(
            "id,portfolio_id,symbol,score,recommendation,rationale,confidence,status,created_at,approved_by"
        ).eq("portfolio_id", str(portfolio_id)).order("created_at", desc=True).execute()
        return _response_data(result, "Unable to load recommendations.") or []

    @app.get("/api/pip/recommendations/{recommendation_id}/events")
    def recommendation_events(
        recommendation_id: UUID,
        user: AuthenticatedUser = Depends(require_user),
    ) -> list[dict[str, Any]]:
        result = user.client.table("sell_recommendations").select(
            "id,portfolio_id"
        ).eq("id", str(recommendation_id)).maybe_single().execute()
        recommendation = _one_row(_response_data(result, "Unable to load recommendation."))
        if recommendation is None:
            raise HTTPException(status_code=404, detail="Recommendation not found.")
        owned_portfolio(user, UUID(recommendation["portfolio_id"]))
        events = user.client.table("audit_logs").select(
            "event_type,event_details,created_at"
        ).eq("entity_type", "sell_recommendation").eq(
            "entity_id", str(recommendation_id)
        ).order("created_at").execute()
        return _response_data(events, "Unable to load approval events.") or []

    @app.post("/api/pip/recommendations/{recommendation_id}/transitions")
    def transition_recommendation(
        recommendation_id: UUID,
        body: ApprovalTransitionRequest,
        user: AuthenticatedUser = Depends(require_user),
    ) -> dict[str, Any]:
        result = user.client.table("sell_recommendations").select(
            "id,portfolio_id,status"
        ).eq("id", str(recommendation_id)).maybe_single().execute()
        recommendation = _one_row(_response_data(result, "Unable to load recommendation."))
        if recommendation is None:
            raise HTTPException(status_code=404, detail="Recommendation not found.")
        portfolio_id = UUID(recommendation["portfolio_id"])
        owned_portfolio(user, portfolio_id)

        workflow = ApprovalWorkflow(
            audit_sink=SupabaseAuditLogSink(user.client, str(portfolio_id), user.user_id)
        )
        current_status = recommendation["status"]
        if current_status == "draft":
            if body.status is not ApprovalStatus.PROPOSED and body.status not in workflow.allowed_transitions[ApprovalStatus.PROPOSED]:
                raise HTTPException(status_code=409, detail="Invalid approval transition.")
            workflow.propose(str(recommendation_id))
            current_status = ApprovalStatus.PROPOSED.value
            if body.status is ApprovalStatus.PROPOSED:
                return {"recommendation_id": str(recommendation_id), "status": current_status}
        try:
            workflow.decisions[str(recommendation_id)] = ApprovalDecision(
                recommendation_id=str(recommendation_id),
                status=ApprovalStatus(current_status),
                actor=None,
            )
        except ValueError as exc:
            raise HTTPException(status_code=409, detail="Recommendation has an unsupported approval state.") from exc

        try:
            decision = _apply_transition(
                workflow,
                str(recommendation_id),
                body.status,
                body.actor,
                body.reason,
            )
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return {
            "recommendation_id": str(recommendation_id),
            "status": decision.status.value,
            "actor": decision.actor,
            "reason": decision.reason,
            "created_at": decision.created_at.isoformat() if decision.created_at else None,
        }

    return app


def _apply_transition(
    workflow: ApprovalWorkflow,
    recommendation_id: str,
    next_status: ApprovalStatus,
    actor: str | None,
    reason: str | None,
) -> ApprovalDecision:
    transition_method = {
        ApprovalStatus.UNDER_REVIEW: workflow.begin_review,
        ApprovalStatus.APPROVED: workflow.approve,
        ApprovalStatus.REJECTED: workflow.reject,
        ApprovalStatus.ESCALATED: workflow.escalate,
        ApprovalStatus.EXPIRED: workflow.expire,
        ApprovalStatus.CANCELLED: workflow.cancel,
        ApprovalStatus.SUBMITTED: workflow.mark_submitted,
    }.get(next_status)
    if transition_method is None:
        raise ValueError("Invalid approval transition.")
    return transition_method(
        recommendation_id,
        actor or "",
        reason or "",
    )


app = create_app()


def main() -> None:
    import uvicorn

    uvicorn.run(
        "stockscanner.pip.api:app",
        host=os.environ.get("PIP_API_HOST", "127.0.0.1"),
        port=int(os.environ.get("PIP_API_PORT", "8000")),
    )
