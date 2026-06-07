#!/usr/bin/env bash
# veil — установка анти-DPI VLESS+Reality ноды с подписками и split-routing (без домена).
# Ставит: Xray-core + mini-sub (раздача профилей) + veil CLI + список РУ-маршрутов.
# Все ключи генерируются ЛОКАЛЬНО. Запуск: sudo bash install.sh
set -euo pipefail

GREEN='\033[0;32m'; YEL='\033[1;33m'; RED='\033[0;31m'; CY='\033[0;36m'; BOLD='\033[1m'; NC='\033[0m'
say()  { echo -e "${CY}  >>${NC} ${BOLD}$*${NC}"; }
ok()   { echo -e "${GREEN}     [OK]${NC} $*"; }
warn() { echo -e "${YEL}     [!!]${NC} $*"; }
die()  { echo -e "${RED}ERR:${NC} $*" >&2; exit 1; }

banner(){ echo -e "${CY}"; cat <<'B'
     __   __ ___ ___ _
     \ \ / /| __|_ _| |
      \ V / | _| | || |__
       \_/  |___|___|____|
        anti-DPI - VLESS + Reality - split-routing
B
echo -e "${NC}"; }

banner
[ "$(id -u)" = "0" ] || die "запусти от root (sudo bash install.sh)"

XRAY_CONF=/usr/local/etc/xray/config.json
VEIL=/etc/veil
META=$VEIL/server.env
PORT_OB=2087          # [Обычный] packet-up   (Cloudflare-HTTPS-alt, отлично от fleet 2096)
PORT_US=2083          # [Усиленный] xmux auto  (Cloudflare-HTTPS-alt, отлично от fleet 8443)
SUB_PORT=8081         # раздача подписок        (отлично от fleet 8080)
SNI=learn.microsoft.com
REPO_DIR="$(cd "$(dirname "$0")" && pwd)"

