import pandas as pd
import numpy as np
import yfinance as yf

print("Python is working!")

ticker = yf.Ticker("NVDA")

history = ticker.history(period="5d")

print(history)