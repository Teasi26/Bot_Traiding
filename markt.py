"""Holt Tageskurse (Yahoo Finance) und berechnet Trend, SMA 50/200 und RSI 14.
Nur Analyse, kein Handel, keine Empfehlung."""
import json, sys, urllib.parse, urllib.request, datetime

MAERKTE = {"Bitcoin": "BTC-USD", "Ethereum": "ETH-USD", "SMI": "^SSMI", "S&P 500": "^GSPC"}

def kurse(symbol):
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{urllib.parse.quote(symbol)}?range=2y&interval=1d"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    data = json.load(urllib.request.urlopen(req, timeout=20))["chart"]["result"][0]
    closes = data["indicators"]["quote"][0]["close"]
    return [(t, c) for t, c in zip(data["timestamp"], closes) if c is not None]

def sma(werte, n):
    return sum(werte[-n:]) / n if len(werte) >= n else None

def rsi(werte, n=14):
    if len(werte) <= n:
        return None
    gew = verl = 0.0
    for i in range(1, n + 1):
        d = werte[i] - werte[i - 1]
        gew += max(d, 0); verl += max(-d, 0)
    gew /= n; verl /= n
    for i in range(n + 1, len(werte)):
        d = werte[i] - werte[i - 1]
        gew = (gew * (n - 1) + max(d, 0)) / n
        verl = (verl * (n - 1) + max(-d, 0)) / n
    return 100.0 if verl == 0 else 100 - 100 / (1 + gew / verl)

def analyse(name, symbol):
    reihe = kurse(symbol)
    werte = [c for _, c in reihe]
    s50, s200 = sma(werte, 50), sma(werte, 200)
    if s50 is None or s200 is None:
        trend = "zu wenig Daten"
    elif werte[-1] > s50 > s200:
        trend = "Aufwärts"
    elif werte[-1] < s50 < s200:
        trend = "Abwärts"
    else:
        trend = "Seitwärts / gemischt"
    return {"name": name, "symbol": symbol,
            "datum": datetime.date.fromtimestamp(reihe[-1][0]).isoformat(),
            "kurs": werte[-1], "sma50": s50, "sma200": s200, "rsi14": rsi(werte),
            "trend": trend, "verlauf": werte[-200:]}

if __name__ == "__main__":
    out = {"stand": datetime.datetime.utcnow().isoformat() + "Z",
           "maerkte": [analyse(n, s) for n, s in MAERKTE.items()]}
    json.dump(out, sys.stdout, ensure_ascii=False, indent=1)
