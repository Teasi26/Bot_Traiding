# Bot_Traiding

Demo-Handelsbot für Alpaca Paper Trading (nur Spielgeld).

- `handel.py`: prüft alle S&P-500-Aktien (Liste in `sp500.txt`) und kauft/verkauft im Alpaca-Demokonto. Regeln stehen oben in der Datei.
- `markt.py`: Kursanalyse (Trend, SMA 50/200, RSI) für Bitcoin, Ethereum, SMI, S&P 500.

Starten: `python3 handel.py` (braucht die Umgebungsvariablen `ALPACA_KEY` und `ALPACA_SECRET`, sonst Probelauf).

## Läuft auf GitHub Actions

`.github/workflows/bot.yml` startet den Bot stündlich zu Börsenzeiten (Mo-Fr). Dafür braucht das Repo zwei Secrets: `ALPACA_KEY` und `ALPACA_SECRET` (Settings → Secrets and variables → Actions).

- Branch `bot-daten`: Log, `status.json` und `hoechststand.json`, alle 2 Minuten neu (immer nur ein Commit).
- Branch `bot-einstellungen`: `einstellungen.json` aus der Handy-App; der Bot liest sie alle 2 Minuten.
