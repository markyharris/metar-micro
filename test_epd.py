# test_epd.py - panel proof test for metar-micro (run from Thonny, not main.py)
#
# Draws a labeled test pattern on the Waveshare 7.5" 3-color panel and sleeps.
# Verifies: wiring, SPI, the two color planes, and refresh - before any of the
# METAR app exists. Expected result:
#   - black filled block top-left, labeled BLACK
#   - red filled block top-right, labeled RED
#   - white middle band with a thin black border around the whole screen
#   - alternating black/red/white stripes along the bottom
# If BLACK and RED come out swapped, or everything is inverted, report exactly
# what you see - it is a one-line fix in the driver, and this test exists to
# catch it now rather than after the layouts are built.

import gc
import time
import framebuf
from epd7in5b import EPD, EPD_WIDTH, EPD_HEIGHT, PLANE_BYTES

print("free RAM before planes:", gc.mem_free())
black = bytearray(PLANE_BYTES)
red = bytearray(PLANE_BYTES)
gc.collect()
print("free RAM after planes: ", gc.mem_free())

bfb = framebuf.FrameBuffer(black, EPD_WIDTH, EPD_HEIGHT, framebuf.MONO_HLSB)
rfb = framebuf.FrameBuffer(red, EPD_WIDTH, EPD_HEIGHT, framebuf.MONO_HLSB)

# Start all-white / no-red
bfb.fill(1)
rfb.fill(0)

# Border (black)
bfb.rect(4, 4, EPD_WIDTH - 8, EPD_HEIGHT - 8, 0)
bfb.rect(6, 6, EPD_WIDTH - 12, EPD_HEIGHT - 12, 0)

# Black block top-left, red block top-right
bfb.fill_rect(40, 40, 320, 160, 0)
rfb.fill_rect(440, 40, 320, 160, 1)

# Labels under the blocks (8x8 font, drawn twice for weight)
for dx in (0, 1):
    bfb.text("BLACK PLANE", 40 + dx, 216, 0)
    bfb.text("RED PLANE", 440 + dx, 216, 0)
    bfb.text("metar-micro panel test", 40 + dx, 248, 0)
    rfb.text("red text line", 40 + dx, 272, 1)

# Bottom stripes: black, white, red, white, black ... (60 px tall)
stripe_w = (EPD_WIDTH - 80) // 6
for i in range(6):
    x = 40 + i * stripe_w
    if i % 3 == 0:
        bfb.fill_rect(x, 360, stripe_w - 4, 60, 0)
    elif i % 3 == 2:
        rfb.fill_rect(x, 360, stripe_w - 4, 60, 1)

print("initializing panel...")
epd = EPD()
t0 = time.ticks_ms()
epd.init()
print("pushing frame (refresh takes ~15-25 s)...")
epd.display(black, red)
print("done in %.1f s - panel asleep" % (time.ticks_diff(time.ticks_ms(), t0) / 1000))
epd.sleep()
print("free RAM at end:", gc.mem_free())
