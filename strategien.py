"""50 bekannte Handelsstrategien für den Demo-Bot, sortiert nach Day-Trade (kurz) und Long-Term (lang).

Die Ideen stammen aus frei beschriebenen, bekannten Regeln (z. B. Investopedia, Quantpedia, Larry Connors,
Bollinger, Turtle-Trader, Momentum- und Niedrig-Volatilitäts-Forschung). Der Bot kennt nur Tagesschlusskurse,
darum fehlen Strategien, die Tageshoch/-tief, Volumen, Datum oder Firmenzahlen brauchen.

Jede Strategie hat:
  - ein Kaufsignal (nur Kaufen, nie Leerverkauf),
  - einen Ausstieg: "regeln" (nur die allgemeinen Day-Trade-Regeln), ("erholung", 10) = verkaufen, sobald der
    Kurs über seinem 5-Tage-Schnitt schliesst (spätestens nach 10 Tagen), ("tage", N) = nach N Börsentagen
    verkaufen, "lang" = halten bis Kurs unter SMA 200 oder Verlust-Stopp, ("rang", Feld) = wie "lang" und
    zusätzlich verkaufen, wenn der Wert nicht mehr unter den stärksten 30 % ist.
Die Gewinnchance rechnet der Bot pro Strategie aus den ähnlichsten früheren Signaltagen dieser Strategie.
Wie gut jede Strategie früher war, steht in strategien_test.json (python3 strategien_test.py)."""
import numpy as np

LANG_TAGE = 63      # Long-Term: Ergebnis nach etwa 3 Monaten
LIVE_TAGE = 400     # so viele letzte Tage reichen für die Kennzahlen eines Tages
RANG_FELDER = ["mom12", "mom6", "mom3", "vol60_tief", "sharpe12", "ret3j_tief", "glatt"]


def _gleitend(w, n):
    out = np.full(len(w), np.nan)
    if len(w) >= n:
        c = np.cumsum(np.insert(w, 0, 0.0))
        out[n - 1:] = (c[n:] - c[:-n]) / n
    return out


def _ema(w, n):
    out = np.empty(len(w))
    a, e = 2 / (n + 1), w[0]
    for i, x in enumerate(w):
        e = a * x + (1 - a) * e
        out[i] = e
    return out


def _rsi(w, n):
    out = np.full(len(w), np.nan)
    if len(w) <= n:
        return out
    d = np.diff(w)
    gew, verl = np.maximum(d[:n], 0).mean(), np.maximum(-d[:n], 0).mean()
    out[n] = 100.0 if verl == 0 else 100 - 100 / (1 + gew / verl)
    for i in range(n + 1, len(w)):
        x = d[i - 1]
        gew = (gew * (n - 1) + max(x, 0)) / n
        verl = (verl * (n - 1) + max(-x, 0)) / n
        out[i] = 100.0 if verl == 0 else 100 - 100 / (1 + gew / verl)
    return out


def _vor(w, k):
    """Kursänderung über k Tage."""
    a = np.full(len(w), np.nan)
    if len(w) > k:
        a[k:] = w[k:] / w[:-k] - 1
    return a


def _streu(w, n):
    return np.sqrt(np.maximum(_gleitend(w ** 2, n) - _gleitend(w, n) ** 2, 0))


def _roll(w, n, f):
    """Höchst- bzw. Tiefstwert der n Tage VOR jedem Tag (ohne heute)."""
    out = np.full(len(w), np.nan)
    if len(w) > n:
        from numpy.lib.stride_tricks import sliding_window_view
        out[n:] = f(sliding_window_view(w[:-1], n), axis=1)
    return out


def _vorher(a, k=1):
    out = np.full(len(a), np.nan)
    out[k:] = a[:-k]
    return out


def _kreuzt(a, b):
    """a steigt heute über b."""
    return (a > b) & (_vorher(a) <= _vorher(b))


