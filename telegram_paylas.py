"""Günün öne çıkan maçlarını Telegram kanalına gönderir.

Her sabah GitHub Actions tarafından çalıştırılır (.github/workflows/telegram.yml).
Elle denemek için:  TELEGRAM_TOKEN=... python3 telegram_paylas.py   (--dene: göndermeden yazdır)
Token kodda veya depoda DURMAZ; ortam değişkeninden ya da ~/.config/mac-analizi/telegram_token dosyasından okunur.
"""
import html
import json
import os
import sys
import time
import urllib.parse
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone

SITE = "https://mac-analizi.onrender.com"
KANAL = os.environ.get("TELEGRAM_KANAL", "@macanliz")
TR = timezone(timedelta(hours=3))
GUN = ["Pazartesi", "Salı", "Çarşamba", "Perşembe", "Cuma", "Cumartesi", "Pazar"]
AY = ["Ocak", "Şubat", "Mart", "Nisan", "Mayıs", "Haziran", "Temmuz", "Ağustos", "Eylül", "Ekim", "Kasım", "Aralık"]
# Önce gösterilecek ligler (kod: veri_indir.LIGLER anahtarları)
ONCELIK = ["T1", "CL", "EL", "ECL", "E0", "SP1", "I1", "D1", "F1", "N1", "P1", "B1", "MIL"]


def token():
    t = os.environ.get("TELEGRAM_TOKEN", "").strip()
    if not t:
        yol = os.path.expanduser("~/.config/mac-analizi/telegram_token")
        if os.path.exists(yol):
            t = open(yol).read().strip()
    if not t:
        sys.exit("TELEGRAM_TOKEN bulunamadı")
    return t


def getir(yol, deneme=1):
    istek = urllib.request.Request(SITE + yol, headers={"User-Agent": "mac-analizi-telegram"})
    with urllib.request.urlopen(istek, timeout=90) as r:
        return json.loads(r.read())


def veriyi_bekle():
    """Ücretsiz sunucu uyuyor olabilir: uyandır, veri indirmesi bitene kadar bekle (en fazla ~8 dk)."""
    for _ in range(32):
        try:
            d = getir("/api/durum")
            if not d.get("guncelleniyor") and d.get("veri_zamani"):
                return
        except Exception as e:
            print("bekleniyor:", e)
        time.sleep(15)
    print("uyarı: veri hazır olmadı, eldekiyle devam ediliyor")


yz = lambda p: f"%{p * 100:.0f}"
e = html.escape


def mesaj_yaz(veri, tarih):
    simdi = datetime.now(TR).strftime("%Y-%m-%dT%H:%M")
    maclar = [m for m in veri["maclar"] if (m.get("baslama") or "9") >= simdi]   # yalnızca henüz başlamamış maçlar
    if not maclar:
        return None
    gun = f"{tarih.day} {AY[tarih.month - 1]} {GUN[tarih.weekday()]}"
    net = [m for m in maclar if not m.get("kaba")]
    havuz = net if len(net) >= 3 else maclar
    fav = lambda m: max(m["ms"].values())
    fav_ad = lambda m: m["ev"] if m["ms"]["1"] >= m["ms"]["2"] else m["dep"]

    satir = [f"⚽ <b>{e(gun)} – Günün maçları</b>", ""]
    if len(havuz) >= 3:
        secim, kullanilan = [], set()
        def ekle(baslik, m, aciklama):
            if id(m) not in kullanilan:
                kullanilan.add(id(m))
                secim.append(f"▪️ <b>{baslik}:</b> {e(m['ev'])} – {e(m['dep'])} ({e(aciklama)})")
        m = max(havuz, key=fav); ekle("En net favori", m, f"{fav_ad(m)} {yz(fav(m))}")
        m = max(havuz, key=lambda m: m["lh"] + m["la"]); ekle("En gollü beklenen", m, f"Üst 2.5 {yz(m['gol']['Üst 2.5'])}")
        m = min(havuz, key=fav); ekle("En dengeli maç", m, f"1 {yz(m['ms']['1'])} · X {yz(m['ms']['X'])} · 2 {yz(m['ms']['2'])}")
        satir += ["🔥 <b>Öne çıkanlar</b>"] + secim + [""]

    sira = {k: i for i, k in enumerate(ONCELIK)}
    secili = sorted(maclar, key=lambda m: (sira.get(m["div"], 99), m["saat"]))[:10]
    satir.append(f"📋 <b>Maçlar</b> ({len(maclar)} maçtan {len(secili)} tanesi)")
    son_lig = None
    for m in secili:
        if m["lig"] != son_lig:
            satir.append(f"<i>{e(m['lig'])}</i>")
            son_lig = m["lig"]
        satir.append(f"{m['saat']} {e(m['ev'])} – {e(m['dep'])} · 1 {yz(m['ms']['1'])} X {yz(m['ms']['X'])} 2 {yz(m['ms']['2'])}")
    adres = f"{SITE}/?tarih={tarih.isoformat()}"
    satir += ["", f'👉 <a href="{adres}">Bütün maçlar, olasılıklar ve canlı skor</a>',
              "", "<i>İstatistik modelinin hesabıdır; garanti değildir, bahis tavsiyesi sayılmaz.</i>"]
    return "\n".join(satir)


