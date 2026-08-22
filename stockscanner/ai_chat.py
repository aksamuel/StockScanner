"""Interactive chat interface for stock analysis queries."""

import os
from typing import Optional, List, Dict, Any
from stockscanner.openai_client import get_chatgpt_client


class StockAnalysisChat:
    """Interactive chat for asking questions about stocks and scan results."""

    def __init__(self):
        self.client = get_chatgpt_client()
        self.enabled = os.getenv("CHATGPT_ENABLED", "true").lower() == "true"
        self.conversation_history = []  # Maintain context across messages

    def ask_about_stock(
        self, symbol: str, question: str, stock_data: Optional[Dict[str, Any]] = None
    ) -> Optional[str]:
        """
        Ask a question about a specific stock.

        Args:
            symbol: Stock ticker.
            question: User's question.
            stock_data: Optional stock data to provide context.

        Returns:
            Answer from ChatGPT.
        """
        if not self.enabled:
            return None

        try:
            context = f"Stock: {symbol}\n"
            if stock_data:
                context += "Data:\n"
                for key, value in stock_data.items():
                    context += f"- {key}: {value}\n"

            prompt = f"{context}\nQuestion: {question}"
            answer = self.client.answer_question(prompt)
            self.conversation_history.append(
                {"role": "user", "content": question}
            )
            self.conversation_history.append(
                {"role": "assistant", "content": answer}
            )
            return answer
        except Exception as e:
            print(f"Chat Error: {e}")
            return None

    def ask_about_market(
        self, question: str, market_summary: str = ""
    ) -> Optional[str]:
        """
        Ask a general market question with optional context.

        Args:
            question: User's question.
            market_summary: Optional market summary for context.

        Returns:
            Answer from ChatGPT.
        """
        if not self.enabled:
            return None

        try:
            context = ""
            if market_summary:
                context = f"Market Context:\n{market_summary}\n\n"

            prompt = f"{context}Question: {question}"
            answer = self.client.answer_question(prompt)
            self.conversation_history.append(
                {"role": "user", "content": question}
            )
            self.conversation_history.append(
                {"role": "assistant", "content": answer}
            )
            return answer
        except Exception as e:
            print(f"Market Chat Error: {e}")
            return None

    def explain_signal(self, signal: str, stock_data: Optional[str] = "") -> Optional[str]:
        """
        Explain what a technical signal means.

        Args:
            signal: Technical signal (e.g., "Strong Uptrend").
            stock_data: Optional stock context.

        Returns:
            Explanation from ChatGPT.
        """
        if not self.enabled:
            return None

        try:
            prompt = f"Explain this technical signal in simple terms: {signal}"
            if stock_data:
                prompt += f"\nContext: {stock_data}"

            return self.client.answer_question(prompt)
        except Exception as e:
            print(f"Signal Explanation Error: {e}")
            return None

    def compare_stocks(self, symbols: List[str], stocks_data: Dict[str, Any]) -> Optional[str]:
        """
        Compare multiple stocks and get analysis.

        Args:
            symbols: List of stock tickers to compare.
            stocks_data: Dictionary of stock data for each ticker.

        Returns:
            Comparative analysis from ChatGPT.
        """
        if not self.enabled:
            return None

        try:
            prompt = f"Compare these stocks and recommend the best opportunity:\n\n"
            for symbol in symbols:
                data = stocks_data.get(symbol, {})
                prompt += f"{symbol}:\n"
                for key, value in data.items():
                    prompt += f"  {key}: {value}\n"
                prompt += "\n"

            return self.client.answer_question(prompt)
        except Exception as e:
            print(f"Comparison Error: {e}")
            return None

    def get_trading_ideas(self, stocks: List[Dict[str, Any]], portfolio_size: float) -> Optional[str]:
        """
        Generate trading ideas based on top stocks and portfolio size.

        Args:
            stocks: List of qualifying stocks with data.
            portfolio_size: Portfolio size in dollars.

        Returns:
            Trading ideas from ChatGPT.
        """
        if not self.enabled:
            return None

        try:
            stocks_str = "\n".join(
                [
                    f"- {s.get('Symbol', 'N/A')}: Score {s.get('Score', 0)}, "
                    f"Entry ${s.get('Entry', 'N/A')}, Target ${s.get('Target', 'N/A')}"
                    for s in stocks[:15]
                ]
            )

            prompt = f"""
Based on a ${portfolio_size:,.0f} portfolio, provide 3-4 trading ideas from these top stocks:

{stocks_str}

Consider:
1. Position sizing (max 5% per position)
2. Diversification across sectors
3. Risk management strategies
4. Entry and exit timing
"""
            return self.client.answer_question(prompt)
        except Exception as e:
            print(f"Trading Ideas Error: {e}")
            return None

    def clear_history(self):
        """Clear conversation history to start fresh."""
        self.conversation_history = []

    def get_history(self) -> List[Dict[str, str]]:
        """Get conversation history."""
        return self.conversation_history.copy()
