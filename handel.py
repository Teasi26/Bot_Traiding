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

Verlust-Stopp: Fällt eine Position unter -5 % (Warnung) und danach noch 2 Prozentpunkte weiter (also -7 %),
wird sie verkauft, damit aus einem kleinen Verlust kein grosser wird. Erholt sie sich vorher, bleibt sie.
Krypto hat eigene Regeln (Standard: Ziel +8 %, sichern ab +2 %, Rückgang 3 bzw. 6 Punkte, Verlust-Stopp
-8 % plus 4 Punkte = -12 %, max. 5 Kryptos).
Verkauft wird, sobald eine Position 5 % im Plus ist, der Trend "Abwärts" kippt oder der RSI über 75 steigt.
Quick-Trade: War eine Position schon mindestens 1 % im Plus und fällt sie danach von ihrem Höchststand zurück:
  - weniger als 1.5 Prozentpunkte: leichter Rückgang, behalten
  - ab 1.5 Prozentpunkten: verkaufen, ausser der Wert hat weiterhin ein Kaufsignal mit genug Chance
  - ab 3 Prozentpunkten: immer verkaufen (starker Fall, Gewinn sichern)
Danach wird derselbe Wert 5 Tage lang nicht wieder gekauft.
Eine Aktie, die heute gekauft wurde, wird erst am nächsten Börsentag verkauft: Konten unter 25'000 $
dürfen höchstens 3 Tageshandel in 5 Tagen machen (Pattern-Day-Trader-Regel). Für Krypto gilt das nicht.

Zwei Töpfe (Aufteilung in der App, Standard halb-halb):
  ⚡ Day-Trade (kurzfristig): Strategie "Trend" (die Regeln oben) und "Rücksetzer" (Connors RSI 2:
     im Aufwärtstrend nach einem kurzen starken Fall kaufen, verkaufen sobald der Kurs wieder über
     seinem 5-Tage-Schnitt liegt). Alle Verkaufsregeln oben gelten.
  📅 Long-Term (langfristig): Strategie "Momentum" (die stärksten 10 % der letzten 12 Monate, ohne den
     letzten Monat, über SMA 200). Gehalten, bis der Kurs unter SMA 200 fällt, der Wert nicht mehr
     unter den stärksten 30 % ist oder der Long-Term-Verlust-Stopp (-15 %) greift. Kein Quick-Trade.
  Jede Strategie hat ihre eigene Gewinnchance (ähnlichste frühere Signaltage dieser Strategie) und
  kauft nur ab der Mindest-Chance. Welche Strategie einen Wert gekauft hat, steht in status.json.
  Keine Strategie garantiert Gewinn.

Einsatz pro Kauf: Day-Trade der Betrag aus den Einstellungen, höchstens Topf / maximale Positionen,
Long-Term Topf / maximale Long-Term-Werte, immer mindestens 1 $. Gekauft wird in Teilstücken.

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
MAX_POSITIONEN = 15   # höchstens so viele Aktien gleichzeitig
# Krypto hat eigene Regeln (in der App unter Regeln → Krypto), Standard etwas geduldiger, weil Krypto stärker schwankt
GEWINN_ZIEL_KRYPTO = 0.08
SICHERN_AB_KRYPTO = 0.02
RUECKGANG_KRYPTO = 0.03
RUECKGANG_STARK_KRYPTO = 0.06
BETRAG_USD_KRYPTO = 5
MAX_POSITIONEN_KRYPTO = 5  # höchstens so viele Kryptos gleichzeitig
VERLUST_WARNUNG = 0.05         # ab diesem Verlust steht eine Aktie unter Beobachtung
VERLUST_WEITER = 0.02          # fällt sie danach so viele Punkte weiter, wird verkauft
VERLUST_WARNUNG_KRYPTO = 0.08
VERLUST_WEITER_KRYPTO = 0.04

