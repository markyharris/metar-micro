# show_weather.py - v1 extra page: city weather for the selected
# airport, widget-style. Identity and coordinates come from the AWC
# METAR record (name/lat/lon); conditions and the 7-day outlook come
# from Open-Meteo (free, no API key), keyed to those coordinates with
# timezone=auto, so the page follows whichever airport is chosen.
# Units are Fahrenheit/mph (US widget convention). Becomes a layout
# in the rotation when the main loop lands.

import network
import time
import urequests
import ntptime
import framebuf
import gc

import wifi_cfg
import epd7in5b
import textdraw
import f48b
import f24b
import f20b
import f16b
import f14b
import f14
import f96wx

AIRPORT = "KFLG"
AWC_URL = "https://aviationweather.gov/api/data/metar?ids=%s&format=json&hours=3" % AIRPORT
OM_URL = ("https://api.open-meteo.com/v1/forecast?latitude=%s&longitude=%s"
          "&current=temperature_2m,relative_humidity_2m,apparent_temperature,"
          "weather_code,wind_speed_10m,wind_direction_10m"
          "&daily=weather_code,temperature_2m_max,temperature_2m_min,"
          "precipitation_probability_max"
          "&temperature_unit=fahrenheit&wind_speed_unit=mph"
          "&timezone=auto&forecast_days=7")
W, H = epd7in5b.EPD_WIDTH, epd7in5b.EPD_HEIGHT
DEG = "\u00b0"

WMO = {0: "Clear", 1: "Mostly clear", 2: "Partly cloudy", 3: "Overcast",
       45: "Fog", 48: "Fog", 51: "Lt drizzle", 53: "Drizzle", 55: "Drizzle",
       56: "Frz drizzle", 57: "Frz drizzle", 61: "Lt rain", 63: "Rain",
       65: "Heavy rain", 66: "Frz rain", 67: "Frz rain", 71: "Lt snow",
       73: "Snow", 75: "Heavy snow", 77: "Snow grains", 80: "Lt showers",
       81: "Showers", 82: "Hvy showers", 85: "Snow showers",
       86: "Snow showers", 95: "T-storms", 96: "T-storms/hail",
       99: "T-storms/hail"}
DAYS = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday",
        "Friday", "Saturday"]
MON = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
       "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
COMPASS = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"]


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
    return "Updated %02d:%02d %s" % (h, t[4], ampm)


def weekday(y, m, d):
    t = [0, 3, 2, 5, 0, 3, 5, 1, 4, 6, 2, 4]
    if m < 3:
        y -= 1
    return (y + y // 4 - y // 100 + y // 400 + t[m - 1] + d) % 7


def get_json(url):
    resp = urequests.get(url)
    if resp.status_code != 200:
        print("fetch failed:", resp.status_code, url[:60])
        resp.close()
        return None
    data = resp.json()
    resp.close()
    return data


def main():
    join_wifi()
    try:
        ntptime.settime()
    except Exception as e:
        print("ntp failed (continuing):", e)
    awc = get_json(AWC_URL)
    if not awc:
        return
    m = awc[0]
    om = get_json(OM_URL % (m.get("lat"), m.get("lon")))
    if not om:
        return
    print("drawing weather page for", m.get("name"))

    name = m.get("name") or AIRPORT
    city = name.split("/")[0]
    parts = [p.strip() for p in name.split(",")]
    state = parts[-2] if len(parts) >= 3 else ""
    header = city + (", " + state if state else "")

    cur = om["current"]
    daily = om["daily"]
    dates = daily["time"]
    y0, m0, d0 = (int(v) for v in dates[0].split("-"))
    date_str = "%s, %s %d" % (DAYS[weekday(y0, m0, d0)][:3], MON[m0 - 1], d0)
    upd = local_now_str()

    black = bytearray(b"\xFF" * epd7in5b.PLANE_BYTES)
    red = bytearray(epd7in5b.PLANE_BYTES)
    bfb = framebuf.FrameBuffer(black, W, H, framebuf.MONO_HLSB)
    rfb = framebuf.FrameBuffer(red, W, H, framebuf.MONO_HLSB)
    for i in range(5):
        rfb.rect(5 + i, 5 + i, 790 - 2 * i, 470 - 2 * i, 1)
    rfb.fill_rect(20, 86, 760, 3, 1)
    rfb.fill_rect(20, 335, 760, 3, 1)

    textdraw.draw_text(bfb, f48b, 20, 14, header, 0)
    textdraw.draw_text(bfb, f24b, 780 - textdraw.text_width(f24b, date_str),
                       24, date_str, 0)
    textdraw.draw_text(bfb, f16b, 780 - textdraw.text_width(f16b, upd),
                       56, upd, 0)

    textdraw.draw_text(bfb, f96wx, 20, 100,
                       "%d%s" % (round(cur["temperature_2m"]), DEG), 0)
    textdraw.draw_text(bfb, f24b, 24, 228,
                       WMO.get(cur["weather_code"], ""), 0)

    wdir = COMPASS[round(cur.get("wind_direction_10m", 0) / 45) % 8]
    pp0 = daily["precipitation_probability_max"][0]
    details = [
        "Feels like: %d%s" % (round(cur["apparent_temperature"]), DEG),
        "Humidity: %d%%" % cur["relative_humidity_2m"],
        "Wind: %s %d mph" % (wdir, round(cur["wind_speed_10m"])),
        "Today: %d%s / %d%s" % (round(daily["temperature_2m_max"][0]), DEG,
                                round(daily["temperature_2m_min"][0]), DEG),
        "Precip chance: %s" % ("--" if pp0 is None else "%d%%" % pp0),
    ]
    for i, ln in enumerate(details):
        textdraw.draw_text(bfb, f20b, 440, 110 + i * 40, ln, 0)

    colw = 108
    for i in range(7):
        x = 20 + i * colw
        cx = x + colw // 2
        if i:
            rfb.vline(x - 6, 345, 120, 1)
        yy, mm, dd = (int(v) for v in dates[i].split("-"))
        day = "Today" if i == 0 else DAYS[weekday(yy, mm, dd)][:3]
        textdraw.draw_text(bfb, f20b, cx - textdraw.text_width(f20b, day) // 2,
                           345, day, 0)
        label = WMO.get(daily["weather_code"][i], "")
        for j, ln in enumerate(textdraw.wrap(f14, label, colw - 6)[:2]):
            textdraw.draw_text(bfb, f14, cx - textdraw.text_width(f14, ln) // 2,
                               375 + j * 16, ln, 0)
        hilo = "%d%s/%d%s" % (round(daily["temperature_2m_max"][i]), DEG,
                              round(daily["temperature_2m_min"][i]), DEG)
        textdraw.draw_text(bfb, f20b, cx - textdraw.text_width(f20b, hilo) // 2,
                           412, hilo, 0)
        pp = daily["precipitation_probability_max"][i]
        ptxt = "--" if pp is None else "%d%%" % pp
        textdraw.draw_text(bfb, f14b, cx - textdraw.text_width(f14b, ptxt) // 2,
                           440, ptxt, 0)

    gc.collect()
    print("free RAM before refresh:", gc.mem_free())
    epd = epd7in5b.EPD()
    epd.init()
    t0 = time.ticks_ms()
    epd.display(black, red)
    print("refresh done in", time.ticks_diff(time.ticks_ms(), t0), "ms")
    epd.sleep()
    print("weather page on panel")


main()
