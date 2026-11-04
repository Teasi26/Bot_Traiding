# Bot_Traiding

Demo-Handelsbot für Alpaca Paper Trading (nur Spielgeld): S&P-500-Aktien und Kryptowährungen.

- `handel.py`: prüft alle S&P-500-Aktien (`sp500.txt`) und 100 Kryptos (`krypto.txt`) und kauft/verkauft im Alpaca-Demokonto. Regeln stehen oben in der Datei. Braucht numpy.
- `strategien.py`: 50 Strategien (31 ⚡ Day-Trade, 19 📅 Long-Term), je mit eigener Gewinnchance und Schalter in der App. Das Geld wird auf die zwei Töpfe aufgeteilt (Standard 50/50).
- `strategien_test.py`: Rückblick-Test aller Strategien auf den letzten 500 Tagen (nur mit älteren Daten gelernt), schreibt `strategien_test.json`. Standardmässig an sind nur bestandene Strategien.
- `markt.py`: Kursanalyse (Trend, SMA 50/200, RSI) für Bitcoin, Ethereum, SMI, S&P 500.

Starten: `python3 handel.py` (braucht die Umgebungsvariablen `ALPACA_KEY` und `ALPACA_SECRET`, sonst Probelauf).

## Läuft auf GitHub Actions

`.github/workflows/bot.yml` startet den Bot stündlich rund um die Uhr (Krypto immer, Aktien nur zur Börsenzeit). Dafür braucht das Repo zwei Secrets: `ALPACA_KEY` und `ALPACA_SECRET` (Settings → Secrets and variables → Actions).

- Branch `bot-daten`: Log, `status.json` und `hoechststand.json`, alle 2 Minuten neu (immer nur ein Commit).
- Branch `bot-einstellungen`: `einstellungen.json` aus der Handy-App; der Bot liest sie alle 2 Minuten.
- `app_abgleich.sh`: läuft in der stündlichen Claude-Aufgabe (handelt nie). Schickt die App-Einstellungen nach `bot-einstellungen` und kopiert alle 2 Minuten die Daten aus `bot-daten` in den Projektordner, den die Handy-App liest.