def kennzahlen(werte):
    """Alle Kennzahlen pro Tag, die die Strategien brauchen."""
    w = np.asarray(werte, float)
    k = {"w": w}
    for n in (5, 10, 20, 50, 100, 200):
        k[f"s{n}"] = _gleitend(w, n)
    k["e9"], k["e12"], k["e21"], k["e26"] = _ema(w, 9), _ema(w, 12), _ema(w, 21), _ema(w, 26)
    k["macd"] = k["e12"] - k["e26"]
    k["macd_sig"] = _ema(k["macd"], 9)
    for n in (2, 3, 14):
        k[f"rsi{n}"] = _rsi(w, n)
    sd20 = _streu(w, 20)
    k["bb_unten"], k["bb_oben"] = k["s20"] - 2 * sd20, k["s20"] + 2 * sd20
    k["bb_breite"] = 4 * sd20 / k["s20"]
    k["z20"] = (w - k["s20"]) / (sd20 + 1e-12)
    for n in (1, 5, 20, 63, 126, 252):
        k[f"r{n}"] = _vor(w, n)
    k["mom12_roh"] = _vorher(_vor(w, 231), 21)   # 12 Monate ohne den letzten Monat
    k["mom6_roh"] = _vorher(_vor(w, 105), 21)    # 6 Monate ohne den letzten Monat
    k["ret3j_roh"] = _vor(w, 756)
    lr = np.concatenate([[0.0], np.diff(np.log(w))])
    k["vol20"], k["vol60"] = _streu(lr, 20), _streu(lr, 60)
    k["sharpe12_roh"] = k["r252"] / (_streu(lr, 252) * np.sqrt(252) + 1e-12)
    k["glatt_roh"] = _gleitend((lr > 0).astype(float), 252)
    for n in (5, 10, 20, 55, 100, 252):
        k[f"hoch{n}"] = _roll(w, n, np.max)
    for n in (5, 10, 252):
        k[f"tief{n}"] = _roll(w, n, np.min)
    runter = np.zeros(len(w))
    for i in range(1, len(w)):
        runter[i] = runter[i - 1] + 1 if w[i] < w[i - 1] else 0
    k["runter"] = runter
    lo, hi = _roll(np.append(w, w[-1]), 14, np.min)[1:], _roll(np.append(w, w[-1]), 14, np.max)[1:]
    k["stoch"] = 100 * (w - lo) / (hi - lo + 1e-12)   # Stochastik nur aus Schlusskursen (14 Tage)
    ueber = (w > k["s200"]).astype(float)
    k["tage_ueber_s200"] = _gleitend(ueber, 120)
    k["s200_steigt"] = k["s200"] > _vorher(k["s200"], 20)
    k["breite_tief"] = k["bb_breite"] <= _roll(np.nan_to_num(k["bb_breite"], nan=9.9), 126, np.min) * 1.05
    k["tief_vor"] = _roll(w, 60, np.min) <= k["tief252"] * 1.0001  # 1-Jahres-Tief in den letzten 60 Tagen
    return k


def raenge(alle_k):
    """Platz pro Tag innerhalb der Gruppe (1 = bester) für die Felder in RANG_FELDER."""
    quellen = {"mom12": ("mom12_roh", 1), "mom6": ("mom6_roh", 1), "mom3": ("r63", 1), "vol60_tief": ("vol60", -1),
               "sharpe12": ("sharpe12_roh", 1), "ret3j_tief": ("ret3j_roh", -1), "glatt": ("glatt_roh", 1)}
    lang = max(len(k["w"]) for k in alle_k.values())
    for feld, (quelle, richtung) in quellen.items():
        M = np.full((len(alle_k), lang), np.nan)
        for z, k in enumerate(alle_k.values()):
            M[z, lang - len(k["w"]):] = richtung * k[quelle]
        gueltig = np.isfinite(M)
        r = np.argsort(np.argsort(np.where(gueltig, M, -np.inf), 0), 0).astype(float)
        anzahl = gueltig.sum(0)
        r = (r - (len(alle_k) - anzahl)) / np.maximum(anzahl - 1, 1)
        r[~gueltig] = np.nan
        for z, k in enumerate(alle_k.values()):
            k[feld] = r[z, lang - len(k["w"]):]


def _r(k, feld):
    return np.nan_to_num(k[feld], nan=-1)


T = lambda k: k["w"] > k["s200"]  # langfristiger Aufwärtstrend

