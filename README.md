# metar-micro — ESP32 E-Paper METAR Display

Aviation weather on a 7.5″ three-color e-paper panel, driven by an
ESP32 running MicroPython — no Raspberry Pi, no SD card, nothing to
wear out. It fetches METARs and TAFs from aviationweather.gov,
renders a rotating set of weather pages, and keeps itself updated
from this repository.

This is the MicroPython port of the Pi-based
[metar](https://github.com/markyharris/metar) project: same panel
(Waveshare 7.5″ e-Paper HAT (B), 800×480, black/white/red), same
layout family, with the Pi Zero replaced by an ESP32 that talks to
the driver HAT through its 8-pin cable socket.

**Building one? Start with [HOWTO.md](HOWTO.md)** — parts list,
wiring, flashing, first run, and every gotcha we hit along the way.

## What it does

- **Nine pages in rotation** (cycle mode) or a preferred subset:
  - **City weather** — current conditions + 7-day outlook for the
    selected airport's city (Open-Meteo, no API key)
  - **Layout 0** — jumbo flight category with the raw METAR
  - **Layout 1** — detailed grid: eight decoded fields, big
    category box, station info box
  - **Layout 2** — two-column decoded data with cloud layers
  - **Layout 3** — jumbo category in a rounded box
  - **Layout 4** — black field column, raw METAR box, big category
  - **Layout 5** — 12-airport grid with per-station category boxes
    (the airport list is editable in the admin page)
  - **Layout 6** — 12-hour trend chart: category band, pressure
    chart with visibility in red on its own scale, temperature
    chart with wind in red on its own scale
  - **Layout 7** — circles theme: category dial with data circles
  - **Layout 8** — TAF forecast: one row per forecast period with
    a derived category chip, FM/TEMPO/PROB tags, raw TAF below
- **Web admin page** on the device (port 80): airport, page mode,
  preferred pages, refresh interval, measurement units
  (imperial/metric), overnight display-off window, the layout 5
  grid editor, display off/on and reboot buttons.
- **Sensible refresh cadence**: interval 0 = auto — the pause
  follows the flight category just shown (VFR 60 min, MVFR 30,
  IFR 20, LIFR 10). Fetch failures draw an error page and retry
  in 60 seconds.
- **Self-updating**: the device checks this repo hourly, flags
  "Update available" in the admin page, and on command downloads
  the changed files, verifies each against its git blob SHA,
  swaps it in (`.bak` kept), and reboots. `wifi_cfg.py` and
  `config.json` are never touched by an update.
- **Rehoming built in**: move the display to a new network or a
  new owner with no keyboard or reflash — if it can't join its
  saved network it raises its own `MetarMicro-Setup` access point
  with a captive setup page (also forced by holding the BOOT
  button just after power-up).
- **No API keys anywhere.** METAR/TAF data comes from
  aviationweather.gov's public JSON API; city weather from
  Open-Meteo.

## Hardware in brief

| Part | Notes |
|---|---|
| Waveshare 7.5″ e-Paper HAT (B) | 800×480, black/white/red, V2 panel; driver HAT Rev2.2 with the PH2.0 8-pin socket |
| ESP32-S3-DevKitC-1 (N8R8) | The reference build; MicroPython `GENERIC_S3-SPIRAM_OCT` |
| PH2.0 8-pin cable | HAT socket to the controller (pre-crimped kit, far ends bare) |
| USB power | 5 V supply; some boards also want a USB feed alongside pin power |

Wiring is eight wires (VCC/GND/DIN/CLK/CS/DC/RST/BUSY) on GPIO
13/18/14/15/4/5 — full table, firmware links, and the switch
settings the HAT needs are in [HOWTO.md](HOWTO.md).

## Files

| File | Role |
|---|---|
| `main.py` | The running loop: Wi-Fi, clock, admin server, page rotation, overnight-off, boot and error screens. Auto-runs on boot |
| `show_layout0.py` … `show_layout8.py`, `show_weather.py` | The nine pages; each is an importable `render()` module and can also be run standalone from Thonny |
| `epd7in5b.py` | Panel driver (SoftSPI bit-bang — deliberate; see HOWTO gotchas) |
| `fetch.py` | Hardened JSON fetcher (raw socket, validates and retries flaky gateway responses) |
| `updater.py` | Manifest self-update against this repo |
| `prov.py` | Rehoming captive portal (`MetarMicro-Setup` AP) |
| `textdraw.py` + `f*.py` | Bitmap text renderer and pre-rendered DejaVu font modules |
| `update_files.txt` | The updater's file manifest — read fresh from the repo on every check |
| `wifi_cfg.py` | **You create this on the device** — holds `SSID` and `PASSWORD`; never in this repo, never overwritten |
| `config.json` | Created on the device by the admin page (settings) |
| `test_epd.py` | Panel test pattern — run this first on a new build |
| `SPEC.md` | Design decisions and the full development/fault log |

## Notes

- Display times are local: the code ships with a Phoenix
  (UTC−7, no DST) offset in `main.py` and the page modules —
  adjust it for your time zone (see HOWTO).
- A full three-color refresh takes about 25 seconds. That's the
  panel, not a hang; it sleeps between updates and holds its last
  image with the power off.
- Layout numbering follows the original Pi project where pages
  were ported. Two Pi pages were not ported (9 is two large
  icons; 10 is a test page), and slot 6 — on the Pi a downloaded
  map image — holds the trend chart here instead.
