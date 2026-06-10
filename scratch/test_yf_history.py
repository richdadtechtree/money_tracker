import yfinance as yf
t = yf.Ticker('AAPL')
hist = t.history(period="5d")
print("History:")
print(hist)
print("Close column:")
print(hist['Close'])
print("Last Close:", hist['Close'].iloc[-1])
