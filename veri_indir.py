#!/usr/bin/env python3
"""
football-data.co.uk erişilemediğinde veriyi ESPN'in açık skor servisinden indirir
ve gunluk_analiz.py'nin beklediği biçimde veri/ klasörüne yazar.

Kullanım:
  python3 veri_indir.py
  python3 gunluk_analiz.py --tarih 21/11/2026

Gelenler: güncel fikstür, sonuçlar, ilk yarı skorları (gol dakikalarından),
korner sayıları ve - yalnızca yakın maçlar için - 1X2 ile Alt/Üst 2.5 oranları.
Oranlar ABD'li bir bahis şirketinindir (DraftKings); Türkiye'deki oranlardan farklı olabilir.
Saatler Türkiye saatidir.
"""
import contextlib
import csv
import gzip
import json
import os
import ssl
import urllib.request

import adlar as ad_cevirici
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta

KAYNAK = "https://site.api.espn.com/apis/site/v2/sports/soccer/{lig}/scoreboard?dates={yil}&limit=1000"
KLASOR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "veri")
TR_FARK = timedelta(hours=3)

# python.org kurulumunda kök sertifikalar eksik olabiliyor; macOS'un kendi listesini de yükle.
SSL_BAGLAM = ssl.create_default_context()
if os.path.exists("/etc/ssl/cert.pem"):
    SSL_BAGLAM.load_verify_locations("/etc/ssl/cert.pem")

LIGLER = {  # analizdeki lig kodu -> (ESPN kodu, ad)
    "T1": ("tur.1", "Türkiye Süper Lig"),
    "E0": ("eng.1", "İngiltere Premier Lig"),
    "E1": ("eng.2", "İngiltere Championship"),
    "SP1": ("esp.1", "İspanya La Liga"),
    "D1": ("ger.1", "Almanya Bundesliga"),
    "I1": ("ita.1", "İtalya Serie A"),
    "F1": ("fra.1", "Fransa Ligue 1"),
    "N1": ("ned.1", "Hollanda Eredivisie"),
    "P1": ("por.1", "Portekiz Primeira Liga"),
    "B1": ("bel.1", "Belçika Pro Lig"),
    "SC0": ("sco.1", "İskoçya Premiership"),
    "G1": ("gre.1", "Yunanistan Süper Lig"),
    "CL": ("uefa.champions", "Şampiyonlar Ligi"),
    "EL": ("uefa.europa", "Avrupa Ligi"),
    "ECL": ("uefa.europa.conf", "Konferans Ligi"),
}

# Milli maçlar: az maç oynandığı için bütün turnuvalar tek havuzda ("MIL") toplanır.
EK_SUTUN = ["HS", "AS", "HST", "AST", "HF", "AF", "HY", "AY", "HR", "AR"]   # şut, isabetli şut, faul, sarı, kırmızı
MILLI_KOD = "MIL"
MILLI = ["uefa.nations", "fifa.friendly", "fifa.worldq.uefa", "fifa.world", "uefa.euro", "uefa.euroq",
         "fifa.worldq.conmebol", "fifa.worldq.caf", "fifa.worldq.afc", "fifa.worldq.concacaf",
         "caf.nations", "caf.nations_qual", "concacaf.nations.league", "afc.cupq"]


@contextlib.contextmanager
def atomik_yaz(yol):
    """Dosyayı önce geçici adla yazar, bitince yerine koyar; okuyan taraf hiçbir zaman yarım dosya görmez."""
    gecici = f"{yol}.{os.getpid()}.tmp"
    with open(gecici, "w", newline="", encoding="utf-8") as f:
        yield f
    os.replace(gecici, yol)


