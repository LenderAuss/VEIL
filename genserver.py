#!/usr/bin/env python3
"""veil genserver — собирает СЕРВЕРНЫЙ конфиг Xray из /etc/veil/server.env.
Единый источник истины для серверной стороны: порты, SNI, ключи, транспорты.
UUID пользователей сохраняются — передай их через --clients <file> (JSON-массив
[{"id":..,"email":..}, ...]); без него clients пустые (первая установка).

Использование:
  genserver.py                      → конфиг с пустыми clients
  genserver.py --clients users.json → конфиг с вставленными clients
Печатает config.json на stdout.
"""
import json, os, sys

ENV = os.environ.get("VEIL_ENV", "/etc/veil/server.env")

def load_env(path):
    d = {}
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                d[k] = v
    return d

def main():
    clients = []
    if "--clients" in sys.argv:
        cf = sys.argv[sys.argv.index("--clients") + 1]
        clients = json.load(open(cf))
    e = load_env(ENV)
    priv, sni = e["PRIV"], e["SNI"]

    def inbound(tag, port, sid, path, mode, extra):
        return {
            "tag": tag, "listen": "0.0.0.0", "port": int(port), "protocol": "vless",
            "settings": {"clients": clients, "decryption": "none"},
            "streamSettings": {
                "network": "xhttp", "security": "reality",
                "realitySettings": {"show": False, "dest": f"{sni}:443", "xver": 0,
                                    "serverNames": [sni], "privateKey": priv, "shortIds": [sid]},
                "xhttpSettings": {"path": path, "mode": mode, "extra": extra},
            },
            "sniffing": {"enabled": True, "destOverride": ["http", "tls"]},
        }

    obychny = inbound("obychny", e["PORT_OB"], e["SID_OB"], e["PATH_OB"], "packet-up", {
        "xPaddingBytes": "100-1000", "scMaxEachPostBytes": "500000-1000000",
        "scMinPostsIntervalMs": "30-50", "scMaxBufferedPosts": 30, "scStreamUpServerSecs": "20-80",
        "xmux": {"maxConcurrency": "16-32", "cMaxReuseTimes": "64-128", "hMaxRequestTimes": "600-900",
                 "hMaxReusableSecs": "1800-3000", "hKeepAlivePeriod": 30}})
    usilenny = inbound("usilenny", e["PORT_US"], e["SID_US"], e["PATH_US"], "auto", {
        "xPaddingBytes": "100-1000", "noGRPCHeader": False, "noSSEHeader": False,
        "xmux": {"cMaxReuseTimes": "300-500", "hKeepAlivePeriod": 30, "hMaxRequestTimes": "600-900",
                 "hMaxReusableSecs": "1800-3000", "maxConcurrency": "8-16"}})

    config = {
        "log": {"loglevel": "warning"},
        "inbounds": [obychny, usilenny],
        "outbounds": [{"protocol": "freedom", "tag": "direct"},
                      {"protocol": "blackhole", "tag": "block"}],
        "routing": {"rules": [{"type": "field", "protocol": ["bittorrent"], "outboundTag": "block"}]},
    }
    print(json.dumps(config, ensure_ascii=False, indent=2))

if __name__ == "__main__":
    main()
