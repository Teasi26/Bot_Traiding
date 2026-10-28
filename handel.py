"""Demo-Handelsbot für Alpaca Paper Trading (nur Spielgeld): Aktien aus dem S&P 500 und Kryptowährungen.

Signal pro Wert: langfristiger Aufwärtstrend (Kurs über SMA 200) und RSI 14 < 70.
Gewinnchance: Wie oft lag der Kurs 20 Tage später höher, wenn die Lage früher ähnlich war?
"Ähnlich" heisst: die 500 Tage aus den letzten 5 Jahren (über alle Aktien bzw. alle Kryptos zusammen),
deren Kennzahlen am nächsten an den heutigen liegen (RSI, Abstand zu SMA 50 und 200,
Kursänderung über 5, 20 und 60 Tage, Schwankung). Das Ergebnis wird leicht zum Durchschnitt hin
gezogen, damit Zufallstreffer nicht zu hohe Werte ergeben. Im Test auf den letzten zwei Jahren
(nur mit älteren Daten gerechnet) traf das besser als die frühere Methode, die pro Aktie nur
alle früheren Signaltage zählte. Es bleibt ein Rückblick, keine Garantie für die Zukunft.
Gekauft wird eine Aktie ab 60 %, eine Kryptowährung ab 70 % Chance.

Verkauft wird, sobald eine Position 5 % im Plus ist, der Trend "Abwärts" kippt oder der RSI über 75 steigt.
Quick-Trade: War eine Position schon mindestens 1 % im Plus und fällt sie danach von ihrem Höchststand zurück:
  - weniger als 1.5 Prozentpunkte: leichter Rückgang, behalten
  - ab 1.5 Prozentpunkten: verkaufen, ausser der Wert hat weiterhin ein Kaufsignal mit genug Chance
  - ab 3 Prozentpunkten: immer verkaufen (starker Fall, Gewinn sichern)
Danach wird derselbe Wert 5 Tage lang nicht wieder gekauft.
Eine Aktie, die heute gekauft wurde, wird erst am nächsten Börsentag verkauft: Konten unter 25'000 $
dürfen höchstens 3 Tageshandel in 5 Tagen machen (Pattern-Day-Trader-Regel). Für Krypto gilt das nicht.

Einsatz pro Kauf: der Betrag aus den Einstellungen, höchstens Kapital / maximale Positionen,
damit es auch mit wenig Geld (Startkapital 100 $) aufgeht. Gekauft wird in Teilstücken.

Ein Aufruf läuft knapp eine Stunde und prüft alle 2 Minuten neu: Aktien während der Börsenzeit
in New York, Krypto rund um die Uhr. Die 5-Jahres-Kurse werden einmal pro Aufruf geladen,
danach nur noch die aktuellen Preise von Alpaca.

Schlüssel als Umgebungsvariablen ALPACA_KEY und ALPACA_SECRET setzen.
Ohne Schlüssel läuft das Skript als Probelauf und zeigt nur, was es tun würde."""
import concurrent.futures, datetime, json, os, time, urllib.error, urllib.parse, urllib.request
from zoneinfo import ZoneInfo
import numpy as np

# Datenordner: auf GitHub setzt der Ablauf BOT_ORDNER, sonst der Projektordner
ORDNER = os.environ.get("BOT_ORDNER", "/mnt/project-files/market-bot")
LOGDATEI = os.path.join(ORDNER, "handelslog.md")  # neuester Lauf zuoberst, falls der Ordner existiert
LOG_TITEL = "# Handelslog Demo-Bot"
STATUSDATEI = os.path.join(ORDNER, "status.json")  # Daten für die Handy-App, bei jedem Lauf neu
STARTKAPITAL = float(os.environ.get("BOT_STARTKAPITAL", 100))
HOCHDATEI = os.path.join(ORDNER, "hoechststand.json")  # höchster Gewinn pro Position (für Quick-Trade)
WOCHENTAGE = ["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"]