def indir(lig, yil):
    url = KAYNAK.format(lig=lig, yil=yil)
    try:
        istek = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(istek, timeout=60, context=SSL_BAGLAM) as r:
            veri = r.read()
        if veri[:2] == b"\x1f\x8b":
            veri = gzip.decompress(veri)
        olaylar = json.loads(veri).get("events", [])
        del veri
        # Ham veriyi hemen küçük hâline çevir: hepsini birden bellekte tutmak sunucuda 600 MB+ yer kaplıyordu
        sonuc = []
        for e in olaylar:
            try:
                sonuc.append(cevir(e, lig))
            except Exception:
                continue
        return sonuc
    except Exception as e:
        print(f"  ! {lig} {yil} indirilemedi ({e})")
        return None   # indirilemedi (boş listeden farklı: o yıl maç yok demek)


def ondalik(amerikan):
    """ABD oranı (+130 / -140) -> ondalık oran (2.30 / 1.71)."""
    try:
        s = str(amerikan).strip().upper()
        if s in ("EVEN", "EV"):
            return 2.0
        v = float(s)
        if v == 0:
            return None
        return round(1 + (v / 100 if v > 0 else 100 / -v), 2)
    except Exception:
        return None


def oranlar(yarisma):
    bos = dict(h="", d="", a="", ust="", alt="")
    try:
        o = (yarisma.get("odds") or [None])[0]
        if not o:
            return bos
        ml = o.get("moneyline") or {}
        al = lambda d, k: ondalik(((d.get(k) or {}).get("close") or {}).get("odds")) or ""
        sonuc = dict(bos, h=al(ml, "home"), d=al(ml, "draw"), a=al(ml, "away"))
        if o.get("overUnder") == 2.5:
            sonuc["ust"] = al(o.get("total") or {}, "over")
            sonuc["alt"] = al(o.get("total") or {}, "under")
        return sonuc
    except Exception:
        return bos


def istatistik(takim, ad):
    for s in takim.get("statistics") or []:
        if s.get("name") == ad:
            try:
                return int(float(s.get("displayValue")))
            except (TypeError, ValueError):
                return ""
    return ""


def ilk_yari(yarisma, ev, dep, hg, ag):
    """Gol dakikalarından ilk yarı skoru; goller maç skoruyla tutmuyorsa boş bırak."""
    say = {ev["team"]["id"]: [0, 0], dep["team"]["id"]: [0, 0]}  # [toplam, ilk yarı]
    for d in yarisma.get("details") or []:
        if not d.get("scoringPlay") or d.get("shootout"):
            continue
        tid = (d.get("team") or {}).get("id")
        if tid not in say:
            return "", ""
        say[tid][0] += 1
        if ((d.get("clock") or {}).get("value") or 0) <= 2700:
            say[tid][1] += 1
    e, p = say[ev["team"]["id"]], say[dep["team"]["id"]]
    if e[0] != hg or p[0] != ag:
        return "", ""
    return e[1], p[1]


def cevir(e, lig=""):
    y = e["competitions"][0]
    ev = next(t for t in y["competitors"] if t["homeAway"] == "home")
    dep = next(t for t in y["competitors"] if t["homeAway"] == "away")
    zaman = datetime.strptime(e["date"][:16], "%Y-%m-%dT%H:%M") + TR_FARK
    durum = e["status"]["type"]
    m = dict(id=e["id"], sezon=e["season"]["year"], z=zaman,
             ev=ad_cevirici.cevir(ev["team"]["displayName"].strip(), lig in MILLI),
             dep=ad_cevirici.cevir(dep["team"]["displayName"].strip(), lig in MILLI),
             bitti=bool(durum.get("completed")), planli=durum.get("name") == "STATUS_SCHEDULED",
             canli=durum.get("state") == "in", espn=lig, oran=oranlar(y))
    if m["bitti"]:
        m["hg"], m["ag"] = int(ev["score"]), int(dep["score"])
        m["hthg"], m["htag"] = ilk_yari(y, ev, dep, m["hg"], m["ag"])
        m["hc"], m["ac"] = istatistik(ev, "wonCorners"), istatistik(dep, "wonCorners")
        m["ek"] = [istatistik(t, ad) for ad in ("totalShots", "shotsOnTarget", "foulsCommitted") for t in (ev, dep)]
        kart = {ev["team"]["id"]: [0, 0], dep["team"]["id"]: [0, 0]}   # [sarı, kırmızı]
        adlar = {ev["team"]["id"]: m["ev"], dep["team"]["id"]: m["dep"]}
        m["olay"] = []
        for d in y.get("details") or []:
            tid = (d.get("team") or {}).get("id")
            tip = (d.get("type") or {}).get("text") or ""
            if tid not in kart or d.get("shootout"):
                continue
            if tip == "Yellow Card":
                kart[tid][0] += 1; kod = "SARI"
            elif tip == "Red Card":
                kart[tid][1] += 1; kod = "KIRMIZI"
            elif d.get("scoringPlay") and tip != "Own Goal":
                kod = "GOL"
            else:
                continue
            for a in (d.get("athletesInvolved") or [])[:1]:
                m["olay"].append((adlar[tid], a.get("id") or "", (a.get("displayName") or "").strip(), kod))
        m["kart"] = kart[ev["team"]["id"]] + kart[dep["team"]["id"]]   # ev sarı, ev kırmızı, dep sarı, dep kırmızı
    return m


