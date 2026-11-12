"""
Site asistanı: ziyaretçinin Türkçe sorusunu anahtar kelimelerle anlar ve sitedeki tahmin
verisinden cevap üretir. Bir dil modeli DEĞİLDİR; internete çıkmaz, yalnızca uygulamanın
hesapladığı olasılıkları, fikstürü, puan durumunu ve karneyi kullanır.

Dışarıya açık tek işlev: cevapla(soru, u)  ->  dict(cevap, maclar, secenekler)
`u`, uygulama modülüdür (analiz, mac_analiz, fikstur_bilgi, karne, canli, lig_sayfa ... için).
"""
import re
from datetime import date, timedelta

GENEL_KELIME = {"united", "city", "real", "sporting", "club", "spor", "athletic", "town", "county", "rovers",
                "wanderers", "inter", "olympique", "racing", "union", "saint", "royal", "deportivo", "atletico",
                "borussia", "bayer", "eintracht", "stade", "sport", "santa", "north", "south", "west", "east"}
TAKMA_AD = {"gs": "galatasaray", "cimbom": "galatasaray", "fb": "fenerbahce", "fener": "fenerbahce",
            "bjk": "besiktas", "kartal": "besiktas", "ts": "trabzonspor", "trabzon": "trabzonspor",
            "milli takim": "turkiye", "milliler": "turkiye", "barca": "barcelona", "manu": "manchester united",
            "bayern": "bayern munih", "basaksehir": "basaksehir", "rize": "caykur rizespor", "kizilyildiz": "kizilyildiz",
            "psg": "paris saint-germain"}
ONERILER = ["Bugün hangi maçlar var?", "Sağlam 3 maçlık kupon", "Galatasaray kazanır mı?", "Tahminler ne kadar tutuyor?"]
UYARI = "Bunlar istatistik modelinin hesabıdır; garanti değildir, bahis tavsiyesi sayılmaz."

_onbellek = {}


def yz(p):
    return f"%{round(p * 100)}"


def takim_dizini(u):
    """Fikstürdeki takımlar: sade ad -> (görünen ad, [(tarih, lig, ev, dep)...])."""
    fb = u.fikstur_bilgi()
    if _onbellek.get("vz") == fb["vz"]:
        return _onbellek["dizin"]
    bugun, dizin = date.today(), {}
    for (div, ev, dep, d) in fb["kimlik"]:
        if d < bugun:
            continue
        for t in (ev, dep):
            dizin.setdefault(u.sade(t), (t, []))[1].append((d, div, ev, dep))
    for _, liste in dizin.values():
        liste.sort()
    _onbellek.update(vz=fb["vz"], dizin=dizin)
    return dizin


def takimlari_bul(q, u):
    """Soruda geçen takımlar, en iyi eşleşenden başlayarak (en fazla 2)."""
    for kisa, uzun in TAKMA_AD.items():
        q = re.sub(rf"\b{re.escape(kisa)}\b", uzun, q)
    bulunan = []
    for sade_ad, (ad, liste) in takim_dizini(u).items():
        puan = 0
        if sade_ad in q:
            puan = 100 + len(sade_ad)
        else:
            for parca in re.split(r"[^a-z0-9]+", sade_ad):
                if len(parca) >= 5 and parca not in GENEL_KELIME and parca in q:
                    puan = max(puan, len(parca))
        if puan:
            bulunan.append((puan, ad, liste))
    bulunan.sort(key=lambda x: -x[0])
    secilen = []
    for puan, ad, liste in bulunan:
        if all(ad not in s[0] and s[0] not in ad for s in secilen):
            secilen.append((ad, liste))
        if len(secilen) == 2:
            break
    return secilen


def gun_bul(q, bugun):
    if "yarin" in q:
        return bugun + timedelta(days=1), "yarın"
    if "bugun" in q or "bu aksam" in q or "bu gece" in q:
        return bugun, "bugün"
    if "hafta sonu" in q or "haftasonu" in q or "cumartesi" in q:
        return bugun + timedelta(days=(5 - bugun.weekday()) % 7), "cumartesi"
    if "pazar" in q.split():
        return bugun + timedelta(days=(6 - bugun.weekday()) % 7), "pazar"
    return None, ""