BASIS = "https://paper-api.alpaca.markets/v2"  # nur das Demo-Konto, nie echtes Geld
DATEN = "https://data.alpaca.markets/v2"        # aktuelle Aktienkurse
KRYPTO_DATEN = "https://data.alpaca.markets/v1beta3/crypto/us"  # aktuelle Kryptokurse
INTERVALL_S = 120     # alle 2 Minuten neu prüfen
LAUFZEIT_MIN = float(os.environ.get("BOT_LAUFZEIT_MIN", 57))  # so lange läuft ein Aufruf (der Ablauf startet stündlich)
BETRAG_USD = 5        # Einsatz pro Kauf (höchstens Kapital / MAX_POSITIONEN)
MIN_CHANCE = 0.60     # Aktien: mindestens 60 % Gewinnchance
MIN_CHANCE_KRYPTO = 0.70  # Krypto: mindestens 70 % Gewinnchance
HALTEDAUER = 20       # Tage für die Gewinnchance
NACHBARN = 500        # so viele ähnliche Tage zählen für die Gewinnchance
DAEMPFUNG = 50        # zieht die Chance um so viele "Durchschnittstage" Richtung Durchschnitt
LERNTAGE = 1260       # etwa 5 Jahre zurück

GEWINN_ZIEL = 0.05    # Position verkaufen, sobald sie 5 % im Plus ist
SICHERN_AB = 0.01     # Quick-Trade greift, sobald eine Position einmal 1 % im Plus war
RUECKGANG = 0.015     # ab diesem Rückgang vom Höchststand verkaufen, wenn die Aussicht nicht mehr gut ist
RUECKGANG_STARK = 0.03  # ab diesem Rückgang immer verkaufen
SPERRE_TAGE = 5       # nach einem Verkauf diesen Wert so lange nicht wieder kaufen
MAX_POSITIONEN = 15   # höchstens so viele Werte gleichzeitig

# Livio kann diese Werte in der Handy-App ändern; sie landen vor jedem Aufruf in dieser Datei.
# Werte ausserhalb der Grenzen werden auf die Grenze gesetzt, fehlende bleiben beim Standard oben.
EINSTELLUNGSDATEI = os.path.join(ORDNER, "einstellungen.json")
GRENZEN = {"MIN_CHANCE": ("min_chance", 0.50, 0.80), "MIN_CHANCE_KRYPTO": ("min_chance_krypto", 0.50, 0.90),
           "GEWINN_ZIEL": ("gewinn_ziel", 0.01, 0.15),
           "SICHERN_AB": ("sichern_ab", 0.005, 0.05), "RUECKGANG": ("rueckgang", 0.005, 0.05),
           "RUECKGANG_STARK": ("rueckgang_stark", 0.01, 0.10),
           "MAX_POSITIONEN": ("max_positionen", 1, 90), "BETRAG_USD": ("betrag", 1.0, 5000.0)}
KAEUFE_PAUSIERT = False  # in der App einschaltbar: nur noch verkaufen, nichts Neues kaufen
KRYPTO_AKTIV = True      # in der App ausschaltbar: dann keine neuen Krypto-Käufe
ZIELE = {}  # eigenes Gewinnziel pro Wert aus der App (Depot), sonst gilt GEWINN_ZIEL

_HIER = os.path.dirname(os.path.abspath(__file__))
# Alle Aktien aus dem S&P 500 (Liste in sp500.txt neben diesem Skript)
AKTIEN = [z.strip() for z in open(os.path.join(_HIER, "sp500.txt")) if z.strip() and not z.startswith("#")]
# 100 Kryptowährungen (krypto.txt): Symbol;Name;Yahoo-Kürzel;bei Alpaca handelbar (1/0)
KRYPTO = {}
for _z in open(os.path.join(_HIER, "krypto.txt")):
    if _z.strip() and not _z.startswith("#"):
        _s, _name, _yahoo, _handelbar = _z.strip().split(";")
        KRYPTO[_s + "USD"] = {"kurz": _s, "name": _name, "yahoo": _yahoo, "handelbar": _handelbar == "1"}

KEY, SECRET = os.environ.get("ALPACA_KEY"), os.environ.get("ALPACA_SECRET")
PROBELAUF = not (KEY and SECRET)

def ist_krypto(symbol):
    return symbol in KRYPTO