# Strategien (in der App einzeln ein- und ausschaltbar). Jede hat ihre eigene Gewinnchance:
# Der Bot sucht die 500 ähnlichsten früheren Tage, an denen genau diese Strategie ein Signal gab,
# und zählt, wie oft der Handel damals mit Gewinn endete. Gekauft wird nur ab der Mindest-Chance.
STRATEGIE_TREND = True     # Day-Trade: Aufwärtstrend + RSI unter 70 (die bisherige Regel)
STRATEGIE_RUECKSETZER = True  # Day-Trade: Kurs fällt kurz stark (RSI 2 unter 10) im Aufwärtstrend, Erholung abwarten
STRATEGIE_MOMENTUM = True  # Long-Term: die stärksten 10 % der letzten 12 Monate kaufen und halten
RSI2_GRENZE = 10           # Rücksetzer: RSI über 2 Tage unter diesem Wert
RSI2_MAX_TAGE = 10         # Rücksetzer: spätestens nach so vielen Tagen ist der Handel vorbei
MOMENTUM_TOP = 0.10        # Momentum: kaufen, wenn unter den besten 10 % der Gruppe
MOMENTUM_BLEIBT = 0.30     # Momentum: verkaufen, wenn nicht mehr unter den besten 30 %
MOMENTUM_TAGE = 63         # Momentum: Gewinnchance für etwa 3 Monate halten

# Geld aufteilen: so viel vom Kapital für Day-Trade (kurz), der Rest für Long-Term (lang)
ANTEIL_KURZ = 0.5
MAX_POSITIONEN_LANG = 10   # höchstens so viele Long-Term-Werte (Aktien und Krypto zusammen)
VERLUST_STOPP_LANG = 0.15  # Long-Term: verkaufen, wenn so viel im Minus

# Livio kann diese Werte in der Handy-App ändern; sie landen vor jedem Aufruf in dieser Datei.
# Werte ausserhalb der Grenzen werden auf die Grenze gesetzt, fehlende bleiben beim Standard oben.
EINSTELLUNGSDATEI = os.path.join(ORDNER, "einstellungen.json")
GRENZEN = {"MIN_CHANCE": ("min_chance", 0.50, 0.80), "MIN_CHANCE_KRYPTO": ("min_chance_krypto", 0.50, 0.90),
           "GEWINN_ZIEL": ("gewinn_ziel", 0.01, 0.15),
           "SICHERN_AB": ("sichern_ab", 0.005, 0.05), "RUECKGANG": ("rueckgang", 0.005, 0.05),
           "RUECKGANG_STARK": ("rueckgang_stark", 0.01, 0.10),
           "MAX_POSITIONEN": ("max_positionen", 1, 90), "BETRAG_USD": ("betrag", 1.0, 5000.0),
           "GEWINN_ZIEL_KRYPTO": ("gewinn_ziel_krypto", 0.01, 0.30),
           "SICHERN_AB_KRYPTO": ("sichern_ab_krypto", 0.005, 0.10), "RUECKGANG_KRYPTO": ("rueckgang_krypto", 0.005, 0.10),
           "RUECKGANG_STARK_KRYPTO": ("rueckgang_stark_krypto", 0.01, 0.20),
           "MAX_POSITIONEN_KRYPTO": ("max_positionen_krypto", 0, 50), "BETRAG_USD_KRYPTO": ("betrag_krypto", 1.0, 5000.0),
           "VERLUST_WARNUNG": ("verlust_warnung", 0.01, 0.30), "VERLUST_WEITER": ("verlust_weiter", 0.0, 0.20),
           "VERLUST_WARNUNG_KRYPTO": ("verlust_warnung_krypto", 0.01, 0.50),
           "VERLUST_WEITER_KRYPTO": ("verlust_weiter_krypto", 0.0, 0.30),
           "ANTEIL_KURZ": ("anteil_kurz", 0.0, 1.0), "MAX_POSITIONEN_LANG": ("max_positionen_lang", 1, 30),
           "VERLUST_STOPP_LANG": ("verlust_stopp_lang", 0.03, 0.50)}
