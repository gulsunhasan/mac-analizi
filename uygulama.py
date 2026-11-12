#!/usr/bin/env python3
"""
Maç Analizi uygulaması: tarayıcıda açılan yerel arayüz.

  python3 uygulama.py            # sunucuyu başlatır ve tarayıcıyı açar
  python3 uygulama.py --sessiz   # tarayıcı açmadan başlatır

Fikstür, sonuç ve oranlar yarım saatte bir, canlı skor ve kadrolar 30 saniyede bir yenilenir. Haberler Google Haberler'den gelir.
Sayfa kapalıyken 15 dakika istek gelmezse sunucu kendini kapatır.
"""
import contextlib
import io
import json
import os
import sys
import threading
import time
import urllib.parse
import urllib.request
import webbrowser
import xml.etree.ElementTree as ET
from datetime import date, datetime
from email.utils import parsedate_to_datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

KOK = os.path.dirname(os.path.abspath(__file__))
os.chdir(KOK)
sys.path.insert(0, KOK)

import gunluk_analiz as g  # noqa: E402
import veri_indir  # noqa: E402

# Site modu (internet sunucusunda): SITE_MODU=1 ortam değişkeniyle açılır. Dışarıdan erişime açılır,
# kendiliğinden kapanmaz, veriyi yarım saatte bir kendi yeniler ve ziyaretçiler güncelleme başlatamaz.
SITE = os.environ.get("SITE_MODU") == "1" or bool(os.environ.get("RENDER"))   # Render sunucusunda kendiliğinden açılır
PORT = int(os.environ.get("PORT", "8765"))
SUNUCU_ADRESI = os.environ.get("BAGLAN") or ("0.0.0.0" if SITE else "127.0.0.1")   # BAGLAN: tünel arkasında yalnızca bu bilgisayarı dinle
ADRES = f"http://127.0.0.1:{PORT}/"
UYGULAMA_DOSYALARI = {   # adres: (dosya, içerik türü)
    "/manifest.webmanifest": ("manifest.webmanifest", "application/manifest+json"),
    "/sw.js": ("sw.js", "text/javascript; charset=utf-8"),
    "/ikon-192.png": ("ikon-192.png", "image/png"),
    "/ikon-512.png": ("ikon-512.png", "image/png"),
    "/apple-touch-icon.png": ("apple-touch-icon.png", "image/png"),
}
YORUM_SINIRI = (5, 600)   # aynı adresten 10 dakikada en fazla 5 yorum
yorum_gecmisi = {}
asistan_gecmisi = {}
VERI_ESKIME_SAAT = 0.5   # fikstür, sonuç ve oranlar yarım saatte bir yenilenir (canlı skor ve kadro 30 sn)
BOSTA_KAPAN_SN = 15 * 60
FIKSTUR = os.path.join(KOK, "veri", "fixtures.csv")
KABA_LIGLER = {"MIL", "CL", "EL", "ECL"}   # az maç / dengesiz rakip: tahmin kaba, kupona alınmaz

# Analiz sırasında engelli siteye gitmeyi deneme; veri_indir'in yazdığı dosyaları kullan.
g.indir = lambda url, yol, max_yas_saat=12: os.path.exists(yol)

LIG_ADI = {k: v[1] for k, v in veri_indir.LIGLER.items()}
LIG_ADI[veri_indir.MILLI_KOD] = "Milli maçlar"

kilit = threading.Lock()
durum = {"guncelleniyor": False, "mesaj": "", "hata": ""}
son_istek = time.time()
lig_onbellek = {}     # div -> (veri zamanı, lig)
haber_onbellek = {}   # (sorgu, gün) -> liste


# ====================== Analiz ======================
def veri_zamani():
    return os.path.getmtime(FIKSTUR) if os.path.exists(FIKSTUR) else 0


def lig_al(div, bugun):
    vz = veri_zamani()
    kayit = lig_onbellek.get(div)
    if not kayit or kayit[0] != vz:
        kayit = (vz, g.lig_hazirla(div, bugun))
        lig_onbellek[div] = kayit
    return kayit[1]


def mac_hesapla(fx, lh, la, kor, lig):
    sh, sa = lig["iy"]
    lh1, la1 = lh * sh, la * sa
    m = g.skor_matrisi(lh, la)
    m_iy = g.skor_matrisi(lh1, la1)
    n = len(m)
    ms = g.sonuc_olasiliklari(m)
    ust = lambda mat, esik: g.ust_olasilik(mat, esik)
    kombi = sorted(g.iy_ms(lh1, la1, lh - lh1, la - la1).items(), key=lambda x: -x[1])[:4]
    skorlar = sorted(((m[i][j], i, j) for i in range(n) for j in range(n)), reverse=True)[:5]
    sonuc = dict(
        div=fx["div"], lig=LIG_ADI.get(fx["div"], fx["div"]), saat=fx["saat"], ev=fx["ev"], dep=fx["dep"],
        lh=lh, la=la, ms=ms, iy=g.sonuc_olasiliklari(m_iy), iyms=kombi,
        gol={"Üst 0.5": ust(m, 1), "Üst 1.5": ust(m, 2), "Üst 2.5": ust(m, 3), "Alt 2.5": 1 - ust(m, 3),
             "Üst 3.5": ust(m, 4), "Üst 4.5": ust(m, 5),
             "KG Var": sum(m[i][j] for i in range(1, n) for j in range(1, n)),
             "İY Üst 0.5": ust(m_iy, 1), "İY Üst 1.5": ust(m_iy, 2)},
        cs={"1X": ms["1"] + ms["X"], "12": ms["1"] + ms["2"], "X2": ms["X"] + ms["2"]},
        takim={f"{fx['ev']} gol atar": 1 - sum(m[0][j] for j in range(n)),
               f"{fx['dep']} gol atar": 1 - sum(m[i][0] for i in range(n)),
               f"{fx['ev']} -1.5": sum(m[i][j] for i in range(n) for j in range(n) if i - j >= 2),
               f"{fx['dep']} -1.5": sum(m[i][j] for i in range(n) for j in range(n) if j - i >= 2)},
        skor=[[f"{i}-{j}", p] for p, i, j in skorlar],
        korner=None, kor=None, piyasa=[], sapma=False)
    if kor:
        mu = sum(kor)
        sonuc["kor"] = [kor[0], kor[1]]
        sonuc["korner"] = {f"Üst {c}": g.korner_ust(mu, c) for c in (7.5, 8.5, 9.5, 10.5, 11.5, 12.5)}
        sonuc["korner"][f"{fx['ev']} Üst 4.5"] = g.korner_ust(kor[0], 4.5)
        sonuc["korner"][f"{fx['dep']} Üst 4.5"] = g.korner_ust(kor[1], 4.5)

    modelp = {**ms, "Ust2.5": ust(m, 3), "Alt2.5": 1 - ust(m, 3)}
    adaylar = []
    for k, o in fx["oran"].items():
        if o:
            ev_ = modelp[k] * o - 1
            sonuc["piyasa"].append(dict(k=k, oran=o, p=modelp[k], ev=ev_))
            adaylar.append(dict(mac=f"{fx['ev']} - {fx['dep']}", pazar=k, oran=o, p=modelp[k], ev=ev_))
    o1, ox, o2 = (fx["oran"].get(k) for k in ("1", "X", "2"))
    if o1 and ox and o2:  # piyasanın (marjı ayıklanmış) olasılığı ile model arasındaki en büyük fark
        t = 1 / o1 + 1 / ox + 1 / o2
        fark = max(abs(ms[k] - (1 / o) / t) for k, o in (("1", o1), ("X", ox), ("2", o2)))
        sonuc["sapma"] = fark > 0.15
    return sonuc, adaylar


fikstur_onbellek = {}