def gonder(metin):
    veri = urllib.parse.urlencode({"chat_id": KANAL, "text": metin, "parse_mode": "HTML",
                                   "disable_web_page_preview": "false"}).encode()
    istek = urllib.request.Request(f"https://api.telegram.org/bot{token()}/sendMessage", data=veri)
    with urllib.request.urlopen(istek, timeout=30) as r:
        sonuc = json.loads(r.read())
    if not sonuc.get("ok"):
        sys.exit(f"Telegram hatası: {sonuc}")
    print("gönderildi, mesaj no:", sonuc["result"]["message_id"])


KAYIT = os.path.expanduser("~/.config/mac-analizi/son_gonderim")   # aynı gün iki kez göndermemek için
SAHIP = os.path.expanduser("~/.config/mac-analizi/sahip_id")        # görselin özelden gideceği kişi
KARNE_KAYIT = os.path.expanduser("~/.config/mac-analizi/son_karne")


def tg(metod, alanlar=None, dosya=None):
    """Telegram Bot API çağrısı; dosya=(alan, ad, bayt, tür) verilirse multipart gönderir."""
    url = f"https://api.telegram.org/bot{token()}/{metod}"
    if dosya:
        sinir = "----macanalizi" + str(int(time.time() * 1000))
        govde = b""
        for k, v in (alanlar or {}).items():
            govde += f'--{sinir}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode()
        alan, ad, bayt, tur = dosya
        govde += (f'--{sinir}\r\nContent-Disposition: form-data; name="{alan}"; filename="{ad}"\r\n'
                  f"Content-Type: {tur}\r\n\r\n").encode() + bayt + f"\r\n--{sinir}--\r\n".encode()
        istek = urllib.request.Request(url, data=govde, headers={"Content-Type": f"multipart/form-data; boundary={sinir}"})
    else:
        istek = urllib.request.Request(url, data=urllib.parse.urlencode(alanlar or {}).encode())
    with urllib.request.urlopen(istek, timeout=60) as r:
        return json.loads(r.read())


def sahip_id():
    """Botu özelden 'Başlat'layan kişinin numarası (ilk bulunduğunda kaydedilir)."""
    if os.path.exists(SAHIP):
        return open(SAHIP).read().strip()
    for g in reversed(tg("getUpdates").get("result", [])):
        sohbet = (g.get("message") or {}).get("chat") or {}
        if sohbet.get("type") == "private":
            if os.path.isdir(os.path.dirname(SAHIP)):
                with open(SAHIP, "w") as f:
                    f.write(str(sohbet["id"]))
            return str(sohbet["id"])
    return None


def one_cikanlar(maclar):
    net = [m for m in maclar if not m.get("kaba")]
    havuz = net if len(net) >= 3 else maclar
    if len(havuz) < 3:
        return []
    fav = lambda m: max(m["ms"].values())
    fav_ad = lambda m: m["ev"] if m["ms"]["1"] >= m["ms"]["2"] else m["dep"]
    a = max(havuz, key=fav)
    b = max(havuz, key=lambda m: m["lh"] + m["la"])
    c = min(havuz, key=fav)
    sonuc, gorulen = [], set()
    for baslik, m, ust, deger in [("En net favori", a, f"En net favori · {fav_ad(a)}", yz(fav(a))),
                                  ("En gollü beklenen", b, "En gollü beklenen", "Ü2.5 " + yz(b["gol"]["Üst 2.5"])),
                                  ("En dengeli maç", c, "En dengeli maç", "X " + yz(c["ms"]["X"]))]:
        if id(m) not in gorulen:
            gorulen.add(id(m))
            sonuc.append(dict(m=m, ust=ust, deger=deger))
    return sonuc


