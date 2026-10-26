# Bot_Traiding

Demo-Handelsbot für Alpaca Paper Trading (nur Spielgeld).

- `handel.py`: prüft 20 US-Aktien und kauft/verkauft im Alpaca-Demokonto. Regeln stehen oben in der Datei.
- `markt.py`: Kursanalyse (Trend, SMA 50/200, RSI) für Bitcoin, Ethereum, SMI, S&P 500.

Starten: `python3 handel.py` (braucht die Umgebungsvariablen `ALPACA_KEY` und `ALPACA_SECRET`, sonst Probelauf).