def auftrag_symbol(symbol):
    """Alpaca will Krypto als BTC/USD, in Positionen heisst es BTCUSD."""
    return KRYPTO[symbol]["kurz"] + "/USD" if ist_krypto(symbol) else symbol

def kurse(symbol):
    ticker = KRYPTO[symbol]["yahoo"] if ist_krypto(symbol) else symbol.replace(".", "-")
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{urllib.parse.quote(ticker)}?range=5y&interval=1d"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    data = json.load(urllib.request.urlopen(req, timeout=20))["chart"]["result"][0]
    return [c for c in data["indicators"]["quote"][0]["close"] if c]  # ohne Lücken und Nullkurse

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

def kaufsignal(tag):
    w, s50, s200, rsi = tag
    return s200 is not None and rsi is not None and w > s200 and rsi < 70

def verkaufsignal(tag):
    w, s50, s200, rsi = tag
    return s200 is not None and ((w < s50 < s200) or (rsi or 0) > 75)

def _gleitend(w, n):
    out = np.full(len(w), np.nan)
    if len(w) >= n:
        c = np.cumsum(np.insert(w, 0, 0.0))
        out[n - 1:] = (c[n:] - c[:-n]) / n
    return out

def merkmale(werte):
    """Pro Tag die Kennzahlen für die Gewinnchance, dazu das Kaufsignal und die Kursänderung 20 Tage später."""
    w = np.array(werte, float)
    n = len(w)
    s50, s200 = _gleitend(w, 50), _gleitend(w, 200)
    rsi = np.array([np.nan if r is None else r for r in rsi_reihe(list(w))])
    def vor(k):
        a = np.full(n, np.nan)
        a[k:] = w[k:] / w[:-k] - 1
        return a
    lr = np.concatenate([[0.0], np.diff(np.log(w))])
    vol = np.sqrt(np.maximum(_gleitend(lr ** 2, 20) - _gleitend(lr, 20) ** 2, 0))
    F = np.stack([rsi / 100, w / s200 - 1, vor(20), vor(5), vol, w / s50 - 1, vor(60)], 1)
    signal = (w > s200) & (rsi < 70)
    spaeter = np.full(n, np.nan)
    spaeter[:-HALTEDAUER] = w[HALTEDAUER:] / w[:-HALTEDAUER] - 1
    return F, signal, spaeter

def chancen(alle):
    """Gewinnchance für den heutigen Tag jedes Werts, gelernt aus allen Werten derselben Gruppe."""
    lern_F, lern_y, heute_F = [], [], {}
    for symbol, werte in alle.items():
        F, _, spaeter = merkmale(werte)
        ok = np.isfinite(F).all(1) & np.isfinite(spaeter)
        idx = np.where(ok)[0][-LERNTAGE:]
        lern_F.append(F[idx])
        lern_y.append(spaeter[idx] > 0)
        if np.isfinite(F[-1]).all():
            heute_F[symbol] = F[-1]
    if not heute_F:
        return {}
    X, y = np.concatenate(lern_F), np.concatenate(lern_y)
    if len(X) < NACHBARN * 2:
        return {s_: (0.0, 0) for s_ in heute_F}
    mitte, streu = X.mean(0), X.std(0) + 1e-12
    Z = (X - mitte) / streu
    schnitt = y.mean()
    out = {}
    for symbol, f in heute_F.items():
        abstand = (((Z - (f - mitte) / streu)) ** 2).sum(1)
        nah = np.argpartition(abstand, NACHBARN)[:NACHBARN]
        out[symbol] = (float((y[nah].sum() + DAEMPFUNG * schnitt) / (NACHBARN + DAEMPFUNG)), NACHBARN)
    return out

