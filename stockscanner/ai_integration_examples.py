"""Integration examples for ChatGPT AI features in StockScanner."""

from stockscanner.ai_analysis import AIAnalyzer
from stockscanner.ai_report import AIReportGenerator
from stockscanner.ai_chat import StockAnalysisChat
from stockscanner.ai_documentation import DocumentationGenerator


def example_1_ai_stock_analysis():
    """Example 1: Analyze stocks with AI insights."""
    analyzer = AIAnalyzer()

    stock_result = {
        "Symbol": "AAPL",
        "Score": 85,
        "Trend": "Strong Uptrend",
        "Entry": 150.0,
        "Stop": 145.0,
        "Target1": 159.0,
        "RR": 2.0,
        "Analyst Rating": "Buy",
        "Target Upside": 12.5,
    }

    latest_data = {"Score": stock_result["Score"]}
    trade_plan = {
        k: stock_result[k]
        for k in ["Trend", "Entry", "Stop", "Target1", "RR"]
    }
    analyst_data = {
        k: stock_result[k]
        for k in ["Analyst Rating", "Target Upside"]
    }

    analysis = analyzer.analyze_stock(
        symbol=stock_result["Symbol"],
        latest_data=latest_data,
        trade_plan=trade_plan,
        analyst_data=analyst_data,
    )

    if analysis:
        print(f"AI Analysis for {stock_result['Symbol']}:")
        print(analysis)


def example_2_ai_report_generation():
    """Example 2: Generate report with AI commentary."""
    report_gen = AIReportGenerator()

    summary = report_gen.generate_executive_summary(
        scan_date="2026-08-22",
        total_scanned=500,
        qualified_count=23,
        top_3_symbols=["NVDA", "MSFT", "AAPL"],
        market_index_performance="SPY +1.5%",
    )

    if summary:
        print("AI Executive Summary:")
        print(summary)

    warnings = report_gen.generate_risk_warnings(
        market_conditions="Post-earnings volatility", volatility_level="High"
    )

    if warnings:
        print("AI Risk Warnings:")
        print(warnings)


def example_3_interactive_chat():
    """Example 3: Interactive chat about stocks."""
    chat = StockAnalysisChat()

    answer = chat.ask_about_stock(
        symbol="NVDA",
        question="What is the risk of buying NVDA at 120?",
        stock_data={
            "Current Price": 118,
            "52-week High": 140,
            "RSI": 65,
            "MA200": 110,
        },
    )

    if answer:
        print("Chat Response about NVDA:")
        print(answer)

    ideas = chat.get_trading_ideas(
        stocks=[
            {"Symbol": "NVDA", "Score": 95, "Entry": 120, "Target": 130},
            {"Symbol": "AMD", "Score": 88, "Entry": 160, "Target": 175},
        ],
        portfolio_size=50000,
    )

    if ideas:
        print("Trading Ideas:")
        print(ideas)


def example_4_documentation_generation():
    """Example 4: Documentation generation."""
    doc_gen = DocumentationGenerator()

    code_snippet = """
def calculate_indicators(df):
    df['MA20'] = df['Close'].rolling(20).mean()
    df['MA50'] = df['Close'].rolling(50).mean()
    return df
"""

    docstring = doc_gen.generate_function_docstring(
        function_name="calculate_indicators",
        code_snippet=code_snippet,
        return_type="pandas.DataFrame",
    )

    if docstring:
        print("AI-Generated Docstring:")
        print(docstring)


if __name__ == "__main__":
    print("Example 1: AI Stock Analysis")
    example_1_ai_stock_analysis()

    print("\nExample 2: AI Report Generation")
    example_2_ai_report_generation()

    print("\nExample 3: Interactive Chat")
    example_3_interactive_chat()

    print("\nExample 4: Documentation Generation")
    example_4_documentation_generation()
