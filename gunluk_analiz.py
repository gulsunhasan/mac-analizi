#!/usr/bin/env python3
"""
Günlük maç tarayıcı: bugünkü bütün maçları analiz eder.

Pazarlar: Maç sonucu (1X2), İlk yarı sonucu, İY/MS, Gol (Alt/Üst 1.5-2.5-3.5, KG),
          Korner (Alt/Üst 8.5-11.5)
Veri:     football-data.co.uk (geçmiş sonuçlar + fikstür + oranlar), otomatik iner.

Kullanım:
  python gunluk_analiz.py                       # bugünkü tüm maçlar
  python gunluk_analiz.py --tarih 14/11/2026    # başka bir gün
  python gunluk_analiz.py --lig T1 E0 SP1       # sadece bu ligler
  python gunluk_analiz.py --sakat sakat.csv     # sakatlık dosyası (team,sakat)
  python gunluk_analiz.py --fikstur bugun.csv   # kendi fikstürün (aşağıya bak)
  python gunluk_analiz.py --piyasa-agirlik 0.5  # model/piyasa harman ağırlığı
  python gunluk_analiz.py --degerlendir         # kayıtlı tahminler vs gerçek sonuçlar

Kendi fikstürün (--fikstur) şu sütunlarla olmalı (oran sütunları isteğe bağlı):
  Div,Date,Time,HomeTeam,AwayTeam,AvgH,AvgD,AvgA,Avg>2.5,Avg<2.5

sakat.csv örneği (0 = tam kadro, 1 = kadro çökmüş; golcü yok ~0.15):
  team,sakat
  Galatasaray,0.15
  Fenerbahce,0.05
"""
import argparse
import csv
import math
import os
import sys
import time
import urllib.request
from collections import defaultdict
from datetime import date, datetime

BASE = "https://www.football-data.co.uk"
KLASOR = "veri"
MAX_G = 8             # skor matrisi boyutu
XI = 0.0005           # zaman azalması (günlük; backtest ile seçildi)
SHRINK_K = 3.0        # az maçlı takımı lig ortalamasına çeker (backtest ile seçildi)
RHO = -0.05           # Dixon-Coles düşük skor düzeltmesi
KORNER_R = 20.0       # korner dağılımı dağılma parametresi (backtest ile seçildi)
GUC_US = 1.15         # gol gücü yayılımı (>1: güçlü-zayıf farkını açar; backtest ile seçildi)
KORNER_US = 0.6       # korner gücü yayılımı (<1: lig ortalamasına çeker; backtest ile seçildi)
KORNER_CIZGILER = [8.5, 9.5, 10.5, 11.5]

# Kupon kuralları
KUPON_MIN_ORAN = 1.60     # düşük oranlı favori koyma
KUPON_MAX_ORAN = 4.00     # uzun oranlı sürprizde model hatası baskın
KUPON_MIN_EV = 0.05       # +%5 altı fark gürültü
KUPON_MAX_EV = 0.40       # bundan yüksek EV büyük ihtimalle model hatası
KUPON_MAX_BACAK = 3       # kupon başına en fazla 3 maç
KUPON_SAYISI = 2          # en fazla 2 kupon

# Piyasa harmanı: karar ihtimali = w*model + (1-w)*piyasa (marjı temizlenmiş).
# Maç sonucu oranları iyi kalibre; harman modelin sahte "değer"ini eler.
# w henüz backtest edilmedi (geçmiş dosyalarda oran yok) -> --degerlendir ile doğrula.
PIYASA_AGIRLIK = 0.5
KAYIT = os.path.join(KLASOR, "tahmin_kaydi.csv")


# ====================== Veri indirme / okuma ======================
def sezon_kodu(bugun, geri=0):
    bas = (bugun.year if bugun.month >= 7 else bugun.year - 1) - geri
    return f"{bas % 100:02d}{(bas + 1) % 100:02d}"