SCHALTER = {"STRATEGIE_TREND": "strategie_trend", "STRATEGIE_RUECKSETZER": "strategie_ruecksetzer",
            "STRATEGIE_MOMENTUM": "strategie_momentum"}  # fehlt der Wert in der App: eingeschaltet
STRATEGIE_NAMEN = {"trend": "Trend", "ruecksetzer": "Rücksetzer", "momentum": "Momentum"}
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

def ruecksetzer_ergebnis(w):
    """Rücksetzer-Strategie: Signaltage und wie der Handel damals ausging.
    Signal: Kurs über SMA 200 und RSI über 2 Tage unter 10. Verkauf, sobald der Kurs wieder über
    seinem 5-Tage-Schnitt schliesst, spätestens nach 10 Tagen."""
    n = len(w)
    s200, s5 = _gleitend(w, 200), _gleitend(w, 5)
    r2 = np.array([np.nan if r is None else r for r in rsi_reihe(list(w), 2)])
    signal = (w > s200) & (r2 < RSI2_GRENZE)
    ergebnis = np.full(n, np.nan)
    for i in np.where(signal)[0]:
        for j in range(i + 1, min(i + RSI2_MAX_TAGE, n - 1) + 1):
            if w[j] > s5[j] or j == i + RSI2_MAX_TAGE:
                ergebnis[i] = w[j] / w[i] - 1
                break
    return signal, ergebnis

def momentum_raenge(alle):
    """Pro Wert und Tag: Platz unter allen Werten der Gruppe nach der Kursänderung über 12 Monate
    (ohne den letzten Monat), als Anteil: 1.0 = der stärkste, 0.0 = der schwächste."""
    lang = max(len(w) for w in alle.values())
    M = np.full((len(alle), lang), np.nan)
    for k, w in enumerate(alle.values()):
        w = np.array(w, float)
        m = np.full(len(w), np.nan)
        m[252:] = w[231:-21] / w[:-252] - 1
        M[k, lang - len(w):] = m  # rechtsbündig: der letzte Tag liegt bei allen gleich
    gueltig = np.isfinite(M)
    rang = np.argsort(np.argsort(np.where(gueltig, M, -np.inf), 0), 0).astype(float)
    anzahl = gueltig.sum(0)
    rang = (rang - (len(alle) - anzahl)) / np.maximum(anzahl - 1, 1)
    rang[~gueltig] = np.nan
    return {s_: rang[k, lang - len(w):] for k, (s_, w) in enumerate(alle.items())}

def momentum_ergebnis(w, rang):
    """Momentum-Strategie: Signal, wenn der Wert unter den besten 10 % ist und über SMA 200 liegt.
    Ergebnis: Kursänderung 3 Monate später."""
    signal = (w > _gleitend(w, 200)) & (np.nan_to_num(rang, nan=0) >= 1 - MOMENTUM_TOP)
    ergebnis = np.full(len(w), np.nan)
    ergebnis[:-MOMENTUM_TAGE] = w[MOMENTUM_TAGE:] / w[:-MOMENTUM_TAGE] - 1
    return signal, ergebnis

def chancen(alle):
    """Gewinnchance für den heutigen Tag jedes Werts, gelernt aus allen Werten derselben Gruppe.
    Gibt {Symbol: (Chance, Fälle)} für die Trend-Regel und {Symbol: {Strategie: Chance}} zurück."""
    raenge = momentum_raenge(alle)
    lern = {"trend": ([], []), "ruecksetzer": ([], []), "momentum": ([], [])}
    heute_F, extra = {}, {}
    for symbol, werte in alle.items():
        F, _, spaeter = merkmale(werte)
        w = np.array(werte, float)
        ok_F = np.isfinite(F).all(1)
        for strategie, (signal, ergebnis) in (("trend", (np.ones(len(w), bool), spaeter)),
                                              ("ruecksetzer", ruecksetzer_ergebnis(w)),
                                              ("momentum", momentum_ergebnis(w, raenge[symbol]))):
            idx = np.where(ok_F & signal & np.isfinite(ergebnis))[0][-LERNTAGE:]
            lern[strategie][0].append(F[idx])
            lern[strategie][1].append(ergebnis[idx] > 0)
        if ok_F[-1]:
            heute_F[symbol] = F[-1]
        extra[symbol] = {"rang": None if np.isnan(raenge[symbol][-1]) else float(raenge[symbol][-1])}
    if not heute_F:
        return {}, extra
    out = {}
    for strategie, (lF, ly) in lern.items():
        for symbol, (chance, faelle) in nachbarn_chance(np.concatenate(lF), np.concatenate(ly), heute_F).items():
            if strategie == "trend":
                out[symbol] = (chance, faelle)
            else:
                extra[symbol][strategie] = chance
    return out, extra

