# metar_fetch5.py - capture test with the fixed hours value.
# AWC now rejects fractional hours (hours=2.5 -> HTTP 400
# 'Invalid value for hours'); integer hours=3 verified good.
# Changes vs fetch3: credentials come from wifi_cfg.py on the board
# (no retyping), and the scan RETRIES - a scan fired right after boot
# can come back empty even when the network is there.
# Then: try each node BSSID of the target network, then fetch KFLG.

import network
import time
import urequests
import gc
import wifi_cfg

SSID = wifi_cfg.SSID
PASSWORD = wifi_cfg.PASSWORD
AIRPORT = "KFLG"

URL = "https://aviationweather.gov/api/data/metar?ids=%s&format=json&hours=3" % AIRPORT


def mac(b):
    return ":".join("%02x" % x for x in b)


def scan_targets(wlan):
    for attempt in range(5):
        nets = wlan.scan()
        hits = [n for n in nets if n[0].decode() == SSID]
        print("scan", attempt + 1, ":", len(nets), "networks,",
              len(hits), "target nodes")
        for n in hits:
            print("  node:", mac(n[1]), "rssi", n[3], "auth", n[4])
        if hits:
            return [n[1] for n in hits]
        time.sleep_ms(1000)
    return []


def try_join(wlan, bssid):
    wlan.active(False)
    time.sleep_ms(300)
    wlan.active(True)
    if bssid is None:
        wlan.connect(SSID, PASSWORD)
    else:
        wlan.connect(SSID, PASSWORD, bssid=bssid)
    t0 = time.ticks_ms()
    last = None
    while not wlan.isconnected():
        last = wlan.status()
        if time.ticks_diff(time.ticks_ms(), t0) > 12000:
            break
        time.sleep_ms(250)
    return wlan.isconnected(), last


def main():
    wlan = network.WLAN(network.STA_IF)
    wlan.active(True)
    time.sleep_ms(500)
    targets = scan_targets(wlan)
    if not targets:
        print("target never seen in 5 scans - stopping")
        return
    print("---- join attempts ----")
    ok = False
    for b in targets:
        ok, st = try_join(wlan, b)
        print("bssid", mac(b), "-> connected:", ok, "last status:", st)
        if ok:
            break
    if not ok:
        print("no node accepted the join - stopping")
        return
    print("connected:", wlan.ifconfig())
    print("---- fetch ----")
    gc.collect()
    print("free RAM:", gc.mem_free())
    resp = urequests.get(URL)
    print("HTTP", resp.status_code)
    if resp.status_code != 200:
        print("error body:", resp.text[:300])
        resp.close()
        return
    data = resp.json()
    resp.close()
    if not data:
        print("empty response - no METAR in the last 2.5 h for", AIRPORT)
        return
    m = data[0]
    print("---- %s ----" % m.get("icaoId"))
    print("name:    ", m.get("name"))
    print("report:  ", m.get("reportTime"))
    print("raw:     ", m.get("rawOb"))
    print("temp/dew:", m.get("temp"), "/", m.get("dewp"), "C")
    print("wind:    ", m.get("wdir"), "at", m.get("wspd"),
          "kt, gust", m.get("wgst"))
    print("visib:   ", m.get("visib"))
    print("altim:   ", m.get("altim"), "hPa")
    print("fltCat:  ", m.get("fltCat"))
    print("wx:      ", m.get("wxString"))
    for c in (m.get("clouds") or []):
        print("cloud:   ", c.get("cover"), c.get("base"))
    print("capture OK")


main()