# (id, Name, Topf, Ausstieg, Erklärung, Kaufsignal)
STRATEGIEN = [
    # ---------- ⚡ Day-Trade: Rücksetzer kaufen (Mean Reversion) ----------
    ("trend", "Trend", "kurz", "regeln", "Aufwärtstrend und nicht überhitzt (RSI unter 70), die ursprüngliche Regel.",
     lambda k: T(k) & (k["rsi14"] < 70)),
    ("ruecksetzer", "Rücksetzer RSI 2", "kurz", ("erholung", 10), "Connors: im Aufwärtstrend RSI über 2 Tage unter 10.",
     lambda k: T(k) & (k["rsi2"] < 10)),
    ("rsi2_5", "RSI 2 unter 5", "kurz", ("erholung", 10), "Wie Rücksetzer, aber nur bei sehr starkem Fall (RSI 2 unter 5).",
     lambda k: T(k) & (k["rsi2"] < 5)),
    ("rsi2_doppel", "RSI 2 zwei Tage", "kurz", ("erholung", 10), "Connors: RSI 2 an zwei Tagen zusammen unter 35.",
     lambda k: T(k) & (k["rsi2"] + _vorher(k["rsi2"]) < 35)),
    ("rsi3", "RSI 3 unter 15", "kurz", ("erholung", 10), "Kurzer RSI über 3 Tage unter 15 im Aufwärtstrend.",
     lambda k: T(k) & (k["rsi3"] < 15)),
    ("drei_runter", "3 Tage runter", "kurz", ("erholung", 10), "Drei Tage hintereinander tiefer geschlossen, im Aufwärtstrend.",
     lambda k: T(k) & (k["runter"] >= 3)),
    ("vier_runter", "4 Tage runter", "kurz", ("erholung", 10), "Vier Tage hintereinander tiefer geschlossen, im Aufwärtstrend.",
     lambda k: T(k) & (k["runter"] >= 4)),
    ("bb_unten", "Bollinger unten", "kurz", ("erholung", 10), "Kurs unter dem unteren Bollinger-Band, im Aufwärtstrend.",
     lambda k: T(k) & (k["w"] < k["bb_unten"])),
    ("bb_unten_frei", "Bollinger unten ohne Trend", "kurz", ("erholung", 10), "Kurs unter dem unteren Bollinger-Band, egal welcher Trend.",
     lambda k: k["w"] < k["bb_unten"]),
    ("tief5", "5-Tage-Tief", "kurz", ("erholung", 10), "Kurs so tief wie seit 5 Tagen nicht, im Aufwärtstrend.",
     lambda k: T(k) & (k["w"] < k["tief5"])),
    ("tief10", "10-Tage-Tief", "kurz", ("erholung", 10), "Kurs so tief wie seit 10 Tagen nicht, im Aufwärtstrend.",
     lambda k: T(k) & (k["w"] < k["tief10"])),
    ("unter_s20", "5 % unter 20-Tage-Schnitt", "kurz", ("erholung", 10), "Kurs 5 % unter seinem 20-Tage-Schnitt, im Aufwärtstrend.",
     lambda k: T(k) & (k["w"] < 0.95 * k["s20"])),
    ("unter_s50", "7 % unter 50-Tage-Schnitt", "kurz", ("erholung", 10), "Kurs 7 % unter seinem 50-Tage-Schnitt, im Aufwärtstrend.",
     lambda k: T(k) & (k["w"] < 0.93 * k["s50"])),
    ("tagesverlust", "Grosser Tagesverlust", "kurz", ("tage", 3), "Ein Tag mit mehr als 3 % Minus im Aufwärtstrend, 3 Tage halten.",
     lambda k: T(k) & (k["r1"] < -0.03)),
    ("rsi14_30", "RSI 14 unter 30", "kurz", ("tage", 10), "Klassisch überverkauft (RSI 14 unter 30), 10 Tage halten.",
     lambda k: k["rsi14"] < 30),
    ("rsi14_30_trend", "RSI 14 unter 30 im Trend", "kurz", ("erholung", 10), "Überverkauft (RSI 14 unter 30), aber im Aufwärtstrend.",
     lambda k: T(k) & (k["rsi14"] < 30)),
    ("stoch_tief", "Stochastik unter 10", "kurz", ("erholung", 10), "Kurs ganz unten in seiner 14-Tage-Spanne, im Aufwärtstrend.",
     lambda k: T(k) & (k["stoch"] < 10)),
    ("z_minus2", "Z-Wert unter −2", "kurz", ("erholung", 10), "Kurs mehr als 2 Schwankungen unter seinem 20-Tage-Schnitt, im Aufwärtstrend.",
     lambda k: T(k) & (k["z20"] < -2)),
    ("dip_s10", "Unter 10-Tage-Schnitt", "kurz", ("erholung", 10), "Kurs unter dem 10-Tage-Schnitt, während 50 über 200 liegt.",
     lambda k: (k["w"] < k["s10"]) & (k["s50"] > k["s200"])),
    ("woche_minus5", "Woche −5 %", "kurz", ("tage", 5), "In 5 Tagen über 5 % gefallen, im Aufwärtstrend, 5 Tage halten.",
     lambda k: T(k) & (k["r5"] < -0.05)),
    ("monat_minus10", "Monat −10 %", "kurz", ("tage", 20), "Kurzfrist-Umkehr (Quantpedia): in 20 Tagen über 10 % gefallen, 20 Tage halten.",
     lambda k: k["r20"] < -0.10),
    # ---------- ⚡ Day-Trade: Ausbrüche und Signale (Trendfolge) ----------
    ("ausbruch20", "Ausbruch 20 Tage", "kurz", ("tage", 10), "Kurs über dem Hoch der letzten 20 Tage, im Aufwärtstrend.",
     lambda k: T(k) & (k["w"] > k["hoch20"])),
    ("ausbruch55", "Ausbruch 55 Tage", "kurz", ("tage", 20), "Turtle-Regel: Kurs über dem 55-Tage-Hoch.",
     lambda k: k["w"] > k["hoch55"]),
    ("kreuz_5_20", "5 kreuzt 20", "kurz", ("tage", 10), "5-Tage-Schnitt steigt über den 20-Tage-Schnitt.",
     lambda k: _kreuzt(k["s5"], k["s20"])),
    ("ema_9_21", "EMA 9 kreuzt 21", "kurz", ("tage", 10), "Schneller Durchschnitt (9) steigt über den langsameren (21), im Aufwärtstrend.",
     lambda k: T(k) & _kreuzt(k["e9"], k["e21"])),
    ("macd_kreuz", "MACD-Kreuz", "kurz", ("tage", 10), "MACD steigt über seine Signallinie, im Aufwärtstrend.",
     lambda k: T(k) & _kreuzt(k["macd"], k["macd_sig"])),
    ("macd_null", "MACD über null", "kurz", ("tage", 10), "MACD steigt über die Nulllinie.",
     lambda k: _kreuzt(k["macd"], np.zeros(len(k["w"])))),
    ("rsi_50", "RSI kreuzt 50", "kurz", ("tage", 10), "RSI 14 steigt über 50, im Aufwärtstrend.",
     lambda k: T(k) & _kreuzt(k["rsi14"], np.full(len(k["w"]), 50.0))),
    ("hoch52_kurz", "52-Wochen-Hoch", "kurz", ("tage", 20), "Neues Jahreshoch, 20 Tage halten.",
     lambda k: k["w"] > k["hoch252"]),
    ("squeeze", "Bollinger-Squeeze", "kurz", ("tage", 20), "Bänder so eng wie seit 6 Monaten nicht und Kurs über dem 50-Tage-Schnitt.",
     lambda k: k["breite_tief"] & (k["w"] > k["s50"])),
    ("bb_oben", "Über Bollinger oben", "kurz", ("tage", 10), "Starker Schub: Kurs über dem oberen Bollinger-Band, im Aufwärtstrend.",
     lambda k: T(k) & (k["w"] > k["bb_oben"])),
    # ---------- 📅 Long-Term ----------
    ("momentum", "Momentum 12 Monate", "lang", ("rang", "mom12"), "Die stärksten 10 % der letzten 12 Monate (ohne letzten Monat), im Aufwärtstrend.",
     lambda k: T(k) & (_r(k, "mom12") >= 0.9)),
    ("momentum6", "Momentum 6 Monate", "lang", ("rang", "mom6"), "Die stärksten 10 % der letzten 6 Monate (ohne letzten Monat).",
     lambda k: T(k) & (_r(k, "mom6") >= 0.9)),
    ("momentum3", "Momentum 3 Monate", "lang", ("rang", "mom3"), "Die stärksten 10 % der letzten 3 Monate.",
     lambda k: T(k) & (_r(k, "mom3") >= 0.9)),
    ("zeitreihen_mom", "Zeitreihen-Momentum", "lang", "lang", "Quantpedia: Kurs höher als vor 12 Monaten und über dem 200-Tage-Schnitt.",
     lambda k: T(k) & (k["r252"] > 0)),
    ("dual_mom", "Dual-Momentum", "lang", ("rang", "mom12"), "Gestiegen in 12 Monaten und unter den stärksten 30 %.",
     lambda k: T(k) & (k["r252"] > 0) & (_r(k, "mom12") >= 0.7)),
    ("golden_cross", "Golden Cross", "lang", "lang", "50-Tage-Schnitt steigt über den 200-Tage-Schnitt (in den letzten 5 Tagen).",
     lambda k: (k["s50"] > k["s200"]) & (_vorher(k["s50"], 5) <= _vorher(k["s200"], 5))),
    ("s200_steigt", "Steigender 200er", "lang", "lang", "Kurs über dem 200-Tage-Schnitt und der Schnitt steigt.",
     lambda k: T(k) & k["s200_steigt"]),
    ("nahe_hoch52", "Nahe Jahreshoch", "lang", "lang", "George/Hwang: Kurs höchstens 5 % unter dem 52-Wochen-Hoch.",
     lambda k: k["w"] >= 0.95 * k["hoch252"]),
    ("tiefe_vola", "Tiefe Schwankung", "lang", "lang", "Niedrig-Volatilitäts-Effekt: die ruhigsten 20 %, im Aufwärtstrend.",
     lambda k: T(k) & (_r(k, "vol60_tief") >= 0.8)),
    ("tiefe_vola_frei", "Tiefe Schwankung ohne Trend", "lang", "lang", "Die ruhigsten 20 % der Gruppe, egal welcher Trend.",
     lambda k: _r(k, "vol60_tief") >= 0.8),
    ("glatt", "Glatter Anstieg", "lang", "lang", "Frog-in-the-pan: stark gestiegen und an vielen Tagen leicht im Plus.",
     lambda k: T(k) & (_r(k, "mom12") >= 0.7) & (_r(k, "glatt") >= 0.7)),
    ("trend_treppe", "Trend-Treppe", "lang", "lang", "Kurs über 50er, 50er über 100er, 100er über 200er.",
     lambda k: (k["w"] > k["s50"]) & (k["s50"] > k["s100"]) & (k["s100"] > k["s200"])),
    ("sharpe_mom", "Ruhiges Momentum", "lang", ("rang", "sharpe12"), "Bester Anstieg pro Schwankung (Top 10 %), im Aufwärtstrend.",
     lambda k: T(k) & (_r(k, "sharpe12") >= 0.9)),
    ("umkehr_3j", "3-Jahres-Umkehr", "lang", "lang", "Quantpedia: die schwächsten 10 % der letzten 3 Jahre, wenn sie wieder über dem 50er sind.",
     lambda k: (_r(k, "ret3j_tief") >= 0.9) & (k["w"] > k["s50"])),
    ("s200_kreuz", "Über den 200er", "lang", "lang", "Kurs steigt von unten über den 200-Tage-Schnitt.",
     lambda k: _kreuzt(k["w"], k["s200"])),
    ("ausbruch100", "Ausbruch 100 Tage", "lang", "lang", "Kurs über dem Hoch der letzten 100 Tage.",
     lambda k: k["w"] > k["hoch100"]),
    ("mom_beschl", "Momentum wird stärker", "lang", "lang", "3-Monats-Anstieg stärker als die Hälfte des 6-Monats-Anstiegs, unter den stärksten 30 %.",
     lambda k: T(k) & (k["r63"] > 0.5 * k["r126"]) & (k["r63"] > 0) & (_r(k, "mom6") >= 0.7)),
    ("wende_tief", "Wende vom Jahrestief", "lang", "lang", "In den letzten 60 Tagen am Jahrestief, jetzt über dem 50er und 10 % höher als vor einem Monat.",
     lambda k: k["tief_vor"] & (k["w"] > k["s50"]) & (k["r20"] > 0.10)),
    ("lange_ueber", "Lange über dem 200er", "lang", "lang", "Kurs seit 6 Monaten durchgehend über dem 200-Tage-Schnitt.",
     lambda k: T(k) & (k["tage_ueber_s200"] >= 0.999)),
]
NACH_ID = {s[0]: s for s in STRATEGIEN}