def nachbarn_chance(X, y, heute_F):
    """Anteil der 500 ähnlichsten früheren Tage, die mit Gewinn endeten (leicht zum Durchschnitt gezogen)."""
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

STRAT = {}  # pro Wert: Gewinnchance je Strategie und Momentum-Platz (aus historie())

def historie():
    """{Symbol: [Symbol, Kurse, Chance, Fälle]} für alle Aktien und Kryptos."""
    with concurrent.futures.ThreadPoolExecutor(8) as pool:
        geladen = dict(h for h in pool.map(laden, AKTIEN + list(KRYPTO)) if h)
    hist = {}
    for gruppe in ([s_ for s_ in geladen if not ist_krypto(s_)], [s_ for s_ in geladen if ist_krypto(s_)]):
        if not gruppe:
            continue
        trend, extra = chancen({s_: geladen[s_] for s_ in gruppe})
        STRAT.update(extra)
        for symbol, (chance, faelle) in trend.items():
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
    global RUECKGANG_STARK, RUECKGANG_STARK_KRYPTO, KAEUFE_PAUSIERT, KRYPTO_AKTIV, ZIELE
    RUECKGANG_STARK = max(RUECKGANG_STARK, RUECKGANG)
    RUECKGANG_STARK_KRYPTO = max(RUECKGANG_STARK_KRYPTO, RUECKGANG_KRYPTO)
    KAEUFE_PAUSIERT = werte.get("kaeufe_pausiert") is True
    KRYPTO_AKTIV = werte.get("krypto_aktiv") is not False
    for name_, feld in SCHALTER.items():
        globals()[name_] = werte.get(feld) is not False
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
            **{feld: globals()[name_] for name_, feld in SCHALTER.items()},
            "ziele": {name(s_): z for s_, z in ZIELE.items()}}

def regel(name_, symbol):
    """Wert einer Regel für diesen Wert: Krypto hat eigene Werte (NAME_KRYPTO)."""
    return globals()[name_ + "_KRYPTO"] if ist_krypto(symbol) else globals()[name_]

def mindest_chance(symbol):
    return regel("MIN_CHANCE", symbol)

def gewinn_ziel(symbol):
    return ZIELE.get(symbol, regel("GEWINN_ZIEL", symbol))

def unter_beobachtung(symbol, gewinn):
    if topf(symbol) == "lang":
        return gewinn <= -VERLUST_STOPP_LANG / 2
    return gewinn <= -regel("VERLUST_WARNUNG", symbol)

def verlust_stopp(symbol, gewinn):
    """Erst Warnung, dann weiter gefallen: verkaufen, bevor der Verlust gross wird."""
    return gewinn <= -(regel("VERLUST_WARNUNG", symbol) + regel("VERLUST_WEITER", symbol))

def quick_verkauf(symbol, hoechst, gewinn, d):
    """Gewinn sichern bei starkem Rückgang; leichte Rückgänge mit guter Aussicht aussitzen."""
    if hoechst < regel("SICHERN_AB", symbol):
        return False
    rueckgang = hoechst - gewinn
    if rueckgang >= regel("RUECKGANG_STARK", symbol):
        return True
    aussicht_gut = d is not None and kaufsignal(d[1]) and d[2] >= mindest_chance(symbol)
    return rueckgang >= regel("RUECKGANG", symbol) and not aussicht_gut

