"""Demo-Handelsbot für Alpaca Paper Trading (nur Spielgeld, nur Aktien).

Signal pro Aktie: langfristiger Aufwärtstrend (Kurs über SMA 200) und RSI 14 < 70.
Damit zählen auch kurze Rücksetzer in einem Aufwärtstrend als Kaufgelegenheit.
Gewinnchance: Wie oft lag die Aktie in den letzten 5 Jahren nach genau so einem Signal
20 Handelstage später höher? Gekauft wird nur, wenn das in mindestens 52 % der Fälle so war.
Das ist ein Rückblick, keine Garantie für die Zukunft.

Verkauft wird, wenn der Trend "Abwärts" kippt oder der RSI über 75 steigt.

Schlüssel als Umgebungsvariablen ALPACA_KEY und ALPACA_SECRET setzen.
Ohne Schlüssel läuft das Skript als Probelauf und zeigt nur, was es tun würde."""
import datetime, io, json, os, sys, urllib.error, urllib.parse, urllib.request

LOGDATEI = "/mnt/project-files/market-bot/handelslog.txt"  # wird angehängt, falls der Ordner existiert

BASIS = "https://paper-api.alpaca.markets/v2"  # nur das Demo-Konto, nie echtes Geld
BETRAG_USD = 1000     # Einsatz pro Kauf
MIN_CHANCE = 0.52     # mindestens 52 % historische Trefferquote
HALTEDAUER = 20       # Handelstage (etwa ein Monat) für die Trefferquote
MIN_FAELLE = 30       # so oft muss das Signal früher vorgekommen sein

AKTIEN = ["AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META", "AVGO", "JPM", "V", "MA",
          "UNH", "LLY", "JNJ", "PG", "KO", "PEP", "COST", "WMT", "HD", "XOM"]

KEY, SECRET = os.environ.get("ALPACA_KEY"), os.environ.get("ALPACA_SECRET")
PROBELAUF = not (KEY and SECRET)

def kurse(symbol):
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{urllib.parse.quote(symbol)}?range=5y&interval=1d"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    data = json.load(urllib.request.urlopen(req, timeout=20))["chart"]["result"][0]
    return [c for c in data["indicators"]["quote"][0]["close"] if c is not None]

def rsi_reihe(werte, n=14):
    """RSI für jeden Tag (None, solange zu wenig Daten)."""
    out = [None] * len(werte)
    if len(werte) <= n:
        return out
    gew = sum(max(werte[i] - werte[i - 1], 0) for i in range(1, n + 1)) / n
    verl = sum(max(werte[i - 1] - werte[i], 0) for i in range(1, n + 1)) / n
    for i in range(n, len(werte)):
        if i > n:
            d = werte[i] - werte[i - 1]
            gew = (gew * (n - 1) + max(d, 0)) / n
            verl = (verl * (n - 1) + max(-d, 0)) / n
        out[i] = 100.0 if verl == 0 else 100 - 100 / (1 + gew / verl)
    return out

def tagesdaten(werte):
    """Pro Tag: (Kurs, SMA50, SMA200, RSI)."""
    rsi = rsi_reihe(werte)
    s50 = s200 = None
    tage = []
    for i, w in enumerate(werte):
        if i >= 199:
            s50 = sum(werte[i - 49:i + 1]) / 50
            s200 = sum(werte[i - 199:i + 1]) / 200
        tage.append((w, s50, s200, rsi[i]))
    return tage

def kaufsignal(tag):
    w, s50, s200, rsi = tag
    return s200 is not None and rsi is not None and w > s200 and rsi < 70

def verkaufsignal(tag):
    w, s50, s200, rsi = tag
    return s200 is not None and ((w < s50 < s200) or (rsi or 0) > 75)

def gewinnchance(werte, tage):
    """Anteil früherer Kaufsignale, nach denen der Kurs HALTEDAUER Tage später höher war."""
    faelle = [werte[i + HALTEDAUER] > werte[i]
              for i in range(len(werte) - HALTEDAUER) if kaufsignal(tage[i])]
    return (sum(faelle) / len(faelle) if faelle else 0.0), len(faelle)

def alpaca(methode, pfad, daten=None):
    req = urllib.request.Request(BASIS + pfad, method=methode,
                                 data=json.dumps(daten).encode() if daten else None,
                                 headers={"APCA-API-KEY-ID": KEY, "APCA-API-SECRET-KEY": SECRET,
                                          "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            text = r.read()
            return json.loads(text) if text else {}
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None
        raise SystemExit(f"Alpaca-Fehler {e.code}: {e.read().decode()}")

def main():
    if PROBELAUF:
        print("Probelauf (keine Schlüssel gesetzt): es wird nichts gehandelt.\n")
    else:
        konto = alpaca("GET", "/account")
        print(f"Demo-Konto: Kapital {float(konto['equity']):,.2f} USD, Cash {float(konto['cash']):,.2f} USD\n")
    for symbol in AKTIEN:
        werte = kurse(symbol)
        tage = tagesdaten(werte)
        heute = tage[-1]
        chance, faelle = gewinnchance(werte, tage)
        pos = None if PROBELAUF else alpaca("GET", "/positions/" + symbol)
        if pos is None and kaufsignal(heute) and chance >= MIN_CHANCE and faelle >= MIN_FAELLE:
            aktion = "KAUFEN"
        elif pos is not None and verkaufsignal(heute):
            aktion = "VERKAUFEN"
        else:
            aktion = "HALTEN"
        signal = "Kaufsignal" if kaufsignal(heute) else "kein Kaufsignal"
        print(f"{symbol:6} Kurs {heute[0]:>9,.2f}  RSI {heute[3]:>3.0f}  {signal:15} "
              f"Chance {chance:4.0%} ({faelle} Fälle){'  Position offen' if pos else ''} -> {aktion}")
        if PROBELAUF or aktion == "HALTEN":
            continue
        if aktion == "KAUFEN":
            alpaca("POST", "/orders", {"symbol": symbol, "notional": str(BETRAG_USD), "side": "buy",
                                       "type": "market", "time_in_force": "day"})
            print(f"       Kaufauftrag über {BETRAG_USD} USD gesendet.")
        else:
            alpaca("DELETE", "/positions/" + symbol)
            print("       Position verkauft.")

if __name__ == "__main__":
    puffer, echt = io.StringIO(), sys.stdout
    sys.stdout = puffer
    try:
        main()
    finally:
        sys.stdout = echt
        print(puffer.getvalue(), end="")
        if os.path.isdir(os.path.dirname(LOGDATEI)):
            with open(LOGDATEI, "a") as f:
                f.write(f"\n===== {datetime.datetime.now(datetime.timezone.utc):%Y-%m-%d %H:%M:%S} UTC =====\n" + puffer.getvalue())