def fikstur_bilgi():
    """Fikstür dosyasının ayrıştırılmış hali (veri değişene kadar önbellekte)."""
    vz = veri_zamani()
    if fikstur_onbellek.get("vz") == vz:
        return fikstur_onbellek
    satirlar = g.csv_oku(FIKSTUR) if os.path.exists(FIKSTUR) else []
    ilk_mac, kimlik, eid_ile = {}, {}, {}
    for r in satirlar:
        d = g.tarih_cevir(r.get("Date"))
        if not d:
            continue
        div, ev, dep = (r.get("Div") or "").strip(), (r.get("HomeTeam") or "").strip(), (r.get("AwayTeam") or "").strip()
        for t in (ev, dep):   # (lig, takım) -> fikstürdeki ilk maç günü; ceza yalnızca o maça uygulanır
            if (div, t) not in ilk_mac or d < ilk_mac[(div, t)]:
                ilk_mac[(div, t)] = d
        eid = (r.get("EventId") or "").strip()
        if eid:
            kimlik[(div, ev, dep, d)] = (eid, (r.get("Espn") or "").strip())
            eid_ile[eid] = (div, ev, dep, d)
    fikstur_onbellek.clear()
    fikstur_onbellek.update(vz=vz, satirlar=satirlar, ilk_mac=ilk_mac, kimlik=kimlik, eid_ile=eid_ile,
                            gunler=sorted({k[3] for k in kimlik} | set(ilk_mac.values())))
    return fikstur_onbellek


def mac_analiz(fx, hedef, bugun, kadro_etki=None):
    """Tek maçın bütün hesabı. kadro_etki verilirse (takım -> 0..0.5) ceza etkisinin yerine kullanılır.
    Dönen: (sonuç, kupon adayları) ya da (None, atlanma nedeni)."""
    fb = fikstur_bilgi()
    lig = lig_al(fx["div"], bugun)
    if not lig:
        return None, "yeterli veri yok"
    eksik = [t for t in (fx["ev"], fx["dep"]) if t not in lig["gol"][0]]
    if eksik:
        return None, f"geçmiş maçı yok: {', '.join(eksik)}"
    try:
        ek = ek_al(fx["div"], bugun)
    except Exception:
        ek = None
    ceza, etki = {}, {}
    for t in (fx["ev"], fx["dep"]):
        ceza[t] = ek["cezali"].get(t, []) if ek and fb["ilk_mac"].get((fx["div"], t)) == hedef else []
        etki[t] = ceza_etkisi(ek, t, ceza[t]) if ek else 0.0
        if kadro_etki is not None:
            etki[t] = kadro_etki.get(t, 0.0)
    lh, la, kor = g.lambdalar(lig, fx["ev"], fx["dep"], etki[fx["ev"]], etki[fx["dep"]])
    sonuc, ad = mac_hesapla(fx, lh, la, kor, lig)
    if ek:
        sonuc.update(ek_bilgi(ek, fx, ceza, etki))
        if fx["div"] == veri_indir.MILLI_KOD:
            sonuc["sira"] = {}   # milli maçlar tek bir lig değil; sıra ve puan anlamsız
        if sonuc.get("kart_b") and sum(sonuc["kart_b"]) < 1.5:
            sonuc["kart"] = sonuc["kart_b"] = None   # kart verisi eksik tutulan maçlar (ör. hazırlık maçları)
    eid, espn = fb["kimlik"].get((fx["div"], fx["ev"], fx["dep"], hedef), ("", ""))
    sonuc.update(kaba=fx["div"] in KABA_LIGLER, eid=eid, espn=espn, sh=lig["iy"][0], sa=lig["iy"][1],
                 baslama=f"{hedef.isoformat()}T{fx['saat'] or '00:00'}")
    return sonuc, ad


analiz_onbellek = {}
OZET_ALANLARI = ("div", "lig", "saat", "ev", "dep", "lh", "la", "ms", "sapma", "kaba", "eid", "espn", "sh", "sa",
                 "baslama", "form", "sira", "cezali", "kart_b", "kor")


def ozetle(m):
    """Maç listesi için küçük özet: kartta görünen alanlar. Tablolar maç açılınca /api/mac ile gelir."""
    o = {k: m[k] for k in OZET_ALANLARI if k in m}
    o["skor"] = m["skor"][:1]
    o["gol"] = {k: m["gol"][k] for k in ("Üst 2.5", "Alt 2.5", "KG Var")}
    o["korner"] = {"Üst 9.5": m["korner"]["Üst 9.5"]} if m.get("korner") else None
    o["kart"] = {"Üst 4.5": m["kart"]["Üst 4.5"]} if m.get("kart") else None
    return o


def analiz_ozet(hedef):
    tam = analiz(hedef)
    return dict(tam, maclar=[ozetle(m) for m in tam["maclar"]])


def tek_mac(hedef, div, ev, dep):
    for m in analiz(hedef)["maclar"]:
        if (m["div"], m["ev"], m["dep"]) == (div, ev, dep):
            return m
    return None


def analiz(hedef):
    anahtar = (hedef, veri_zamani(), date.today())
    if anahtar in analiz_onbellek:
        return analiz_onbellek[anahtar]
    sonuc = analiz_hesapla(hedef)
    if len(analiz_onbellek) > 40:
        analiz_onbellek.clear()
    analiz_onbellek[anahtar] = sonuc
    return sonuc


def analiz_hesapla(hedef):
    bugun = date.today()
    fb = fikstur_bilgi()
    if not fb["satirlar"]:
        return dict(tarih=hedef.isoformat(), maclar=[], atlanan=[], kuponlar=[], gunler=[], veri_zamani=0)
    maclar, atlanan, adaylar = [], [], []
    for fx in sorted(g.fikstur_yukle(FIKSTUR, hedef, None), key=lambda x: (x["saat"], x["div"])):
        sonuc, ad = mac_analiz(fx, hedef, bugun)
        if sonuc is None:
            atlanan.append(f"{fx['ev']} - {fx['dep']} ({ad})")
            continue
        maclar.append(sonuc)
        if not sonuc["sapma"] and not sonuc["kaba"]:   # güvenilmez tahminleri kupona koyma
            adaylar += ad
    return dict(tarih=hedef.isoformat(), maclar=maclar, atlanan=atlanan,
                kuponlar=g.kupon_olustur(adaylar), gunler=[d.isoformat() for d in fb["gunler"][:60]],
                veri_zamani=veri_zamani())


# ====================== Ligler sekmesi ======================
# Puan durumu bölgeleri: (ilk sıra, son sıra, kod). Eksi sayılar sondan sayar (-1 = son sıra).
# Yaklaşık kurallardır: kupa şampiyonları ve ülke puanı Avrupa kontenjanlarını değiştirebilir.
BOLGE_ADI = {"sl": "Şampiyonlar Ligi", "sle": "Şampiyonlar Ligi elemesi", "al": "Avrupa Ligi",
             "kl": "Konferans Ligi", "yuk": "Üst lige yükselme", "po": "Play-off",
             "tur": "Son 16'ya doğrudan", "baraj": "Düşmeme barajı", "dus": "Küme düşme", "elen": "Elenir"}
