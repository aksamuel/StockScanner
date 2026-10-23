"""AI-enhanced report generation with ChatGPT commentary."""

import os
from typing import Optional, List, Dict, Any
from stockscanner.openai_client import get_chatgpt_client


class AIReportGenerator:
    """Generate AI-powered commentary and summaries for reports."""

    def __init__(self):
        self.client = get_chatgpt_client()
        self.enabled = os.getenv("CHATGPT_ENABLED", "true").lower() == "true"

    def generate_executive_summary(
        self,
        scan_date: str,
        total_scanned: int,
        qualified_count: int,
        top_3_symbols: List[str],
        market_index_performance: Optional[str] = None,
    ) -> Optional[str]:
        """
        Generate AI executive summary for the full scan report.

        Args:
            scan_date: Date of the scan.
            total_scanned: Total stocks scanned.
            qualified_count: Stocks meeting criteria.
            top_3_symbols: Top 3 qualifying stocks.
            market_index_performance: Market index info (e.g., "SPY +1.5%").

        Returns:
            AI-generated executive summary.
        """
        if not self.enabled:
            return None

        try:
            prompt = f"""
Generate a professional executive summary (4-5 sentences) for a stock scan report:

Scan Date: {scan_date}
Total Stocks Scanned: {total_scanned}
Qualified Stocks: {qualified_count}
Top 3 Picks: {', '.join(top_3_symbols)}
"""
            if market_index_performance:
                prompt += f"Market Context: {market_index_performance}\n"

            prompt += """
The summary should:
1. Summarize scan results and market conditions
2. Highlight top opportunities
3. Provide a recommended trading approach
4. Mention risk factors to consider
5. Be suitable for inclusion in an investment report
"""
            return self.client.chat(prompt, max_tokens=400)
        except Exception as e:
            print(f"Executive Summary Generation Error: {e}")
            return None

    def generate_stock_commentary(
        self,
        symbol: str,
        technical_data: Dict[str, Any],
        position_data: Dict[str, Any],
    ) -> Optional[str]:
        """
        Generate detailed AI commentary for a specific stock in the report.

        Args:
            symbol: Stock ticker.
            technical_data: Technical analysis data.
            position_data: Position sizing and trade plan data.

        Returns:
            AI-generated commentary.
        """
        if not self.enabled:
            return None

        try:
            prompt = f"""
Write a professional 2-3 sentence investment commentary for this stock report entry:

Stock: {symbol}
Score: {technical_data.get('Score', 'N/A')}/100
Trend: {technical_data.get('Trend', 'Unknown')}
RSI: {technical_data.get('RSI', 'N/A')}
MACD: {technical_data.get('MACD', 'N/A')}
Support: {technical_data.get('Support', 'N/A')}
Resistance: {technical_data.get('Resistance', 'N/A')}

Entry Price: ${position_data.get('Entry', 'N/A')}
Target Price: ${position_data.get('Target1', 'N/A')}
Stop Loss: ${position_data.get('Stop', 'N/A')}
Risk/Reward: {position_data.get('RR', 'N/A')}
Suggested Shares: {position_data.get('Shares', 'N/A')}

The commentary should focus on:
- Why this stock is a good opportunity
- Key technical strengths
- Risk considerations
"""
            return self.client.chat(prompt, max_tokens=300)
        except Exception as e:
            print(f"Stock Commentary Error for {symbol}: {e}")
            return None

    def generate_risk_warnings(
        self, market_conditions: str, volatility_level: str = "Normal"
    ) -> Optional[str]:
        """
        Generate AI-powered risk warnings for the report.

        Args:
            market_conditions: Description of current market conditions.
            volatility_level: Volatility level (Low, Normal, High, Extreme).

        Returns:
            AI-generated risk warnings.
        """
        if not self.enabled:
            return None

        try:
            prompt = f"""
Generate a brief risk warning section (2-3 sentences) for a trading report:

Current Market Conditions: {market_conditions}
Volatility Level: {volatility_level}

The warning should:
1. Address current market risks
2. Recommend position sizing caution
3. Suggest stop-loss discipline
4. Be concise and actionable
"""
            return self.client.chat(prompt, max_tokens=250)
        except Exception as e:
            print(f"Risk Warnings Generation Error: {e}")
            return None

    def generate_html_commentary(
        self, section_name: str, data_summary: str
    ) -> Optional[str]:
        """
        Generate concise HTML-friendly commentary for dashboard sections.

        Args:
            section_name: Name of report section (e.g., "Technical Analysis").
            data_summary: Summary of data in this section.

        Returns:
            AI-generated HTML-friendly commentary.
        """
        if not self.enabled:
            return None

        try:
            prompt = f"""
Write a one-liner insight (max 30 words) for a dashboard section:

Section: {section_name}
Data: {data_summary}

Make it engaging and actionable.
"""
            return self.client.chat(prompt, max_tokens=100)
        except Exception as e:
            print(f"HTML Commentary Error: {e}")
            return None