def tarih_yaz(d):
    aylar = ["Ocak", "Şubat", "Mart", "Nisan", "Mayıs", "Haziran", "Temmuz", "Ağustos", "Eylül", "Ekim", "Kasım", "Aralık"]
    gunler = ["Pazartesi", "Salı", "Çarşamba", "Perşembe", "Cuma", "Cumartesi", "Pazar"]
    return f"{d.day} {aylar[d.month - 1]} {gunler[d.weekday()]}"


def mac_getir(u, d, div, ev, dep):
    for fx in u.g.fikstur_yukle(u.FIKSTUR, d, [div]):
        if fx["ev"] == ev and fx["dep"] == dep:
            sonuc, _ = u.mac_analiz(fx, d, date.today())
            return sonuc
    return None


def mac_baglantisi(d, div, ev, dep):
    return dict(tarih=d.isoformat(), div=div, ev=ev, dep=dep)


# ---------------------------------------------------------------- tek maç soruları
def mac_cevabi(q, u, takimlar):
    ad, liste = takimlar[0]
    secim = liste[0]
    if len(takimlar) == 2:   # iki takım birlikte sorulduysa aralarındaki maçı bul
        ortak = [m for m in liste if takimlar[1][0] in (m[2], m[3])]
        if ortak:
            secim = ortak[0]
    d, div, ev, dep = secim
    m = mac_getir(u, d, div, ev, dep)
    baslik = f"{ev} – {dep} ({tarih_yaz(d)}, {u.LIG_ADI.get(div, div)})"
    bag = [mac_baglantisi(d, div, ev, dep)]
    if not m:
        return dict(cevap=f"{baslik}\nBu maç için yeterli geçmiş veri yok, tahmin üretemiyorum.", maclar=bag)
    ms, ev_mi = m["ms"], ad == ev
    kendi = ms["1"] if ev_mi else ms["2"]
    rakip = dep if ev_mi else ev
    satir = [baslik]

    if re.search(r"kazan|yener|galip|alir mi|yenilir|kaybeder|maglup|berabere|kim al", q):
        yorum = ("net favori" if kendi >= 0.6 else "hafif favori" if kendi >= 0.45 else
                 "dengeli bir maç, favori değil" if kendi >= 0.33 else "zor bir maç, favori değil")
        satir.append(f"{ad} kazanır: {yz(kendi)} — {yorum}.")
        satir.append(f"Beraberlik {yz(ms['X'])}, {rakip} kazanır {yz(ms['2'] if ev_mi else ms['1'])}.")
        satir.append(f"En olası skor {m['skor'][0][0]} ({yz(m['skor'][0][1])}).")
    elif re.search(r"kg|karsilikli", q):
        kg = m["gol"]["KG Var"]
        satir.append(f"Karşılıklı gol olur: {yz(kg)}, olmaz: {yz(1 - kg)}.")
        satir.append(f"Beklenen gol {m['lh']:.1f} – {m['la']:.1f}.")
    elif re.search(r"korner", q):
        if m.get("korner"):
            satir.append(f"Beklenen korner {m['kor'][0]:.1f} – {m['kor'][1]:.1f} (toplam {sum(m['kor']):.1f}).")
            satir.append("  ".join(f"{k}: {yz(v)}" for k, v in list(m["korner"].items())[:4]))
        else:
            satir.append("Bu maç için korner verisi yok.")
    elif re.search(r"kart", q):
        if m.get("kart"):
            satir.append(f"Beklenen kart {m['kart_b'][0]:.1f} – {m['kart_b'][1]:.1f}.")
            satir.append("  ".join(f"{k}: {yz(v)}" for k, v in list(m["kart"].items())[:3]))
        else:
            satir.append("Bu maç için kart verisi yok.")
    elif re.search(r"cezali|eksik|sakat|kadro|ilk 11", q):
        ceza = m.get("cezali") or {}
        bulundu = False
        for t in (ev, dep):
            for c in ceza.get(t, []):
                satir.append(f"{t}: {c['ad']} cezalı görünüyor ({c['neden']}).")
                bulundu = True
            sinir = (m.get("sinirda") or {}).get(t) or []
            if sinir:
                satir.append(f"{t} – sarı kart sınırında: {', '.join(sinir[:4])}.")
                bulundu = True
        if not bulundu:
            satir.append("Kart kayıtlarına göre cezalı ya da sınırda oyuncu görünmüyor.")
        satir.append("Sakatlıkları bilemem; ilk 11'ler maçtan yaklaşık bir saat önce sitede görünür.")
    elif re.search(r"ust|alt|gol|skor|kac kac|biter", q):
        ust = m["gol"]["Üst 2.5"]
        satir.append(f"Beklenen gol {m['lh']:.1f} – {m['la']:.1f}.")
        satir.append(f"Üst 2.5: {yz(ust)}, Alt 2.5: {yz(1 - ust)}. Üst 1.5: {yz(m['gol']['Üst 1.5'])}, Üst 3.5: {yz(m['gol']['Üst 3.5'])}.")
        satir.append("En olası skorlar: " + ", ".join(f"{s} ({yz(p)})" for s, p in m["skor"][:3]) + ".")
    else:
        satir.append(f"{ev} {yz(ms['1'])} · beraberlik {yz(ms['X'])} · {dep} {yz(ms['2'])}.")
        satir.append(f"Beklenen gol {m['lh']:.1f} – {m['la']:.1f}; Üst 2.5 {yz(m['gol']['Üst 2.5'])}, KG Var {yz(m['gol']['KG Var'])}.")
        satir.append(f"En olası skor {m['skor'][0][0]}.")
        adet = sum(len(v) for v in (m.get("cezali") or {}).values())
        if adet:
            satir.append(f"Bu maçta {adet} cezalı oyuncu görünüyor.")
    if m.get("kaba"):
        satir.append("Not: bu turnuvada takım başına az maç olduğu için tahmin kabadır.")
    return dict(cevap="\n".join(satir), maclar=bag,
                secenekler=[f"{ad} maçı kaç gol olur?", f"{ad} maçında cezalı var mı?", "Sağlam 3 maçlık kupon"])


