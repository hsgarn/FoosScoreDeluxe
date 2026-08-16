# Example showing how functions, that accept tuples of rgb values,
# simplify working with gradients

import config
import time
from neopixel import Neopixel

LEDS = config.LEDSTRIP
numpix = config.NUMBER_PIXELS
print(f'LEDS={LEDS}, numpixs={numpix}')

if numpix < 13:
    numpix = 13
strip = Neopixel(numpix, 1, LEDS, "GRB")
# strip = Neopixel(numpix, 0, 0, "GRBW")

red = (255, 0, 0)
orange = (255, 50, 0)
yellow = (255, 100, 0)
green = (0, 255, 0)
blue = (0, 0, 255)
indigo = (100, 0, 90)
violet = (200, 0, 100)
colors_rgb = [red, orange, yellow, green, blue, indigo, violet]

# same colors as normaln rgb, just 0 added at the end
colors_rgbw = [color+tuple([0]) for color in colors_rgb]
#colors_rgbw.append((0, 0, 0, 255))

# uncomment colors_rgbw if you have RGBW strip
colors = colors_rgb
#colors = colors_rgbw


step = round(numpix / len(colors))
current_pixel = 0
strip.brightness(50)
print("before for")
for color1, color2 in zip(colors, colors[1:]):
    print(f"color1: {color1}, color2: {color2}")
    strip.set_pixel_line_gradient(current_pixel, current_pixel + step, color1, color2)
    current_pixel += step

strip.set_pixel_line_gradient(current_pixel, numpix - 1, violet, red)

for _ in range(300):
    strip.rotate_right(1)
    time.sleep(0.042)
    strip.show()
strip.clear()
strip.show()