def gorsel_yap(maclar, tarih):
    """Instagram/TikTok için 1080x1080 PNG (macOS'ta qlmanage ile SVG'den). Yapılamazsa None."""
    import shutil, subprocess, tempfile
    from xml.sax.saxutils import escape as x
    secim = one_cikanlar(maclar)
    if not secim or not shutil.which("qlmanage"):
        return None
    kisalt = lambda s, n: s if len(s) <= n else s[:n - 1] + "…"
    gun = f"{tarih.day} {AY[tarih.month - 1]} {GUN[tarih.weekday()]}"
    kartlar = ""
    for i, s in enumerate(secim):
        y = 330 + i * 190
        kartlar += (f'<rect x="60" y="{y}" width="960" height="165" rx="26" fill="#ffffff" fill-opacity="0.07"/>'
                    f'<text x="100" y="{y + 58}" font-size="30" fill="#9fc7b1">{x(kisalt(s["ust"], 40))}</text>'
                    f'<text x="100" y="{y + 118}" font-size="44" font-weight="700" fill="#ffffff">'
                    f'{x(kisalt(s["m"]["ev"] + " – " + s["m"]["dep"], 30))}</text>'
                    f'<text x="980" y="{y + 105}" font-size="52" font-weight="800" fill="#4cc38a" text-anchor="end">{x(s["deger"])}</text>')
    svg = f'''<svg xmlns="http://www.w3.org/2000/svg" width="1080" height="1080" viewBox="0 0 1080 1080"
  font-family="Helvetica Neue, Arial, sans-serif">
  <rect width="1080" height="1080" fill="#123524"/>
  <g transform="translate(60 60) scale(1.9)">
    <g fill="none" stroke-width="9" transform="rotate(-90 32 32)">
      <circle cx="32" cy="32" r="19" stroke="#4cc38a" stroke-dasharray="57 62.4"/>
      <circle cx="32" cy="32" r="19" stroke="#d5dcd7" stroke-dasharray="23 96.4" stroke-dashoffset="-60"/>
      <circle cx="32" cy="32" r="19" stroke="#7aa7ee" stroke-dasharray="30.4 89" stroke-dashoffset="-86"/>
    </g>
    <circle cx="32" cy="32" r="6.5" fill="#ffffff"/>
  </g>
  <text x="200" y="118" font-size="58" font-weight="700" fill="#ffffff">Maç Analizi</text>
  <text x="202" y="166" font-size="32" fill="#9fc7b1">{x(gun)}</text>
  <text x="60" y="280" font-size="60" font-weight="800" fill="#ffffff">Günün öne çıkanları</text>
  {kartlar}
  <text x="60" y="960" font-size="36" font-weight="700" fill="#ffffff">t.me/macanliz</text>
  <text x="1020" y="960" font-size="30" fill="#9fc7b1" text-anchor="end">mac-analizi.onrender.com</text>
  <text x="60" y="1020" font-size="24" fill="#9fc7b1">İstatistik modelinin hesabıdır; garanti değildir, bahis tavsiyesi sayılmaz.</text>
</svg>'''
    with tempfile.TemporaryDirectory() as klasor:
        yol = os.path.join(klasor, "gorsel.svg")
        with open(yol, "w", encoding="utf-8") as f:
            f.write(svg)
        subprocess.run(["qlmanage", "-t", "-s", "1080", "-o", klasor, yol], capture_output=True, timeout=60)
        png = yol + ".png"
        return open(png, "rb").read() if os.path.exists(png) else None


def gorsel_gonder(maclar, tarih):
    kisi = sahip_id()
    if not kisi:
        print("görsel gönderilmedi: bot henüz özelden başlatılmamış")
        return
    png = gorsel_yap(maclar, tarih)
    if not png:
        print("görsel üretilemedi")
        return
    sonuc = tg("sendPhoto", {"chat_id": kisi, "caption": "📲 Bugünün Instagram/TikTok görseli hazır. Uzun bas → Kaydet, sonra paylaş."},
               ("photo", f"mac-analizi-{tarih.isoformat()}.png", png, "image/png"))
    print("görsel özelden gönderildi" if sonuc.get("ok") else f"görsel hatası: {sonuc}")