HERKUNFT = {}  # Symbol → Strategie, mit der der Bot den Wert gekauft hat (steht in status.json)

def herkunft_laden():
    """Welche Strategie welchen Wert gekauft hat. Ältere Käufe ohne Eintrag zählen als Trend (Day-Trade)."""
    global HERKUNFT
    try:
        h = json.load(open(STATUSDATEI)).get("herkunft", {})
        HERKUNFT = {s_: v for s_, v in h.items() if v in STRATEGIE_NAMEN}
    except (OSError, ValueError, AttributeError):
        HERKUNFT = {}

def strategie(symbol):
    return HERKUNFT.get(symbol, "trend")

def topf(symbol):
    """Day-Trade (kurz) oder Long-Term (lang)."""
    return "lang" if strategie(symbol) == "momentum" else "kurz"

def stopp_grenze(symbol):
    """Ab diesem Verlust wird verkauft (negativ)."""
    if topf(symbol) == "lang":
        return -VERLUST_STOPP_LANG
    return -(regel("VERLUST_WARNUNG", symbol) + regel("VERLUST_WEITER", symbol))

def kurz_werte(werte):
    """(RSI über 2 Tage, 5-Tage-Schnitt) für den Rücksetzer, mit dem aktuellen Preis."""
    return rsi_reihe(werte[-60:], 2)[-1], sum(werte[-5:]) / 5

def kaufgruende(symbol, d, werte):
    """Alle eingeschalteten Strategien, die diesen Wert jetzt kaufen würden: [(Strategie, Chance)]."""
    w, s50, s200, rsi = d[1]
    grenze, extra = mindest_chance(symbol), STRAT.get(symbol, {})
    gruende = []
    if STRATEGIE_TREND and kaufsignal(d[1]) and d[2] >= grenze:
        gruende.append(("trend", d[2]))
    if STRATEGIE_RUECKSETZER and w > s200:
        rsi2, _ = kurz_werte(werte)
        if rsi2 is not None and rsi2 < RSI2_GRENZE and extra.get("ruecksetzer", 0) >= grenze:
            gruende.append(("ruecksetzer", extra["ruecksetzer"]))
    if (STRATEGIE_MOMENTUM and w > s200 and (extra.get("rang") or 0) >= 1 - MOMENTUM_TOP
            and extra.get("momentum", 0) >= grenze):
        gruende.append(("momentum", extra["momentum"]))
    return gruende

def verkaufsgrund(symbol, gewinn, hoechst, d, werte):
    """Warum diese Position jetzt verkauft wird, sonst None. Long-Term hält länger als Day-Trade."""
    if symbol in ZIELE and gewinn >= ZIELE[symbol]:
        return f"+{gewinn:.1%} Gewinnziel erreicht"
    if topf(symbol) == "lang":
        if gewinn <= -VERLUST_STOPP_LANG:
            return f"Verlust-Stopp Long-Term bei {gewinn:+.1%}"
        if d and d[1][0] < d[1][2]:
            return "Long-Term: Kurs unter dem 200-Tage-Schnitt, Trend gebrochen"
        rang = STRAT.get(symbol, {}).get("rang")
        if rang is not None and rang < 1 - MOMENTUM_BLEIBT:
            return f"Long-Term: nicht mehr unter den stärksten {MOMENTUM_BLEIBT:.0%}"
        return None
    if gewinn >= gewinn_ziel(symbol):
        return f"+{gewinn:.1%} Gewinnziel erreicht"
    if verlust_stopp(symbol, gewinn):
        return f"Verlust-Stopp bei {gewinn:+.1%}, weiter gefallen nach der Warnung"
    if quick_verkauf(symbol, hoechst, gewinn, d):
        return f"Quick-Trade, Gewinn gesichert (Höchststand {hoechst:+.1%})"
    if d and verkaufsignal(d[1]):
        return "Verkaufssignal"
    if strategie(symbol) == "ruecksetzer" and werte and kurz_werte(werte)[1] < werte[-1]:
        return f"Rücksetzer erholt (über dem 5-Tage-Schnitt, {gewinn:+.1%})"
    return None

