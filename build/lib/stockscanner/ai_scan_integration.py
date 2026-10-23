"""Integration of ChatGPT AI features into scan workflow."""

import os
from typing import Optional, Dict, Any
from stockscanner.ai_analysis import AIAnalyzer
from stockscanner.ai_report import AIReportGenerator
from stockscanner.ai_chat import StockAnalysisChat


def enhance_scan_result_with_ai(result: Dict[str, Any]) -> Dict[str, Any]:
    """Enhance scan result with AI-generated analysis.

    Args:
        result: Stock scan result dictionary.

    Returns:
        Enhanced result with 'AI_Analysis' field.
    """
    if not os.getenv("CHATGPT_ENABLED", "true").lower() == "true":
        return result

    try:
        analyzer = AIAnalyzer()
        symbol = result.get("Symbol")

        if not symbol:
            return result

        latest_data = {"Score": result.get("Score", 0)}
        trade_plan = {
            k: result.get(k)
            for k in ["Trend", "Entry", "Stop", "Target1", "RR"]
        }
        analyst_data = {
            k: result.get(k) for k in ["Analyst Rating", "Target Upside"]
        }

        ai_analysis = analyzer.analyze_stock(
            symbol=symbol,
            latest_data=latest_data,
            trade_plan=trade_plan,
            analyst_data=analyst_data,
        )

        if ai_analysis:
            result["AI_Analysis"] = ai_analysis

    except Exception as e:
        print(f"Warning: AI analysis error: {e}")

    return result


def generate_ai_report_enhancements(
    scan_date: str,
    total_scanned: int,
    qualified_results: list,
    market_performance: str = "Normal",
) -> Dict[str, Optional[str]]:
    """Generate AI enhancements for the full scan report.

    Args:
        scan_date: Date of scan.
        total_scanned: Total stocks scanned.
        qualified_results: List of qualifying results.
        market_performance: Market summary.

    Returns:
        Dictionary with AI-generated report sections.
    """
    if not os.getenv("CHATGPT_ENABLED", "true").lower() == "true":
        return {}

    report_gen = AIReportGenerator()
    enhancements = {}

    try:
        top_symbols = [
            r.get("Symbol") for r in qualified_results[:3]
        ]
        qualified_count = len(qualified_results)

        summary = report_gen.generate_executive_summary(
            scan_date=scan_date,
            total_scanned=total_scanned,
            qualified_count=qualified_count,
            top_3_symbols=top_symbols,
            market_index_performance=market_performance,
        )
        if summary:
            enhancements["executive_summary"] = summary

        warnings = report_gen.generate_risk_warnings(
            market_conditions=market_performance,
            volatility_level="Normal"
        )
        if warnings:
            enhancements["risk_warnings"] = warnings

    except Exception as e:
        print(f"Warning: Report enhancement error: {e}")

    return enhancements


def create_chat_session_for_results(results: list) -> StockAnalysisChat:
    """Create interactive chat session for scan results.

    Args:
        results: List of scan results.

    Returns:
        Initialized StockAnalysisChat session.
    """
    chat = StockAnalysisChat()

    if results:
        top_5 = results[:5]
        context = "\\n".join(
            [
                f"{r.get('Symbol')}: Score {r.get('Score')}"
                for r in top_5
            ]
        )
        print(f"Chat session created with {len(results)} results.")
        print(f"Top 5: {context}")

    return chat
