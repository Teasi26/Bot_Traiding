"""Rückblick-Test aller Strategien: Wie gut waren sie in den letzten ~2 Jahren (500 Tage),
wenn der Bot nur mit älteren Daten gelernt hätte? Schreibt strategien_test.json.
Aufruf: python3 strategien_test.py  (lädt 5 Jahre Kurse, dauert ein paar Minuten; handelt nie)."""
import concurrent.futures, json, os, sys, time
import numpy as np
os.environ.pop("ALPACA_KEY", None); os.environ.pop("ALPACA_SECRET", None)  # nie handeln
import strategien as S

TEST_TAGE = 500
GRENZE = 0.60  # Mindest-Chance für die Zeile "mit Chance"


def pruefen(alle, handelbar=None):
    """{Strategie: Kennzahlen des Tests} für eine Gruppe (Aktien oder Krypto).
    Gelernt wird mit allen Werten, getestet nur mit den handelbaren. Einzelne Ergebnisse werden auf
    −90 % bis +100 % begrenzt, damit fehlerhafte Kurse (z. B. bei kleinen Kryptos) den Schnitt nicht verzerren."""
    K = {s: S.kennzahlen(w) for s, w in alle.items()}
    S.raenge(K)
    tag = []
    roh = {sid: {"lF": [], "ly": [], "tF": [], "ty": [], "td": []} for sid, *_ in S.STRATEGIEN}
    for s, k in K.items():
        F = S.merkmale(k)
        okF = np.isfinite(F).all(1)
        sig = S.signale(k)
        n = len(k["w"])
        im_test = handelbar is None or s in handelbar
        if im_test:
            r1 = k["r1"][n - TEST_TAGE:]
            tag.append(np.clip(r1[np.isfinite(r1)], -0.9, 1.0))
        for sid, _, topf, ausstieg, _, _ in S.STRATEGIEN:
            erg, dauer = S.ergebnis(k, ausstieg, sig[sid], mit_dauer=True)
            frist = S.haltetage(ausstieg) or (20 if ausstieg == "regeln" else S.LANG_TAGE)
            i = np.where(okF & sig[sid] & np.isfinite(erg))[0]
            lern, test = i[i < n - TEST_TAGE - frist], i[i >= n - TEST_TAGE]
            r = roh[sid]
            r["lF"].append(F[lern]); r["ly"].append(erg[lern] > 0)
            if im_test:
                r["tF"].append(F[test]); r["ty"].append(np.clip(erg[test], -0.9, 1.0)); r["td"].append(dauer[test])
    pro_tag = float(np.concatenate(tag).mean())  # Schnitt pro Tag, wenn man einfach irgendwann kauft
    out = {}
    for sid, _, topf, ausstieg, _, _ in S.STRATEGIEN:
        r = roh[sid]
        ty = np.concatenate(r["ty"]) if r["ty"] else np.array([])
        e = {"n": int(len(ty))}
        if len(ty):
            tage = float(np.concatenate(r["td"]).mean())
            e.update(tage=round(tage, 1), basis=round(pro_tag * tage, 4),
                     treffer=round(float((ty > 0).mean()), 3), schnitt=round(float(ty.mean()), 4))
            tF = np.concatenate(r["tF"])
            if len(tF) > 3000:
                idx = np.random.default_rng(1).choice(len(tF), 3000, replace=False)
                tF, ty = tF[idx], ty[idx]
            ch = S.nachbarn(np.concatenate(r["lF"]), np.concatenate(r["ly"]), tF)
            m = ch >= GRENZE
            if m.sum():
                e.update(n_chance=int(m.sum()), treffer_chance=round(float((ty[m] > 0).mean()), 3),
                         schnitt_chance=round(float(ty[m].mean()), 4))
        # Bestanden: mindestens 30 Testfälle, öfter im Plus als nicht und im Schnitt besser als
        # einfach irgendwann gleich lange zu halten
        e["bestanden"] = bool(e["n"] >= 30 and e.get("treffer", 0) >= 0.5 and e.get("schnitt", -1) > e.get("basis", 9))
        out[sid] = e
    return out


if __name__ == "__main__":
    import handel  # nur für die Kursliste und das Laden der Kurse
    t = time.time()
    with concurrent.futures.ThreadPoolExecutor(8) as pool:
        geladen = dict(h for h in pool.map(handel.laden, handel.AKTIEN + list(handel.KRYPTO)) if h)
    aktien = {s: w for s, w in geladen.items() if not handel.ist_krypto(s)}
    krypto = {s: w for s, w in geladen.items() if handel.ist_krypto(s)}
    erg = {"stand": time.strftime("%Y-%m-%d"), "test_tage": TEST_TAGE, "grenze": GRENZE,
           "aktien": pruefen(aktien),
           "krypto": pruefen(krypto, {s for s in krypto if handel.KRYPTO[s]["handelbar"]})}
    for sid, name, topf, *_ in S.STRATEGIEN:
        a, k = erg["aktien"][sid], erg["krypto"][sid]
        erg.setdefault("standard", {})[sid] = a["bestanden"] or k["bestanden"]
    json.dump(erg, open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "strategien_test.json"), "w"), indent=1, ensure_ascii=False)
    print(f"fertig in {time.time() - t:.0f} s")