def alpaca(methode, pfad, daten=None, basis=BASIS):
    req = urllib.request.Request(basis + pfad, method=methode,
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

def name(symbol):
    return KRYPTO[symbol]["kurz"] if ist_krypto(symbol) else symbol

def zeile(symbol, heute, chance, faelle, aktion, hat_position):
    """Eine kurze, handyfreundliche Zeile pro Wert."""
    zeichen = {"KAUFEN": "🟢", "VERKAUFEN": "🔴"}.get(aktion, "💼" if hat_position else "⚪")
    text = {"KAUFEN": "gekauft", "VERKAUFEN": "verkauft"}.get(aktion, "im Depot" if hat_position else "warten")
    return f"{zeichen} {name(symbol)}: {heute[0]:,.6g} $ · RSI {heute[3]:.0f} · Chance {chance:.0%} → {text}"

def laden(symbol):
    """5-Jahres-Kurse eines Werts; None, wenn keine oder zu wenige Kurse kamen."""
    try:
        werte = kurse(symbol)
    except Exception:
        return None
    return (symbol, werte) if len(werte) >= 250 else None

def historie():
    """{Symbol: [Symbol, Kurse, Chance, Fälle]} für alle Aktien und Kryptos."""
    with concurrent.futures.ThreadPoolExecutor(8) as pool:
        geladen = dict(h for h in pool.map(laden, AKTIEN + list(KRYPTO)) if h)
    hist = {}
    for gruppe in ([s_ for s_ in geladen if not ist_krypto(s_)], [s_ for s_ in geladen if ist_krypto(s_)]):
        for symbol, (chance, faelle) in chancen({s_: geladen[s_] for s_ in gruppe}).items():
            hist[symbol] = [symbol, geladen[symbol], chance, faelle]
    return hist

def heute(werte):
    """(Kurs, SMA50, SMA200, RSI) nur für den letzten Tag, schnell genug für alle 2 Minuten."""
    return werte[-1], sum(werte[-50:]) / 50, sum(werte[-200:]) / 200, rsi_reihe(werte[-400:])[-1]

def preise_aktualisieren(hist, aktien_auch):
    """Ersetzt den heutigen Kurs durch den letzten Handelspreis von Alpaca."""
    if aktien_auch:
        symbole = [s_ for s_ in hist if not ist_krypto(s_)]
        for i in range(0, len(symbole), 100):
            antwort = alpaca("GET", "/stocks/snapshots?feed=iex&symbols=" + ",".join(symbole[i:i + 100]), basis=DATEN) or {}
            for symbol, snap in antwort.items():
                preis = ((snap or {}).get("latestTrade") or {}).get("p")
                if preis and symbol in hist:
                    hist[symbol][1][-1] = preis
    krypto = [s_ for s_ in hist if ist_krypto(s_) and KRYPTO[s_]["handelbar"]]
    if krypto:
        antwort = alpaca("GET", "/snapshots?symbols=" + urllib.parse.quote(",".join(map(auftrag_symbol, krypto))),
                         basis=KRYPTO_DATEN) or {}
        for paar, snap in (antwort.get("snapshots") or {}).items():
            preis = ((snap or {}).get("latestTrade") or {}).get("p")
            symbol = paar.replace("/", "")
            if preis and symbol in hist:
                hist[symbol][1][-1] = preis

LAUF = {}  # Zusammenfassung des aktuellen Laufs für status.json

def einstellungen_laden():
    """Übernimmt die Werte aus der Handy-App, falls vorhanden."""
    try:
        werte = json.load(open(EINSTELLUNGSDATEI))
    except (OSError, ValueError):
        return
    for name_, (feld, tief, hoch) in GRENZEN.items():
        try:
            wert = min(max(float(werte[feld]), tief), hoch)
            globals()[name_] = round(wert) if isinstance(tief, int) else wert
        except (KeyError, TypeError, ValueError):
            pass
    global RUECKGANG_STARK, KAEUFE_PAUSIERT, KRYPTO_AKTIV, ZIELE
    RUECKGANG_STARK = max(RUECKGANG_STARK, RUECKGANG)
    KAEUFE_PAUSIERT = werte.get("kaeufe_pausiert") is True
    KRYPTO_AKTIV = werte.get("krypto_aktiv") is not False
    ZIELE = {}
    ziele = werte.get("ziele")
    for symbol, ziel in (ziele.items() if isinstance(ziele, dict) else []):
        symbol = str(symbol).replace("/", "")
        symbol = symbol + "USD" if symbol + "USD" in KRYPTO else symbol  # App nennt Krypto ohne USD
        try:
            ZIELE[symbol] = min(max(float(ziel), 0.005), 0.30)
        except (TypeError, ValueError):
            pass  # leer oder ungültig: Standardziel

def einstellungen():
    werte = {feld: globals()[name_] for name_, (feld, _, _) in GRENZEN.items()}
    return {**werte, "kaeufe_pausiert": KAEUFE_PAUSIERT, "krypto_aktiv": KRYPTO_AKTIV,
            "ziele": {name(s_): z for s_, z in ZIELE.items()}}

def mindest_chance(symbol):
    return MIN_CHANCE_KRYPTO if ist_krypto(symbol) else MIN_CHANCE

def quick_verkauf(hoechst, gewinn, d):
    """Gewinn sichern bei starkem Rückgang; leichte Rückgänge mit guter Aussicht aussitzen."""
    if hoechst < SICHERN_AB:
        return False
    rueckgang = hoechst - gewinn
    if rueckgang >= RUECKGANG_STARK:
        return True
    aussicht_gut = d is not None and kaufsignal(d[1]) and d[2] >= mindest_chance(d[0])
    return rueckgang >= RUECKGANG and not aussicht_gut

def main(hist, boerse_offen):
    """Eine Prüfrunde: handelt und gibt den Logeintrag als Markdown zurück."""
    jetzt = datetime.datetime.now(ZoneInfo("Europe/Zurich"))
    kopf = f"## {WOCHENTAGE[jetzt.weekday()]} {jetzt:%d.%m.%Y, %H:%M} Uhr"
    if PROBELAUF:
        konto_text = "Probelauf (keine Schlüssel), es wurde nichts gehandelt."
        positionen, offen, gesperrt, heute_gekauft, cash, kapital = {}, set(), set(), set(), float("inf"), STARTKAPITAL
    else:
        konto = alpaca("GET", "/account")
        cash, kapital = float(konto["cash"]), float(konto["equity"])
        konto_text = f"Kapital **{kapital:,.2f} $** · Cash {cash:,.2f} $".replace(",", "'")
        positionen = {p["symbol"]: float(p["unrealized_plpc"]) for p in alpaca("GET", "/positions")}
        seit = (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=SPERRE_TAGE)).strftime("%Y-%m-%dT%H:%M:%SZ")
        geschlossen = alpaca("GET", f"/orders?status=closed&limit=500&after={seit}") or []
        gesperrt = {o["symbol"].replace("/", "") for o in geschlossen if o["side"] == "sell"}
        # Heute gekaufte Aktien nicht heute verkaufen (Tageshandel-Regel für kleine Konten)
        heute_ny = datetime.datetime.now(ZoneInfo("America/New_York")).date().isoformat()
        heute_gekauft = {o["symbol"] for o in geschlossen if o["side"] == "buy" and o.get("filled_at")
                         and datetime.datetime.fromisoformat(o["filled_at"].replace("Z", "+00:00"))
                         .astimezone(ZoneInfo("America/New_York")).date().isoformat() == heute_ny}
        # Noch nicht ausgeführte Kaufaufträge zählen wie eine Position, damit nicht doppelt gekauft wird.
        offen = {o["symbol"].replace("/", "") for o in alpaca("GET", "/orders?status=open") or []}

    daten = {s_: (s_, heute(werte), chance, faelle) for s_, werte, chance, faelle in hist.values()}

    try:
        hoch = json.load(open(HOCHDATEI))
    except (OSError, ValueError):
        hoch = {}
    hoch = {s_: max(hoch.get(s_, g), g) for s_, g in positionen.items()}

    verkauft, bestand, zeilen = [], [], []
    for symbol in sorted(set(positionen) | offen):
        d = daten.get(symbol)
        gewinn = positionen.get(symbol)
        handelbar_jetzt = ist_krypto(symbol) or boerse_offen
        if symbol in offen:
            bestand.append(name(symbol))
            zeilen.append(f"⏳ {name(symbol)}: Auftrag wartet auf Ausführung")
        elif (gewinn is not None and handelbar_jetzt and symbol not in heute_gekauft
              and (gewinn >= ZIELE.get(symbol, GEWINN_ZIEL) or (d and verkaufsignal(d[1]))
                   or quick_verkauf(hoch[symbol], gewinn, d))):
            if gewinn >= ZIELE.get(symbol, GEWINN_ZIEL):
                grund = f"+{gewinn:.1%} Gewinnziel erreicht"
            elif quick_verkauf(hoch[symbol], gewinn, d):
                grund = f"Quick-Trade, Gewinn gesichert (Höchststand {hoch[symbol]:+.1%})"
            else:
                grund = "Verkaufssignal"
            try:
                if not PROBELAUF:
                    alpaca("DELETE", "/positions/" + symbol.replace(".", ""))
                verkauft.append(f"{name(symbol)} ({gewinn:+.1%})")
                zeilen.append(f"🔴 {name(symbol)}: verkauft, {grund}")
                hoch.pop(symbol, None)
            except SystemExit as e:
                bestand.append(name(symbol))
                zeilen.append(f"⚠️ {name(symbol)}: Verkauf abgelehnt ({e})")
        elif symbol in positionen:
            bestand.append(name(symbol))
            zusatz = " · heute gekauft, Verkauf frühestens morgen" if symbol in heute_gekauft else ""
            zeilen.append((zeile(*d, "HALTEN", True) if d else f"💼 {name(symbol)}") + f" · {gewinn:+.1%}" + zusatz)

    if not PROBELAUF and os.path.isdir(os.path.dirname(HOCHDATEI)):
        with open(HOCHDATEI, "w") as f:
            json.dump(hoch, f)

    # Kandidaten mit der höchsten Chance zuerst, bis das Limit oder das Cash erreicht ist
    def kaufbar(s_, d):
        if ist_krypto(s_):
            return KRYPTO_AKTIV and KRYPTO[s_]["handelbar"] and d[2] >= MIN_CHANCE_KRYPTO
        return boerse_offen and d[2] >= MIN_CHANCE
    kandidaten = sorted((d for s_, d in daten.items() if s_ not in set(positionen) | offen | gesperrt
                         and kaufsignal(d[1]) and kaufbar(s_, d)), key=lambda d: -d[2])
    platz = 0 if KAEUFE_PAUSIERT else MAX_POSITIONEN - len(bestand)
    betrag = round(min(BETRAG_USD, kapital / MAX_POSITIONEN), 2)
    gekauft = []
    for d in kandidaten:
        if len(gekauft) >= platz or cash < betrag or betrag < 1:
            break
        try:
            if not PROBELAUF:
                alpaca("POST", "/orders", {"symbol": auftrag_symbol(d[0]), "notional": f"{betrag:.2f}", "side": "buy",
                                           "type": "market", "time_in_force": "gtc" if ist_krypto(d[0]) else "day"})
        except SystemExit as e:
            zeilen.append(f"⚠️ {name(d[0])}: Kauf abgelehnt ({e})")
            continue
        gekauft.append(name(d[0]))
        zeilen.append(zeile(*d, "KAUFEN", False) + f" · {betrag:.2f} $")
        cash -= betrag
    LAUF.update(gekauft=gekauft, verkauft=verkauft, geprueft=len(daten), signale=len(kandidaten), betrag=betrag)
    anzahl_k = sum(ist_krypto(s_) for s_ in daten)
    konto_text += (f"  \n{len(daten) - anzahl_k} Aktien und {anzahl_k} Kryptos geprüft"
                   f"{'' if boerse_offen else ' (Börse zu, nur Krypto gehandelt)'} · {len(kandidaten)} mit Kaufsignal"
                   f" · {betrag:.2f} $ pro Kauf · Depot max. {MAX_POSITIONEN}")
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

