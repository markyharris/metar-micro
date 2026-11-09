# epd7in5b.py - MicroPython driver for Waveshare 7.5" 3-color e-Paper (B) V2
# metar-micro project (ESP32 port of github.com/markyharris/metar)
#
# Ported from Waveshare's epd7in5b_V2.py in Mark's Pi repo: identical init
# sequence, busy handling, refresh and deep-sleep commands; only the plumbing
# (machine.SPI / machine.Pin instead of epdconfig) is new.
#
# Transport: SoftSPI (bit-banged), NOT the hardware SPI peripheral.
# Nov 9, 2026 fault hunt (see SPEC.md): with wiring, power, HAT, panel and
# two different drivers all verified, the panel stayed deaf through the
# hardware SPI(1) path at 100 kHz-10 MHz, then answered POWER ON on the
# first SoftSPI attempt over the same pins. (Hardware SPI(2) is worse: on
# the S3 GENERIC_S3-SPIRAM_OCT v1.29 build, constructing it watchdog-
# resets the chip.) E-paper is slow; bit-banged clocks cost a few seconds
# per frame and buy a path that provably works on both chip families.
#
# Panel: 800 x 480, UC8179 controller, colors: black / white / red.
# Buffer format (one bytearray per plane, 800*480/8 = 48000 bytes):
#   black plane: bit 0 = black pixel, bit 1 = white (matches framebuf MONO_HLSB
#                if you fill(1) and draw with color 0)
#   red plane:   bit 1 = red pixel,   bit 0 = empty (fill(0), draw with color 1)

import time
from machine import Pin, SoftSPI

EPD_WIDTH = 800
EPD_HEIGHT = 480
PLANE_BYTES = EPD_WIDTH * EPD_HEIGHT // 8

# Default pins: valid on BOTH the classic HW-463 devkit and the S3 DevKitC-1
# (N8R8), and broken out on both. Changed Nov 8, 2026 from 27/26/32: those
# GPIOs are not available on the S3 (octal PSRAM bus), and 16/17 are not
# broken out on the HW-463, so DC/RST/BUSY moved to 15/4/21.
# BUSY moved again the same day, 21 -> 5, so all eight wires land on the
# S3 breakout's left rail: 3V3, GND, 13, 18, 14, 15, 4, 5.
# GPIO 5 note: on the S3 it is plain general-purpose I/O (S3 strapping pins
# are 0/3/45/46), so BUSY on 5 is clean there. On the classic ESP32 GPIO 5
# is a strapping pin (internal pull-up, SDIO-slave timing) - BUSY idles HIGH,
# which matches its default, and SDIO-slave mode is not used, so it boots
# normally; if a classic board ever failed to boot with the panel attached,
# disconnect BUSY and retest before suspecting anything else.
PIN_DIN = 13    # MOSI
PIN_CLK = 18    # SCK
PIN_CS = 14
PIN_DC = 15
PIN_RST = 4
PIN_BUSY = 5


class EPD:
    def __init__(self, din=PIN_DIN, clk=PIN_CLK, cs=PIN_CS, dc=PIN_DC,
                 rst=PIN_RST, busy=PIN_BUSY, baudrate=100_000, miso_dummy=9):
        self.width = EPD_WIDTH
        self.height = EPD_HEIGHT
        self.cs = Pin(cs, Pin.OUT, value=1)
        self.dc = Pin(dc, Pin.OUT, value=0)
        self.rst = Pin(rst, Pin.OUT, value=1)
        self.busy = Pin(busy, Pin.IN)
        # SoftSPI, NOT hardware SPI: on the S3 bench board the hardware SPI(1)
        # path never got a panel response (two drivers, 100 kHz-10 MHz, power
        # and wiring all verified), while bit-banged clocks on the same pins
        # worked first try (probe_soft2.py, Nov 9, 2026 - BUSY dipped).
        # ESP32 SoftSPI requires a miso pin even for write-only use; miso_dummy
        # is any spare input (GPIO 9 on the S3 bench; use 19 on classic HW-463,
        # where 6-11 are flash pins and 19 is broken out).
        self.spi = SoftSPI(baudrate=baudrate, polarity=0, phase=0,
                           sck=Pin(clk), mosi=Pin(din), miso=Pin(miso_dummy))

    # ---- low level -----------------------------------------------------
    def _cmd(self, command, data=None):
        self.dc.value(0)
        self.cs.value(0)
        self.spi.write(bytes([command]))
        self.cs.value(1)
        if data is not None:
            self._data(data)

    def _data(self, data):
        self.dc.value(1)
        self.cs.value(0)
        if isinstance(data, int):
            self.spi.write(bytes([data]))
        else:
            self.spi.write(data)
        self.cs.value(1)

    def reset(self):
        self.rst.value(1)
        time.sleep_ms(200)
        self.rst.value(0)
        time.sleep_ms(4)
        self.rst.value(1)
        time.sleep_ms(200)

    def read_busy(self, timeout_ms=60_000):
        # Same scheme as the proven Pi driver: wait while BUSY reads low
        # (0 = busy, 1 = idle). Timeout guards a disconnected panel.
        t0 = time.ticks_ms()
        while self.busy.value() == 0:
            if time.ticks_diff(time.ticks_ms(), t0) > timeout_ms:
                raise OSError("e-paper busy timeout - check wiring/BUSY pin")
            time.sleep_ms(10)
        time.sleep_ms(200)

    # ---- panel operations ----------------------------------------------
    def init(self):
        self.reset()
        self._cmd(0x01, bytes([0x07, 0x07, 0x3F, 0x3F]))   # POWER SETTING
        self._cmd(0x04)                                    # POWER ON
        time.sleep_ms(100)
        self.read_busy()
        self._cmd(0x00, b"\x0F")                           # PANEL SETTING
        self._cmd(0x61, bytes([0x03, 0x20, 0x01, 0xE0]))   # RESOLUTION 800x480
        self._cmd(0x15, b"\x00")                           # DUAL SPI
        self._cmd(0x50, bytes([0x11, 0x07]))               # VCOM/DATA INTERVAL
        self._cmd(0x60, b"\x22")                           # TCON SETTING
        self._cmd(0x65, bytes([0x00, 0x00, 0x00, 0x00]))
        return 0

    def display(self, black_plane, red_plane):
        """Push both planes and refresh. Full refresh takes ~15-25 s."""
        if len(black_plane) != PLANE_BYTES or len(red_plane) != PLANE_BYTES:
            raise ValueError("planes must be %d bytes" % PLANE_BYTES)
        self._cmd(0x10)                 # old data start (black plane)
        self._data(black_plane)
        self._cmd(0x13)                 # new data start (red plane)
        self._data(red_plane)
        self._cmd(0x12)                 # DISPLAY REFRESH
        time.sleep_ms(100)
        self.read_busy(timeout_ms=90_000)

    def clear(self):
        black = bytearray(b"\xFF" * PLANE_BYTES)   # all white
        red = bytearray(PLANE_BYTES)               # no red
        self.display(black, red)

    def sleep(self):
        self._cmd(0x02)                 # POWER OFF
        self.read_busy()
        self._cmd(0x07, b"\xA5")        # DEEP SLEEP
        time.sleep_ms(200)
