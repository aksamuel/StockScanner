import yfinance as yf
import pandas as pd

def download_data(symbol):

    stock = yf.Ticker(symbol)

    df = stock.history(period="1y")

    return df