def krypto_liste(hist, positionen):
    """Alle 100 Kryptos für den Krypto-Reiter der App, in der Reihenfolge von krypto.txt."""
    liste = []
    for symbol, info in KRYPTO.items():
        h = hist.get(symbol)
        eintrag_ = {"symbol": info["kurz"], "name": info["name"], "handelbar": info["handelbar"],
                    "im_depot": symbol in positionen}
        if h:
            w, s50, s200, rsi = heute(h[1])
            trend = "auf" if w > s200 else ("ab" if w < s50 < s200 else "seitwärts")
            eintrag_.update(kurs=w, rsi=round(rsi, 1), trend=trend, chance=round(h[2], 4),
                            signal=kaufsignal((w, s50, s200, rsi)),
                            woche=round(h[1][-1] / h[1][-8] - 1, 4) if len(h[1]) > 8 else None)
        liste.append(eintrag_)
    return liste

def status_schreiben(hist):
    """Kontostand, Positionen und letzte Aufträge als JSON für die Handy-App. Nur lesende Abfragen."""
    if PROBELAUF or not os.path.isdir(os.path.dirname(STATUSDATEI)):
        return
    jetzt = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    konto = alpaca("GET", "/account")
    kapital = float(konto["equity"])
    roh = alpaca("GET", "/positions")
    positionen = [{"symbol": name(p["symbol"]), "krypto": p.get("asset_class") == "crypto",
                   "wert": float(p["market_value"]), "einstand": float(p["cost_basis"]),
                   "kurs": float(p["current_price"]), "gewinn": float(p["unrealized_pl"]),
                   "prozent": float(p["unrealized_plpc"]), "heute": float(p["change_today"] or 0),
                   "chance": round(hist[p["symbol"]][2], 4) if p["symbol"] in hist else None}
                  for p in roh]
    auftraege = [{"symbol": o["symbol"].replace("/USD", ""), "seite": o["side"], "status": o["status"],
                  "zeit": o["filled_at"] or o["submitted_at"],
                  "betrag": float(o["notional"]) if o["notional"] else None,
                  "preis": float(o["filled_avg_price"]) if o["filled_avg_price"] else None,
                  "stueck": float(o["filled_qty"] or 0)}
                 for o in alpaca("GET", "/orders?status=all&limit=30&direction=desc") or []]
    uhr = alpaca("GET", "/clock")
    try:
        verlauf = json.load(open(STATUSDATEI)).get("verlauf", [])
    except (OSError, ValueError):
        verlauf = []
    verlauf = (verlauf + [{"zeit": jetzt, "kapital": round(kapital, 2)}])[-500:]
    status = {"stand": jetzt, "kapital": kapital, "cash": float(konto["cash"]),
              "kapital_gestern": float(konto["last_equity"]), "startkapital": STARTKAPITAL,
              "max_positionen": MAX_POSITIONEN, "gewinn_ziel": GEWINN_ZIEL, "einstellungen": einstellungen(),
              "boerse_offen": uhr["is_open"], "naechste_oeffnung": uhr["next_open"],
              "lauf": LAUF, "positionen": positionen, "auftraege": auftraege, "verlauf": verlauf,
              "krypto": krypto_liste(hist, {p["symbol"] for p in roh})}
    with open(STATUSDATEI + ".neu", "w") as f:
        json.dump(status, f, ensure_ascii=False)
    os.replace(STATUSDATEI + ".neu", STATUSDATEI)

