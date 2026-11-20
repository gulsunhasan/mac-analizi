#!/data/data/com.termux/files/usr/bin/bash
# Maç Analizi – tablet (Termux) kurulumu.
# Termux'ta tek satır:  curl -sL https://raw.githubusercontent.com/gulsunhasan/mac-analizi/main/tablet_kur.sh | bash
# Ne yapar: gerekli programları kurar, Mac'in bu tablete Wi-Fi üzerinden bağlanmasına izin verir
# (yalnızca aşağıdaki Mac anahtarıyla; şifreyle giriş kapalı), tabletin uyumasını engeller.
set -e
echo "==> Programlar kuruluyor (birkaç dakika sürebilir)..."
yes | pkg update -y >/dev/null 2>&1 || true
yes | pkg install -y python git openssh cronie termux-services termux-api iproute2 >/dev/null 2>&1 || \
  yes | pkg install -y python git openssh cronie termux-services iproute2

echo "==> Mac'e bağlantı izni veriliyor..."
mkdir -p ~/.ssh && chmod 700 ~/.ssh
ANAHTAR='ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAICPf11xJA8sbrGwLvGdfwp0vN1T6khHL3ptLXX/31NgL mac-analizi-mac'
touch ~/.ssh/authorized_keys && chmod 600 ~/.ssh/authorized_keys
grep -qF "$ANAHTAR" ~/.ssh/authorized_keys || echo "$ANAHTAR" >> ~/.ssh/authorized_keys
SSHD=$PREFIX/etc/ssh/sshd_config
grep -q "^PasswordAuthentication no" $SSHD || echo "PasswordAuthentication no" >> $SSHD

echo "==> Arka plan servisleri açılıyor..."
mkdir -p ~/.config/mac-analizi && chmod 700 ~/.config/mac-analizi
[ -d ~/mac-analizi ] || git clone -q https://github.com/gulsunhasan/mac-analizi.git ~/mac-analizi
# Termux açılınca sshd ve zamanlayıcı kendiliğinden başlasın
grep -q "mac-analizi" ~/.bashrc 2>/dev/null || cat >> ~/.bashrc <<'B'
# mac-analizi: servisler
pgrep -x sshd >/dev/null || sshd
pgrep -x crond >/dev/null || crond
command -v termux-wake-lock >/dev/null && termux-wake-lock
B
pgrep -x sshd >/dev/null || sshd
pgrep -x crond >/dev/null || crond
command -v termux-wake-lock >/dev/null && termux-wake-lock || true

IP=$(ip -4 addr show wlan0 2>/dev/null | awk '/inet /{print $2}' | cut -d/ -f1)
echo
echo "=========================================="
echo " KURULUM TAMAM"
echo " Claude'a şunu yaz:  tablet $(whoami)@${IP:-IP_BULUNAMADI}"
echo "=========================================="
