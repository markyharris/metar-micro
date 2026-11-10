# show_layout0.py - v1 render step: fetch KFLG and draw layout 0 on the
# panel, mirroring the Pi version's layout 0 (metar_layouts.layout0):
# red border + divider, airport top-left, flight category huge and
# centered (color scheme follows the category), last-updated line, raw
# METAR wrapped in the bottom strip. The Pi's weather icon is not in
# this step yet.
#
# Category comes from AWC's fltCat field. Local time via NTP, fixed
# UTC-7 (Phoenix). Fonts + textdraw + epd7in5b must be on the board.

import network
import time
import fetch
import ntptime
import framebuf
import gc

import wifi_cfg
import epd7in5b
import textdraw
import f48b
import f24
import f20
import f16b
import fcat

AIRPORT = "KFLG"
URL = "https://aviationweather.gov/api/data/metar?ids=%s&format=json&hours=3" % AIRPORT
W, H = epd7in5b.EPD_WIDTH, epd7in5b.EPD_HEIGHT


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
    # RTC holds UTC after ntptime; Phoenix is UTC-7 year-round.
    t = time.localtime(time.time() - 7 * 3600)
    h = t[3] % 12
    if h == 0:
        h = 12
    ampm = "AM" if t[3] < 12 else "PM"
    return "Last Updated at %02d:%02d %s" % (h, t[4], ampm)


def render(airport=None):
    # Returns the flight category on success, None on fetch failure.
    # Called by main.py's loop; also runnable standalone (see bottom).
    join_wifi()
    try:
        ntptime.settime()
    except Exception as e:
        print("ntp failed (continuing):", e)
    url = ("https://aviationweather.gov/api/data/metar?ids=%s"
           "&format=json&hours=3" % (airport or AIRPORT))
    status, data = fetch.get_json(url)
    if status != 200:
        print("fetch failed: HTTP", status)
        return
    if data is None:
        print("fetch failed: unparseable response")
        return
    if not data:
        print("no METAR available for", AIRPORT)
        return
    m = data[0]
    airport = m.get("icaoId") or AIRPORT
    cat = m.get("fltCat") or "N/A"
    raw = "METAR: " + (m.get("rawOb") or "")
    upd = local_now_str()
    print("drawing layout 0:", airport, cat)

    black = bytearray(b"\xFF" * epd7in5b.PLANE_BYTES)
    red = bytearray(epd7in5b.PLANE_BYTES)
    bfb = framebuf.FrameBuffer(black, W, H, framebuf.MONO_HLSB)
    rfb = framebuf.FrameBuffer(red, W, H, framebuf.MONO_HLSB)

    # Red border (5 px) + divider at y=380, on the red plane.
    for i in range(5):
        rfb.rect(5 + i, 5 + i, 790 - 2 * i, 470 - 2 * i, 1)
    rfb.fill_rect(5, 380, 790, 5, 1)

    # Category block, mirroring the Pi's per-category color scheme.
    cat_text = cat if cat in ("VFR", "MVFR", "IFR", "LIFR") else "N/A"
    cx = (W - textdraw.text_width(fcat, cat_text)) // 2
    ux = (W - textdraw.text_width(f16b, upd)) // 2
    if cat == "MVFR":
        bfb.fill_rect(5, 5, 790, 375, 0)
        textdraw.draw_text(bfb, f48b, 20, 20, airport, 1)
        textdraw.draw_text(bfb, fcat, cx, 50, cat_text, 1)
        textdraw.draw_text(bfb, f16b, ux, 340, upd, 1)
    elif cat == "IFR":
        textdraw.draw_text(rfb, f48b, 20, 20, airport, 1)
        textdraw.draw_text(rfb, fcat, cx, 50, cat_text, 1)
        textdraw.draw_text(rfb, f16b, ux, 340, upd, 1)
    elif cat == "LIFR":
        rfb.fill_rect(5, 5, 790, 375, 1)
        textdraw.draw_text(rfb, f48b, 20, 20, airport, 0)
        textdraw.draw_text(rfb, fcat, cx, 50, cat_text, 0)
        textdraw.draw_text(rfb, f16b, ux, 340, upd, 0)
    else:  # VFR or unknown
        textdraw.draw_text(bfb, f48b, 20, 20, airport, 0)
        textdraw.draw_text(bfb, fcat, cx, 50, cat_text, 0)
        textdraw.draw_text(bfb, f16b, ux, 340, upd, 0)

    # Raw METAR in the bottom strip: 24 px, dropping to 20 px if it
    # would take more than 3 lines (same idea as the Pi's wrap).
    lines = textdraw.wrap(f24, raw, 760)
    font, step, y0 = f24, 30, 388
    if len(lines) > 3:
        lines = textdraw.wrap(f20, raw, 760)[:4]
        font, step, y0 = f20, 24, 386
    for i, ln in enumerate(lines):
        textdraw.draw_text(bfb, font, 20, y0 + i * step, ln, 0)

    gc.collect()
    print("free RAM before refresh:", gc.mem_free())
    epd = epd7in5b.EPD()
    epd.init()
    t0 = time.ticks_ms()
    epd.display(black, red)
    print("refresh done in", time.ticks_diff(time.ticks_ms(), t0), "ms")
    epd.sleep()
    print("layout 0 on panel")
    return cat


if __name__ == "__main__":
    render()