# ---------------------------------------------------------------- kupon
def kupon_cevabi(q, u):
    bugun = date.today()
    risk = ("dusuk" if re.search(r"saglam|banko|garanti|dusuk|guvenli|temkinli", q) else
            "orta" if re.search(r"orta|dengeli|normal", q) else
            "yuksek" if re.search(r"surpriz|yuksek|riskli|buyuk oran|cilgin", q) else None)
    sayi = re.search(r"\b([2-6])\b", q)
    adet = int(sayi.group(1)) if sayi else 3
    if risk is None:
        return dict(cevap="Nasıl bir kupon istersin? Risk seviyesini seç; maç sayısını da yazabilirsin (örneğin \"sağlam 4 maç\").",
                    maclar=[], secenekler=[f"Sağlam {adet} maçlık kupon", f"Orta riskli {adet} maçlık kupon", f"Sürpriz {adet} maçlık kupon"])
    hedef, gun_adi = gun_bul(q, bugun)
    gunler = [d for d in u.fikstur_bilgi()["gunler"] if d >= (hedef or bugun)][:10]   # o gün maç yoksa sonraki günlere bakar
    adaylar, secilen_gun, son_gun = [], None, None
    for d in gunler:
        if secilen_gun and (d - secilen_gun).days > 3:   # kuponu en fazla dört güne yay
            break
        onceki = len(adaylar)
        for m in u.analiz(d)["maclar"]:
            if m["kaba"] or m["sapma"]:
                continue
            ms, gol = m["ms"], m["gol"]
            secimler = [(f"{m['ev']} kazanır", ms["1"]), ("Beraberlik", ms["X"]), (f"{m['dep']} kazanır", ms["2"])]
            if risk != "yuksek":
                secimler += [(f"{m['ev']} kaybetmez (1X)", ms["1"] + ms["X"]), (f"{m['dep']} kaybetmez (X2)", ms["X"] + ms["2"]),
                             ("Üst 2.5", gol["Üst 2.5"]), ("Alt 2.5", gol["Alt 2.5"]), ("Üst 1.5", gol["Üst 1.5"]),
                             ("KG Var", gol["KG Var"]), ("KG Yok", 1 - gol["KG Var"])]
            aralik = {"dusuk": (0.72, 0.93), "orta": (0.55, 0.72), "yuksek": (0.30, 0.50)}[risk]
            uygun = [s for s in secimler if aralik[0] <= s[1] <= aralik[1]]
            if uygun:
                en_iyi = max(uygun, key=lambda s: s[1])
                adaylar.append((en_iyi[1], en_iyi[0], m, d))
        if len(adaylar) > onceki:
            secilen_gun, son_gun = secilen_gun or d, d
        if len(adaylar) >= adet:
            break
    if len(adaylar) < 2:
        return dict(cevap="Bu kriterlere uyan yeterli maç bulamadım. Başka bir gün ya da risk seviyesi dener misin?",
                    maclar=[], secenekler=["Orta riskli 3 maçlık kupon", "Hafta sonu sağlam kupon"])
    adaylar.sort(key=lambda a: -a[0])
    kupon = adaylar[:adet]
    toplam, adil = 1.0, 1.0
    risk_adi = {"dusuk": "Sağlam", "orta": "Orta riskli", "yuksek": "Sürpriz"}[risk]
    gunler_k = sorted({d for _, _, _, d in kupon})
    aralik_yazi = tarih_yaz(gunler_k[0]) + (f" – {tarih_yaz(gunler_k[-1])}" if len(gunler_k) > 1 else "")
    satir = [f"{risk_adi} kupon – {aralik_yazi}"]
    for p, secim, m, d in kupon:
        toplam *= p
        adil *= 1 / p
        gun_eki = f" [{d.day}.{d.month:02d}]" if len(gunler_k) > 1 else ""
        satir.append(f"• {m['ev']} – {m['dep']}{gun_eki}: {secim} ({yz(p)}, adil oran {1 / p:.2f})")
    satir.append(f"Hepsinin birlikte tutma ihtimali modele göre {yz(toplam)}; adil toplam oran {adil:.2f}.")
    if len(kupon) < adet:
        satir.append(f"Bu kritere uyan yalnızca {len(kupon)} maç vardı.")
    satir.append("Bahis sitesindeki oran adil orandan düşükse o seçim değerli değildir. " + UYARI)
    return dict(cevap="\n".join(satir), maclar=[mac_baglantisi(d, m["div"], m["ev"], m["dep"]) for _, _, m, d in kupon],
                secenekler=["Orta riskli 3 maçlık kupon", "Sürpriz 3 maçlık kupon", "Tahminler ne kadar tutuyor?"])