BOLGELER = {
    "T1": [(1, 1, "sl"), (2, 2, "sle"), (3, 3, "al"), (4, 4, "kl"), (-3, -1, "dus")],
    "E0": [(1, 4, "sl"), (5, 5, "al"), (6, 6, "kl"), (-3, -1, "dus")],
    "E1": [(1, 2, "yuk"), (3, 6, "po"), (-3, -1, "dus")],
    "SP1": [(1, 4, "sl"), (5, 6, "al"), (7, 7, "kl"), (-3, -1, "dus")],
    "D1": [(1, 4, "sl"), (5, 5, "al"), (6, 6, "kl"), (-3, -3, "baraj"), (-2, -1, "dus")],
    "I1": [(1, 4, "sl"), (5, 5, "al"), (6, 6, "kl"), (-3, -1, "dus")],
    "F1": [(1, 3, "sl"), (4, 4, "sle"), (5, 5, "al"), (6, 6, "kl"), (-3, -3, "baraj"), (-2, -1, "dus")],
    "N1": [(1, 2, "sl"), (3, 3, "sle"), (4, 4, "al"), (5, 8, "po"), (-3, -3, "baraj"), (-2, -1, "dus")],
    "P1": [(1, 2, "sl"), (3, 3, "sle"), (4, 4, "al"), (5, 5, "kl"), (-3, -3, "baraj"), (-2, -1, "dus")],
    "B1": [(1, 6, "po"), (-4, -1, "dus")],
    "SC0": [(1, 1, "sle"), (2, 2, "al"), (3, 4, "kl"), (-2, -2, "baraj"), (-1, -1, "dus")],
    "G1": [(1, 4, "po"), (-2, -1, "dus")],
    "CL": [(1, 8, "tur"), (9, 24, "po"), (25, 36, "elen")],
    "EL": [(1, 8, "tur"), (9, 24, "po"), (25, 36, "elen")],
    "ECL": [(1, 8, "tur"), (9, 24, "po"), (25, 36, "elen")],
}
BOLGE_NOTU = {"B1": "Belçika'da ilk 6 şampiyonluk play-off'una kalır; son 4 düşmeme play-off'u oynar.",
              "G1": "Yunanistan'da ilk 4 şampiyonluk play-off'una kalır; alt grup düşmeme için oynar.",
              "SC0": "İskoçya'da 33. haftadan sonra lig ilk 6 ve son 6 olarak ikiye ayrılır.",
              "E1": "3.-6. sıradakiler yükselme play-off'u oynar."}


def bolge_bul(div, sira, takim_sayisi):
    for ilk, son, kod in BOLGELER.get(div, []):
        a = ilk if ilk > 0 else takim_sayisi + 1 + ilk
        b = son if son > 0 else takim_sayisi + 1 + son
        if a <= sira <= b:
            return kod
    return ""


def ligler():
    """Fikstürde yaklaşan maçı olan ligler: maç sayısı ve ilk maç günü."""
    bugun, sayim = date.today(), {}
    for (div, ev, dep, d) in fikstur_bilgi()["kimlik"]:
        if d >= bugun:
            k = sayim.setdefault(div, [0, d])
            k[0] += 1
            k[1] = min(k[1], d)
    return [dict(div=div, lig=LIG_ADI[div], sayi=sayim[div][0], ilk=sayim[div][1].isoformat())
            for div in LIG_ADI if div in sayim]


def lig_sayfa(div, adet=30):
    """Bir ligin yaklaşan maçları (tahminleriyle) ve puan durumu."""
    if div not in LIG_ADI:
        return dict(div=div, lig=div, maclar=[], tablo=[])
    bugun = date.today()
    gunler = sorted({d for (dv, ev, dep, d) in fikstur_bilgi()["kimlik"] if dv == div and d >= bugun})
    maclar = []
    for d in gunler:
        for fx in sorted(g.fikstur_yukle(FIKSTUR, d, [div]), key=lambda x: x["saat"]):
            sonuc, _ = mac_analiz(fx, d, bugun)
            kayit = dict(tarih=d.isoformat(), saat=fx["saat"], ev=fx["ev"], dep=fx["dep"], div=div)
            if sonuc:
                kayit.update(ms=sonuc["ms"], skor=sonuc["skor"][0][0], kaba=sonuc["kaba"],
                             cezali=sum(len(v) for v in sonuc.get("cezali", {}).values()))
            maclar.append(kayit)
        if len(maclar) >= adet:
            break
    tablo = []
    if div != veri_indir.MILLI_KOD:   # milli maçlar tek bir lig değil; puan durumu anlamsız
        try:
            ek = ek_al(div, bugun)
            for t, k in sorted(ek["tablo"].items(), key=lambda x: x[1].get("sira", 999)):
                tablo.append(dict(sira=k["sira"], takim=t, o=k["o"], ag=k["ag"], yg=k["yg"], p=k["p"],
                                  form=ek["form"].get(t, [])[-5:],
                                  bolge=bolge_bul(div, k["sira"], len(ek["tablo"]))))
        except Exception:
            pass
    kullanilan = []
    for t in tablo:
        if t["bolge"] and t["bolge"] not in kullanilan:
            kullanilan.append(t["bolge"])
    return dict(div=div, lig=LIG_ADI[div], maclar=maclar, tablo=tablo,
                bolgeler=[[k, BOLGE_ADI[k]] for k in kullanilan], bolge_notu=BOLGE_NOTU.get(div, ""))


# ====================== Takım sayfası ve yorum akışı ======================
def takim_sayfa(ad, div=""):
    """Bir takımın bu sezonki maçları, iç saha/deplasman dengesi, golcüleri, kart durumu ve sıradaki maçları."""
    bugun, fb = date.today(), fikstur_bilgi()
    gelecek = sorted((d, dv, ev, dep) for (dv, ev, dep, d) in fb["kimlik"] if ad in (ev, dep) and d >= bugun)
    ligler = [dv for _, dv, _, _ in gelecek]
    if div not in LIG_ADI or div not in ligler:
        div = next((dv for dv in ligler if dv not in KABA_LIGLER), ligler[0] if ligler else "")
    if not div:
        return dict(ad=ad, bulundu=False)
    ek = ek_al(div, bugun)
    bu = sorted((m for m in ek["maclar"] if m["bu"] and ad in (m["h"], m["a"])), key=lambda m: m["d"], reverse=True)
    son, denge = [], {"ic": dict(g=0, b=0, m=0, ag=0, yg=0), "dis": dict(g=0, b=0, m=0, ag=0, yg=0)}
    for m in bu:
        ic = m["h"] == ad
        atilan, yenen = (m["hg"], m["ag"]) if ic else (m["ag"], m["hg"])
        harf = "g" if atilan > yenen else ("b" if atilan == yenen else "m")
        k = denge["ic" if ic else "dis"]
        k[harf] += 1; k["ag"] += atilan; k["yg"] += yenen
        if len(son) < 10:
            son.append(dict(tarih=m["d"].isoformat(), ev=m["h"], dep=m["a"], skor=f"{m['hg']}-{m['ag']}", sonuc=harf.upper()))
    sira = ek["tablo"].get(ad)
    yaklasan = []
    for d, dv, ev, dep in gelecek[:6]:
        kayit = dict(tarih=d.isoformat(), div=dv, lig=LIG_ADI.get(dv, dv), ev=ev, dep=dep, saat="")
        for fx in g.fikstur_yukle(FIKSTUR, d, [dv]):
            if fx["ev"] == ev and fx["dep"] == dep:
                kayit["saat"] = fx["saat"]
                sonuc, _ = mac_analiz(fx, d, bugun)
                if sonuc:
                    kayit.update(ms=sonuc["ms"], skor=sonuc["skor"][0][0])
        yaklasan.append(kayit)
    golculer = sorted(ek["gol"].get(ad, {}).items(), key=lambda x: -x[1])[:8]
    return dict(ad=ad, bulundu=True, div=div, lig=LIG_ADI[div], diger_ligler=sorted({dv for dv in ligler if dv != div}),
                sira=dict(sira, bolge=bolge_bul(div, sira["sira"], len(ek["tablo"]))) if sira and div != veri_indir.MILLI_KOD else None,
                form=ek["form"].get(ad, [])[-5:], son=son, denge=denge,
                golculer=[[o[1], n] for o, n in golculer], sinirda=ek["sinirda"].get(ad, []),
                cezali=ek["cezali"].get(ad, []), sinir=ek["sinir"], yaklasan=yaklasan)


def yorum_akisi(adet=60):
    """Bütün maçlardaki yorumlar, en yeniden eskiye."""
    bugun, hepsi = date.today().isoformat(), []
    for mac, liste in yorumlari_oku().items():
        parca = mac.split("|")
        if len(parca) != 4:
            continue
        for y in liste:
            hepsi.append(dict(zaman=y.get("zaman", 0), ad=y.get("ad", ""), metin=y.get("metin", ""),
                              tarih=parca[0], div=parca[1], ev=parca[2], dep=parca[3], acik=parca[0] >= bugun))
    hepsi.sort(key=lambda y: -y["zaman"])
    return hepsi[:adet]


# ====================== Tahmin karnesi ======================
karne_onbellek = {}