# ── 1. зависимости ──────────────────────────────────────────────────────────
say "Проверяю зависимости…"
command -v apt-get >/dev/null || die "нужен apt (Debian/Ubuntu). Другие дистрибутивы пока не поддержаны."
export DEBIAN_FRONTEND=noninteractive
# команда -> apt-пакет (если команда называется иначе)
declare -A PKG=( [jq]=jq [qrencode]=qrencode [python3]=python3 [openssl]=openssl [curl]=curl [git]=git )
need=()
for c in "${!PKG[@]}"; do command -v "$c" >/dev/null 2>&1 || need+=("${PKG[$c]}"); done
if [ ${#need[@]} -gt 0 ]; then
  say "Доустанавливаю: ${need[*]} ca-certificates"
  apt-get update -qq || die "apt-get update не прошёл (проверь сеть/репозитории)"
  apt-get install -y -qq "${need[@]}" ca-certificates >/dev/null || die "не удалось поставить: ${need[*]}"
else
  ok "всё уже стоит"
fi
# верификация
for c in jq qrencode python3 openssl curl git; do
  command -v "$c" >/dev/null 2>&1 || die "после установки нет команды: $c"
done
ok "зависимости готовы"

# ── 2. Xray-core ────────────────────────────────────────────────────────────
if ! command -v xray >/dev/null 2>&1; then
  say "Ставлю Xray-core…"
  bash -c "$(curl -L https://github.com/XTLS/Xray-install/raw/main/install-release.sh)" @ install >/dev/null
  ok "Xray установлен"
else
  ok "Xray уже установлен ($(xray version 2>/dev/null | head -1 || true))"
fi

# ── 3. ключи/идентификаторы (всё своё) ──────────────────────────────────────
say "Генерирую Reality-ключи и идентификаторы…"
KP=$(xray x25519)
PRIV=$(echo "$KP" | awk '/PrivateKey|Private key/{print $NF}' | head -1)
PUB=$(echo  "$KP" | awk '/Password|PublicKey|Public key/{print $NF}' | head -1)
[ -n "$PRIV" ] && [ -n "$PUB" ] || die "не смог распарсить xray x25519:\n$KP"
SID_OB=$(openssl rand -hex 8)
SID_US=$(openssl rand -hex 8)
PATH_OB="/$(openssl rand -hex 6)"
PATH_US="/$(openssl rand -hex 6)"
SRV_IP=$(curl -s --max-time 10 https://api.ipify.org || curl -s --max-time 10 https://ifconfig.me || echo "СЕРВЕР_IP")
ok "ключи сгенерированы (pbk ${PUB:0:12}…)"

# ── 4. каталог veil + единый источник (server.env) ──────────────────────────
say "Разворачиваю $VEIL (единый источник параметров + генераторы)…"
mkdir -p "$VEIL" "$VEIL/sub"; chmod 700 "$VEIL"
install -m 644 "$REPO_DIR/genprofile.py"     "$VEIL/genprofile.py"
install -m 644 "$REPO_DIR/genserver.py"      "$VEIL/genserver.py"
install -m 644 "$REPO_DIR/veil-subserver.py" "$VEIL/veil-subserver.py"
install -m 644 "$REPO_DIR/routes.json"       "$VEIL/routes.json"
[ -f "$VEIL/users.json" ] || echo '{}' > "$VEIL/users.json"
chmod 600 "$VEIL/users.json"
cat > "$META" <<ENV
SRV_IP=$SRV_IP
SNI=$SNI
PRIV=$PRIV
PBK=$PUB
PORT_OB=$PORT_OB
PORT_US=$PORT_US
SUB_PORT=$SUB_PORT
SID_OB=$SID_OB
SID_US=$SID_US
PATH_OB=$PATH_OB
PATH_US=$PATH_US
REPO_DIR=$REPO_DIR
ENV
chmod 600 "$META"
ok "единый источник $META готов"

# ── 5. серверный конфиг Xray (из genserver.py — один источник) ──────────────
say "Собираю серверный конфиг Xray из единого источника…"
mkdir -p "$(dirname "$XRAY_CONF")"
VEIL_ENV="$META" python3 "$VEIL/genserver.py" > "$XRAY_CONF"
xray run -test -c "$XRAY_CONF" >/dev/null 2>&1 || die "xray не принял конфиг (xray run -test -c $XRAY_CONF)"
ok "серверный конфиг валиден"

# ── 6. systemd для mini-sub ─────────────────────────────────────────────────
say "Поднимаю сервис раздачи подписок (veil-sub :$SUB_PORT)…"
cat > /etc/systemd/system/veil-sub.service <<UNIT
[Unit]
Description=veil subscription server
After=network.target
[Service]
Environment=VEIL_SUB_DIR=$VEIL/sub
Environment=VEIL_SUB_PORT=$SUB_PORT
ExecStart=/usr/bin/python3 $VEIL/veil-subserver.py
Restart=always
[Install]
WantedBy=multi-user.target
UNIT
systemctl daemon-reload
systemctl enable veil-sub >/dev/null 2>&1 || true

# ── 7. sysctl tuning (буферы, BBR, conntrack) ───────────────────────────────
say "Применяю сетевой tuning…"
cat > /etc/sysctl.d/99-veil-tuning.conf <<'SYS'
vm.swappiness=10
net.ipv4.tcp_max_syn_backlog=4096
net.ipv4.tcp_rmem=4096 87380 4194304
net.ipv4.tcp_wmem=4096 65536 4194304
net.core.somaxconn=8192
net.core.netdev_max_backlog=4096
net.ipv4.tcp_fastopen=3
net.ipv4.tcp_syncookies=1
net.core.default_qdisc=fq
net.ipv4.tcp_congestion_control=bbr
net.netfilter.nf_conntrack_max=131072
net.netfilter.nf_conntrack_tcp_timeout_established=86400
net.netfilter.nf_conntrack_tcp_timeout_close_wait=30
net.netfilter.nf_conntrack_tcp_timeout_fin_wait=30
net.netfilter.nf_conntrack_tcp_timeout_time_wait=30
net.netfilter.nf_conntrack_generic_timeout=120
SYS
echo nf_conntrack > /etc/modules-load.d/nf_conntrack.conf
modprobe nf_conntrack 2>/dev/null || true
sysctl --system >/dev/null 2>&1 || warn "часть sysctl не применилась (conntrack модуль?) — не критично"
ok "tuning применён"

# ── 8. firewall (ufw — настраивается автоматически) ─────────────────────────
say "Настраиваю firewall (ufw)…"
if ! command -v ufw >/dev/null 2>&1; then
  apt-get install -y -qq ufw >/dev/null 2>&1 || warn "не смог поставить ufw"
fi
if command -v ufw >/dev/null 2>&1; then
  # СНАЧАЛА разрешаем SSH, иначе ufw enable отрежет доступ к серверу.
  # Порт текущей SSH-сессии ($SSH_CONNECTION: 4-е поле = порт sshd) + стандартный 22.
  SSH_PORT=$(echo "${SSH_CONNECTION:-}" | awk '{print $4}')
  [ -n "$SSH_PORT" ] && ufw allow "$SSH_PORT"/tcp >/dev/null 2>&1 || true
  ufw allow 22/tcp >/dev/null 2>&1 || true
  # рабочие порты ноды
  for p in "$PORT_OB" "$PORT_US" "$SUB_PORT"; do ufw allow "$p"/tcp >/dev/null 2>&1 || true; done
  ufw default deny incoming  >/dev/null 2>&1 || true
  ufw default allow outgoing >/dev/null 2>&1 || true
  ufw --force enable >/dev/null 2>&1 || true
  if ufw status 2>/dev/null | grep -q "Status: active"; then
    ok "firewall активен (открыты SSH${SSH_PORT:+/$SSH_PORT}, $PORT_OB, $PORT_US, $SUB_PORT)"
  else
    warn "ufw не включился — открой в firewall провайдера TCP $PORT_OB, $PORT_US, $SUB_PORT"
  fi
else
  warn "ufw недоступен — открой в firewall провайдера TCP $PORT_OB, $PORT_US, $SUB_PORT"
fi

# ── 9. veil CLI + старт ─────────────────────────────────────────────────────
install -m 755 "$REPO_DIR/veil" /usr/local/bin/veil
systemctl enable xray >/dev/null 2>&1 || true
systemctl restart xray; sleep 1
systemctl is-active --quiet xray || die "Xray не стартовал (journalctl -u xray)"
systemctl restart veil-sub; sleep 1
systemctl is-active --quiet veil-sub || die "veil-sub не стартовал (journalctl -u veil-sub)"
ok "Xray и veil-sub запущены"

echo
echo -e "${GREEN}  +------------------------------------------------+${NC}"
echo -e "${GREEN}  |  ГОТОВО. Нода veil поднята.                     |${NC}"
echo -e "${GREEN}  +------------------------------------------------+${NC}"
echo "   Сервер:     ${SRV_IP}   (подписки на :${SUB_PORT})"
echo "   Транспорты: [Обычный] :$PORT_OB   |   [Усиленный] :$PORT_US"
echo
echo "   Создать ключ:   veil create-key <имя>"
echo "   Список:         veil list-keys"
echo "   Удалить:        veil delete-key <имя>"
echo "   Состояние:      veil status"
echo "   Обновить:       veil update"
