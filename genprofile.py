#!/usr/bin/env python3
"""veil genprofile — собирает клиентский профиль (подписку) для одного UUID.
Воспроизводит боевую схему hey_vpn: 2 конфига (Обычный packet-up / Усиленный xmux),
split-routing РУ-направления мимо VPN (из routes.json), DNS dns-in, TLS-fragment, UDP/443 block.

Использование: genprofile.py <uuid>   → печатает JSON-массив на stdout
Параметры ноды берутся из /etc/veil/server.env, маршруты из /etc/veil/routes.json.
"""
import json, os, sys

ENV   = os.environ.get("VEIL_ENV",   "/etc/veil/server.env")
ROUTES= os.environ.get("VEIL_ROUTES","/etc/veil/routes.json")

def load_env(path):
    d = {}
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            d[k] = v
    return d

def build_routing(routes):
    rules = []
    proto = routes.get("direct_protocol") or []
    if proto:
        rules.append({"type": "field", "protocol": proto, "outboundTag": "direct"})
    ips = (routes.get("direct_ip") or []) + (routes.get("direct_geoip") or [])
    if ips:
        rules.append({"type": "field", "ip": ips, "outboundTag": "direct"})
    doms = routes.get("direct_domains") or []
    if doms:
        rules.append({"type": "field", "domain": doms, "outboundTag": "direct"})
    # QUIC/UDP-443 в block — чтобы трафик не утекал мимо split-роутинга
    rules.append({"type": "field", "network": "udp", "port": "443", "outboundTag": "block"})
    # DNS как в боевом happ-smart: запросы внутреннего резолвера (dns-in) идут
    # ЧЕРЕЗ VPN (proxy) — анти-leak, иначе DNS резолвится РУ-провайдером и палит
    # гео (ломались сервисы вроде RedotPay); port 53 → dns-out. Теги dns-in
    # (в dns-блоке base) и dns-out (в outbounds) уже есть.
    rules.append({"type": "field", "inboundTag": ["dns-in"], "outboundTag": "proxy"})
    rules.append({"type": "field", "port": "53", "outboundTag": "dns-out"})
    return {"domainMatcher": "hybrid", "domainStrategy": "IPIfNonMatch", "rules": rules}

def main():
    if len(sys.argv) < 2:
        sys.exit("usage: genprofile.py <uuid>")
    uuid = sys.argv[1]
    e = load_env(ENV)
    routes = json.load(open(ROUTES))
    sni = e["SNI"]
    flag = e.get("FLAG") or "\U0001F30D"  # флаг страны сервера (ведущая иконка), fallback 🌍

    base = {"log": {"loglevel": "error"},
            "dns": {"queryStrategy": "UseIPv4", "servers": ["8.8.8.8", "1.1.1.1"], "tag": "dns-in"}}
    inbounds = [
        {"listen": "127.0.0.1", "port": 10808, "protocol": "socks",
         "settings": {"auth": "noauth", "udp": True},
         "sniffing": {"enabled": True, "destOverride": ["http", "tls", "quic"]}, "tag": "socks"},
        {"listen": "127.0.0.1", "port": 10809, "protocol": "http",
         "settings": {"allowTransparent": False},
         "sniffing": {"enabled": True, "destOverride": ["http", "tls", "quic"]}, "tag": "http"},
    ]
    frag = {"tag": "fragment", "protocol": "freedom",
            "settings": {"fragment": {"packets": "tlshello", "length": "50-100",
                                       "interval": "10-20", "maxSplit": "100-200"}},
            "streamSettings": {"network": "raw", "security": "",
                               "sockopt": {"domainStrategy": "ForceIPv4", "mark": 255, "TcpNoDelay": True}}}
    static = [
        {"protocol": "freedom", "settings": {},
         "streamSettings": {"sockopt": {"domainStrategy": "ForceIPv4"}}, "tag": "direct"},
        {"protocol": "blackhole", "settings": {"response": {"type": "http"}}, "tag": "block"},
        {"protocol": "dns", "tag": "dns-out"},
    ]
    routing = build_routing(routes)

    def vless(port, sid, path, mode, extra):
        return {"tag": "proxy", "protocol": "vless",
                "settings": {"vnext": [{"address": e["SRV_IP"], "port": int(port),
                                        "users": [{"id": uuid, "encryption": "none", "flow": ""}]}]},
                "streamSettings": {"network": "xhttp", "security": "reality",
                    "realitySettings": {"fingerprint": "chrome", "serverName": sni,
                                        "publicKey": e["PBK"], "shortId": sid},
                    "xhttpSettings": {"path": path, "mode": mode, "extra": extra}}}

    obychny = vless(e["PORT_OB"], e["SID_OB"], e["PATH_OB"], "packet-up", {
        "xPaddingBytes": "100-1000", "scMaxEachPostBytes": "500000-1000000",
        "scMinPostsIntervalMs": "30-50", "scMaxBufferedPosts": 30, "scStreamUpServerSecs": "20-80",
        "xmux": {"maxConcurrency": "16-32", "cMaxReuseTimes": "64-128", "hMaxRequestTimes": "600-900",
                 "hMaxReusableSecs": "1800-3000", "hKeepAlivePeriod": 30}})
    usilenny = vless(e["PORT_US"], e["SID_US"], e["PATH_US"], "auto", {
        "xPaddingBytes": "100-1000", "noGRPCHeader": False, "noSSEHeader": False,
        "xmux": {"cMaxReuseTimes": "300-500", "hKeepAlivePeriod": 30, "hMaxRequestTimes": "600-900",
                 "hMaxReusableSecs": "1800-3000", "maxConcurrency": "8-16"}})

    configs = [
        {**base, "inbounds": inbounds, "outbounds": [obychny, frag] + static,
         "routing": routing, "remarks": f"{flag} Обычный"},
        {**base, "inbounds": inbounds, "outbounds": [usilenny, frag] + static,
         "routing": routing, "remarks": f"{flag} Усиленный"},
    ]
    print(json.dumps(configs, ensure_ascii=False, indent=2))

if __name__ == "__main__":
    main()
