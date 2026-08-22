"""OpenAI ChatGPT client for StockScanner analysis and report generation."""

import os
from typing import Optional
from dotenv import load_dotenv
from openai import OpenAI, APIError, APIConnectionError, RateLimitError

# Load environment variables from .env file
load_dotenv()


class ChatGPTClient:
    """Wrapper for OpenAI ChatGPT API interactions."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: str = "gpt-4-turbo-preview",
        temperature: float = 0.7,
        max_tokens: int = 2000,
    ):
        """
        Initialize ChatGPT client.

        Args:
            api_key: OpenAI API key. If None, reads from OPENAI_API_KEY env var.
            model: Model ID to use (default: gpt-4-turbo-preview).
            temperature: Sampling temperature (0-2). Lower = more deterministic.
            max_tokens: Maximum tokens in response.
        """
        self.api_key = api_key or os.getenv("OPENAI_API_KEY")
        self.model = model or os.getenv("OPENAI_MODEL", "gpt-4-turbo-preview")
        self.temperature = temperature or float(
            os.getenv("OPENAI_TEMPERATURE", "0.7")
        )
        self.max_tokens = max_tokens or int(os.getenv("OPENAI_MAX_TOKENS", "2000"))
        self.enabled = os.getenv("CHATGPT_ENABLED", "true").lower() == "true"

        if not self.api_key:
            raise ValueError(
                "OpenAI API key not found. Set OPENAI_API_KEY env var or .env file."
            )

        self.client = OpenAI(api_key=self.api_key)

    def chat(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
    ) -> str:
        """
        Send a chat message and get a response.

        Args:
            prompt: User message/prompt.
            system_prompt: System context. If None, uses default financial analyst prompt.
            temperature: Override instance temperature.
            max_tokens: Override instance max_tokens.

        Returns:
            Response text from ChatGPT.

        Raises:
            ValueError: If ChatGPT is disabled or API key missing.
            APIError: On OpenAI API errors.
        """
        if not self.enabled:
            raise ValueError("ChatGPT is disabled. Set CHATGPT_ENABLED=true in .env")

        if not system_prompt:
            system_prompt = os.getenv(
                "CHATGPT_SYSTEM_PROMPT",
                "You are an expert financial analyst specializing in stock market analysis, "
                "technical indicators, and trading strategies. Provide insights based on the data provided.",
            )

        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": prompt},
                ],
                temperature=temperature or self.temperature,
                max_tokens=max_tokens or self.max_tokens,
            )
            return response.choices[0].message.content.strip()
        except (APIError, APIConnectionError, RateLimitError) as e:
            raise APIError(f"OpenAI API error: {str(e)}") from e

    def generate_analysis(
        self,
        symbol: str,
        score: float,
        trend: str,
        technical_summary: str,
        analyst_rating: str = "Unavailable",
        target_upside: Optional[float] = None,
    ) -> str:
        """
        Generate AI-powered stock analysis commentary.

        Args:
            symbol: Ticker symbol.
            score: Technical score (0-100).
            trend: Trend description (e.g., "Strong Uptrend").
            technical_summary: Summary of technical indicators.
            analyst_rating: Analyst consensus rating.
            target_upside: Analyst target upside percentage.

        Returns:
            AI-generated analysis as a string.
        """
        prompt = f"""
Provide a concise investment analysis (2-3 sentences) for the following stock:

Symbol: {symbol}
Technical Score: {score}/100
Trend: {trend}
Technical Summary: {technical_summary}
Analyst Rating: {analyst_rating}
Target Upside: {target_upside}% if available

Focus on:
1. What the score and trend tell us about momentum
2. Alignment with analyst consensus
3. Key risks or opportunities

Keep it professional and actionable.
"""
        return self.chat(prompt)

    def generate_report_summary(self, results_summary: str, top_picks: str) -> str:
        """
        Generate AI-powered executive summary for scan reports.

        Args:
            results_summary: Summary of scan results (e.g., "Scanned 500 stocks, 23 qualified").
            top_picks: Description of top performing stocks.

        Returns:
            AI-generated report summary.
        """
        prompt = f"""
Generate a brief executive summary (3-4 sentences) for a stock scan report:

Scan Summary: {results_summary}
Top Picks:
{top_picks}

Include:
1. Overall market conditions reflected in results
2. Key themes in top performers
3. Recommended next steps for the trader
"""
        return self.chat(prompt)

    def answer_question(
        self, question: str, context: str = ""
    ) -> str:
        """
        Answer questions about stock scanning and analysis.

        Args:
            question: User's question.
            context: Optional context about scan results or specific stocks.

        Returns:
            Answer from ChatGPT.
        """
        prompt = f"""
Answer the following question about stock market analysis:

Question: {question}
"""
        if context:
            prompt += f"\nContext:\n{context}"

        return self.chat(prompt)


def get_chatgpt_client() -> ChatGPTClient:
    """Get or create a ChatGPT client singleton."""
    if not hasattr(get_chatgpt_client, "_instance"):
        get_chatgpt_client._instance = ChatGPTClient()
    return get_chatgpt_client._instance