def haftalik_karne(tarih):
    """Pazartesi: son 7 günde modelin ne kadar tuttuğunu kanala yazar (haftada bir kez)."""
    hafta = f"{tarih.isocalendar()[0]}-{tarih.isocalendar()[1]}"
    if tarih.weekday() != 0 or (os.path.exists(KARNE_KAYIT) and open(KARNE_KAYIT).read().strip() == hafta):
        return
    k = getir("/api/karne")
    bas = (tarih - timedelta(days=7)).isoformat()
    son = [m for m in k.get("maclar", []) if bas <= m["tarih"] < tarih.isoformat()]
    if len(son) < 10:
        return
    tut = sum(m["tuttu"] for m in son)
    emin = [m for m in son if m["guven"] >= 0.6]
    ust = [m for m in son if m.get("ust_tuttu") is not None]
    satir = [f"📊 <b>Haftalık karne</b> ({len(son)} maç)", "",
             f"▪️ Modelin favorisi kazandı: <b>{tut}/{len(son)}</b> (%{tut / len(son) * 100:.0f})"]
    if emin:
        t2 = sum(m["tuttu"] for m in emin)
        satir.append(f"▪️ Model çok emindi (%60+): <b>{t2}/{len(emin)}</b> (%{t2 / len(emin) * 100:.0f})")
    if ust:
        t3 = sum(1 for m in ust if m["ust_tuttu"])
        satir.append(f"▪️ 2.5 üst/alt tahmini: <b>{t3}/{len(ust)}</b> (%{t3 / len(ust) * 100:.0f})")
    satir += ["", "Tutmayanları da saklamıyoruz: bütün maçlar sitede, Karne sekmesinde 👇",
              f'<a href="{SITE}">mac-analizi.onrender.com</a>']
    if tg("sendMessage", {"chat_id": KANAL, "text": "\n".join(satir), "parse_mode": "HTML"}).get("ok"):
        print("haftalık karne gönderildi")
        if os.path.isdir(os.path.dirname(KARNE_KAYIT)):
            with open(KARNE_KAYIT, "w") as f:
                f.write(hafta)


def main():
    tarih = datetime.now(TR).date()
    deneme = "--dene" in sys.argv or os.environ.get("DENEME") == "true"
    if not deneme and os.path.exists(KAYIT) and open(KAYIT).read().strip() == tarih.isoformat():
        print("bugünün mesajı zaten gönderilmiş")
        return
    veriyi_bekle()
    veri = getir(f"/api/analiz?tarih={tarih.isoformat()}")
    metin = mesaj_yaz(veri, tarih)
    if not metin:
        print("bugün maç yok, mesaj gönderilmedi")
        return
    if deneme:
        print(metin)
        # Token doğru mu ve bot kanalda mesaj atabiliyor mu? (mesaj göndermeden kontrol)
        t = token()
        with urllib.request.urlopen(f"https://api.telegram.org/bot{t}/getMe", timeout=30) as r:
            bot = json.loads(r.read())["result"]
        uye = urllib.parse.urlencode({"chat_id": KANAL, "user_id": bot["id"]})
        with urllib.request.urlopen(f"https://api.telegram.org/bot{t}/getChatMember?{uye}", timeout=30) as r:
            durum = json.loads(r.read())["result"]
        print(f"\nDENEME TAMAM: bot @{bot['username']}, kanalda '{durum['status']}', mesaj atabilir: {durum.get('can_post_messages')}")
        return
    gonder(metin)
    if os.path.isdir(os.path.dirname(KAYIT)):
        with open(KAYIT, "w") as f:
            f.write(tarih.isoformat())
    # Ek işler: biri hata verse de günlük mesaj gitmiş olur
    simdi = datetime.now(TR).strftime("%Y-%m-%dT%H:%M")
    for is_, *arg in [(gorsel_gonder, [m for m in veri["maclar"] if (m.get("baslama") or "9") >= simdi], tarih),
                      (haftalik_karne, tarih)]:
        try:
            is_(*arg)
        except Exception as e:
            print(f"{is_.__name__} yapılamadı: {e}")


def hata_bildir(metin):
    """GitHub Actions'ta hatayı herkese açık 'annotation' olarak yaz (token asla yazılmaz)."""
    t = os.environ.get("TELEGRAM_TOKEN", "")
    if t:
        metin = metin.replace(t, "***")
    print(f"::error::{metin}" if os.environ.get("GITHUB_ACTIONS") else metin, flush=True)


if __name__ == "__main__":
    try:
        main()
    except SystemExit as e:
        if e.code not in (None, 0):
            hata_bildir(str(e.code))
        raise
    except urllib.error.HTTPError as e:
        hata_bildir(f"HTTP {e.code} {e.url.split('/bot')[0]}: {e.read()[:300]!r}")
        sys.exit(1)
    except Exception as e:
        hata_bildir(f"{type(e).__name__}: {e}")
        sys.exit(1)