# ---------------------------------------------------------------- liste, canlı, puan durumu, karne
def gun_listesi(q, u):
    bugun = date.today()
    hedef, gun_adi = gun_bul(q, bugun)
    hedef = hedef or bugun
    maclar = u.analiz(hedef)["maclar"]
    if not maclar:
        sonraki = next((d for d in u.fikstur_bilgi()["gunler"] if d > hedef), None)
        ek = f" En yakın maç günü {tarih_yaz(sonraki)}." if sonraki else ""
        return dict(cevap=f"{tarih_yaz(hedef)} için fikstürde maç yok.{ek}", maclar=[],
                    secenekler=["Hafta sonu hangi maçlar var?", "Sağlam 3 maçlık kupon"])
    onemli = sorted(maclar, key=lambda m: (m["kaba"], m["saat"]))[:10]
    satir = [f"{tarih_yaz(hedef)} – {len(maclar)} maç" + (" (ilk 10)" if len(maclar) > 10 else "")]
    for m in onemli:
        fav = max(m["ms"], key=m["ms"].get)
        fav_ad = {"1": m["ev"], "X": "beraberlik", "2": m["dep"]}[fav]
        satir.append(f"• {m['saat']} {m['ev']} – {m['dep']}: favori {fav_ad} {yz(m['ms'][fav])}")
    return dict(cevap="\n".join(satir), maclar=[mac_baglantisi(hedef, m["div"], m["ev"], m["dep"]) for m in onemli],
                secenekler=["Sağlam 3 maçlık kupon", "Şu an oynanan maç var mı?"])


def canli_cevabi(u):
    bugun = date.today()
    durum = u.canli(bugun)
    ad = {m["eid"]: m for m in u.analiz(bugun)["maclar"]}
    oynanan = [(ad[e], c) for e, c in durum.items() if c["durum"] == "in" and e in ad]
    biten = [(ad[e], c) for e, c in durum.items() if c["durum"] == "post" and e in ad]
    if not oynanan and not biten:
        return dict(cevap="Şu anda oynanan ya da bugün bitmiş maç yok.", maclar=[], secenekler=["Bugün hangi maçlar var?"])
    satir = []
    if oynanan:
        satir.append("Şu an oynanıyor:")
        satir += [f"• {c['dakika']} {m['ev']} {c['skor'][0]} – {c['skor'][1]} {m['dep']}" for m, c in oynanan]
    if biten:
        satir.append("Bugün biten:")
        satir += [f"• {m['ev']} {c['skor'][0]} – {c['skor'][1]} {m['dep']}" for m, c in biten[:8]]
    satir.append("Ayrıntılar Canlı sekmesinde.")
    return dict(cevap="\n".join(satir), maclar=[mac_baglantisi(bugun, m["div"], m["ev"], m["dep"]) for m, _ in (oynanan + biten)[:8]],
                secenekler=["Bugün hangi maçlar var?"])