def karne(gun=30):
    """Son `gun` günde oynanan lig maçlarında modelin ne kadar tuttuğu.
    Her maç, yalnızca o maçtan ÖNCEKİ sonuçlarla yeniden tahmin edilir (geriye dönük hesap)."""
    vz = veri_zamani()
    if karne_onbellek.get("vz") == vz:
        return karne_onbellek["sonuc"]
    bugun = date.today()
    sinir = date.fromordinal(bugun.toordinal() - gun)
    us = getattr(g, "GUC_US", 1.0)
    satirlar, lig_ozet = [], []
    for div in LIG_ADI:
        if div in KABA_LIGLER:
            continue
        lig = lig_al(div, bugun)
        if not lig:
            continue
        gecmis = sorted(lig["maclar"], key=lambda m: m["d"])
        fitler, n, dogru = {}, 0, 0
        for m in gecmis:
            if m["d"] < sinir or m["d"] >= bugun:
                continue
            if m["d"] not in fitler:
                onceki = [x for x in gecmis if x["d"] < m["d"]]
                try:
                    fitler[m["d"]] = g.guclar(onceki, "hg", "ag", m["d"], us=us)
                except TypeError:
                    fitler[m["d"]] = g.guclar(onceki, "hg", "ag", m["d"])
            fit = fitler[m["d"]]
            if not fit or m["h"] not in fit[0] or m["a"] not in fit[0]:
                continue
            lh, la, _ = g.lambdalar(dict(lig, gol=fit, korner=None), m["h"], m["a"], 0.0, 0.0)
            mat = g.skor_matrisi(lh, la)
            ms = g.sonuc_olasiliklari(mat)
            favori = max(ms, key=ms.get)
            sonuc = "1" if m["hg"] > m["ag"] else ("X" if m["hg"] == m["ag"] else "2")
            ust = g.ust_olasilik(mat, 3)
            satirlar.append(dict(tarih=m["d"].isoformat(), div=div, lig=LIG_ADI[div], ev=m["h"], dep=m["a"],
                                 skor=f"{m['hg']}-{m['ag']}", ms=ms, favori=favori, guven=ms[favori],
                                 tuttu=favori == sonuc, ust=ust,
                                 ust_tuttu=(ust >= 0.5) == (m["hg"] + m["ag"] >= 3)))
            n += 1
            dogru += favori == sonuc
        if n:
            lig_ozet.append(dict(div=div, lig=LIG_ADI[div], n=n, isabet=dogru / n))
    toplam = len(satirlar)
    dilimler = []
    for ad, alt, ust_ in (("Model çok emin (%60 ve üstü)", 0.60, 2), ("Model orta emin (%45–60)", 0.45, 0.60),
                          ("Model kararsız (%45 altı)", 0, 0.45)):
        grup = [x for x in satirlar if alt <= x["guven"] < ust_]
        if grup:
            dilimler.append(dict(ad=ad, n=len(grup), isabet=sum(x["tuttu"] for x in grup) / len(grup),
                                 beklenen=sum(x["guven"] for x in grup) / len(grup)))
    satirlar.sort(key=lambda x: x["tarih"], reverse=True)
    sonuc = dict(gun=gun, n=toplam,
                 isabet=sum(x["tuttu"] for x in satirlar) / toplam if toplam else 0,
                 ust_isabet=sum(x["ust_tuttu"] for x in satirlar) / toplam if toplam else 0,
                 dilimler=dilimler, ligler=sorted(lig_ozet, key=lambda x: -x["isabet"]), maclar=satirlar[:80])
    karne_onbellek.update(vz=vz, sonuc=sonuc)
    return sonuc


# ====================== Canlı skor, kadro, simülasyon ======================
ESPN = "https://site.api.espn.com/apis/site/v2/sports/soccer"
canli_onbellek = {}    # (espn lig, gün) -> (zaman, {eid: durum})
kadro_onbellek = {}    # eid -> (zaman, özet)
ag_kilidi = threading.Lock()


OLAY_ADI = {"Goal": "Gol", "Goal - Header": "Gol (kafa)", "Goal - Free-kick": "Gol (serbest vuruş)",
            "Penalty - Scored": "Gol (penaltı)", "Own Goal": "Kendi kalesine gol", "Penalty - Missed": "Penaltı kaçtı",
            "Penalty - Saved": "Penaltı kurtarıldı", "Yellow Card": "Sarı kart", "Red Card": "Kırmızı kart",
            "Substitution": "Oyuncu değişikliği", "Kickoff": "Maç başladı", "Halftime": "İlk yarı bitti",
            "Start 2nd Half": "İkinci yarı başladı", "End Regular Time": "Maç bitti", "VAR - Goal Disallowed": "VAR: gol iptal"}
ISTATISTIK_ADI = [("possessionPct", "Topa sahip olma %"), ("totalShots", "Şut"), ("shotsOnTarget", "İsabetli şut"),
                  ("wonCorners", "Korner"), ("foulsCommitted", "Faul"), ("yellowCards", "Sarı kart"),
                  ("redCards", "Kırmızı kart"), ("offsides", "Ofsayt"), ("saves", "Kurtarış"),
                  ("totalPasses", "Pas"), ("accuratePasses", "İsabetli pas")]
ozet_onbellek = {}   # eid -> (zaman, ESPN maç özeti)


def ozet_al(eid, espn, omur):
    kayit, simdi = ozet_onbellek.get(eid), time.time()
    if kayit and simdi - kayit[0] < omur:
        return kayit[1]
    ozet = espn_al(f"{espn}/summary?event={eid}")
    ozet_onbellek[eid] = (simdi, ozet)
    if len(ozet_onbellek) > 200:
        for k in sorted(ozet_onbellek, key=lambda k: ozet_onbellek[k][0])[:100]:
            ozet_onbellek.pop(k, None)
    return ozet


def mac_detay(eid):
    """Oynanan ya da bitmiş maçın anlatımı, istatistikleri ve oyuncu değişiklikleriyle kadroları."""
    fb = fikstur_bilgi()
    if eid not in fb["eid_ile"]:
        return dict(anlatim=[], istatistik=[], kadro={})
    div, ev, dep, d = fb["eid_ile"][eid]
    ozet = ozet_al(eid, fb["kimlik"][(div, ev, dep, d)][1], 20)
    anlatim = []
    for c in ozet.get("commentary") or []:
        oyun = c.get("play") or {}
        tip = (oyun.get("type") or {}).get("text") or ""
        kisiler = [((k.get("athlete") or {}).get("displayName") or "") for k in oyun.get("participants") or []]
        takim = (oyun.get("team") or {}).get("displayName") or ""
        if tip in OLAY_ADI:
            metin = OLAY_ADI[tip]
            if kisiler:
                metin += " — " + (" ⇄ ".join(k for k in kisiler if k) if tip == "Substitution" else kisiler[0])
            if takim:
                metin += f" ({takim})"
        else:
            metin = c.get("text") or ""   # ayrıntılı anlatım ESPN'den İngilizce gelir
        if metin:
            anlatim.append(dict(dk=(c.get("time") or {}).get("displayValue") or "", metin=metin,
                                onemli=tip in OLAY_ADI and tip != "Substitution"))
    istatistik = []
    takimlar = (ozet.get("boxscore") or {}).get("teams") or []
    if len(takimlar) == 2:
        sirali = sorted(takimlar, key=lambda t: 0 if t.get("homeAway") == "home" else 1)
        degerler = [{x.get("name"): x.get("displayValue") for x in t.get("statistics") or []} for t in sirali]
        for anahtar, ad in ISTATISTIK_ADI:
            if anahtar in degerler[0] and anahtar in degerler[1]:
                istatistik.append([ad, degerler[0][anahtar], degerler[1][anahtar]])
    if all(str(x) in ("0", "0.0", "") for _, a, b in istatistik for x in (a, b)):
        istatistik = []   # ESPN bu maç için istatistik tutmuyor; sıfır dolu tablo gösterme
    kadro = {}
    for r in ozet.get("rosters") or []:
        ad = ev if r.get("homeAway") == "home" else dep
        liste = r.get("roster") or []
        isim = lambda o: (o.get("athlete") or {}).get("displayName") or ""
        kadro[ad] = dict(dizilis=r.get("formation") or "",
                         ilk11=[dict(ad=isim(o), cikti=bool(o.get("subbedOut"))) for o in liste if o.get("starter")],
                         giren=[isim(o) for o in liste if o.get("subbedIn")])
    return dict(anlatim=anlatim[::-1], istatistik=istatistik, kadro=kadro)


