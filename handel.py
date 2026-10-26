"""Demo-Handelsbot für Alpaca Paper Trading (nur Spielgeld, nur Aktien).

Signal pro Aktie: langfristiger Aufwärtstrend (Kurs über SMA 200) und RSI 14 < 70.
Damit zählen auch kurze Rücksetzer in einem Aufwärtstrend als Kaufgelegenheit.
Gewinnchance: Wie oft lag die Aktie in den letzten 5 Jahren nach genau so einem Signal
20 Handelstage später höher? Gekauft wird nur, wenn das in mindestens 52 % der Fälle so war.
Das ist ein Rückblick, keine Garantie für die Zukunft.

Verkauft wird, sobald eine Position 5 % im Plus ist, der Trend "Abwärts" kippt oder der RSI über 75 steigt.
Danach wird dieselbe Aktie 5 Tage lang nicht wieder gekauft.
Geprüft werden alle S&P-500-Aktien; höchstens 50 Positionen gleichzeitig, die mit der höchsten Chance zuerst.

Schlüssel als Umgebungsvariablen ALPACA_KEY und ALPACA_SECRET setzen.
Ohne Schlüssel läuft das Skript als Probelauf und zeigt nur, was es tun würde."""
import concurrent.futures, datetime, json, os, urllib.error, urllib.parse, urllib.request
from zoneinfo import ZoneInfo

LOGDATEI = "/mnt/project-files/market-bot/handelslog.md"  # neuester Lauf zuoberst, falls der Ordner existiert
LOG_TITEL = "# Handelslog Demo-Bot"
WOCHENTAGE = ["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"]

BASIS = "https://paper-api.alpaca.markets/v2"  # nur das Demo-Konto, nie echtes Geld
BETRAG_USD = 1000     # Einsatz pro Kauf
MIN_CHANCE = 0.52     # mindestens 52 % historische Trefferquote
HALTEDAUER = 20       # Handelstage (etwa ein Monat) für die Trefferquote
MIN_FAELLE = 30       # so oft muss das Signal früher vorgekommen sein

GEWINN_ZIEL = 0.05    # Position verkaufen, sobald sie 5 % im Plus ist
SPERRE_TAGE = 5       # nach einem Verkauf diese Aktie so lange nicht wieder kaufen
MAX_POSITIONEN = 50   # höchstens so viele Aktien gleichzeitig (50 x 1000 USD = halbes Spielgeld)

# Alle Aktien aus dem S&P 500 (Liste in sp500.txt neben diesem Skript)
_LISTE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "sp500.txt")
AKTIEN = [z.strip() for z in open(_LISTE) if z.strip() and not z.startswith("#")]

KEY, SECRET = os.environ.get("ALPACA_KEY"), os.environ.get("ALPACA_SECRET")
PROBELAUF = not (KEY and SECRET)

def kurse(symbol):
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{urllib.parse.quote(symbol.replace(".", "-"))}?range=5y&interval=1d"
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

def zeile(symbol, heute, chance, faelle, aktion, hat_position):
    """Eine kurze, handyfreundliche Zeile pro Aktie."""
    zeichen = {"KAUFEN": "🟢", "VERKAUFEN": "🔴"}.get(aktion, "💼" if hat_position else "⚪")
    text = {"KAUFEN": "gekauft", "VERKAUFEN": "verkauft"}.get(aktion, "im Depot" if hat_position else "warten")
    return f"{zeichen} {symbol}: {heute[0]:,.2f} $ · RSI {heute[3]:.0f} · Chance {chance:.0%} → {text}"

def pruefen(symbol):
    """Kennzahlen einer Aktie; None, wenn keine Kurse kamen."""
    try:
        werte = kurse(symbol)
    except Exception:
        return None
    if len(werte) < 250:
        return None
    tage = tagesdaten(werte)
    chance, faelle = gewinnchance(werte, tage)
    return symbol, tage[-1], chance, faelle

