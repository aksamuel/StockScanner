# StockScanner v2.11.0

[![Stock Scanner](https://github.com/aksamuel/StockScanner/actions/workflows/scan.yml/badge.svg)](https://github.com/aksamuel/StockScanner/actions/workflows/scan.yml)

StockScanner scans a watchlist or the NYSE universe, calculates technical and
analyst signals, sizes positions, and produces Excel and GitHub Pages reports.

**NEW in v2.11.0: AI-Powered Features with ChatGPT Integration** 🤖

## Features

- Full NYSE universe and custom watchlist scanning
- Parallel Yahoo Finance market-data requests
- Technical scoring, signals, trends, RSI, MACD, and moving averages
- Support and resistance zones based on completed daily candles
- Intraday price overlays without changing daily indicators
- Analyst ratings and target upside as confirmation data
- Percentage-based position sizing and risk controls
- Excel reports and linked HTML dashboards
- Hourly market-hours price snapshots
- Time-bounded exception-list management
- **NEW: AI-Powered Stock Analysis with ChatGPT** 🎯
  - Individual stock analysis and recommendations
  - AI-generated executive summaries for scan reports
  - Interactive chat interface for Q&A about stocks
  - Automated trading idea generation
  - AI-assisted documentation and docstring generation
  - Comparative stock analysis

## AI Features (ChatGPT Integration)

### 1. Stock Analysis Enhancement

ChatGPT generates contextual analysis for each stock:

```python
from stockscanner.ai_analysis import AIAnalyzer

analyzer = AIAnalyzer()
analysis = analyzer.analyze_stock(
    symbol="AAPL",
    latest_data={"Score": 85, "RSI": 65},
    trade_plan={"Trend": "Strong Uptrend", "Entry": 150, "Stop": 145},
    analyst_data={"Analyst Rating": "Buy", "Target Upside": 12.5}
)
print(analysis)  # AI-powered analysis
```

### 2. Report Generation with AI Commentary

Auto-generate executive summaries and stock commentary:

```python
from stockscanner.ai_report import AIReportGenerator

report_gen = AIReportGenerator()
summary = report_gen.generate_executive_summary(
    scan_date="2026-08-22",
    total_scanned=500,
    qualified_count=23,
    top_3_symbols=["NVDA", "MSFT", "TSLA"]
)
print(summary)
```

### 3. Interactive Chat Interface

Ask questions about stocks and market conditions:

```python
from stockscanner.ai_chat import StockAnalysisChat

chat = StockAnalysisChat()
answer = chat.ask_about_stock(
    symbol="AAPL",
    question="Should I buy AAPL if it breaks above 155?",
    stock_data={"Current Price": 151, "RSI": 65}
)
print(answer)
```

## Setup for AI Features

### 1. Install Dependencies

```powershell
.\.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.\.venv\Scripts\python.exe -m pip install -e .
```

### 2. Get OpenAI API Key

1. Sign up at [OpenAI Platform](https://platform.openai.com)
2. Generate an API key from [API Keys](https://platform.openai.com/api-keys)
3. Copy the key

### 3. Configure Environment

Copy `.env.example` to `.env`:

```bash
OPENAI_API_KEY=sk-your-actual-api-key-here
OPENAI_MODEL=gpt-4-turbo-preview
CHATGPT_ENABLED=true
```

### 4. Test the Integration

```powershell
.\.\.venv\Scripts\python.exe -c "from stockscanner.openai_client import get_chatgpt_client; client = get_chatgpt_client(); print(client.chat('What is technical analysis?'))"
```

## Windows Setup

Requirements:

- Windows 10 or later
- Python 3.11 or later
- Git
- OpenAI API key (for AI features)

Open PowerShell and run:

```powershell
cd C:\StockScanner
python -m venv .venv
.\.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.\.venv\Scripts\python.exe -m pip install -e .
```

## Run a Full Local Scan

```powershell
cd C:\StockScanner
.\.\.venv\Scripts\python.exe -m stockscanner.cli --universe --force-download --parallel --workers 20 --portfolio 50000 --position-size 5 --risk 1 --html
```

## CLI Options

| Option | Description | Default |
|---|---|---:|
| `--universe` | Scan NYSE universe | Off |
| `--limit N` | Limit universe for test | All |
| `--parallel` | Enable parallel processing | Off |
| `--workers N` | Parallel worker count | 10 |
| `--html` | Generate HTML dashboards | Off |
| `--quiet` | Suppress per-ticker output | Off |

## Reports

Each run creates files under `reports\\YYYY-MM-DD\\`:

| Page | Purpose |
|---|---|
| `index.html` | KPI Dashboard |
| `technical.html` | Technical Analysis |
| `analysts.html` | Analyst ratings |
| `exceptions.html` | Exception list |

Live site: <https://aksamuel.github.io/StockScanner/>

## Testing

```powershell
cd C:\StockScanner
.\.\.venv\Scripts\python.exe -m pytest -q
```

## License

MIT