def espn_al(yol):
    istek = urllib.request.Request(f"{ESPN}/{yol}", headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(istek, timeout=20, context=veri_indir.SSL_BAGLAM) as r:
        veri = r.read()
    if veri[:2] == b"\x1f\x8b":
        import gzip
        veri = gzip.decompress(veri)
    return json.loads(veri)


def canli_lig(espn, gun):
    anahtar, simdi = (espn, gun), time.time()
    kayit = canli_onbellek.get(anahtar)
    if kayit and simdi - kayit[0] < 25:
        return kayit[1]
    sonuc = {}
    try:
        for e in espn_al(f"{espn}/scoreboard?dates={gun}&limit=300").get("events", []):
            y = e["competitions"][0]
            d = e["status"]["type"]
            ev = next(t for t in y["competitors"] if t["homeAway"] == "home")
            dep = next(t for t in y["competitors"] if t["homeAway"] == "away")
            kirmizi = {ev["team"]["id"]: 0, dep["team"]["id"]: 0}
            olaylar = []
            for o in y.get("details") or []:
                tid = (o.get("team") or {}).get("id")
                tip = (o.get("type") or {}).get("text") or ""
                if tid not in kirmizi or o.get("shootout"):
                    continue
                if tip == "Red Card":
                    kirmizi[tid] += 1
                ad = OLAY_ADI.get(tip) or ("Gol" if o.get("scoringPlay") else None)
                if ad:
                    olaylar.append(dict(dk=(o.get("clock") or {}).get("displayValue") or "", tip=ad,
                                        taraf="ev" if tid == ev["team"]["id"] else "dep",
                                        oyuncu=", ".join(a.get("displayName") or "" for a in (o.get("athletesInvolved") or [])[:1])))
            sonuc[e["id"]] = dict(
                durum=d.get("state") or "pre", bitti=bool(d.get("completed")),
                aciklama=d.get("shortDetail") or d.get("description") or "",
                dakika=e["status"].get("displayClock") or "",
                saniye=float(e["status"].get("clock") or 0), yari=int(e["status"].get("period") or 0),
                skor=[int(ev.get("score") or 0), int(dep.get("score") or 0)],
                kirmizi=[kirmizi[ev["team"]["id"]], kirmizi[dep["team"]["id"]]], olaylar=olaylar)
    except Exception:
        if kayit:
            return kayit[1]
    canli_onbellek[anahtar] = (simdi, sonuc)
    return sonuc


def canli(hedef):
    """O günün maçlarının anlık durumu: {eid: {durum, dakika, skor, kırmızı kart...}}."""
    fb = fikstur_bilgi()
    ligler = {espn for (div, ev, dep, d), (eid, espn) in fb["kimlik"].items() if d == hedef and espn}
    gunler = {hedef.strftime("%Y%m%d"), date.fromordinal(hedef.toordinal() - 1).strftime("%Y%m%d")}
    istenen = {eid for (div, ev, dep, d), (eid, espn) in fb["kimlik"].items() if d == hedef}
    sonuc = {}
    with ag_kilidi:
        for espn in ligler:
            for gun in gunler:   # ESPN günü ABD saatine göre böler; gece maçları önceki güne düşebilir
                for eid, durum in canli_lig(espn, gun).items():
                    if eid in istenen:
                        sonuc[eid] = durum
    return sonuc


def kadro(eid):
    """Kadro açıklandıysa ilk 11'leri getirir ve tahmini eksik golcülere göre yeniden hesaplar."""
    fb = fikstur_bilgi()
    if eid not in fb["eid_ile"]:
        return dict(aciklandi=False)
    div, ev, dep, d = fb["eid_ile"][eid]
    espn = fb["kimlik"][(div, ev, dep, d)][1]
    kayit, simdi = kadro_onbellek.get(eid), time.time()
    if kayit and simdi - kayit[0] < 120:
        return kayit[1]
    ozet = ozet_al(eid, espn, 60)
    takimlar = {}
    for r in ozet.get("rosters") or []:
        ad = ev if r.get("homeAway") == "home" else dep
        oyuncular = [dict(id=(o.get("athlete") or {}).get("id") or "", ad=(o.get("athlete") or {}).get("displayName") or "",
                          mevki=(o.get("position") or {}).get("abbreviation") or "", no=o.get("jersey") or "",
                          ilk11=bool(o.get("starter"))) for o in r.get("roster") or []]
        takimlar[ad] = dict(dizilis=r.get("formation") or "", ilk11=[o for o in oyuncular if o["ilk11"]],
                            yedek=[o for o in oyuncular if not o["ilk11"]])
    if len(takimlar) < 2 or any(len(t["ilk11"]) < 11 for t in takimlar.values()):
        sonuc = dict(aciklandi=False)
        kadro_onbellek[eid] = (simdi, sonuc)
        return sonuc

    bugun = date.today()
    try:
        ek = ek_al(div, bugun)
    except Exception:
        ek = None
    etki, eksikler = {}, {}
    for t, k in takimlar.items():
        etki[t], eksikler[t] = 0.0, []
        goller = (ek or {}).get("gol", {}).get(t, {})
        toplam = sum(goller.values())
        ilk11 = {o["id"] for o in k["ilk11"]}
        yedek = {o["id"] for o in k["yedek"]}
        for (pid, ad), n in sorted(goller.items(), key=lambda x: -x[1]):
            if n < 2 or pid in ilk11 or not toplam:
                continue
            yedekte = pid in yedek
            etki[t] += (0.3 if yedekte else 0.6) * n / toplam   # yedekteki golcü yarı ağırlıkla sayılır
            eksikler[t].append(dict(ad=ad, gol=n, durum="yedekte" if yedekte else "kadroda yok"))
        etki[t] = min(0.5, etki[t])
    fx = next((f for f in g.fikstur_yukle(FIKSTUR, d, None) if (f["div"], f["ev"], f["dep"]) == (div, ev, dep)), None)
    mac = None
    if fx:
        mac, _ = mac_analiz(fx, d, bugun, kadro_etki=etki)
    sonuc = dict(aciklandi=True, takimlar=takimlar, eksikler=eksikler, etki=etki, mac=mac)
    kadro_onbellek[eid] = (simdi, sonuc)
    return sonuc


def simule(lh, la, sh, sa, dakika=0.0, skor=(0, 0), kirmizi=(0, 0), n=10000):
    """Maçı dakika dakika n kez oynatır. Canlı maçta kalan süreyi mevcut skor ve kırmızı kartlarla oynatır.
    Gol hızları: ilk yarı lh*sh ve la*sa, ikinci yarı kalanı; kırmızı kart takımını %30 yavaşlatır, rakibi %15 hızlandırır."""
    import random
    rnd = random.Random()
    ev_carpan = 0.7 ** kirmizi[0] * 1.15 ** kirmizi[1]
    dep_carpan = 0.7 ** kirmizi[1] * 1.15 ** kirmizi[0]
    hiz = [(lh * sh / 45 * ev_carpan, la * sa / 45 * dep_carpan),              # ilk yarı, dakika başına
           (lh * (1 - sh) / 45 * ev_carpan, la * (1 - sa) / 45 * dep_carpan)]  # ikinci yarı
    dakika = min(max(dakika, 0.0), 90.0)
    dilimler = []   # (başlangıç, bitiş, yarı)
    if dakika < 45:
        dilimler.append((dakika, 45.0, 0))
    dilimler.append((max(dakika, 45.0), 90.0, 1))
    sonuclar = {"1": 0, "X": 0, "2": 0}
    skorlar, ilk_gol, yari = {}, {"ev": 0, "dep": 0, "yok": 0}, {"ilk": 0, "esit": 0, "ikinci": 0}
    ust25 = kg = toplam_gol = 0
    bastan = dakika == 0
    for _ in range(n):
        h, a = skor
        en_erken, kim = 999.0, "yok"
        yari_gol = [0, 0]
        for bas, bit, y in dilimler:
            sure = bit - bas
            for taraf, r in ((0, hiz[y][0]), (1, hiz[y][1])):
                t = bas
                while True:   # Poisson süreci: goller arası süre üstel dağılır
                    t += rnd.expovariate(r) if r > 0 else 1e9
                    if t >= bit:
                        break
                    if taraf == 0:
                        h += 1
                    else:
                        a += 1
                    yari_gol[y] += 1
                    if t < en_erken:
                        en_erken, kim = t, ("ev" if taraf == 0 else "dep")
        sonuclar["1" if h > a else ("X" if h == a else "2")] += 1
        skorlar[(h, a)] = skorlar.get((h, a), 0) + 1
        ilk_gol[kim] += 1
        ust25 += h + a >= 3
        kg += h > 0 and a > 0
        toplam_gol += h + a
        if bastan:
            yari["ilk" if yari_gol[0] > yari_gol[1] else ("esit" if yari_gol[0] == yari_gol[1] else "ikinci")] += 1
    en_olasi = sorted(skorlar.items(), key=lambda x: -x[1])[:6]
    return dict(n=n, canli=not bastan, ms={k: v / n for k, v in sonuclar.items()},
                skor=[[f"{h}-{a}", c / n] for (h, a), c in en_olasi],
                ust25=ust25 / n, kg=kg / n, ort_gol=toplam_gol / n,
                sonraki_gol={k: v / n for k, v in ilk_gol.items()},
                yari={k: v / n for k, v in yari.items()} if bastan else None)


# ====================== Ek istatistikler: kart, şut, faul, form, cezalılar ======================
# Kaç sarı kartta 1 maç ceza geldiği (lig kuralı). Listede olmayan liglerde yalnızca kırmızı kart cezası aranır.
SARI_SINIRI = {"T1": 4, "E0": 5, "E1": 5, "SP1": 5, "D1": 5, "I1": 5, "N1": 5, "P1": 5, "B1": 5,
               "CL": 3, "EL": 3, "ECL": 3}
KART_R = 12.0   # kart sayısı dağılımının dağınıklığı
ek_onbellek = {}


def ek_al(div, bugun):
    vz = veri_zamani()
    kayit = ek_onbellek.get(div)
    if kayit and kayit[0] == vz:
        return kayit[1]
    bu_kod = g.sezon_kodu(bugun)
    maclar = []
    for kod in (bu_kod, g.sezon_kodu(bugun, 1)):
        yol = os.path.join(KOK, "veri", f"{div}_{kod}.csv")
        if not os.path.exists(yol):
            continue
        for r in g.csv_oku(yol):
            d, hg, ag = g.tarih_cevir(r.get("Date")), g.sayi(r, "FTHG"), g.sayi(r, "FTAG")
            if d is None or hg is None or ag is None:
                continue
            topla = lambda a, b: None if g.sayi(r, a) is None or g.sayi(r, b) is None else g.sayi(r, a) + g.sayi(r, b)
            maclar.append(dict(d=d, h=r["HomeTeam"].strip(), a=r["AwayTeam"].strip(), hg=hg, ag=ag, bu=kod == bu_kod,
                               kart_h=topla("HY", "HR"), kart_a=topla("AY", "AR"),
                               sut_h=g.sayi(r, "HS"), sut_a=g.sayi(r, "AS"), isb_h=g.sayi(r, "HST"), isb_a=g.sayi(r, "AST"),
                               faul_h=g.sayi(r, "HF"), faul_a=g.sayi(r, "AF")))
    guc = {}
    for ad in ("kart", "sut", "isb", "faul"):
        try:
            guc[ad] = g.guclar(maclar, ad + "_h", ad + "_a", bugun)
        except Exception:
            guc[ad] = None

    # Bu sezon: puan durumu, form, son maç tarihi
    bu = sorted((m for m in maclar if m["bu"]), key=lambda m: m["d"])
    tablo, form, son_mac = {}, {}, {}
    for m in bu:
        for t, atilan, yenen in ((m["h"], m["hg"], m["ag"]), (m["a"], m["ag"], m["hg"])):
            k = tablo.setdefault(t, dict(o=0, p=0, ag=0, yg=0))
            k["o"] += 1; k["ag"] += atilan; k["yg"] += yenen
            k["p"] += 3 if atilan > yenen else (1 if atilan == yenen else 0)
            form.setdefault(t, []).append("G" if atilan > yenen else ("B" if atilan == yenen else "M"))
            son_mac[t] = m["d"]
    sirali = sorted(tablo, key=lambda t: (-tablo[t]["p"], -(tablo[t]["ag"] - tablo[t]["yg"]), -tablo[t]["ag"]))
    for i, t in enumerate(sirali, 1):
        tablo[t]["sira"] = i

    # Oyuncu olayları: sarı kart sayıları, son maçtaki kırmızılar, goller
    sari, gol, son_sari, son_kirmizi = {}, {}, {}, {}
    yol = os.path.join(KOK, "veri", "olaylar.csv")
    if os.path.exists(yol):
        for r in g.csv_oku(yol):
            if r.get("Div") != div:
                continue
            t, oyuncu, d = r["Team"], (r["PlayerId"], r["Player"]), g.tarih_cevir(r.get("Date"))
            if r["Tip"] == "SARI":
                sari.setdefault(t, {}).setdefault(oyuncu, 0)
                sari[t][oyuncu] += 1
                if d == son_mac.get(t):
                    son_sari.setdefault(t, set()).add(oyuncu)
            elif r["Tip"] == "KIRMIZI" and d == son_mac.get(t):
                son_kirmizi.setdefault(t, set()).add(oyuncu)
            elif r["Tip"] == "GOL":
                gol.setdefault(t, {}).setdefault(oyuncu, 0)
                gol[t][oyuncu] += 1
    sinir = SARI_SINIRI.get(div)
    cezali, sinirda = {}, {}
    for t in tablo:
        liste = [dict(ad=o[1], neden="son maçta kırmızı kart", gol=gol.get(t, {}).get(o, 0))
                 for o in son_kirmizi.get(t, ())]
        if sinir:
            for o, n in sari.get(t, {}).items():
                if o in son_kirmizi.get(t, ()):
                    continue
                if n % sinir == 0 and o in son_sari.get(t, ()):
                    liste.append(dict(ad=o[1], neden=f"{n}. sarı kart", gol=gol.get(t, {}).get(o, 0)))
                elif n % sinir == sinir - 1:
                    sinirda.setdefault(t, []).append(f"{o[1]} ({n} sarı)")
        if liste:
            cezali[t] = liste
    sonuc = dict(maclar=maclar, guc=guc, tablo=tablo, form=form, cezali=cezali, sinirda=sinirda,
                 takim_gol={t: sum(v.values()) for t, v in gol.items()}, gol=gol, sinir=sinir)
    ek_onbellek[div] = (vz, sonuc)
    return sonuc


def ceza_etkisi(ek, takim, cezalilar):
    """Cezalı oyuncuların takıma etkisi (0-0.5): oyuncu başına 0.04 + takım gollerindeki payının 0.6 katı."""
    if not cezalilar:
        return 0.0
    toplam = ek["takim_gol"].get(takim, 0)
    pay = sum(c["gol"] for c in cezalilar) / toplam if toplam else 0.0
    return min(0.5, 0.04 * len(cezalilar) + 0.6 * pay)


def ek_bilgi(ek, fx, ceza, etki):
    ev, dep = fx["ev"], fx["dep"]

    def beklenen(ad):
        r = ek["guc"].get(ad)
        if not r or ev not in r[0] or dep not in r[0]:
            return None
        G, ah, aa = r
        return [ah * G[ev]["att_h"] * G[dep]["def_a"], aa * G[dep]["att_a"] * G[ev]["def_h"]]

    ust = lambda mu, cizgi: 1 - sum(g.nb_pmf(k, mu, KART_R) for k in range(int(cizgi) + 1))
    bilgi = dict(kart=None, kart_b=None, ist=[], form={}, sira={}, cezali=ceza, etki=etki,
                 sinirda={t: ek["sinirda"].get(t, []) for t in (ev, dep)}, sinir=ek["sinir"], aralarinda=[])
    kb = beklenen("kart")
    if kb:
        mu = sum(kb)
        bilgi["kart_b"] = kb
        bilgi["kart"] = {"Üst 3.5": ust(mu, 3.5), "Üst 4.5": ust(mu, 4.5), "Üst 5.5": ust(mu, 5.5),
                         f"{ev} Üst 1.5": ust(kb[0], 1.5), f"{dep} Üst 1.5": ust(kb[1], 1.5),
                         f"{ev} Üst 2.5": ust(kb[0], 2.5), f"{dep} Üst 2.5": ust(kb[1], 2.5)}
    for etiket, ad in (("Şut", "sut"), ("İsabetli şut", "isb"), ("Faul", "faul"), ("Kart", "kart")):
        b = beklenen(ad)
        if b:
            bilgi["ist"].append([etiket, b[0], b[1]])
    for t in (ev, dep):
        bilgi["form"][t] = ek["form"].get(t, [])[-5:]
        k = ek["tablo"].get(t)
        if k:
            bilgi["sira"][t] = dict(sira=k["sira"], puan=k["p"], oynanan=k["o"], ag=k["ag"], yg=k["yg"])
    karsilasma = [m for m in ek["maclar"] if {m["h"], m["a"]} == {ev, dep}]
    for m in sorted(karsilasma, key=lambda m: m["d"], reverse=True)[:5]:
        bilgi["aralarinda"].append([m["d"].strftime("%d.%m.%Y"), m["h"], m["a"], f"{m['hg']}-{m['ag']}"])
    return bilgi


# ====================== Arama ve yorumlar ======================
YORUM_DOSYASI = os.path.join(KOK, "yorumlar.json")
yorum_kilidi = threading.Lock()
_CEVIRI = str.maketrans("çğıöşüâîû", "cgiosuaiu")


def sade(metin):
    """Aramada büyük/küçük harf ve Türkçe karakter farkını yok say."""
    return metin.replace("İ", "i").replace("I", "i").casefold().translate(_CEVIRI)


def ara(sorgu):
    q = sade(sorgu.strip())
    if len(q) < 2 or not os.path.exists(FIKSTUR):
        return []
    bugun, sonuc = date.today(), []
    for r in g.csv_oku(FIKSTUR):
        ev, dep = (r.get("HomeTeam") or "").strip(), (r.get("AwayTeam") or "").strip()
        d = g.tarih_cevir(r.get("Date"))
        if d and d >= bugun and (q in sade(ev) or q in sade(dep)):
            div = (r.get("Div") or "").strip()
            sonuc.append(dict(tarih=d.isoformat(), saat=(r.get("Time") or "").strip(), ev=ev, dep=dep,
                              div=div, lig=LIG_ADI.get(div, div)))
    sonuc.sort(key=lambda x: (x["tarih"], x["saat"]))
    return sonuc[:30]


def yorumlari_oku():
    try:
        with open(YORUM_DOSYASI, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def yorum_ekle(mac, ad, metin):
    mac, ad, metin = mac.strip()[:200], " ".join(ad.split())[:40], metin.strip()[:500]
    if not mac or not metin:
        raise ValueError("Yorum boş olamaz.")
    with yorum_kilidi:
        hepsi = yorumlari_oku()
        liste = hepsi.setdefault(mac, [])
        if len(liste) >= 200:
            raise ValueError("Bu maç için yorum sınırı doldu.")
        liste.append(dict(ad=ad or "Misafir", metin=metin, zaman=time.time()))
        gecici = YORUM_DOSYASI + ".tmp"
        with open(gecici, "w", encoding="utf-8") as f:
            json.dump(hepsi, f, ensure_ascii=False)
        os.replace(gecici, YORUM_DOSYASI)
        return liste


# ====================== Haberler ======================
def haber_cek(sorgu, dil="tr"):
    anahtar = (sorgu, dil, date.today())
    if anahtar in haber_onbellek:
        return haber_onbellek[anahtar]
    yer = "hl=tr&gl=TR&ceid=TR:tr" if dil == "tr" else "hl=en-US&gl=US&ceid=US:en"
    url = f"https://news.google.com/rss/search?q={urllib.parse.quote(sorgu + ' when:7d')}&{yer}"
    istek = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(istek, timeout=20, context=veri_indir.SSL_BAGLAM) as r:
        kok = ET.fromstring(r.read())
    liste = []
    for it in kok.iter("item"):
        baslik = (it.findtext("title") or "").strip()
        link = (it.findtext("link") or "").strip()
        if not baslik or not link.startswith("https://"):
            continue
        try:
            zaman = parsedate_to_datetime(it.findtext("pubDate")).timestamp()
        except Exception:
            zaman = 0
        liste.append(dict(baslik=baslik, link=link, zaman=zaman, kaynak=(it.findtext("source") or "").strip()))
    liste.sort(key=lambda h: -h["zaman"])
    haber_onbellek[anahtar] = liste[:8]
    return haber_onbellek[anahtar]


def mac_haberleri(ev, dep):
    haberler = haber_cek(f"{ev} {dep}", "tr")
    if len(haberler) < 3:
        gorulen = {h["link"] for h in haberler}
        haberler = haberler + [h for h in haber_cek(f"{ev} {dep}", "en") if h["link"] not in gorulen]
    return haberler[:8]


# ====================== Veri güncelleme ======================
def guncelle():
    with kilit:
        if durum["guncelleniyor"]:
            return
        durum.update(guncelleniyor=True, mesaj="Veri indiriliyor...", hata="", son_deneme=time.time())

    def calis():
        try:
            # Çıktıyı yönlendirmek yerine doğrudan durum mesajına yaz (yönlendirme bütün iş parçacıklarını etkiler)
            veri_indir.main(yaz=lambda metin: durum.update(mesaj=str(metin).strip()[:120]))
            lig_onbellek.clear()
            ek_onbellek.clear()
            kadro_onbellek.clear()
        except Exception as e:
            durum["hata"] = f"Veri güncellenemedi: {e}"
        finally:
            durum.update(guncelleniyor=False, mesaj="")

    threading.Thread(target=calis, daemon=True).start()


# ====================== Sunucu ======================
def yuvarla(o):
    """Yanıtı küçültmek için ondalıkları 4 basamağa indirir (0.4885836207578354 -> 0.4886)."""
    if isinstance(o, float):
        return round(o, 4)
    if isinstance(o, dict):
        return {k: yuvarla(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [yuvarla(v) for v in o]
    return o


class Istek(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def gonder(self, govde, tur="application/json; charset=utf-8", kod=200):
        veri = govde if isinstance(govde, bytes) else json.dumps(yuvarla(govde), ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        sikistir = len(veri) > 1024 and "gzip" in (self.headers.get("Accept-Encoding") or "")
        if sikistir:   # yavaş bağlantıda sayfa ve analiz verisi 8-10 kat küçülür
            import gzip
            veri = gzip.compress(veri, 6)
        self.send_response(kod)
        if sikistir:
            self.send_header("Content-Encoding", "gzip")
            self.send_header("Vary", "Accept-Encoding")
        self.send_header("Content-Type", tur)
        self.send_header("Content-Length", str(len(veri)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")
        self.end_headers()
        self.wfile.write(veri)

    def do_GET(self):
        global son_istek
        son_istek = time.time()
        u = urllib.parse.urlparse(self.path)
        q = urllib.parse.parse_qs(u.query)
        try:
            if u.path == "/":
                with open(os.path.join(KOK, "arayuz.html"), "rb") as f:
                    return self.gonder(f.read(), "text/html; charset=utf-8")
            if u.path == "/logo.svg":
                with open(os.path.join(KOK, "logo.svg"), "rb") as f:
                    return self.gonder(f.read(), "image/svg+xml")
            if u.path in UYGULAMA_DOSYALARI:   # telefona uygulama olarak kurulum (PWA) dosyaları
                ad, tur = UYGULAMA_DOSYALARI[u.path]
                with open(os.path.join(KOK, ad), "rb") as f:
                    return self.gonder(f.read(), tur)
            if u.path == "/reklam":   # reklam.html varsa reklam kodu; yoksa boş
                yol = os.path.join(KOK, "reklam.html")
                kod = open(yol, "rb").read() if os.path.exists(yol) else b""
                return self.gonder(kod, "text/html; charset=utf-8")
            if u.path == "/api/durum":
                return self.gonder(dict(durum, veri_zamani=veri_zamani(), site=SITE))
            if u.path == "/api/analiz":
                try:
                    hedef = datetime.strptime(q.get("tarih", [""])[0], "%Y-%m-%d").date()
                except ValueError:
                    hedef = date.today()
                return self.gonder(analiz_ozet(hedef) if q.get("ozet") else analiz(hedef))
            if u.path == "/api/mac":
                try:
                    hedef = datetime.strptime(q.get("tarih", [""])[0], "%Y-%m-%d").date()
                except ValueError:
                    return self.gonder({"hata": "tarih gerekli"}, kod=400)
                m = tek_mac(hedef, q.get("div", [""])[0][:8], q.get("ev", [""])[0][:60], q.get("dep", [""])[0][:60])
                return self.gonder(m) if m else self.gonder({"hata": "Maç bulunamadı."}, kod=404)
            if u.path == "/api/takim":
                return self.gonder(takim_sayfa(q.get("ad", [""])[0][:60], q.get("div", [""])[0][:8]))
            if u.path == "/api/yorumlar":
                return self.gonder(yorum_akisi())
            if u.path == "/api/karne":
                return self.gonder(karne())
            if u.path == "/api/ligler":
                return self.gonder(ligler())
            if u.path == "/api/lig":
                return self.gonder(lig_sayfa(q.get("div", [""])[0][:8]))
            if u.path == "/api/canli":
                try:
                    hedef = datetime.strptime(q.get("tarih", [""])[0], "%Y-%m-%d").date()
                except ValueError:
                    hedef = date.today()
                return self.gonder(canli(hedef))
            if u.path == "/api/macdetay":
                return self.gonder(mac_detay(q.get("eid", [""])[0][:20]))
            if u.path == "/api/kadro":
                return self.gonder(kadro(q.get("eid", [""])[0][:20]))
            if u.path == "/api/sim":
                sayi = lambda ad, alt, ust, vars=0.0: min(max(float(q.get(ad, [vars])[0]), alt), ust)
                return self.gonder(simule(
                    sayi("lh", 0.01, 8), sayi("la", 0.01, 8), sayi("sh", 0.1, 0.9, 0.45), sayi("sa", 0.1, 0.9, 0.45),
                    dakika=sayi("dk", 0, 90), skor=(int(sayi("h", 0, 20)), int(sayi("a", 0, 20))),
                    kirmizi=(int(sayi("kh", 0, 4)), int(sayi("ka", 0, 4)))))
            if u.path == "/api/ara":
                return self.gonder(ara(q.get("q", [""])[0][:60]))
            if u.path == "/api/yorum":
                return self.gonder(yorumlari_oku().get(q.get("mac", [""])[0][:200], []))
            if u.path == "/api/haber":
                ev, dep = q.get("ev", [""])[0][:60], q.get("dep", [""])[0][:60]
                if q.get("genel"):
                    return self.gonder(haber_cek("Süper Lig sakat OR cezalı OR kadro", "tr"))
                return self.gonder(mac_haberleri(ev, dep))
            self.gonder({"hata": "bulunamadı"}, kod=404)
        except Exception as e:
            import traceback
            print(f"[{time.strftime('%H:%M:%S')}] HATA {self.path}", file=sys.stderr)
            traceback.print_exc()   # kayıt dosyasına düşer; sonradan nedenini bulmak için
            self.gonder({"hata": str(e)}, kod=500)

    def do_POST(self):
        global son_istek
        son_istek = time.time()
        if self.path == "/api/guncelle":
            if SITE:
                return self.gonder({"hata": "Veri sunucuda kendiliğinden güncellenir."}, kod=403)
            guncelle()
            return self.gonder({"tamam": True})
        if self.path == "/api/asistan":
            try:
                boyut = int(self.headers.get("Content-Length") or 0)
                if not 0 < boyut <= 4096:
                    raise ValueError("Soru çok uzun.")
                soru = str(json.loads(self.rfile.read(boyut).decode("utf-8")).get("soru", ""))
                kimden = (self.headers.get("X-Forwarded-For") or "").split(",")[0].strip() if SITE else ""
                kimden = kimden or self.client_address[0]
                simdi = time.time()
                eski = [t for t in asistan_gecmisi.get(kimden, []) if simdi - t < 60]
                if len(eski) >= 20:
                    return self.gonder({"hata": "Çok hızlı soruyorsun; bir dakika sonra tekrar dene."}, kod=429)
                asistan_gecmisi[kimden] = eski + [simdi]
                import asistan
                return self.gonder(asistan.cevapla(soru, sys.modules[__name__]))
            except ValueError as e:
                return self.gonder({"hata": str(e)}, kod=400)
            except Exception as e:
                return self.gonder({"hata": f"Asistan cevap veremedi: {e}"}, kod=500)
        if self.path == "/api/yorum":
            try:
                boyut = int(self.headers.get("Content-Length") or 0)
                if not 0 < boyut <= 8192:
                    raise ValueError("Yorum çok uzun.")
                v = json.loads(self.rfile.read(boyut).decode("utf-8"))
                kimden = (self.headers.get("X-Forwarded-For") or "").split(",")[0].strip() if SITE else ""
                kimden = kimden or self.client_address[0]
                simdi = time.time()
                eski = [t for t in yorum_gecmisi.get(kimden, []) if simdi - t < YORUM_SINIRI[1]]
                if len(eski) >= YORUM_SINIRI[0]:
                    return self.gonder({"hata": "Çok hızlı yorum yazıyorsun; biraz sonra tekrar dene."}, kod=429)
                yorum_gecmisi[kimden] = eski + [simdi]
                return self.gonder(yorum_ekle(str(v.get("mac", "")), str(v.get("ad", "")), str(v.get("metin", ""))))
            except ValueError as e:
                return self.gonder({"hata": str(e)}, kod=400)
        self.gonder({"hata": "bulunamadı"}, kod=404)


def main():
    sessiz = SITE or "--sessiz" in sys.argv
    try:
        sunucu = ThreadingHTTPServer((SUNUCU_ADRESI, PORT), Istek)
    except OSError:  # zaten açık: sadece sayfayı göster
        if not sessiz:
            webbrowser.open(ADRES)
        return
    if time.time() - veri_zamani() > VERI_ESKIME_SAAT * 3600:
        guncelle()

    def bekci():
        while True:
            time.sleep(30)
            eski = time.time() - veri_zamani() > VERI_ESKIME_SAAT * 3600
            bekledi = time.time() - durum.get("son_deneme", 0) > 300   # başarısız denemeden sonra 5 dk bekle
            if eski and bekledi and (SITE or time.time() - son_istek < 120):   # sayfa açıkken (ya da sitede) kendiliğinden yenile
                guncelle()
            if SITE:
                pass
            elif time.time() - son_istek > BOSTA_KAPAN_SN and not durum["guncelleniyor"]:
                os._exit(0)

    threading.Thread(target=bekci, daemon=True).start()
    if not sessiz:
        threading.Timer(0.5, lambda: webbrowser.open(ADRES)).start()
    print(f"Maç Analizi çalışıyor: {ADRES}")
    sunucu.serve_forever()


if __name__ == "__main__":
    main()