def main():
    """Handelt und gibt den Logeintrag als Markdown zurück."""
    jetzt = datetime.datetime.now(ZoneInfo("Europe/Zurich"))
    kopf = f"## {WOCHENTAGE[jetzt.weekday()]} {jetzt:%d.%m.%Y, %H:%M} Uhr"
    if PROBELAUF:
        konto_text = "Probelauf (keine Schlüssel), es wurde nichts gehandelt."
        positionen, offen, gesperrt, cash = {}, set(), set(), float("inf")
    else:
        konto = alpaca("GET", "/account")
        cash = float(konto["cash"])
        konto_text = f"Kapital **{float(konto['equity']):,.0f} $** · Cash {cash:,.0f} $".replace(",", "'")
        positionen = {p["symbol"]: float(p["unrealized_plpc"]) for p in alpaca("GET", "/positions")}
        seit = (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=SPERRE_TAGE)).strftime("%Y-%m-%dT%H:%M:%SZ")
        gesperrt = {o["symbol"] for o in alpaca("GET", f"/orders?status=closed&limit=500&after={seit}") or []
                    if o["side"] == "sell"}
        # Noch nicht ausgeführte Kaufaufträge (z.B. ausserhalb der Börsenzeit) zählen wie eine Position,
        # damit nicht doppelt gekauft wird.
        offen = {o["symbol"] for o in alpaca("GET", "/orders?status=open") or []}

    with concurrent.futures.ThreadPoolExecutor(8) as pool:
        daten = {d[0]: d for d in pool.map(pruefen, AKTIEN) if d}

    verkauft, bestand, zeilen = [], [], []
    for symbol in sorted(set(positionen) | offen):
        d = daten.get(symbol)
        gewinn = positionen.get(symbol)
        if gewinn is not None and (gewinn >= GEWINN_ZIEL or (d and verkaufsignal(d[1]))):
            grund = f"+{gewinn:.1%} Gewinnziel erreicht" if gewinn >= GEWINN_ZIEL else "Verkaufssignal"
            verkauft.append(f"{symbol} ({gewinn:+.1%})")
            zeilen.append(f"🔴 {symbol}: verkauft, {grund}")
            if not PROBELAUF:
                alpaca("DELETE", "/positions/" + symbol.replace(".", ""))
        elif symbol in positionen:
            bestand.append(symbol)
            zeilen.append((zeile(*d, "HALTEN", True) if d else f"💼 {symbol}") + f" · {gewinn:+.1%}")
        else:
            bestand.append(symbol)
            zeilen.append(f"⏳ {symbol}: Kaufauftrag wartet auf Börsenöffnung")

    # Kandidaten mit der höchsten Chance zuerst, bis das Limit oder das Cash erreicht ist
    kandidaten = sorted((d for s_, d in daten.items() if s_ not in set(positionen) | offen | gesperrt
                         and kaufsignal(d[1]) and d[2] >= MIN_CHANCE and d[3] >= MIN_FAELLE),
                        key=lambda d: -d[2])
    platz = MAX_POSITIONEN - len(bestand)
    gekauft = []
    for d in kandidaten:
        if len(gekauft) >= platz or cash < BETRAG_USD:
            break
        gekauft.append(d[0])
        zeilen.append(zeile(*d, "KAUFEN", False))
        cash -= BETRAG_USD
        if not PROBELAUF:
            alpaca("POST", "/orders", {"symbol": d[0], "notional": str(BETRAG_USD), "side": "buy",
                                       "type": "market", "time_in_force": "day"})
    konto_text += f"  \n{len(daten)} Aktien geprüft · {len(kandidaten)} mit Kaufsignal · Depot max. {MAX_POSITIONEN}"
    return eintrag(kopf, konto_text, gekauft, verkauft, bestand, zeilen)

def eintrag(kopf, konto_text, gekauft, verkauft, bestand, zeilen=None):
    teile = [kopf, "", konto_text, "",
             f"🟢 Gekauft: {', '.join(gekauft) or '–'}  ",
             f"🔴 Verkauft: {', '.join(verkauft) or '–'}  ",
             f"💼 Im Depot: {', '.join(bestand) or '–'}"]
    if zeilen:
        teile += ["", "<details><summary>Details</summary>", ""] + [z + "  " for z in zeilen] + ["", "</details>"]
    return "\n".join(teile) + "\n"

def ins_log(text):
    """Neuester Eintrag zuoberst. Probeläufe werden nicht protokolliert."""
    if PROBELAUF or not os.path.isdir(os.path.dirname(LOGDATEI)):
        return
    alt = open(LOGDATEI).read() if os.path.exists(LOGDATEI) else ""
    alt = alt.split("\n", 2)[2] if alt.startswith(LOG_TITEL) else alt
    with open(LOGDATEI, "w") as f:
        f.write(LOG_TITEL + "\n\n" + text + "\n---\n\n" + alt)

if __name__ == "__main__":
    text = main()
    print(text)
    ins_log(text)