def indir(url, yol, max_yas_saat=12):
    if os.path.exists(yol) and (time.time() - os.path.getmtime(yol)) < max_yas_saat * 3600:
        return True
    try:
        istek = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(istek, timeout=30) as r:
            veri = r.read()
        os.makedirs(os.path.dirname(yol) or ".", exist_ok=True)
        with open(yol, "wb") as f:
            f.write(veri)
        return True
    except Exception as e:
        print(f"  ! indirilemedi: {url} ({e})")
        return os.path.exists(yol)


def tarih_cevir(s):
    s = (s or "").strip()
    for fmt in ("%d/%m/%Y", "%d/%m/%y", "%Y-%m-%d"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            pass
    return None


def csv_oku(yol):
    with open(yol, newline="", encoding="utf-8-sig", errors="replace") as f:
        return list(csv.DictReader(f))


def sayi(r, k, tip=int):
    try:
        return tip(r[k])
    except Exception:
        return None


def maclari_ayikla(rows):
    out = []
    for r in rows:
        d = tarih_cevir(r.get("Date"))
        hg, ag = sayi(r, "FTHG"), sayi(r, "FTAG")
        if d is None or hg is None or ag is None:
            continue
        hc, ac = sayi(r, "HC"), sayi(r, "AC")
        if hc == 0 and ac == 0:  # 0-0 korner pratikte olmaz: veri eksik (MIL'de yaygın)
            hc = ac = None
        out.append(dict(d=d, h=r["HomeTeam"].strip(), a=r["AwayTeam"].strip(),
                        hg=hg, ag=ag, hthg=sayi(r, "HTHG"), htag=sayi(r, "HTAG"),
                        hc=hc, ac=ac))
    return out


def gecmis_yukle(div, bugun):
    maclar = []
    for geri in (0, 1):  # bu sezon + geçen sezon
        kod = sezon_kodu(bugun, geri)
        yol = os.path.join(KLASOR, f"{div}_{kod}.csv")
        if indir(f"{BASE}/mmz4281/{kod}/{div}.csv", yol):
            maclar += maclari_ayikla(csv_oku(yol))
    return maclar


# ====================== Güç hesabı ======================
def guclar(maclar, kh, ka, bugun, iterasyon=60, us=1.0):
    """Takımların hücum-savunma gücü, RAKİP GÜCÜNE GÖRE DÜZELTİLMİŞ (Maher tipi iteratif fit).

    Model: ev golü ~ ah * att[ev] * def[dep],  dep golü ~ aa * att[dep] * def[ev].
    Zayıf rakiplere atılan gol daha az, güçlü rakiplere atılan gol daha çok sayılır.
    Zaman ağırlıklı; az maçlı takım SHRINK_K sahte maçla 1.0'a (ortalamaya) çekilir.
    """
    veri = []
    wt = hs = as_ = 0.0
    for m in maclar:
        if m[kh] is None or m[ka] is None:
            continue
        w = math.exp(-XI * max((bugun - m["d"]).days, 0))
        veri.append((w, m["h"], m["a"], m[kh], m[ka]))
        wt += w; hs += w * m[kh]; as_ += w * m[ka]
    if wt < 20:
        return None
    ah, aa = hs / wt, as_ / wt
    ort = (ah + aa) / 2  # bir sahte maçın beklenen gol katkısı

    takimlar = {t for _, h, a, _, _ in veri for t in (h, a)}
    att = dict.fromkeys(takimlar, 1.0)
    dfn = dict.fromkeys(takimlar, 1.0)
    atilan = defaultdict(float); yenen = defaultdict(float)
    for w, h, a, gh, ga in veri:
        atilan[h] += w * gh; atilan[a] += w * ga
        yenen[h] += w * ga; yenen[a] += w * gh

    for _ in range(iterasyon):
        # hücum: atılan / (rakip savunmasına göre beklenen)
        bek = defaultdict(float)
        for w, h, a, _, _ in veri:
            bek[h] += w * ah * dfn[a]; bek[a] += w * aa * dfn[h]
        att = {t: (atilan[t] + SHRINK_K * ort) / (bek[t] + SHRINK_K * ort) for t in takimlar}
        o = sum(att.values()) / len(att)
        att = {t: v / o for t, v in att.items()}
        # savunma: yenen / (rakip hücumuna göre beklenen)
        bek = defaultdict(float)
        for w, h, a, _, _ in veri:
            bek[h] += w * aa * att[a]; bek[a] += w * ah * att[h]
        dfn = {t: (yenen[t] + SHRINK_K * ort) / (bek[t] + SHRINK_K * ort) for t in takimlar}
        o = sum(dfn.values()) / len(dfn)
        dfn = {t: v / o for t, v in dfn.items()}

    # Kalibrasyon: güç farklarını us üssüyle aç/kıs (shrinkage + Poisson farkı sıkıştırıyor)
    if us != 1.0:
        att = {t: v ** us for t, v in att.items()}
        dfn = {t: v ** us for t, v in dfn.items()}
    # Ölçek: modelin beklediği toplam ev/dep golü gerçekleşenle eşleşsin
    beh = sum(w * ah * att[h] * dfn[a] for w, h, a, _, _ in veri)
    bea = sum(w * aa * att[a] * dfn[h] for w, h, a, _, _ in veri)
    ah, aa = ah * hs / beh, aa * as_ / bea
    g ={t: dict(att_h=att[t], att_a=att[t], def_h=dfn[t], def_a=dfn[t]) for t in takimlar}
    return g, ah, aa


def iy_payi(maclar):
    """Liginde gollerin ne kadarı ilk yarıda atılıyor (ev / deplasman ayrı)."""
    ht_h = ft_h = ht_a = ft_a = 0
    for m in maclar:
        if m["hthg"] is None or m["htag"] is None:
            continue
        ht_h += m["hthg"]; ft_h += m["hg"]; ht_a += m["htag"]; ft_a += m["ag"]
    if ft_h < 50 or ft_a < 50:
        return 0.45, 0.45
    return ht_h / ft_h, ht_a / ft_a


def lig_hazirla(div, bugun):
    maclar = gecmis_yukle(div, bugun)
    gol = guclar(maclar, "hg", "ag", bugun, us=GUC_US)
    if gol is None:
        return None
    return dict(maclar=maclar, gol=gol, korner=guclar(maclar, "hc", "ac", bugun, us=KORNER_US),
                iy=iy_payi(maclar))


# ====================== Olasılık modeli ======================
def pois(k, lam):
    return math.exp(-lam) * lam ** k / math.factorial(k)


def tau(i, j, lh, la):
    if i == 0 and j == 0: return 1 - lh * la * RHO
    if i == 0 and j == 1: return 1 + lh * RHO
    if i == 1 and j == 0: return 1 + la * RHO
    if i == 1 and j == 1: return 1 - RHO
    return 1.0


def skor_matrisi(lh, la):
    m = [[pois(i, lh) * pois(j, la) * tau(i, j, lh, la) for j in range(MAX_G + 1)]
         for i in range(MAX_G + 1)]
    t = sum(map(sum, m))
    return [[x / t for x in s] for s in m]


def sonuc_olasiliklari(m):
    n = len(m)
    p1 = sum(m[i][j] for i in range(n) for j in range(n) if i > j)
    px = sum(m[i][i] for i in range(n))
    return {"1": p1, "X": px, "2": 1 - p1 - px}


def ust_olasilik(m, esik):  # toplam gol >= esik
    n = len(m)
    return sum(m[i][j] for i in range(n) for j in range(n) if i + j >= esik)


def iy_ms(lh1, la1, lh2, la2):
    """İY/MS: ilk yarı DC matrisi + bağımsız ikinci yarı Poisson."""
    m1 = skor_matrisi(lh1, la1)
    n = 6
    p2h = [pois(k, lh2) for k in range(n)]
    p2a = [pois(k, la2) for k in range(n)]
    sonuc = defaultdict(float)
    harf = lambda a, b: "1" if a > b else ("X" if a == b else "2")
    for i in range(n):
        for j in range(n):
            for k in range(n):
                for l in range(n):
                    sonuc[harf(i, j) + "/" + harf(i + k, j + l)] += m1[i][j] * p2h[k] * p2a[l]
    t = sum(sonuc.values())
    return {k: v / t for k, v in sonuc.items()}


def nb_pmf(k, mu, r):
    p = r / (r + mu)
    return math.exp(math.lgamma(k + r) - math.lgamma(r) - math.lgamma(k + 1)
                    + r * math.log(p) + k * math.log(1 - p))


def korner_ust(mu, cizgi):
    return 1 - sum(nb_pmf(k, mu, KORNER_R) for k in range(int(cizgi) + 1))


def lambdalar(lig, ev, dep, sakat_ev, sakat_dep):
    g, ah, aa = lig["gol"]
    lh = ah * g[ev]["att_h"] * g[dep]["def_a"]
    la = aa * g[dep]["att_a"] * g[ev]["def_h"]
    lh *= (1 - 0.25 * sakat_ev) * (1 + 0.20 * sakat_dep)
    la *= (1 - 0.25 * sakat_dep) * (1 + 0.20 * sakat_ev)
    kor = None
    if lig["korner"] and ev in lig["korner"][0] and dep in lig["korner"][0]:
        kg, kh, ka = lig["korner"]
        ch = kh * kg[ev]["att_h"] * kg[dep]["def_a"] * (1 - 0.10 * sakat_ev) * (1 + 0.08 * sakat_dep)
        ca = ka * kg[dep]["att_a"] * kg[ev]["def_h"] * (1 - 0.10 * sakat_dep) * (1 + 0.08 * sakat_ev)
        kor = (ch, ca)
    return lh, la, kor


# ====================== Fikstür ======================
def oran_al(r, adaylar):
    for k in adaylar:
        v = sayi(r, k, float)
        if v and v > 1.0:
            return v
    return None


def fikstur_yukle(yol, hedef, ligler):
    out = []
    for r in csv_oku(yol):
        d = tarih_cevir(r.get("Date"))
        if d != hedef:
            continue
        div = (r.get("Div") or "").strip()
        if ligler and div not in ligler:
            continue
        out.append(dict(
            div=div, saat=(r.get("Time") or "").strip(),
            ev=r["HomeTeam"].strip(), dep=r["AwayTeam"].strip(),
            oran={"1": oran_al(r, ["AvgH", "B365H", "MaxH", "PSH"]),
                  "X": oran_al(r, ["AvgD", "B365D", "MaxD", "PSD"]),
                  "2": oran_al(r, ["AvgA", "B365A", "MaxA", "PSA"]),
                  "Ust2.5": oran_al(r, ["Avg>2.5", "B365>2.5", "Max>2.5", "P>2.5"]),
                  "Alt2.5": oran_al(r, ["Avg<2.5", "B365<2.5", "Max<2.5", "P<2.5"])}))
    return out


def sakat_yukle(yol):
    if not yol:
        return {}
    s = {}
    for r in csv_oku(yol):
        try:
            s[r["team"].strip()] = min(max(float(r["sakat"]), 0.0), 1.0)
        except Exception:
            pass
    return s


# ====================== Çıktı ======================
def yz(p):
    return f"%{p * 100:4.1f}"


def adil(p):
    return f"{1 / p:5.2f}" if p > 0.001 else "  -  "


def mac_yazdir(fx, hedef_tarih, lh, la, kor, lig, aday_listesi):
    ev, dep = fx["ev"], fx["dep"]
    sh, sa = lig["iy"]
    lh1, la1 = lh * sh, la * sa
    lh2, la2 = lh - lh1, la - la1

    ms = sonuc_olasiliklari(skor_matrisi(lh, la))
    iy = sonuc_olasiliklari(skor_matrisi(lh1, la1))
    kombi = iy_ms(lh1, la1, lh2, la2)
    m = skor_matrisi(lh, la)
    ust15, ust25, ust35 = ust_olasilik(m, 2), ust_olasilik(m, 3), ust_olasilik(m, 4)
    kg = sum(m[i][j] for i in range(1, len(m)) for j in range(1, len(m)))

    print("\n" + "=" * 64)
    print(f"[{fx['div']}] {ev} - {dep}   {hedef_tarih:%d/%m} {fx['saat']}")
    baslik = f"Beklenen gol {lh:.2f}-{la:.2f} | İY {lh1:.2f}-{la1:.2f}"
    if kor:
        baslik += f" | korner {kor[0]:.1f}-{kor[1]:.1f} (toplam {sum(kor):.1f})"
    print(baslik)
    print("-" * 64)
    print("Maç sonucu : " + "   ".join(f"{k} {yz(v)} ({adil(v)})" for k, v in ms.items()))
    print("İlk yarı   : " + "   ".join(f"{k} {yz(v)} ({adil(v)})" for k, v in iy.items()))
    en_iyi = sorted(kombi.items(), key=lambda x: -x[1])[:3]
    print("İY/MS (en olası 3): " + "   ".join(f"{k} {yz(v)} ({adil(v)})" for k, v in en_iyi))
    print(f"Gol        : Üst1.5 {yz(ust15)} ({adil(ust15)})  Üst2.5 {yz(ust25)} ({adil(ust25)})  "
          f"Üst3.5 {yz(ust35)} ({adil(ust35)})")
    print(f"             Alt2.5 {yz(1 - ust25)} ({adil(1 - ust25)})  "
          f"KG Var {yz(kg)} ({adil(kg)})  KG Yok {yz(1 - kg)} ({adil(1 - kg)})")
    # Ek pazarlar
    cs = {"1X": ms["1"] + ms["X"], "12": ms["1"] + ms["2"], "X2": ms["X"] + ms["2"]}
    print("Çifte şans : " + "   ".join(f"{k} {yz(v)} ({adil(v)})" for k, v in cs.items()))
    ust05, ust45 = ust_olasilik(m, 1), ust_olasilik(m, 5)
    m_iy = skor_matrisi(lh1, la1)
    iy05, iy15 = ust_olasilik(m_iy, 1), ust_olasilik(m_iy, 2)
    print(f"Gol (ek)   : Üst0.5 {yz(ust05)} ({adil(ust05)})  Üst4.5 {yz(ust45)} ({adil(ust45)})  "
          f"İY Üst0.5 {yz(iy05)} ({adil(iy05)})  İY Üst1.5 {yz(iy15)} ({adil(iy15)})")
    n = len(m)
    ev_gol = 1 - sum(m[0][j] for j in range(n))
    dep_gol = 1 - sum(m[i][0] for i in range(n))
    print(f"Takım golü : {ev} gol atar {yz(ev_gol)} ({adil(ev_gol)})   "
          f"{dep} gol atar {yz(dep_gol)} ({adil(dep_gol)})")
    h1 = sum(m[i][j] for i in range(n) for j in range(n) if i - j >= 2)   # ev -1.5
    h2 = sum(m[i][j] for i in range(n) for j in range(n) if j - i >= 2)   # dep -1.5
    print(f"Handikap   : {ev} -1.5 {yz(h1)} ({adil(h1)})   {dep} -1.5 {yz(h2)} ({adil(h2)})")
    skorlar = sorted(((m[i][j], i, j) for i in range(n) for j in range(n)), reverse=True)[:4]
    print("Skor (en olası 4): " + "   ".join(f"{i}-{j} {yz(p)} ({adil(p)})" for p, i, j in skorlar))
    if kor:
        mu = sum(kor)
        print("Korner     : " + "   ".join(
            f"Üst{c} {yz(korner_ust(mu, c))} ({adil(korner_ust(mu, c))})" for c in KORNER_CIZGILER))
        print(f"Korner (ek): Üst7.5 {yz(korner_ust(mu, 7.5))} ({adil(korner_ust(mu, 7.5))})   "
              f"Üst12.5 {yz(korner_ust(mu, 12.5))} ({adil(korner_ust(mu, 12.5))})   "
              f"{ev} Üst4.5 {yz(korner_ust(kor[0], 4.5))}   {dep} Üst4.5 {yz(korner_ust(kor[1], 4.5))}")
        if fx["div"] == "MIL":
            print("             ! Milli maç korner tahmini backtest'te lig ortalamasını geçemedi: güvenme.")
    print("             (İY gol tahmini backtest'te zayıf: maçlar arası farkı az ayırt ediyor.)")

    # Piyasa oranı varsa: model + piyasa harmanı ile EV (sadece 1X2 ve Alt/Üst 2.5)
    modelp = {**ms, "Ust2.5": ust25, "Alt2.5": 1 - ust25}
    piyp = piyasa_olasilik(fx["oran"])
    satirlar = []
    for k, o in fx["oran"].items():
        if not o:
            continue
        pm, pp = modelp[k], piyp.get(k)
        ph = pm if pp is None else PIYASA_AGIRLIK * pm + (1 - PIYASA_AGIRLIK) * pp
        ev_ = ph * o - 1
        satirlar.append((k, o, pm, pp, ph, ev_))
        aday_listesi.append(dict(mac=f"{ev} - {dep}", div=fx["div"], ev_takim=ev, dep_takim=dep,
                                 pazar=k, oran=o, p=ph, pm=pm, pp=pp, ev=ev_))
    if satirlar:
        print("Piyasa     : " + "   ".join(
            f"{k} @{o:.2f} EV {e * 100:+.0f}%" + ("*" if e >= KUPON_MIN_EV else "")
            for k, o, pm, pp, ph, e in satirlar))
        print("  ihtimal  : " + "   ".join(
            f"{k} model %{pm * 100:.0f}" + (f" piyasa %{pp * 100:.0f} harman %{ph * 100:.0f}" if pp else "")
            for k, o, pm, pp, ph, e in satirlar))


def piyasa_olasilik(oran):
    """Oranlardan marjı temizlenmiş piyasa ihtimali (1X2 ve Alt/Üst 2.5 ayrı gruplar)."""
    out = {}
    for grup in (("1", "X", "2"), ("Ust2.5", "Alt2.5")):
        if all(oran.get(k) for k in grup):
            q = {k: 1 / oran[k] for k in grup}
            t = sum(q.values())
            out.update({k: v / t for k, v in q.items()})
    return out


# ====================== Tahmin kaydı / değerlendirme ======================
KAYIT_ALANLAR = ["tarih", "div", "ev", "dep", "pazar", "oran", "p_model", "p_piyasa"]


def kaydet(hedef, adaylar):
    """Günün tahminlerini kayda yazar (aynı gün + maç yeniden çalışınca üzerine yazar)."""
    t = f"{hedef:%d/%m/%Y}"
    yeni = [dict(tarih=t, div=a["div"], ev=a["ev_takim"], dep=a["dep_takim"], pazar=a["pazar"],
                 oran=f"{a['oran']:.2f}", p_model=f"{a['pm']:.4f}",
                 p_piyasa="" if a["pp"] is None else f"{a['pp']:.4f}") for a in adaylar]
    if not yeni:
        return
    anahtar = {(r["tarih"], r["ev"], r["dep"]) for r in yeni}
    eski = [r for r in csv_oku(KAYIT) if (r["tarih"], r["ev"], r["dep"]) not in anahtar] \
        if os.path.exists(KAYIT) else []
    os.makedirs(KLASOR, exist_ok=True)
    with open(KAYIT, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=KAYIT_ALANLAR)
        w.writeheader(); w.writerows(eski + yeni)
    print(f"\n{len(yeni)} tahmin kaydedildi -> {KAYIT}")


def degerlendir():
    """Kayıttaki tahminleri gerçek sonuçlarla karşılaştırır: model / piyasa / harman."""
    if not os.path.exists(KAYIT):
        raise SystemExit("Henüz kayıt yok. Birkaç gün normal çalıştır, sonra tekrar dene.")
    kayit = csv_oku(KAYIT)
    bugun = date.today()
    sonuc = {}
    for div in {r["div"] for r in kayit}:
        for m in gecmis_yukle(div, bugun):
            sonuc[(m["d"], m["h"], m["a"])] = (m["hg"], m["ag"])
    agirliklar = [0.0, 0.25, 0.5, 0.75, 1.0]
    for ad, grup in (("Maç sonucu (1X2)", ("1", "X", "2")), ("Alt/Üst 2.5", ("Ust2.5", "Alt2.5"))):
        ll = defaultdict(float); n = 0; mac = defaultdict(dict)
        for r in kayit:
            if r["pazar"] in grup and r["p_piyasa"]:
                mac[(r["tarih"], r["ev"], r["dep"])][r["pazar"]] = (float(r["p_model"]), float(r["p_piyasa"]))
        for (t, e, d), p in mac.items():
            sk = sonuc.get((tarih_cevir(t), e, d))
            if sk is None or len(p) != len(grup):
                continue
            hg, ag = sk
            if grup[0] == "1":
                gercek = "1" if hg > ag else ("X" if hg == ag else "2")
            else:
                gercek = "Ust2.5" if hg + ag >= 3 else "Alt2.5"
            pm, pp = p[gercek]
            for w in agirliklar:
                ll[w] -= math.log(max(w * pm + (1 - w) * pp, 1e-9))
            n += 1
        print(f"\n{ad}: sonucu belli {n} maç")
        if n == 0:
            continue
        for w in agirliklar:
            etiket = "sadece piyasa" if w == 0 else "sadece model" if w == 1 else f"harman w={w}"
            print(f"  {etiket:<15} log-loss {ll[w] / n:.4f}")
        en = min(agirliklar, key=lambda w: ll[w])
        print(f"  -> en iyi w = {en}" + ("  (az veri: en az ~200 maç bekle)" if n < 200 else ""))


def kupon_olustur(adaylar):
    """Kurallar: oran 1.60..4.00, EV +%5..+%40, maç başına tek seçim, en fazla 2 kupon x 3 bacak."""
    uygun = [a for a in adaylar
             if KUPON_MIN_ORAN <= a["oran"] <= KUPON_MAX_ORAN and KUPON_MIN_EV <= a["ev"] <= KUPON_MAX_EV]
    en_iyi = {}
    for a in uygun:  # maç başına en yüksek EV'li seçim
        if a["mac"] not in en_iyi or a["ev"] > en_iyi[a["mac"]]["ev"]:
            en_iyi[a["mac"]] = a
    sirali = sorted(en_iyi.values(), key=lambda a: -a["ev"])
    kuponlar = []
    for i in range(KUPON_SAYISI):
        bacaklar = sirali[i * KUPON_MAX_BACAK:(i + 1) * KUPON_MAX_BACAK]
        if bacaklar:
            kuponlar.append(bacaklar)
    return kuponlar


def kupon_yazdir(kuponlar):
    print("\n" + "=" * 64)
    print("KUPON ÖNERİSİ (en fazla 2 kupon, kupon başına en fazla 3 maç)")
    if not kuponlar:
        print("Kurallara uyan seçim yok (oran 1.60-4.00 ve EV +%5..+%40). Bugün kupon yapma.")
        return
    for n, kupon in enumerate(kuponlar, 1):
        oran = math.prod(b["oran"] for b in kupon)
        olas = math.prod(b["p"] for b in kupon)
        print(f"\nKupon {n}  (toplam oran {oran:.2f}, harman ihtimale göre tutma %{olas * 100:.1f})")
        for b in kupon:
            pp = f"piyasa %{b['pp'] * 100:.0f}" if b["pp"] else "piyasa  - "
            print(f"  {b['mac']:<36} {b['pazar']:<7} @{b['oran']:.2f}  "
                  f"model %{b['pm'] * 100:.0f}  {pp}  EV {b['ev'] * 100:+.0f}%")
    print("\nNot: Bu modelin hesabıdır, garanti değildir. Sakat/ceza/rotasyon bilgisini")
    print("kupondan önce kendin kontrol et; kupon başına küçük bahis yap.")


# ====================== Ana akış ======================
def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    ap = argparse.ArgumentParser(description="Günlük maç tarayıcı")
    ap.add_argument("--tarih", help="GG/AA/YYYY (varsayılan: bugün)")
    ap.add_argument("--lig", nargs="+", help="lig kodları: T1 E0 SP1 D1 I1 F1 ...")
    ap.add_argument("--fikstur", help="kendi fikstür dosyan (yoksa football-data fixtures.csv iner)")
    ap.add_argument("--sakat", help="sakatlık dosyası (team,sakat)")
    ap.add_argument("--piyasa-agirlik", type=float, default=None,
                    help="harmanda modelin ağırlığı 0..1 (varsayılan 0.5; 1 = sadece model)")
    ap.add_argument("--degerlendir", action="store_true",
                    help="kayıttaki geçmiş tahminleri sonuçlarla karşılaştır")
    a = ap.parse_args()
    global PIYASA_AGIRLIK
    if a.piyasa_agirlik is not None:
        PIYASA_AGIRLIK = min(max(a.piyasa_agirlik, 0.0), 1.0)
    if a.degerlendir:
        degerlendir()
        return

    bugun = date.today()
    hedef = tarih_cevir(a.tarih) if a.tarih else bugun
    if hedef is None:
        raise SystemExit("Tarih formatı GG/AA/YYYY olmalı.")

    fx_yol = a.fikstur
    if not fx_yol:
        fx_yol = os.path.join(KLASOR, "fixtures.csv")
        if not indir(f"{BASE}/fixtures.csv", fx_yol, max_yas_saat=3):
            raise SystemExit("Fikstür indirilemedi. --fikstur ile kendi dosyanı ver.")
    maclar = fikstur_yukle(fx_yol, hedef, a.lig)
    if not maclar:
        tarihler = sorted({tarih_cevir(r.get("Date")) for r in csv_oku(fx_yol)} - {None})
        print(f"{hedef:%d/%m/%Y} için maç bulunamadı.")
        if tarihler:
            print("Dosyadaki tarihler: " + ", ".join(f"{d:%d/%m}" for d in tarihler[:12]))
        return

    sakat = sakat_yukle(a.sakat)
    ligler, adaylar, atlanan = {}, [], []
    print(f"{hedef:%d/%m/%Y} - {len(maclar)} maç analiz ediliyor...")
    for fx in sorted(maclar, key=lambda x: (x["div"], x["saat"])):
        div = fx["div"]
        if div not in ligler:
            print(f"  {div} geçmiş verisi yükleniyor...")
            ligler[div] = lig_hazirla(div, bugun)
        lig = ligler[div]
        if not lig:
            atlanan.append(f"{fx['ev']} - {fx['dep']} ({div}: yeterli veri yok)")
            continue
        g = lig["gol"][0]
        eksik = [t for t in (fx["ev"], fx["dep"]) if t not in g]
        if eksik:
            atlanan.append(f"{fx['ev']} - {fx['dep']} (veride yok: {', '.join(eksik)})")
            continue
        lh, la, kor = lambdalar(lig, fx["ev"], fx["dep"],
                                sakat.get(fx["ev"], 0.0), sakat.get(fx["dep"], 0.0))
        mac_yazdir(fx, hedef, lh, la, kor, lig, adaylar)

    if atlanan:
        print("\nAtlanan maçlar:")
        for s in atlanan:
            print("  - " + s)
    kupon_yazdir(kupon_olustur(adaylar))
    kaydet(hedef, adaylar)


if __name__ == "__main__":
    main()