def fehler_eintrag(fehler):
    jetzt = datetime.datetime.now(ZoneInfo("Europe/Zurich"))
    return f"## {WOCHENTAGE[jetzt.weekday()]} {jetzt:%d.%m.%Y, %H:%M} Uhr\n\n⚠️ Fehler in dieser Runde: {fehler}\n"

if __name__ == "__main__":
    hist = historie()
    ende = time.time() + LAUFZEIT_MIN * 60
    runden, letzter_fehler = 0, None
    while True:
        try:
            einstellungen_laden()
            boerse_offen = PROBELAUF or alpaca("GET", "/clock")["is_open"]
            if not PROBELAUF:
                preise_aktualisieren(hist, boerse_offen)
            text = main(hist, boerse_offen)
            runden += 1
            # Ins Log nur die erste Runde jedes Aufrufs und Runden mit Käufen/Verkäufen
            if runden == 1 or LAUF["gekauft"] or LAUF["verkauft"]:
                print(text)
                ins_log(text)
            status_schreiben(hist)
        except (Exception, SystemExit) as e:
            print(fehler_eintrag(e))
            if str(e) != letzter_fehler:  # denselben Fehler nicht alle 2 Minuten ins Log schreiben
                ins_log(fehler_eintrag(e))
            letzter_fehler = str(e)
        if PROBELAUF or time.time() + INTERVALL_S > ende:
            break
        time.sleep(INTERVALL_S)
    print(f"Fertig: {runden} Prüfrunden.")
