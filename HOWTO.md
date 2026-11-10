# HOWTO — Build and Set Up the metar-micro E-Paper METAR Display

Everything needed to go from parts to a running display, in the
order you'd actually do it. The gotchas section at the end is the
expensive part of this document — every entry there cost real
debugging time during development.

## 1. Parts

| Part | What to get | Notes |
|---|---|---|
| E-paper panel + driver HAT | **Waveshare 7.5inch e-Paper HAT (B)** (Waveshare SKU 13505) | 800×480, black/white/**red**, **V2** panel. The (B) matters: the plain 7.5″ HAT is black/white only and uses a different driver. This build used the Driver HAT **Rev2.2** with the **PH2.0 8-pin** cable socket (count the pins — a Rev2.3 HAT uses a 9-pin GH1.25 socket instead). [Waveshare wiki](https://www.waveshare.com/wiki/7.5inch_e-Paper_HAT) · [Driver HAT manual (PDF)](https://files.waveshare.com/upload/8/8e/E-paper-driver-hat-user-manual.pdf) |
| Controller | **ESP32-S3-DevKitC-1, N8R8** (8 MB flash, 8 MB octal PSRAM) | The reference build. A classic **ESP32-WROOM-32 devkit** (e.g. HW-463) also runs the same code unchanged — see the firmware table below |
| Cable | **PH2.0 8-pin pre-crimped cable kit** | One end plugs into the HAT socket; clip the far ends to bare wire for header pins or a screw-terminal breakout |
| Breakout (optional) | 44-pin ESP32-S3 screw-terminal breakout | Makes the wiring far less fiddly; not required |
| Power | 5 V USB supply (1 A+) and a **data-capable** USB cable | USB-C for the S3, micro-USB for the classic board. Charge-only cables will light the board's LED and pass no data — see gotchas |
| Computer software | **Thonny 4.1 or newer** | From [thonny.org](https://thonny.org). The version matters — see gotchas |
| Firmware | MicroPython v1.29.0 (or current stable) | From the [MicroPython download page](https://micropython.org/download/) — pick per the table below |

Firmware builds used by this project:

| Board | Build to download | Flash address |
|---|---|---|
| ESP32-S3 N8R8 | `ESP32_GENERIC_S3-SPIRAM_OCT-*.bin` (e.g. `ESP32_GENERIC_S3-SPIRAM_OCT-20260824-v1.29.0.bin`) | `0x0` |
| Classic ESP32-WROOM-32 | `ESP32_GENERIC-*.bin` | `0x1000` |

Thonny's installer handles the address **if** the chip family is
set correctly in its dialog (next section).

## 2. Set the HAT's configuration switches

The driver HAT has two configuration switches. For this panel
they must be:

- **Interface Config: 0** (4-wire SPI)
- **Display Config: B** (0.47R — the setting for the (B) panel)

A bumped switch leaves the panel powered and partly responsive
but deaf — check these first if a finished build ever stops
drawing after being handled.

## 3. Wire the HAT to the ESP32

The HAT's 8-pin socket carries, in order:
**BUSY · RST · DC · CS · CLK · DIN · GND · VCC** (as silkscreened
on the HAT). Land them on the controller like this — the same
GPIOs on both board families:

| HAT signal | ESP32 GPIO | Notes |
|---|---|---|
| VCC | **3V3** | Feed from the board's 3V3 pin — see gotcha on rails |
| GND | GND | |
| DIN (MOSI) | GPIO 13 | |
| CLK (SCK) | GPIO 18 | |
| CS | GPIO 14 | |
| DC | GPIO 15 | |
| RST | GPIO 4 | |
| BUSY | GPIO 5 | |

One wire color set that works (from a typical pre-crimped kit —
yours may differ; trust the table, not the colors): red VCC,
black GND, green DIN, yellow CLK, blue CS, white DC,
yellow/black RST, white/black BUSY.

**The ribbon cables between the HAT and the panel**: the FPC
contacts face **down, toward the circuit board**, on both ends.
A reversed ribbon is the single nastiest fault in this build —
the panel stays powered, BUSY answers, continuity checks pass,
and nothing ever draws. If a new build is deaf, reseat the
ribbons first. (This one cost us a day; the panel, two HATs, and
the wiring were all proven good before the ribbon was suspected.)

## 4. Flash MicroPython with Thonny

1. Install Thonny **4.1+** (5.x is fine).
2. Connect the board by USB. On Windows, a classic ESP32 board
   (CP2102 USB-serial) may need the Silicon Labs CP210x VCP
   driver before any COM port appears; the S3 uses native USB
   and needs none.
3. In Thonny: *Tools → Options → Interpreter* → MicroPython
   (ESP32), select the port, then **Install or update
   MicroPython**.
4. Set the **MicroPython family** field to match your chip
   (**ESP32-S3** for the S3 build). This field is what makes
   Thonny write the S3 image at `0x0` instead of the classic
   address. To use a firmware file you downloaded yourself, pick
   it via the dialog's ☰ menu → *Select local MicroPython image*.
5. Flash, then confirm the board answers at the `>>>` prompt.

If an S3 flashed with an old Thonny seems to install fine
("Hash of data verified") but then boot-loops with
`invalid header: 0xffffffff`, it was written at the wrong
address — reflash with Thonny 4.1+ and the family set to
ESP32-S3.

## 5. Upload the project files

Download this repository (or clone it), then in Thonny's file
view upload **every file listed in `update_files.txt`** to the
root of the device — code modules, page modules, and all the
`f*.py` font modules. The pages import the fonts and helper
modules by name; one missing file (a font, `textdraw.py`,
`fetch.py`) makes the pages that need it fail at import time.

**Skip `test_epd.py` for now** (it's in the repo but not in the
updater manifest — you'll use it once, in step 7).

Then create one file that is deliberately *not* in the repo —
your Wi-Fi credentials. On the device, create `wifi_cfg.py`
containing exactly:

```python
SSID = "YourNetworkName"
PASSWORD = "YourNetworkPassword"
```

Type the password directly in Thonny on your own machine; it
lives only on the device, is never uploaded to GitHub, and the
self-updater is hard-coded to never overwrite it. The same
applies to `config.json`, which the device creates itself.

## 6. First run

1. Open `main.py` in Thonny and run it (or just power-cycle the
   board — `main.py` runs automatically on every boot).
2. The console shows the Wi-Fi join and the board's IP address;
   the panel draws a boot screen with the admin URL.
3. Browse to `http://<board-ip>/` — that's the admin page. Set:
   - **Airport (ICAO)** — the station everything keys off
     (default KFLG)
   - **Mode** — Cycle (all pages) or Preferred (your subset)
   - **Measurements** — Imperial or Metric
   - **Interval** — leave at **0 (auto)** unless you want a fixed
     cadence; auto follows the flight category (VFR 60 min down
     to LIFR 10 min), and each page fetches fresh data when it
     draws
4. Save. The page bounces straight back to the form with your
   values in it — that's the confirmation.

**Time zone:** the code computes local time as UTC−7 year-round
(Phoenix). To run elsewhere, change `TZ_OFFSET` in `main.py` and
the `- 7 * 3600` offsets in the page modules to your offset.

## 7. Prove the panel alone (optional but recommended)

Before blaming the software on a fresh build, run the panel test:

1. Upload `test_epd.py` from the repo.
2. Run it. You should get the full test pattern — black block and
   RED block across the top, text lines, blocks along the bottom.
3. No pattern? Work the gotchas list below in order: ribbons,
   HAT switches, VCC rail, wiring against the table.

## 8. Day-to-day use

- **Update available**: the admin page checks GitHub hourly and
  after boot. When it shows *Update available: N file(s)*, press
  **Update now** — files download, get verified, swap in, and the
  board reboots itself. Settings and Wi-Fi credentials are never
  touched.
- **Turn display OFF / ON** blanks the panel (it holds no image;
  the app and admin page keep running). **Reboot board** restarts.
- **Turn off overnight**: set the window and the display stops
  refreshing overnight, holding its last image; the admin page
  stays live.
- **Layout 5's grid** is edited right on the admin page — twelve
  airport IDs filling the grid column by column. A save only
  applies when all twelve are valid IDs; otherwise the old grid
  stays.

## 9. Moving or gifting the display (rehoming)

No keyboard, monitor, or reflash needed:

1. Plug the display in at the new location. It tries its saved
   network, fails to join, and raises its own open access point
   named **`MetarMicro-Setup`**.
2. Join that network with a phone. The setup page pops up
   (captive portal): pick the new network from the list (or type
   it), enter the password, save.
3. The board saves **only** the credentials and reboots onto the
   new network.

To force setup mode on a working display (e.g. before handing it
over): hold the board's **BOOT** button starting **just after**
power-up, for about 3 seconds. (Holding BOOT *while* plugging in
puts the S3 into firmware-download mode instead — the hold must
start after power-up.)

If you're gifting it, there's nothing else to wipe: your home
Wi-Fi password is replaced the moment the new owner completes
setup.

## 10. Gotchas and troubleshooting

Hard-won, roughly in the order to check them:

1. **Ribbon orientation.** FPC contacts face **down** toward the
   board. Reversed = panel alive, BUSY responsive, nothing draws,
   and every continuity test passes. Reseat first, debug second.
2. **HAT switches.** Interface Config **0**, Display Config **B**.
   See step 2.
3. **A refresh takes ~25 seconds.** Full three-color refresh is
   slow by nature. A "stuck" board mid-refresh is normal; the
   panel sleeps between updates and draws nothing in between.
4. **The driver uses SoftSPI on purpose.** `epd7in5b.py`
   bit-bangs the bus. On the development S3 the hardware SPI path
   left the panel completely deaf (wiring, power, HAT, and two
   drivers all proven good; SoftSPI worked first try) — and
   constructing `SPI(2)` on the S3 MicroPython build
   watchdog-resets the chip instantly. Don't "upgrade" the driver
   to hardware SPI.
5. **Thonny version.** Below 4.1, Thonny writes S3 firmware at
   the classic address and the board boot-loops despite a
   "verified" install. Use 4.1+ and set the family to ESP32-S3.
6. **Charge-only USB cables.** The board's LED lights on any
   cable; only a data cable enumerates a port. If the PC sees
   nothing at all, swap the cable before anything else. Classic
   boards may also need the CP210x driver (step 4).
7. **Meter the VCC rail at the load end.** Feed the HAT from the
   board's **3V3** pin. On at least one clone screw-terminal
   breakout, the 5V terminal carried nothing at all while the
   board's own 5V pin read 4.1 V (clone VBUS diode drop). Power
   that looks right at the source can be wrong at the HAT.
8. **Wi-Fi wedged after repeated soft reboots.** After several
   Thonny stop/run cycles the S3's radio can wedge — scans return
   zero networks, joins throw `Wifi Internal State Error`. A full
   USB unplug/replug clears it. It's the radio, not your code or
   your network.
9. **BOOT during plug-in = download mode.** For setup mode the
   BOOT hold starts *after* power-up. See step 9.
10. **One board in a batch can just be bad.** A controller whose
    filesystem comes up unformatted (`OSError: 84`; Thonny: "the
    filesystem appears to be corrupted") can be formatted at the
    REPL (`from flashbdev import bdev` →
    `os.VfsLfs2.mkfs(bdev)` → reset) — but if uploaded files then
    vanish or writes fail at 0 bytes, retire the board and use
    another. One faulty unit fought on every front; its twin was
    perfect out of the box.
11. **Upload ALL the files.** Pages import fonts and helpers by
    name; a single missing module (say `f14b.py`) takes down
    every page that uses it, and the console error is just an
    ImportError at page time. The complete list is
    `update_files.txt`.
12. **Occasional `fetch attempt 1 failed` console lines are
    normal.** aviationweather.gov's gateway occasionally returns
    an empty or garbled response; `fetch.py` retries on a fresh
    connection and the page draws anyway. A genuine outage draws
    the error page and retries in 60 seconds.
13. **Updates never touch your settings.** `wifi_cfg.py` and
    `config.json` are excluded from the updater by design, even
    if a manifest were to list them.
