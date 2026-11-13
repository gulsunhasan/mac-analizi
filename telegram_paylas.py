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


def main():
    tarih = datetime.now(TR).date()
    veriyi_bekle()
    veri = getir(f"/api/analiz?tarih={tarih.isoformat()}")
    metin = mesaj_yaz(veri, tarih)
    if not metin:
        print("bugün maç yok, mesaj gönderilmedi")
        return
    if "--dene" in sys.argv or os.environ.get("DENEME") == "true":
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


if __name__ == "__main__":
    main()
