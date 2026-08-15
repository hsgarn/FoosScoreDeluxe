#RGB color constants for the LED strip and menu system. Split out of main.py (v3.01) so it's
#its own small, independent compile unit - see main.py's changelog for why that matters here.
red = (255,0,0)
softred = tuple(int(element * .3) for element in red)
green = (0,255,0)
softgreen = tuple(int(element * .3) for element in green)
blue = (0,0,255)
softblue = tuple(int(element * .3) for element in blue)
yellow = (255,255,0)
softyellow = tuple(int(element * .3) for element in yellow)
off = (0,0,0)
orange = (255,50,0)
indigo = (100,0,90)
violet = (200,0,100)
colors_rgb = [red,orange,yellow,green,blue,indigo,violet]