def puan_cevabi(q, u, takimlar):
    div = None
    if takimlar:
        ligler = [m[1] for m in takimlar[0][1] if m[1] not in u.KABA_LIGLER]
        div = ligler[0] if ligler else None
    else:
        for kod, adi in u.LIG_ADI.items():
            if any(k in q for k in u.sade(adi).split() if len(k) >= 5 and k not in ("ligi", "super")):
                div = kod
                break
        div = div or "T1"
    if not div:
        return None
    tablo = u.lig_sayfa(div)["tablo"]
    if not tablo:
        return None
    satir = [f"{u.LIG_ADI[div]} puan durumu"]
    if takimlar:
        t = next((x for x in tablo if x["takim"] == takimlar[0][0]), None)
        if t:
            satir.append(f"{t['takim']} {t['sira']}. sırada: {t['o']} maçta {t['p']} puan, gol {t['ag']}-{t['yg']}.")
    satir += [f"{x['sira']}. {x['takim']} – {x['p']} puan" for x in tablo[:5]]
    return dict(cevap="\n".join(satir) + "\nTamamı Ligler sekmesinde.", maclar=[], secenekler=["Sağlam 3 maçlık kupon"])


def karne_cevabi(u):
    k = u.karne()
    if not k["n"]:
        return dict(cevap="Karne için yeterli oynanmış maç yok.", maclar=[])
    satir = [f"Son {k['gun']} günde {k['n']} lig maçı değerlendirildi.",
             f"Model favoriyi {yz(k['isabet'])} oranında bildi; Alt/Üst 2.5'te {yz(k['ust_isabet'])}."]
    satir += [f"• {d['ad']}: {d['n']} maçın {yz(d['isabet'])}'i tuttu" for d in k["dilimler"]]
    satir.append("Ayrıntılar Karne sekmesinde. Geçmişteki isabet gelecek için garanti değildir.")
    return dict(cevap="\n".join(satir), maclar=[], secenekler=["Sağlam 3 maçlık kupon", "Bugün hangi maçlar var?"])


# ---------------------------------------------------------------- giriş noktası
def cevapla(soru, u):
    q = u.sade(soru.strip())[:300]
    q = re.sub(r"[^a-z0-9 .]+", " ", q)
    q = re.sub(r"\s+", " ", q).strip()
    sonuc = None
    if not q:
        sonuc = dict(cevap="Bir soru yaz; örneğin bir takımın maçını ya da kupon önerisi sorabilirsin.", maclar=[])
    else:
        takimlar = takimlari_bul(q, u)
        if "kupon" in q or "kombine" in q or "banko" in q:
            sonuc = kupon_cevabi(q, u)
        elif re.search(r"karne|tutuyor|isabet|basari|guvenilir|ne kadar dogru", q):
            sonuc = karne_cevabi(u)
        elif re.search(r"puan durumu|lider|kacinci|siralama|kume du", q):
            sonuc = puan_cevabi(q, u, takimlar)
        elif takimlar:
            sonuc = mac_cevabi(q, u, takimlar)
        elif re.search(r"canli|su an|oynanan|devam eden", q):
            sonuc = canli_cevabi(u)
        elif re.search(r"mac|fikstur|program|kimler oynuyor|bugun|yarin|hafta sonu", q):
            sonuc = gun_listesi(q, u)
        elif re.search(r"merhaba|selam|naber|kimsin|ne yapabil|yardim|neler sor", q):
            sonuc = dict(cevap="Merhaba, ben sitenin maç asistanıyım. Sitedeki tahminlerden cevap veririm: bir takımın sıradaki maçı, "
                               "kazanma ihtimali, gol ve korner beklentisi, cezalılar, puan durumu, canlı skor ve kupon önerisi sorabilirsin.",
                         maclar=[])
    if not sonuc:
        sonuc = dict(cevap="Bunu anlayamadım. Takım adı yazarak maç sorabilir ya da aşağıdaki örneklerden birini deneyebilirsin. "
                           "Genel sohbet edemem ve internette araştırma yapamam; yalnızca sitedeki verilerden cevap veririm.", maclar=[])
    sonuc.setdefault("maclar", [])
    sonuc.setdefault("secenekler", ONERILER)
    return sonuc
