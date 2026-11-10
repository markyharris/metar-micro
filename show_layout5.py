# show_layout5.py - v1 render step: layout 5, the 12-airport grid,
# mirroring the Pi version (metar_layouts.layout5). Rounded boxes in
# 3 columns x 4 rows (list order fills column by column), each box
# shows ICAO:category in 36pt bold with the station name under it;
# box style follows the category (VFR black outline, MVFR black fill,
# IFR red outline, LIFR red fill). Home airport strip across the
# bottom with its raw METAR. Category icons are not in this step yet.
#
# Deviations from the Pi original, both deliberate: each box shows its
# OWN station name (the Pi code passes the home name to every box),
# and an unknown category shows as N/A in a black outline box (the
# Pi's fallback text is effectively invisible).

import network
import time
import math
import urequests
import ntptime
import framebuf
import gc

import wifi_cfg
import epd7in5b
import textdraw
import f36b
import f14b
import f14
import f16b

AIRPORTS = ["KEYW", "KFVE", "KSEA", "KCVG", "KLAS", "KCMR",
            "KGRR", "KMSN", "KLAX", "KNBC", "KFVE", "KBUF"]
HOME = "KFLG"
URL = ("https://aviationweather.gov/api/data/metar?ids=%s"
       "&format=json&hours=3" % ",".join(AIRPORTS + [HOME]))
W, H = epd7in5b.EPD_WIDTH, epd7in5b.EPD_HEIGHT

COLS_X = [20, 290, 550]
CELL_W = [270, 260, 260]
ROWS_Y = [10, 100, 190, 280]
BOX_H = 65
RADIUS = 10


def join_wifi():
    wlan = network.WLAN(network.STA_IF)
    wlan.active(True)
    if wlan.isconnected():
        return wlan
    print("joining", wifi_cfg.SSID, "...")
    wlan.connect(wifi_cfg.SSID, wifi_cfg.PASSWORD)
    t0 = time.ticks_ms()
    while not wlan.isconnected():
        if time.ticks_diff(time.ticks_ms(), t0) > 20000:
            raise OSError("wifi join timeout")
        time.sleep_ms(250)
    print("connected:", wlan.ifconfig())
    return wlan


def local_now_str():
    t = time.localtime(time.time() - 7 * 3600)
    h = t[3] % 12
    if h == 0:
        h = 12
    ampm = "AM" if t[3] < 12 else "PM"
    return "Last Updated at %02d:%02d %s" % (h, t[4], ampm)


def round_box(fb, x, y, w, h, r, col, fill):
    if fill:
        fb.fill_rect(x + r, y, w - 2 * r, h, col)
        fb.fill_rect(x, y + r, w, h - 2 * r, col)
        for cx, cy in ((x + r, y + r), (x + w - r - 1, y + r),
                       (x + r, y + h - r - 1), (x + w - r - 1, y + h - r - 1)):
            fb.ellipse(cx, cy, r, r, col, True)
        return
    for d in (0, 1):
        fb.hline(x + r, y + d, w - 2 * r, col)
        fb.hline(x + r, y + h - 1 - d, w - 2 * r, col)
        fb.vline(x + d, y + r, h - 2 * r, col)
        fb.vline(x + w - 1 - d, y + r, h - 2 * r, col)
    for cx, cy, sx, sy in ((x + r, y + r, -1, -1), (x + w - r - 1, y + r, 1, -1),
                           (x + r, y + h - r - 1, -1, 1), (x + w - r - 1, y + h - r - 1, 1, 1)):
        for rr in (r, r - 1):
            for a in range(0, 91, 3):
                rad = math.radians(a)
                fb.pixel(cx + sx * round(rr * math.cos(rad)),
                         cy + sy * round(rr * math.sin(rad)), col)


