import pandas as pd

from stockscanner.scoring import score_stock
from stockscanner.signals import generate_signal


def test_score_stock_basic():
    df = pd.DataFrame([
        {
            'Close': 120.0,
            'MA200': 100.0,
            'MA20': 110.0,
            'MA50': 105.0,
            'RSI': 60.0,
            'MACD': 1.0,
            'MACD_SIGNAL': 0.5,
            'AVG_VOLUME': 1000000.0,
            'Volume': 1200000.0,
            'High': 130.0,
        }
    ])
    score = score_stock(df, relative_strength=25)
    assert score >= 50


def test_generate_signal_neutral():
    df = pd.DataFrame([
        {
            'Close': 100.0,
            'High': 100.0,
            'MA20': 95.0,
            'MA50': 96.0,
            'MA200': 97.0,
            'RSI': 50.0,
            'MACD': -1.0,
            'MACD_SIGNAL': -0.5,
        }
    ])
    assert generate_signal(df) == "⚪ Neutral"