def signale(k):
    """{Strategie: Kaufsignal-Reihe (bool)} für einen Wert."""
    out = {}
    with np.errstate(invalid="ignore", divide="ignore"):
        for sid, _, _, _, _, f in STRATEGIEN:
            out[sid] = np.asarray(f(k), bool)
    return out


def ergebnis(k, ausstieg, signal, mit_dauer=False):
    """Wie der Handel an jedem Signaltag ausgegangen wäre (Kursänderung), NaN wenn noch offen.
    Mit mit_dauer=True zusätzlich, wie viele Tage er gedauert hätte."""
    w, n = k["w"], len(k["w"])
    erg, dauer = np.full(n, np.nan), np.full(n, np.nan)
    if isinstance(ausstieg, tuple) and ausstieg[0] == "erholung":
        s5 = k["s5"]
        for i in np.where(signal)[0]:
            for j in range(i + 1, min(i + ausstieg[1], n - 1) + 1):
                if w[j] > s5[j] or j == i + ausstieg[1]:
                    erg[i], dauer[i] = w[j] / w[i] - 1, j - i
                    break
    else:
        tage = 20 if ausstieg == "regeln" else ausstieg[1] if ausstieg[0] == "tage" else LANG_TAGE
        erg[:-tage] = w[tage:] / w[:-tage] - 1
        dauer[:-tage] = tage
    return (erg, dauer) if mit_dauer else erg