def fiksturde(m, bugun):
    """Gelecek maçlar; ayrıca bugünün başlamış ya da bitmiş maçları (canlı skor için listede kalır)."""
    if m["planli"]:
        return m["z"].date() >= bugun
    return m["z"].date() == bugun and (m["canli"] or m["bitti"])


def main(yaz=print):
    bugun = date.today()
    bas = bugun.year if bugun.month >= 7 else bugun.year - 1  # sezonun başladığı yıl
    os.makedirs(KLASOR, exist_ok=True)
    fikstur, olaylar = [], []
    # Bütün istekleri önce, aynı anda 6'şar tane indir (sırayla ~100 sn yerine ~15 sn sürer)
    istekler = [(lig, yil) for lig, _ in LIGLER.values() for yil in (bas - 1, bas, bas + 1)]
    istekler += [(lig, yil) for lig in MILLI for yil in range(bas - 2, bas + 2)]
    with ThreadPoolExecutor(max_workers=3) as havuz:
        hazir = dict(zip(istekler, havuz.map(lambda x: indir(*x), istekler)))
    basarisiz = [k for k, v in hazir.items() if v is None]
    if len(basarisiz) > len(istekler) * 0.15:
        # Bağlantı sorunu: eksik veriyle eski dosyaların üstüne yazma, olduğu gibi bırak.
        raise RuntimeError(f"{len(basarisiz)}/{len(istekler)} istek indirilemedi; eski veri korunuyor")
    hazir = {k: v or [] for k, v in hazir.items()}
    # Ayrıştırma sağlam mı? indir() her maçı okunur hâle çevirip döndürür; okunamayanlar düşer.
    # Normalde binlerce maç gelir; çok azı geldiyse hiçbir dosyaya dokunma.
    toplam = sum(len(v) for v in hazir.values())
    if toplam < 1000:
        raise RuntimeError(f"maç verisi okunamadı (yalnızca {toplam} maç geldi); eski veri korunuyor")
    for div, (lig, ad) in LIGLER.items():
        maclar = {}
        for yil in (bas - 1, bas, bas + 1):
            for m in hazir[(lig, yil)]:
                maclar[m["id"]] = m
        ozet = []
        for sezon in (bas, bas - 1):
            oynanan = sorted((m for m in maclar.values() if m["sezon"] == sezon and m["bitti"]),
                             key=lambda m: m["z"])
            if not oynanan:
                continue
            kod = f"{sezon % 100:02d}{(sezon + 1) % 100:02d}"
            with atomik_yaz(os.path.join(KLASOR, f"{div}_{kod}.csv")) as f:
                w = csv.writer(f)
                w.writerow(["Div", "Date", "Time", "HomeTeam", "AwayTeam",
                            "FTHG", "FTAG", "HTHG", "HTAG", "HC", "AC"] + EK_SUTUN)
                for m in oynanan:
                    w.writerow([div, m["z"].strftime("%d/%m/%Y"), m["z"].strftime("%H:%M"), m["ev"], m["dep"],
                                m["hg"], m["ag"], m["hthg"], m["htag"], m["hc"], m["ac"]]
                               + m["ek"] + [m["kart"][0], m["kart"][2], m["kart"][1], m["kart"][3]])
                    if sezon == bas:
                        olaylar += [(div, m["z"].strftime("%d/%m/%Y"), *o) for o in m["olay"]]
            ozet.append(f"{kod}: {len(oynanan)} maç (son {oynanan[-1]['z']:%d/%m})")
        gelecek = [m for m in maclar.values()
                   if m["sezon"] == bas and fiksturde(m, bugun)]
        fikstur += [(div, m) for m in gelecek]
        yaz(f"  {div:<4}{ad:<26}{' | '.join(ozet) or 'sonuç yok'} | {len(gelecek)} gelecek maç")

    # Bu sezonun oyuncu olayları (kart ve gol): cezalı tahmini ve golcü payı için
    with atomik_yaz(os.path.join(KLASOR, "olaylar.csv")) as f:
        w = csv.writer(f)
        w.writerow(["Div", "Date", "Team", "PlayerId", "Player", "Tip"])
        w.writerows(olaylar)

    # Milli maçlar: son ~2.5 yılın bütün turnuvaları tek dosyada
    maclar = {}
    for lig in MILLI:
        for yil in range(bas - 2, bas + 2):
            for m in hazir[(lig, yil)]:
                maclar[m["id"]] = m
    oynanan = sorted((m for m in maclar.values() if m["bitti"]), key=lambda m: m["z"])
    kod = f"{bas % 100:02d}{(bas + 1) % 100:02d}"
    with atomik_yaz(os.path.join(KLASOR, f"{MILLI_KOD}_{kod}.csv")) as f:
        w = csv.writer(f)
        w.writerow(["Div", "Date", "Time", "HomeTeam", "AwayTeam",
                    "FTHG", "FTAG", "HTHG", "HTAG", "HC", "AC"] + EK_SUTUN)
        for m in oynanan:
            w.writerow([MILLI_KOD, m["z"].strftime("%d/%m/%Y"), m["z"].strftime("%H:%M"), m["ev"], m["dep"],
                        m["hg"], m["ag"], m["hthg"], m["htag"], m["hc"], m["ac"]]
                       + m["ek"] + [m["kart"][0], m["kart"][2], m["kart"][1], m["kart"][3]])
    gelecek = [m for m in maclar.values() if fiksturde(m, bugun)]
    fikstur += [(MILLI_KOD, m) for m in gelecek]
    son = f"(son {oynanan[-1]['z']:%d/%m})" if oynanan else ""
    yaz(f"  {MILLI_KOD:<4}{'Milli maçlar':<26}{len(oynanan)} maç {son} | {len(gelecek)} gelecek maç")

    fikstur.sort(key=lambda x: (x[1]["z"], x[0]))
    with atomik_yaz(os.path.join(KLASOR, "fixtures.csv")) as f:
        w = csv.writer(f)
        w.writerow(["Div", "Date", "Time", "HomeTeam", "AwayTeam",
                    "AvgH", "AvgD", "AvgA", "Avg>2.5", "Avg<2.5", "EventId", "Espn"])
        for div, m in fikstur:
            o = m["oran"]
            w.writerow([div, m["z"].strftime("%d/%m/%Y"), m["z"].strftime("%H:%M"), m["ev"], m["dep"],
                        o["h"], o["d"], o["a"], o["ust"], o["alt"], m["id"], m["espn"]])
    oranli = sum(1 for _, m in fikstur if m["oran"]["h"])
    yaz(f"Fikstür: {len(fikstur)} gelecek maç yazıldı ({oranli} tanesinde oran var).")
    gunler = sorted({m["z"].date() for _, m in fikstur})[:10]
    if gunler:
        yaz("En yakın maç günleri: " + ", ".join(f"{g:%d/%m}" for g in gunler))


if __name__ == "__main__":
    main()
