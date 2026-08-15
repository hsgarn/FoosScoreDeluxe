#NeoPixel LED-strip command queue + animation patterns. Split out of main.py (v3.01) as its own
#small compile unit. No longer spawns its own thread (see main.py's core1Worker) - the command
#queue/lock are created here and drained by the shared core-1 worker instead.
import time
import _thread
from collections import deque
from neopixel import Neopixel
from debuglog import debug
from colors import red,green,off,violet,colors_rgb

class LEDStrip:
    def __init__(self,pin=28,num_pixels=30,state_machine=0,rgb_mode="GRB"):
        debug("Init LED Strip",level="DEBUG")
        self.num_pixels = num_pixels
        self.strip = Neopixel(num_pixels,state_machine,pin,rgb_mode)
        self.command_maxlen = 10
        self.command = deque((),self.command_maxlen)
        self.command_lock = _thread.allocate_lock()
        #Full-strip range, used as send_command()'s default when no explicit ranges is given.
        #main.py overwrites this with the real team LED ranges once config is loaded.
        self.all_ranges = [(0,num_pixels - 1)]

    def send_command(self,command="blink",ranges=None,duration=1,color=red):
        if ranges is None:
            ranges = self.all_ranges
        debug("send_command: {},ranges: {},duration: {},color: {}",command,ranges,duration,color,level="DEBUG")
        self.command_lock.acquire()
        try:
            if len(self.command) < self.command_maxlen:
                self.command.append((command,ranges,duration,color))
            else:
                debug("Command queue full!  Dropping command: {}",command,level="WARNING")
        finally:
            self.command_lock.release()

    def _non_blocking_sleep(self,duration):
        target_time = time.ticks_add(time.ticks_ms(),int(duration * 1000))
        while time.ticks_diff(target_time,time.ticks_ms()) > 0:
            time.sleep(0.001)

    def _set_color(self,ranges,color):
        for start,end in ranges:
           start = max(0,min(start,self.num_pixels - 1))
           end = max(0,min(end,self.num_pixels - 1))
           for i in range(start,end + 1):
                self.strip[i] = color

    def _clear_strip(self):
        for i in range(self.num_pixels):
            self.strip[i] = off
        self.strip.show()

    def _execute_command(self,command,ranges,duration,color):
        if command == "blink":
            cycles = int(duration *2)
            for _ in range(cycles):
                self._set_color(ranges,color)
                self.strip.show()
                self._non_blocking_sleep(0.5)
                self._clear_strip()
                self._non_blocking_sleep(0.5)
        elif command == "solid":
            self._set_color(ranges,color)
            self.strip.show()
        elif command == "fade":
            steps = 51
            step_time = duration / (steps * 2)
            for brightness in range(0,256,5):
                factor = brightness / 255.0
                adjusted_color = tuple(int(c * factor) for c in color)
                self._set_color(ranges,adjusted_color)
                self.strip.show()
                self._non_blocking_sleep(step_time)
            for brightness in range(255,-1,-5):
                factor = brightness / 255.0
                adjusted_color = tuple(int(c * factor) for c in color)
                self._set_color(ranges,adjusted_color)
                self.strip.show()
                self._non_blocking_sleep(step_time)
        elif command == "clear":
            self._clear_strip()
        elif command == "score":
            for _ in range(3):
                self._set_color(ranges,green)
                self.strip.show()
                self._non_blocking_sleep(duration)
                self._set_color(ranges,red)
                self.strip.show()
                self._non_blocking_sleep(duration)
            self._clear_strip()
        elif command == "timeout":
            self._set_color(ranges,red)
            self.strip.show()
            self._non_blocking_sleep(duration*.666/1000)
            self._set_color(ranges,green)
            self.strip.show()
            self._non_blocking_sleep(duration*.334/1000)
            self._clear_strip()
        elif command == "test":
            for i in range(0,self.num_pixels):
                self.strip.set_pixel(i,red)
                if i > 0: self.strip.set_pixel(i-1,off)
                if i == 0: self.strip.set_pixel(self.num_pixels-1,off)
                self.strip.show()
                self._non_blocking_sleep(duration)
            for x in range(0,self.num_pixels):
                i = self.num_pixels - x
                self.strip.set_pixel(i-1,green)
                if i < self.num_pixels: self.strip.set_pixel(i,off)
                if i == self.num_pixels: self.strip.set_pixel(self.num_pixels-1,off)
                self.strip.show()
                self._non_blocking_sleep(duration)
            self._clear_strip()
        elif command == "rainbowchase":
            step = round(self.num_pixels / len(colors_rgb))
            current_pixel = 0
            self.strip.brightness(50)
            for color1,color2 in zip(colors_rgb,colors_rgb[1:]):
                self.strip.set_pixel_line_gradient(current_pixel,current_pixel + step,color1,color2)
                current_pixel += step
            self.strip.set_pixel_line_gradient(current_pixel,self.num_pixels - 1,violet,red)
            for _ in range(duration):
                self.strip.rotate_right(1)
                self._non_blocking_sleep(0.042)
                self.strip.show()
            self._clear_strip()
        else:
            for i in range(0,self.num_pixels):
                self.strip.set_pixel(i,red)
                self.strip.show()
                self._non_blocking_sleep(.1)
            self._clear_strip()
