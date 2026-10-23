"""AI-powered stock analysis using ChatGPT."""

import os
from typing import Optional, Dict, Any
from stockscanner.openai_client import ChatGPTClient, get_chatgpt_client


class AIAnalyzer:
    """Generate AI insights for individual stocks and scan results."""

    def __init__(self, client: Optional[ChatGPTClient] = None):
        """
        Initialize AI Analyzer.

        Args:
            client: ChatGPTClient instance. If None, uses singleton.
        """
        self.client = client or get_chatgpt_client()
        self.enabled = os.getenv("CHATGPT_ENABLED", "true").lower() == "true"

    def analyze_stock(
        self,
        symbol: str,
        latest_data: Dict[str, Any],
        trade_plan: Dict[str, Any],
        analyst_data: Dict[str, Any],
    ) -> Optional[str]:
        """
        Generate AI analysis for a single stock.

        Args:
            symbol: Ticker symbol.
            latest_data: Latest price data including indicators.
            trade_plan: Generated trade plan with entry, stop, targets.
            analyst_data: Analyst ratings and target data.

        Returns:
            AI-generated analysis or None if ChatGPT disabled.
        """
        if not self.enabled:
            return None

        try:
            score = latest_data.get("Score", 0)
            trend = trade_plan.get("Trend", "Unknown")
            entry = trade_plan.get("Entry", 0)
            stop = trade_plan.get("Stop", 0)
            target1 = trade_plan.get("Target1", 0)
            rr = trade_plan.get("RR", 0)

            technical_summary = (
                f"Entry: ${entry:.2f}, Stop: ${stop:.2f}, Target: ${target1:.2f}, "
                f"Risk/Reward: {rr:.2f}:1"
            )
            analyst_rating = analyst_data.get("Analyst Rating", "Unavailable")
            target_upside = analyst_data.get("Target Upside")

            return self.client.generate_analysis(
                symbol=symbol,
                score=score,
                trend=trend,
                technical_summary=technical_summary,
                analyst_rating=analyst_rating,
                target_upside=target_upside,
            )
        except Exception as e:
            print(f"AI Analysis Error for {symbol}: {e}")
            return None

    def generate_recommendations(
        self, top_stocks: list, market_condition: str = "Normal"
    ) -> Optional[str]:
        """
        Generate AI recommendations based on top stocks.

        Args:
            top_stocks: List of top performing stocks with scores.
            market_condition: Current market condition (e.g., "Bullish", "Bearish").

        Returns:
            AI-generated recommendations.
        """
        if not self.enabled:
            return None

        try:
            stocks_str = "\n".join(
                [
                    f"- {stock.get('Symbol', 'N/A')}: Score {stock.get('Score', 0)}, "
                    f"{stock.get('Trend', 'Unknown')}"
                    for stock in top_stocks[:10]
                ]
            )

            prompt = f"""
Based on the following top-performing stocks from today's scan, provide 3-4 key trading recommendations:

Market Condition: {market_condition}

Top Stocks:
{stocks_str}

Consider:
1. Common themes and patterns
2. Risk management strategies
3. Portfolio diversification
4. Position sizing advice
"""
            return self.client.chat(prompt)
        except Exception as e:
            print(f"AI Recommendations Error: {e}")
            return None

    def explain_technical_signal(self, signal: str, context: str = "") -> Optional[str]:
        """
        Explain what a technical signal means.

        Args:
            signal: The technical signal (e.g., "Strong Uptrend").
            context: Additional context.

        Returns:
            Explanation from ChatGPT.
        """
        if not self.enabled:
            return None

        try:
            prompt = f"""
Briefly explain what this technical trading signal means and how a trader should interpret it:

Signal: {signal}
"""
            if context:
                prompt += f"Context: {context}"

            return self.client.chat(prompt, max_tokens=500)
        except Exception as e:
            print(f"Signal Explanation Error: {e}")
            return None