def draw_box(bfb, rfb, x, y, w, apt, m):
    cat = (m.get("fltCat") if m else None) or "N/A"
    name = ((m.get("name") or "")[:26]) if m else ""
    title = "%s:%s" % (apt, cat)
    if cat == "MVFR":
        round_box(bfb, x, y, w, BOX_H, RADIUS, 0, True)
        plane, ink = bfb, 1
    elif cat == "LIFR":
        round_box(rfb, x, y, w, BOX_H, RADIUS, 1, True)
        plane, ink = rfb, 0
    elif cat == "IFR":
        round_box(rfb, x, y, w, BOX_H, RADIUS, 1, False)
        plane, ink = rfb, 1
    else:
        round_box(bfb, x, y, w, BOX_H, RADIUS, 0, False)
        plane, ink = bfb, 0
    textdraw.draw_text(plane, f36b,
                       x + (w - textdraw.text_width(f36b, title)) // 2,
                       y + 4, title, ink)
    textdraw.draw_text(plane, f14b,
                       x + (w - textdraw.text_width(f14b, name)) // 2,
                       y + 46, name, ink)


def render(home=None):
    # Returns the HOME airport's flight category on success, None on
    # fetch failure. Called by main.py's loop; also runnable standalone.
    hv = home or HOME
    join_wifi()
    try:
        ntptime.settime()
    except Exception as e:
        print("ntp failed (continuing):", e)
    url = ("https://aviationweather.gov/api/data/metar?ids=%s"
           "&format=json&hours=3" % ",".join(AIRPORTS + [hv]))
    resp = urequests.get(url)
    if resp.status_code != 200:
        print("fetch failed:", resp.status_code, resp.text[:200])
        resp.close()
        return
    data = {}
    for m in resp.json():
        data.setdefault(m.get("icaoId"), m)
    resp.close()
    print("reports for", len(data), "stations")

    black = bytearray(b"\xFF" * epd7in5b.PLANE_BYTES)
    red = bytearray(epd7in5b.PLANE_BYTES)
    bfb = framebuf.FrameBuffer(black, W, H, framebuf.MONO_HLSB)
    rfb = framebuf.FrameBuffer(red, W, H, framebuf.MONO_HLSB)

    for i, apt in enumerate(AIRPORTS):
        col, row = i // 4, i % 4
        draw_box(bfb, rfb, COLS_X[col], ROWS_Y[row],
                 CELL_W[col] - 25, apt, data.get(apt))

    # Home strip
    m = data.get(hv)
    cat = (m.get("fltCat") if m else None) or "N/A"
    if cat == "MVFR":
        round_box(bfb, 20, 370, 765, 95, RADIUS, 0, True)
        plane, ink = bfb, 1
    elif cat == "LIFR":
        round_box(rfb, 20, 370, 765, 95, RADIUS, 1, True)
        plane, ink = rfb, 0
    elif cat == "IFR":
        round_box(rfb, 20, 370, 765, 95, RADIUS, 1, False)
        plane, ink = rfb, 1
    else:
        round_box(bfb, 20, 370, 765, 95, RADIUS, 0, False)
        plane, ink = bfb, 0
    textdraw.draw_text(plane, f36b, 30, 380, "%s:%s" % (hv, cat), ink)
    if m:
        textdraw.draw_text(plane, f14, 30, 420, (m.get("name") or "")[:26], ink)
    textdraw.draw_text(plane, f16b, 30, 445, local_now_str(), ink)
    if m:
        raw = "METAR: " + (m.get("rawOb") or "")
        for j, ln in enumerate(textdraw.wrap(f16b, raw, 480)[:3]):
            textdraw.draw_text(plane, f16b, 290, 375 + j * 20, ln, ink)

    gc.collect()
    print("free RAM before refresh:", gc.mem_free())
    epd = epd7in5b.EPD()
    epd.init()
    t0 = time.ticks_ms()
    epd.display(black, red)
    print("refresh done in", time.ticks_diff(time.ticks_ms(), t0), "ms")
    epd.sleep()
    print("layout 5 on panel")
    return cat


if __name__ == "__main__":
    render()
