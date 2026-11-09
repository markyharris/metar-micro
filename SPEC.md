# metar-micro — ESP32 port of the E-Paper METAR Display

Port of Mark's Pi project (github.com/markyharris/metar) to ESP32 / MicroPython.
Decisions (Mark, Nov 7, 2026):
- CONFIRMED Nov 7: his HAT is the PH2.0 8-pin revision (Mark counted 8 pins) - not the GH1.25 9-pin Rev2.3. He is assembling the cable from a pre-crimped PH2.0 kit (8P housing included); far ends clipped to bare wire for the screw-terminal breakouts.
  - Wire colors (agreed Nov 8, 2026, Mark's kit palette): red = VCC, black = GND, green = DIN, yellow = CLK, blue = CS, white = DC, yellow w/ black stripe = RST, white w/ black stripe = BUSY.
- Same physical panel: Waveshare 7.5" 3-color (B) e-Paper HAT, 800x480. The Pi Zero
  comes off; the ESP32 drives the HAT through its 8-pin PH2.0 cable socket
  (VCC/GND/DIN/CLK/CS/DC/RST/BUSY). Panel + HAT logic is 3.3 V — native match for ESP32.
- Hardware order: classic ESP32-WROOM-32 (HW-463) first (all he has today);
  code must run unchanged on ESP32-S3-DevKitC-1-N8R8 when those arrive.
- Night mode: NOT a display mode. Just an admin setting: turn off overnight
  (stop refreshing / panel sleep during a set window, hold last image).
- Repo name: metar-micro (github.com/markyharris/metar-micro), consistent with
  livesectional-lite-micro. Mark creates it; Buster pushes.
- House rules apply: rehoming setup-AP captive portal from the start;
  'update available' + git-less self-update reading update_files.txt manifest
  (ticker v6.1 pattern), config never overwritten by updates.

## Source behavior to duplicate (from markyharris/metar, read Nov 7, 2026)
- Fetch: https://aviationweather.gov/api/data/metar?ids=<APT>&format=json&hours=2.5
- Decode: wind dir/spd/gust, clouds, visibility, temp/dew, altimeter, wx string,
  flight category, remarks decoder (metar_remarks.py table).
- Layouts 0-10 (metar_layouts.py) + cycle / random / fixed / preferred-subset modes.
  Layout 6 (downloaded vfrmap chart image) does NOT port — skip or substitute later.
  Layout 5 = 12-airport category grid from random_airports list.
- Interval: fixed seconds, or 0 = auto by category (VFR 3600, MVFR 1800, IFR 1200, LIFR 600).
- Admin fields (from webapp.py / data.txt): airport, layout mode, interval, remarks
  on/off, wind/cloud/visibility/temp/pressure unit selectors, preferred layouts,
  plus display off / reboot. Boot screen shows admin URL for 60 s.
- Error screen on fetch failure (testpattern / message), retry after 60 s.
- Panel sleeps between updates (epd.sleep()).

## Rendering plan
- Two framebuffer planes, 800x480 / 8 = 48,000 B each (black + red), allocated once.
  Wire format (from Waveshare driver): black plane bit 0 = black pixel, 1 = white;
  red plane bit 1 = red pixel, 0 = empty. framebuf MONO_HLSB maps directly:
  black fb fill(1) + draw color 0; red fb fill(0) + draw color 1.
- Fonts: pre-render NotoMono-Regular / LiberationMono-Bold (the Pi project's fonts)
  at the sizes the layouts use into bitmap font modules offline (no TTF on device).
- Icons: the repo's 54 PNGs converted offline to 1-bit bitmaps.

## Wiring (defaults in code; valid on BOTH HW-463 classic and S3 N8R8)
DIN(MOSI)=GPIO13, CLK(SCK)=GPIO18, CS=GPIO14, DC=GPIO15, RST=GPIO4, BUSY=GPIO5,
VCC=3V3, GND=GND. All eight land on the S3 breakout's left rail.
History: first pass used DC=27, RST=26, BUSY=32 on the theory that S3 GPIOs run
0-21 and 26-48. Wrong for the N8R8: on octal-PSRAM S3 boards GPIO 26-32 are the
MSPI flash/PSRAM bus and are not broken out (confirmed Nov 8, 2026 against the
YD-ESP32-S3 44P breakout in hand, which has no 26/27/32 terminals). GPIO 16/17
were rejected because the HW-463 does not break them out. DC/RST/BUSY first
moved to 15/4/21; BUSY then moved 21 -> 5 the same day so all eight fit the
left rail. GPIO 5 is plain I/O on the S3 (strapping pins there are 0/3/45/46);
on the classic it is a strapping pin whose default is HIGH, which BUSY idles
at, and its strapping role (SDIO-slave timing) is unused here.

## Phasing
- Step 1 (this): epd7in5b.py driver port + test_epd.py test pattern. Prove panel on classic.
- v1: fetch/decode + layouts 0, 1, 5 + admin (all Pi fields + overnight-off) +
  cycle/preferred modes + auto interval + boot URL screen + error screen.
- v2: remaining layouts + icons; self-update + rehoming portal wired to the repo.

## Status log
- Nov 7, 2026: repo reviewed; decisions recorded; driver port + test pattern written.
- Nov 7, 2026: Mark created github.com/markyharris/metar-micro (empty). Step-1 files push after his panel test passes, per our usual rhythm.
- Nov 7, 2026: HAT socket confirmed PH2.0 8-pin (counted). Pre-crimped PH2.0 kit identified for the cable.
- Nov 8, 2026: Mark has the PH2.0 kit and is building the harness (wire colors agreed — see above). Awaiting him to finish wiring and run test_epd.py.
- Nov 8, 2026: Harness built (photo checked against the HAT silkscreen: BUSY/RST/DC/CS/CLK/DIN/GND/VCC top-to-bottom at the plug). Pins revised to DIN 13, CLK 18, CS 14, DC 15, RST 4, BUSY 21 (see Wiring) after the YD-ESP32-S3 breakout showed 26/27/32 don't exist on it; epd7in5b.py updated, compile-checked, both step-1 files sent to Mark.
- Nov 8, 2026: Panel test PAUSED — the new S3 controllers are delayed, and the classic HW-463 programmed Nov 7 cannot substitute: it is 30-pin and does not fit the 44-pin S3 breakout (breadboard workaround offered, declined). When the S3s land: plug into the adapter as wired, copy epd7in5b.py + test_epd.py, run the test.
- Nov 8, 2026 (evening): S3 controllers arrived. Test files sent again for the panel run: epd7in5b_busy5.py (upload to the board AS epd7in5b.py — test_epd.py imports that name) + test_epd.py. Awaiting Mark's report of the pattern (BLACK block top-left / RED top-right / stripes bottom) before the step-1 push and the v1 build.
- Nov 8, 2026 (evening): First new controller proved to be a dud — FS unformatted out of the box (OSError 84), manual mkfs made it look healthy, then a Thonny upload failed at 0 bytes and previously stored files vanished from the root listing. Mark swapped to a second new controller, which behaved properly and took both test files. Panel test is next on the good board; the dud is set aside (details in TOOLS.md).
- Nov 8, 2026 (evening): First panel-test run produced no pattern; board watchdog-reset during init. A disconnected BUSY wire (pin 5) was found and reconnected, but the resets persisted — REPL bisection (sleep OK, GPIO 4 toggle OK, SPI construction = instant WDT reset) proved the driver's SPI(2) was the cause: on the S3 GENERIC_S3-SPIRAM_OCT v1.29 build, SPI(2) construction watchdog-resets the chip. The LED ticker has always used SPI(1) on the same build. Driver fixed to SPI(1), verified 'spi ok' at the REPL; fixed copy sent as epd7in5b_spi1.py. Awaiting the panel test re-run.
- Nov 8, 2026: BUSY moved 21 -> GPIO 5 so all eight wires fit the S3 breakout's left rail (3V3, GND, 13, 18, 14, 15, 4, 5). Driver updated and compile-checked; deliverable copy saved as epd7in5b_busy5.py (new filename per the chat-cache rule — the earlier epd7in5b.py was already sent). test_epd.py needs no change (it uses the driver's defaults). S3 note: GPIO 5 is plain I/O on the S3; classic-board strapping caveat recorded in the driver header.
- Nov 9, 2026: Panel still deaf after SPI(1) fix — test_epd.py completes in ~1.1s, no pattern, no flicker. Probes: BUSY reads correctly and drops on RST pulse (panel powered, controller alive), but POWER ON never produces a BUSY dip (probe_busy2; same at 1 MHz). Driver diffed byte-by-byte against Waveshare original — clean. Continuity verified breakout -> HAT solder points on all lines. Ribbon re-seated: no change. Second (spare) HAT swapped in: identical result — HAT exonerated. Remaining suspects: pin order through the PH2.0 cable under signal (continuity passes a swap), or the panel itself. Next: probe_pins.py wiggle test, metering each signal at the HAT while the ESP32 toggles it.
- Nov 9, 2026: probe_pins.py wiggle test PASSED — all five signals (RST 4, CS 14, DC 15, CLK 18, DIN 13) meter 0 <-> 3.3V at the HAT solder points, each on its own turn: no swaps, no dead lines. ESP32, cable, and both HATs fully cleared. (Earlier same day: panel 2 tried — BUSY stuck at 0, never ready; proves the BUSY path carries the panel's true state, but panel 2 is of unknown model/health, so no verdict from it.) Remaining suspects are past the HAT: panel-end ribbon (FPC) contacts — pin-specific failure fits, since RST/BUSY/power clearly get through — or panel 1's controller. Next: re-seat ribbon at the PANEL end and rerun probe_busy2; if still deaf, Pi decider (HAT + panel 1 on a Pi, original Waveshare code).
- Nov 9, 2026: PI DECIDER DONE — Mark reimaged a Pi with the original software; display dead on first boot, then he REVERSED the ribbon cables and the display WORKED (Pi + epd7in5b_V2.py). Panel, HAT, and ribbons are all proven good; ribbon orientation was a (or the) fault all along in the ESP32 setup. Suspecting the ported driver, Buster pulled all three drivers and compared: Mark's Pi epd7in5b_V2.py has the 0x06 BOOSTER block commented out (Pico MicroPython comments out 0x01 instead and uses booster data 0x17,0x17,0x28) — and the ESP32 port's init matches the proven Pi init command-for-command, byte-for-byte. Driver init is NOT the difference. Mark's ESP32 retest after the Pi proof still failed, but ribbon orientation during that retest is uncontrolled (any re-dressing could have restored the bad orientation). Next: move HAT+panel+ribbon to the ESP32 as one untouched unit (swap only the 8-pin socket connection) and rerun test_epd.py. If still deaf: run Waveshare's own Pico MicroPython driver (fetched: waveshare_pico_75b_orig.py in this folder) with only pin numbers adapted; then suspect the breakout 3V3 rail under booster load.
- Nov 9, 2026: Unit-move retest of test_epd.py still failed identically (1.1s, BUSY never low). At Mark's request, fetched Waveshare's own MicroPython driver (Pico_ePaper_Code, python/Pico-ePaper-7.5-B.py, blob 9015e5d; saved as waveshare_pico_75b_orig.py) and prepared epd7in5b_ws.py — identical except pin constants (RST 4, DC 15, CS 14, BUSY 5) and SPI init pin args (sck 18, mosi 13); diff-verified, compile-checked. Plus test_ws.py (single refresh, bold two-plane pattern). Awaiting Mark's run. If it also fails, last suspect standing: breakout 3V3 rail sagging under the panel booster at POWER ON.
- Nov 9, 2026: Waveshare-driver test ALSO failed identically (busy prints passed through instantly, total 0.958s). Driver theory dead twice over: two different drivers, two init recipes, same deaf panel, while the Pi drives the same HAT/panel/ribbons fine. Realization: every low-baud probe (probe_busy3, 1 MHz) ran with the panel ribbon in its BAD orientation, so a slow-clock test with the proven ribbon setup has never been run — the wiggle test only proved DC levels, not MHz edge quality over the jumper harness. Next: probe_baud.py — POWER ON at 4 MHz / 1 MHz / 100 kHz, watching for any BUSY dip. If all fail, remaining suspect is HAT power via the socket route (breakout 3V3 under booster load, or 5V feed).
- Nov 9, 2026: probe_baud.py — NO BUSY dip at 4 MHz, 1 MHz, or 100 kHz. Clock-edge/signal-integrity theory dead too. Scoreboard: two drivers/init recipes, three baud rates, DC path (wiggle), two HATs, panel, ribbons — all cleared. The only remaining difference between the working Pi rig and the ESP32 rig is HAT power: Pi header (5V + stiff 3.3V) vs breakout 3V3 pin (devkit regulator shared with ESP32+PSRAM). BUSY answering RST takes ~no current; the booster starting at POWER ON is the one real draw — a sag there fits every observation (alive panel, no BUSY dip, instant busy-wait pass-through). Next test: move the harness VCC wire from the breakout 3V3 terminal to its 5V terminal (HAT is Rev2.2, takes 5V; it receives 5V from the Pi header in the working setup), rerun test_ws.py.
- Nov 9, 2026: 5V VCC feed test ALSO failed identically (test_ws 0.957s) — power-rail theory dead. Every ESP32 attempt so far used the hardware SPI peripheral; the wiggle test only proved GPIO-mode toggling. Next: probe_soft.py — POWER ON via SoftSPI bit-bang (bypasses the SPI peripheral entirely). Also flagged for Mark: re-confirm the HAT config switches (Interface 0, Display B) since the HAT has been handled all day — a bumped Interface switch (3-line mode) would produce exactly this alive-but-deaf symptom. If SoftSPI also fails, the only span never yet proven is the HAT's 8-pin socket route itself (the Pi success used the 40-pin header route); decider then is driving the socket from the Pi.
- Nov 9, 2026: BREAKTHROUGH — probe_soft2.py (SoftSPI bit-bang, dummy miso GPIO 9): BUSY after reset 1, BUSY dipped = True. The panel heard POWER ON and started its booster for the first time on the ESP32. Everything else identical (pins, wires, power, Pi init recipe). Culprit: the hardware SPI(1) peripheral path on this bench S3 — mechanism unproven, empirical fact solid (ticker's MAX7219 on a different S3/pins works via hardware SPI, so it is setup-specific, not a blanket S3 rule). HAT switches also confirmed B / 0 today. Next: epd7in5b_soft.py (driver switched to SoftSPI 100 kHz, read_busy simplified to the Pi driver's plain delay loop) uploaded as epd7in5b.py, run existing test_epd.py for the full pattern.
- Nov 9, 2026: STEP 1 PASSED. test_epd.py with the SoftSPI driver drew the full test pattern on the panel (photo from Mark: black block + BLACK PLANE label top-left, red block + RED PLANE top-right, 'metar-micro panel test', red text line, blocks along the bottom). The ESP32 now drives the 7.5" B V2 panel end to end. epd7in5b.py canonicalized on SoftSPI and pushed to github.com/markyharris/metar-micro as the initial commit with test_epd.py and this SPEC. Next phase is v1 (fetch/decode + layouts 0/1/5 + admin + overnight-off) when Mark says go.