def main(hist, boerse_offen):
    """Eine Prüfrunde: handelt und gibt den Logeintrag als Markdown zurück."""
    global HERKUNFT
    jetzt = datetime.datetime.now(ZoneInfo("Europe/Zurich"))
    kopf = f"## {WOCHENTAGE[jetzt.weekday()]} {jetzt:%d.%m.%Y, %H:%M} Uhr"
    if PROBELAUF:
        konto_text = "Probelauf (keine Schlüssel), es wurde nichts gehandelt."
        positionen, werte_pos, offen, gesperrt, heute_gekauft = {}, {}, {}, set(), set()
        cash, kapital = float("inf"), STARTKAPITAL
    else:
        konto = alpaca("GET", "/account")
        cash, kapital = float(konto["cash"]), float(konto["equity"])
        konto_text = f"Kapital **{kapital:,.2f} $** · Cash {cash:,.2f} $".replace(",", "'")
        roh = alpaca("GET", "/positions")
        positionen = {p["symbol"]: float(p["unrealized_plpc"]) for p in roh}
        werte_pos = {p["symbol"]: float(p["market_value"]) for p in roh}
        seit = (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=SPERRE_TAGE)).strftime("%Y-%m-%dT%H:%M:%SZ")
        geschlossen = alpaca("GET", f"/orders?status=closed&limit=500&after={seit}") or []
        gesperrt = {o["symbol"].replace("/", "") for o in geschlossen if o["side"] == "sell"}
        # Heute gekaufte Aktien nicht heute verkaufen (Tageshandel-Regel für kleine Konten)
        heute_ny = datetime.datetime.now(ZoneInfo("America/New_York")).date().isoformat()
        heute_gekauft = {o["symbol"] for o in geschlossen if o["side"] == "buy" and o.get("filled_at")
                         and datetime.datetime.fromisoformat(o["filled_at"].replace("Z", "+00:00"))
                         .astimezone(ZoneInfo("America/New_York")).date().isoformat() == heute_ny}
        # Noch nicht ausgeführte Kaufaufträge zählen wie eine Position, damit nicht doppelt gekauft wird.
        offen = {}
        for o in alpaca("GET", "/orders?status=open") or []:
            offen[o["symbol"].replace("/", "")] = float(o.get("notional") or 0)
        HERKUNFT = {s_: v for s_, v in HERKUNFT.items() if s_ in positionen or s_ in offen}

    daten = {s_: (s_, heute(werte), chance, faelle) for s_, werte, chance, faelle in hist.values()}
    kurse_ = {s_: h[1] for s_, h in hist.items()}

    try:
        hoch = json.load(open(HOCHDATEI))
    except (OSError, ValueError):
        hoch = {}
    hoch = {s_: max(hoch.get(s_, g), g) for s_, g in positionen.items()}

    verkauft, bestand, zeilen = [], [], []
    behalten = []  # Symbole, die nach dieser Runde im Depot bleiben (für die Höchstzahl pro Gruppe)
    for symbol in sorted(set(positionen) | set(offen)):
        d = daten.get(symbol)
        gewinn = positionen.get(symbol)
        handelbar_jetzt = ist_krypto(symbol) or boerse_offen
        marke = "📅" if topf(symbol) == "lang" else "⚡"
        grund = None
        if symbol not in offen and gewinn is not None and handelbar_jetzt and symbol not in heute_gekauft:
            grund = verkaufsgrund(symbol, gewinn, hoch[symbol], d, kurse_.get(symbol))
        if symbol in offen:
            bestand.append(name(symbol))
            behalten.append(symbol)
            zeilen.append(f"⏳ {name(symbol)}: Auftrag wartet auf Ausführung")
        elif grund:
            try:
                if not PROBELAUF:
                    alpaca("DELETE", "/positions/" + symbol.replace(".", ""))
                verkauft.append(f"{name(symbol)} ({gewinn:+.1%})")
                zeilen.append(f"🔴 {marke} {name(symbol)}: verkauft, {grund}")
                hoch.pop(symbol, None)
            except SystemExit as e:
                bestand.append(name(symbol))
                behalten.append(symbol)
                zeilen.append(f"⚠️ {name(symbol)}: Verkauf abgelehnt ({e})")
        elif symbol in positionen:
            bestand.append(name(symbol))
            behalten.append(symbol)
            zusatz = f" · {marke} {STRATEGIE_NAMEN[strategie(symbol)]}"
            zusatz += " · heute gekauft, Verkauf frühestens morgen" if symbol in heute_gekauft else ""
            if gewinn is not None and unter_beobachtung(symbol, gewinn):
                zusatz += f" · ⚠️ unter Beobachtung, Verkauf bei {stopp_grenze(symbol):.1%}"
            zeilen.append((zeile(*d, "HALTEN", True) if d else f"💼 {name(symbol)}") + f" · {gewinn:+.1%}" + zusatz)

    if not PROBELAUF and os.path.isdir(os.path.dirname(HOCHDATEI)):
        with open(HOCHDATEI, "w") as f:
            json.dump(hoch, f)

    # Zwei Töpfe: Day-Trade (kurz) und Long-Term (lang), jeder mit seinem Anteil am Kapital
    budget = {"kurz": kapital * ANTEIL_KURZ, "lang": kapital * (1 - ANTEIL_KURZ)}
    genutzt = {"kurz": 0.0, "lang": 0.0}
    for s_ in behalten:
        genutzt[topf(s_)] += werte_pos.get(s_, 0.0) + offen.get(s_, 0.0)
    # Einsatz: Topf geteilt durch seine möglichen Positionen, höchstens der Betrag aus den Einstellungen, mindestens 1 $
    plaetze_kurz = max(1, MAX_POSITIONEN + (MAX_POSITIONEN_KRYPTO if KRYPTO_AKTIV else 0))
    betraege = {gruppe: round(max(1.0, min(globals()["BETRAG_USD" + endung], budget["kurz"] / plaetze_kurz)), 2)
                for gruppe, endung in (("aktien", ""), ("krypto", "_KRYPTO"))}
    betraege["lang"] = round(max(1.0, budget["lang"] / MAX_POSITIONEN_LANG), 2)
    platz = {"aktien": MAX_POSITIONEN - sum(not ist_krypto(s_) and topf(s_) == "kurz" for s_ in behalten),
             "krypto": MAX_POSITIONEN_KRYPTO - sum(ist_krypto(s_) and topf(s_) == "kurz" for s_ in behalten),
             "lang": MAX_POSITIONEN_LANG - sum(topf(s_) == "lang" for s_ in behalten)}
    if KAEUFE_PAUSIERT:
        platz = {k: 0 for k in platz}

    def kaufbar(s_):
        if ist_krypto(s_):
            return KRYPTO_AKTIV and KRYPTO[s_]["handelbar"]
        return boerse_offen

    # Kandidaten mit der höchsten Chance zuerst: zuerst Long-Term, dann Day-Trade
    kandidaten = []
    for s_, d in daten.items():
        if s_ in positionen or s_ in offen or s_ in gesperrt or not kaufbar(s_):
            continue
        for strat, chance in kaufgruende(s_, d, kurse_[s_]):
            kandidaten.append((0 if strat == "momentum" else 1, -chance, s_, strat, chance))
    kandidaten.sort()
    gekauft, gekauft_set = [], set()
    for _, _, s_, strat, chance in kandidaten:
        if s_ in gekauft_set:
            continue
        t = "lang" if strat == "momentum" else "kurz"
        gruppe = "lang" if t == "lang" else ("krypto" if ist_krypto(s_) else "aktien")
        betrag = betraege[gruppe]
        if platz[gruppe] <= 0 or cash < betrag or genutzt[t] + betrag > budget[t] + 0.01:
            continue
        try:
            if not PROBELAUF:
                alpaca("POST", "/orders", {"symbol": auftrag_symbol(s_), "notional": f"{betrag:.2f}", "side": "buy",
                                           "type": "market", "time_in_force": "gtc" if ist_krypto(s_) else "day"})
        except SystemExit as e:
            zeilen.append(f"⚠️ {name(s_)}: Kauf abgelehnt ({e})")
            continue
        platz[gruppe] -= 1
        genutzt[t] += betrag
        cash -= betrag
        HERKUNFT[s_] = strat
        gekauft_set.add(s_)
        gekauft.append(name(s_))
        d = daten[s_]
        zeilen.append(zeile(s_, d[1], chance, d[3], "KAUFEN", False)
                      + f" · {'📅 Long-Term' if t == 'lang' else '⚡ Day-Trade'}, {STRATEGIE_NAMEN[strat]} · {betrag:.2f} $")
    LAUF.update(gekauft=gekauft, verkauft=verkauft, geprueft=len(daten), signale=len({k[2] for k in kandidaten}),
                betrag=betraege["aktien"], betrag_krypto=betraege["krypto"], betrag_lang=betraege["lang"],
                toepfe={t: {"budget": round(budget[t], 2), "genutzt": round(genutzt[t], 2)} for t in budget})
    anzahl_k = sum(ist_krypto(s_) for s_ in daten)
    konto_text += (f"  \n{len(daten) - anzahl_k} Aktien und {anzahl_k} Kryptos geprüft"
                   f"{'' if boerse_offen else ' (Börse zu, nur Krypto gehandelt)'} · {len({k[2] for k in kandidaten})} mit Kaufsignal"
                   f"  \n⚡ Day-Trade {genutzt['kurz']:.2f} von {budget['kurz']:.2f} $ · pro Kauf {betraege['aktien']:.2f} $ (Aktie)"
                   f" / {betraege['krypto']:.2f} $ (Krypto) · max. {MAX_POSITIONEN} Aktien und {MAX_POSITIONEN_KRYPTO} Kryptos"
                   f"  \n📅 Long-Term {genutzt['lang']:.2f} von {budget['lang']:.2f} $ · pro Kauf {betraege['lang']:.2f} $"
                   f" · max. {MAX_POSITIONEN_LANG} Werte")
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
            gruende = kaufgruende(symbol, (symbol, (w, s50, s200, rsi), h[2], h[3]), h[1])
            trend = "auf" if w > s200 else ("ab" if w < s50 < s200 else "seitwärts")
            beste = max(gruende, key=lambda g: g[1]) if gruende else ("trend", h[2])
            extra = STRAT.get(symbol, {})
            eintrag_.update(kurs=w, rsi=round(rsi, 1), trend=trend, chance=round(beste[1], 4),
                            signal=bool(gruende) or kaufsignal((w, s50, s200, rsi)), strategie=beste[0],
                            chancen={"trend": round(h[2], 4),
                                     **{k: round(extra[k], 4) for k in ("ruecksetzer", "momentum") if k in extra}},
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
                   "beobachtung": unter_beobachtung(p["symbol"], float(p["unrealized_plpc"])),
                   "stopp": stopp_grenze(p["symbol"]),
                   "strategie": strategie(p["symbol"]), "topf": topf(p["symbol"]),
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
              "krypto": krypto_liste(hist, {p["symbol"] for p in roh}),
              "herkunft": HERKUNFT}
    with open(STATUSDATEI + ".neu", "w") as f:
        json.dump(status, f, ensure_ascii=False)
    os.replace(STATUSDATEI + ".neu", STATUSDATEI)

def fehler_eintrag(fehler):
    jetzt = datetime.datetime.now(ZoneInfo("Europe/Zurich"))
    return f"## {WOCHENTAGE[jetzt.weekday()]} {jetzt:%d.%m.%Y, %H:%M} Uhr\n\n⚠️ Fehler in dieser Runde: {fehler}\n"

if __name__ == "__main__":
    herkunft_laden()
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