def haltetage(ausstieg):
    """Nach so vielen Börsentagen spätestens verkaufen (None = kein Zeitlimit)."""
    if isinstance(ausstieg, tuple) and ausstieg[0] in ("tage", "erholung"):
        return ausstieg[1]
    return None


def nachbarn(X, y, Q, anzahl=500, daempfung=50, max_lern=20000, seed=0):
    """Für jede Zeile in Q: Anteil der `anzahl` ähnlichsten Lerntage mit Gewinn, leicht zum Schnitt gezogen.
    Zu viele Lerntage werden zufällig auf max_lern verkleinert (gleiches Ergebnis im Mittel, viel schneller)."""
    if len(X) < anzahl * 2 or not len(Q):
        return np.full(len(Q), np.nan)
    if len(X) > max_lern:
        idx = np.random.default_rng(seed).choice(len(X), max_lern, replace=False)
        X, y = X[idx], y[idx]
    mitte, streu = X.mean(0), X.std(0) + 1e-12
    Z, Qz = (X - mitte) / streu, (Q - mitte) / streu
    zz = (Z ** 2).sum(1)
    schnitt, out = y.mean(), np.empty(len(Q))
    for a in range(0, len(Q), 200):
        d = zz[None, :] - 2 * Qz[a:a + 200] @ Z.T
        nah = np.argpartition(d, anzahl, axis=1)[:, :anzahl]
        out[a:a + 200] = (y[nah].sum(1) + daempfung * schnitt) / (anzahl + daempfung)
    return out


def merkmale(k):
    """Die 7 Kennzahlen, mit denen ähnliche Tage gesucht werden (wie bei der Trend-Chance)."""
    return np.stack([k["rsi14"] / 100, k["w"] / k["s200"] - 1, k["r20"], k["r5"], k["vol20"],
                     k["w"] / k["s50"] - 1, k["r63"]], 1)
