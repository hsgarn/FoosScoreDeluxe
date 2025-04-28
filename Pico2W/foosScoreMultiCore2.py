#Copyright 2023-2025 Hugh Garner
#Permission is hereby granted, free of charge, to any person obtaining a copy 
#of this software and associated documentation files (the "Software"), to deal 
#in the Software without restriction, including without limitation the rights 
#to use, copy, modify, merge, publish, distribute, sublicense, and/or sell 
#copies of the Software, and to permit persons to whom the Software is 
#furnished to do so, subject to the following conditions:
#
#The above copyright notice and this permission notice shall be included in 
#all copies or substantial portions of the Software.
#
#THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR 
#IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, 
#FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL 
#THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR 
#OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, 
#ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR 
#OTHER DEALINGS IN THE SOFTWARE.
#v2.09 04/27/2025 Reworked LED Strip handling and send_command queue. Added Test LEDs sub menu.
#v2.08 11/20/2024 LCD improvements, Show Host, force standalonemode when no network available, add team colors, debugmode.
#v2.07 12/31/2023
#v2.06 12/29/2023 Pass c around to fix errors when scoring, time out. Got config save working
#v2.05 07/31/2023 Test Inputs, Test LEDs, FoosOBS Mode, StandAlone Mode mostly working
#v2.04 07/15/2023 Reworked configuration and validation
#v2.03 06/30/2023 Add led strips
#v2.02 02/17/2023 Add lcd displays
#v2.01 02/04/2023 Add Time Out push button logic
#v2.00 01/01/2023 Compatible with FoosOBSPlus v2.00 and above

import network
import secretsHP
import secretsHome
import config
import configHelper
import time
import sys
import socket
import select
import _thread
from pico_i2c_lcd import I2cLcd
import machine
from machine import Pin
from machine import Timer
from machine import I2C
from neopixel import Neopixel
from collections import deque

isHome = True
TEAM1 = 0
TEAM2 = 1
showLog = True
LOG_LEVEL = "DEBUG"
keepRunning = True
pointsToWin = 5
maxPointsToWin = 99
minPointsToWin = 1
gamesToWin = 2
maxGamesToWin = 99
minGamesToWin = 1
ballsInRack = 9
maxBallsInRack = 99
minBallsInRack = 1
rackMode = "On"
tourneyMode = "Off"
changeValueMode = False
allLEDs = []
skipNetwork = 0
# Color RGB values
red = (255, 0, 0)
softred = tuple(int(element * .3) for element in red)
green = (0,255,0)
softgreen = tuple(int(element * .3) for element in green)
blue = (0,0,255)
softblue = tuple(int(element * .3) for element in blue)
yellow = (255,255,0)
softyellow = tuple(int(element * .3) for element in yellow)
off = (0,0,0)
orange = (255, 50, 0)
indigo = (100, 0, 90)
violet = (200, 0, 100)
colors_rgb = [red, orange, yellow, green, blue, indigo, violet]

def debug(message, *args, level="INFO", exc=None, multiLine=False):
    """
    A flexible debug function with adjustable logging levels.

    Args:
        message (str): The main debug message.
        *args: Additional arguments to format into the message.
        level (str): The severity level of the debug message. Default is "INFO".
        exc (Exception, optional): Pass an exception to include its traceback.
    """
    # Define logging level priorities
    level_priority = {"DEBUG": 1, "INFO": 2, "WARNING": 3, "ERROR": 4}
    current_level_priority = level_priority.get(level.upper(), 0)
    min_level_priority = level_priority.get(LOG_LEVEL.upper(), 0)

    # Skip messages with lower priority than the global LOG_LEVEL
    if current_level_priority < min_level_priority:
        return

    levels = {"DEBUG": "[DEBUG]", "INFO": "[INFO]", "WARNING": "[WARNING]", "ERROR": "[ERROR]"}
    prefix = levels.get(level.upper(), "[DEBUG]")
    
    # Format the message
    formatted_message = message.format(*args) if args else message
    
    # Print the formatted debug message
    if multiLine:
        print(f"{prefix} {formatted_message}", end="")
    else:
        print(f"{prefix} {formatted_message}")
    
    # Print exception traceback if provided
    if exc is not None:
        print(f"{prefix} Exception: {exc}")
        sys.print_exception(exc)

class LEDStrip:
    def __init__(self, pin=28, num_pixels=30, state_machine=0, rgb_mode="GRB"):
        debug("Init LED Strip", level="DEBUG")
        debug("pin: {}",pin, level="DEBUG")
        debug("num_pixels: {}",num_pixels,level="DEBUG")
        debug("state_machine: {}",state_machine,level="DEBUG")
        debug("rgb_mode: {}",rgb_mode,level="DEBUG")
        self.num_pixels = num_pixels
        self.strip = Neopixel(num_pixels, state_machine, pin, rgb_mode)
        self.command_maxlen = 10
        self.command = deque((),self.command_maxlen)
        self.command_lock = None

    def initialize(self):
        debug("initializing thread...", level="DEBUG")
        self.command_lock = _thread.allocate_lock()
        # Start the LED control thread on Core 1
        debug("launching thread: {}", id(self), level="DEBUG")
        _thread.start_new_thread(self._led_control_loop, ())
        debug("thread launched.",level="DEBUG")

    def send_command(self, command="blink", ranges=allLEDs, duration=1, color=red):
        """
        Send a command to the LED strip.
        :param command: The pattern to display (e.g., 'blink', 'fade').
        :param ranges: One or more ranges of led pixels (e.g., ((1,5),(7,12)...)
        :param duration: Duration for the pattern in seconds.
        """
        debug("send_command: {}, ranges: {}, duration: {}, color: {}",command,ranges,duration,color,level="DEBUG")
        self.command_lock.acquire()
        try:
            if len(self.command) < self.command_maxlen:
                self.command.append((command, ranges, duration, color))
            else:
                debug("Command queue full!  Dropping command: {}",command, level="WARNING")
        finally:
            self.command_lock.release()

    def _led_control_loop(self):
        """Core 1 thread loop to control the LED strip."""
        debug("led control loop thread running",level="DEBUG")
        debug("Using lock from", id(self),level="DEBUG")
        debug("command_lock is:", self.command_lock,level="DEBUG")
        while True:
            cmd = None
            self.command_lock.acquire()
            try:
                if self.command:
                    cmd = self.command.popleft()
            finally:
                self.command_lock.release()
            if cmd:
                command, ranges, duration, color = cmd
                self._execute_command(command, ranges, duration, color)
            else:
                # No command available, sleep a little bit
                time.sleep(0.1)

    def _set_color(self, ranges, color):
        # Iterate over the specified ranges
        for start, end in ranges:
            # Set the color for each LED within the range
            for i in range(start, end + 1):
                self.strip[i] = color

    def _clear_strip(self):
        """Turn off all LEDs."""
        for i in range(self.num_pixels):
            self.strip[i] = off
        self.strip.show()
        
    def _execute_command(self, command, ranges, duration, color):
        """
        Execute the given LED pattern.
        :param pattern: The pattern to display.
        :param duration: Duration for the pattern in seconds.
        """
        if command == "blink":
            for _ in range(duration * 2):  # Blink for duration seconds
                self._set_color(ranges, color)
                self.strip.show()
                time.sleep(0.5)
                self._clear_strip()
                time.sleep(0.5)
        elif command == "solid":
            self._set_color(ranges, color)
            self.strip.show()
        elif command == "fade":
            for brightness in range(0, 256, 5):  # Fade in
                for i in range(self.num_pixels):
                    self.strip[i] = (brightness, brightness, brightness)
                self.strip.show()
                time.sleep(0.05)
            for brightness in range(255, -1, -5):  # Fade out
                for i in range(self.num_pixels):
                    self.strip[i] = (brightness, brightness, brightness)
                self.strip.show()
                time.sleep(0.05)
        elif command == "clear":
            self._clear_strip()
        elif command == "score":
            for _ in range(3):
                self._set_color(ranges, green)
                self.strip.show()
                time.sleep(duration)
                self._set_color(ranges, red)
                self.strip.show()
                time.sleep(duration)
            self._clear_strip()
        elif command == "timeout":
            debug("executing timeout command - red",level="DEBUG")
            self._set_color(ranges, red)
            self.strip.show()
            time.sleep(duration*.666/1000)
            debug("executing timeout command - green",level="DEBUG")
            self._set_color(ranges, green)
            self.strip.show()
            time.sleep(duration*.334/1000)
            debug("executing timeout command - clear",level="DEBUG")
            self._clear_strip()
        elif command == "test":
            for i in range(0, NUMBER_PIXELS):
                self.strip.set_pixel(i, red)
                if i > 0: self.strip.set_pixel(i-1, off)
                if i == 0: self.strip.set_pixel(NUMBER_PIXELS-1, off)
                self.strip.show()
                time.sleep(duration)
            for x in range(0,NUMBER_PIXELS):
                i = NUMBER_PIXELS - x
                self.strip.set_pixel(i-1, green)
                if i < NUMBER_PIXELS: self.strip.set_pixel(i, off)
                if i == NUMBER_PIXELS: self.strip.set_pixel(NUMBER_PIXELS-1, off)
                self.strip.show()
                time.sleep(duration)
            self._clear_strip()
        elif command == "rainbowchase":
            step = round(self.num_pixels / len(colors_rgb))
            current_pixel = 0
            self.strip.brightness(50)
            for color1, color2 in zip(colors_rgb, colors_rgb[1:]):
                self.strip.set_pixel_line_gradient(current_pixel, current_pixel + step, color1, color2)
                current_pixel += step
            self.strip.set_pixel_line_gradient(current_pixel, self.num_pixels - 1, violet, red)
            for _ in range(duration):
                self.strip.rotate_right(1)
                time.sleep(0.042)
                self.strip.show()
            self._clear_strip()
        else:
            for i in range(0, NUMBER_PIXELS):
                self.strip.set_pixel(i,red)
                self.strip.show()
                time.sleep(.1)
            self._clear_strip()

def resetAll():
    global teamScore, teamGames, teamTO, lastScored, teamGameWon, teamMatchWon, newMatchReady, ballsInRack, pointsToWin, gamesToWin, isRackMode, isFoosOBSMode, isStandAloneMode, isTestMode, isMenuOn
    teamScore = [0, 0]
    teamGames = [0, 0]
    teamTO = [0, 0]
    lastScored = "-"
    teamGameWon = [False, False]
    teamMatchWon = [False, False]
    newMatchReady = False
    ballsInRack = 9
    pointsToWin = 5
    gamesToWin = 2
    isRackMode = True
    isFoosOBSMode = True
    isStandAloneMode = False
    isTestMode = False
    isMenuOn = False

def mainMenu():
    global menuLevel, isMenuOn
    isMenuOn = True
    printMenuLCD(lcd)
    return

def printMenuLCD(lcd):
    global menuItems, menuLength, menuFirstLine, menuLevel
    row = 0
    menuPtr = menuFirstLine
    menuLength = len(menuItems[menuLevel])
    for x in range(menuFirstRow,menuLastRow+1):
        printLCD(lcd,0,row,f" {menuItems[menuLevel][menuPtr+row]}",True)
        row += 1
    if changeValueMode:
        invertCursorLCD(lcd)
    else:
        printCursorLCD(lcd)

def decrementCursor(lcd):
    global cursorLine, menuFirstLine, menuLength
    cursorLine -= 1
    if cursorLine < 0:
        menuFirstLine -= 1
        if menuFirstLine < 0:
            menuFirstLine = menuLength-4
            cursorLine = 3
        else:
            cursorLine = 0
    printMenuLCD(lcd)
    return cursorLine
        
def incrementCursor(lcd):
    global cursorLine, menuFirstLine, menuLength
    cursorLine += 1
    if cursorLine > 3:
        menuFirstLine += 1
        if menuFirstLine > menuLength-4:
            menuFirstLine = 0
            cursorLine = 0
        else:
            cursorLine = 3
    printMenuLCD(lcd)
    return cursorLine

def printLCD(lcd,col,row,line,clearRow):
    global lcdDisplayWidth
    lcd.move_to(col,row)
    lcd.putstr(f"{line:<{lcdDisplayWidth}}")

def printCursorLCD(lcd):
    global cursorLine, lcdDisplayWidth
    lcd.move_to(0,cursorLine)
    lcd.putstr("<")
    lcd.move_to(lcdDisplayWidth-1,cursorLine)
    lcd.putstr(">")

def invertCursorLCD(lcd):
    global cursorLine, lcdDisplayWidth
    lcd.move_to(0,cursorLine)
    lcd.putstr(">")
    lcd.move_to(lcdDisplayWidth-1,cursorLine)
    lcd.putstr("<")

def blink(blinks, duration):
    global skipBlinks
    if skipBlinks:
        return
    while blinks > 0:
            LED.value(True)
            time.sleep(duration)
            LED.value(False)
            time.sleep(duration)
            blinks = blinks - 1

def pinId(pin):
#    Apparently pin has different formats depending on uf2 loaded.
    debug("pin: {}",pin,level="DEBUG")
    return int(''.join(filter(str.isdigit, str(pin).rstrip(",")))) 
#    return int(str(pin)[4:6].rstrip(","))  #Pin(18, mode=IN)      pico 1 W
#    return int(str(pin)[8:10].rstrip(",")) #Pin(GPIO16, mode=IN)  pico 2 W

def timerDone(Source):
    global isBlocked, sensorPinNbr
    isBlocked = False
    team1LED.value(0)
    team2LED.value(0)
    debug("Sensor: {}: Timer done",sensorPinNbr,level="DEBUG")

def timerPBDone(x):
    global isPBBlocked
    isPBBlocked[x] = False
    timeOutLED.value(0)
    debug("timerPBDone: {}",x,level="DEBUG")
#    clearLEDStrip()

def sensorInterrupt(pin):
    global sensorStates, blockingScoreTimer, isBlocked, teamScored, sensorPinNbr, delaySensor
    id = pinId(pin)
    idx = pins.index(id)
    sensorState = sensorStates[idx]
    led = leds[idx]
    team = teams[idx]-1
    for sensor in sensors:
        sensor.irq(handler=None)
    for pushbutton in pushbuttons:
        pushbutton.irq(handler=None)
    sensor = sensors[idx]
    if (sensor.value() == onState) and (sensorStates[idx] == 0):
        if not(isBlocked):
            sensorStates[idx] = 1
            isBlocked = True
            led.value(1)
            teamScored[team] = True
            sensorPinNbr = id
            debug("Sensor: {}, Team {}: On",sensorPinNbr, team+1, level="DEBUG")
    elif (sensor.value() == offState) and (sensorStates[idx] == 1):
        blockingScoreTimer = Timer(period = delaySensor, mode = Timer.ONE_SHOT, callback = timerDone)
        sensorStates[idx] = 0
    for sensor in sensors:
        sensor.irq(handler=sensorInterrupt)
    for pushbutton in pushbuttons:
        pushbutton.irq(handler=pushbuttonInterrupt)

def pushbuttonInterrupt(pin):
    global teamTimeOut, pushbuttonPinNbr, isPBBlocked, delayPBTime, blockingPBTimer, timeOutWarnTimer, isMenuOn, isActionPBPressed, isTestMode
    if isMenuOn:
        timeDelay = delayActionPB
    else:
        timeDelay = delayPBTime
    id = pinId(pin)
    idx = pushbuttonPins.index(id)
    team = teams[idx]-1
    for sensor in sensors:
        sensor.irq(handler=None)
    for pushbutton in pushbuttons:
        pushbutton.irq(handler=None)
    pushbutton = pushbuttons[idx]
    if idx == 2: #Action Button
        if (pushbutton.value() == onPBState) and not(isPBBlocked[idx]):
            isPBBlocked[idx] = True
            timeOutLED.value(1)
            pushbuttonPinNbr = id
            isActionPBPressed = True
            blockingPBTimer[idx].deinit()
            blockingPBTimer[idx] = Timer(period = delayActionPB, mode = Timer.ONE_SHOT, callback = lambda b: timerPBDone(idx))
            print(f"actionPB: {pushbuttonPinNbr}: On")
    else: #TimeOut Buttons
        if isTestMode:
            blockingPBTimer[idx].deinit()
            blockingPBTimer[idx] = Timer(period = timeDelay, mode = Timer.ONE_SHOT, callback = lambda b: timerPBDone(idx))
        else:
            if (pushbutton.value() == onPBState) and not(isPBBlocked[idx]):
                isPBBlocked[idx] = True
                timeOutLED.value(1)
                pushbuttonPinNbr = id
                teamTimeOut[team] = True
                blockingPBTimer[idx].deinit()
                blockingPBTimer[idx] = Timer(period = timeDelay, mode = Timer.ONE_SHOT, callback = lambda b: timerPBDone(idx))
                if isMenuOn:
                    debug("PB{}: {}: Pressed ",idx,pushbuttonPinNbr,level="DEBUG")
                else:
                    debug("Team{}TO",idx+1,level="DEBUG")
    for sensor in sensors:
        sensor.irq(handler=sensorInterrupt)
    for pushbutton in pushbuttons:
        pushbutton.irq(handler=pushbuttonInterrupt)

def sendMessage(c, message):
    global isConnected
    try:
        displayMessage = message.replace("\r","\\r")
        displayMessage = displayMessage.replace("\n","\\n")
        debug("Sending: [{}]",displayMessage,level="INFO")
        c.send(message.encode(FORMAT))
    except Exception as ex:
        if(type(ex).__name__=="OSError"):
            debug("{} exception in [sendMessage] function: ",type(ex).__name__,level="ERROR",exc=ex)
            debug("Socket disconnected.",level="INFO")
        else:
            debug("{} exception in [sendMessage] function: ",type(ex).__name__,level="ERROR",exc=ex)
        debug("Closing socket.",level="INFO")
        c.close()
        isConnected = False

def sendScore(c,teamAndPin):
    sendMessage(c,f"Team:{teamAndPin}\r\n")

def sendTimeOut(c,teamAndPin):
    sendMessage(c,f"TO:{teamAndPin}\r\n")

def parseSave():
    writeDone = False
    dateStamp = ""
    config = ""
    configArray = []
    text = cmd[1].rsplit("\n")
    for t in text:
        debug("Received: {}",format(t),level="INFO")
        if t != "":
            if t[0:3] == "End":
                debug("Got End",level="INFO")
                if configHelper.validateConfigArray(configArray,requiredConfigNames,requiredConfigTests,validPins,validSDAs,validSCLs,validI2Cs,validStateMachines):
                    if dateStamp != "":
                        oldConfig = configHelper.readConfigFile(CONFIGFILE)
                        if oldConfig == config:
                            debug("New config same as old config - write aborted.",level="WARNING")
                        else:
                            configHelper.writeConfigFile(oldConfig,f"{CONFIGFILE}{dateStamp}")
                            debug("Old config backed up as {}{}.",CONFIGFILE,dateStamp,level="INFO")
                            debug("writing config...",level="INFO")
                            configHelper.writeConfigFile(config,CONFIGFILE)
                    else:
                        debug("No dateStamp found - write aborted.",level="WARNING")
                else:
                    debug("Invalid config - write aborted.",level="ERROR")
            elif t[0:4] == "date":
                dateStamp = t[7:21]
            else:
                config = f"{config}{t.strip()}\r\n"
                configArray.append(t.strip())

def sendConfigFile(filename):
    config = configHelper.readConfigFile(filename)
    sendMessage(c,"Read:\r\n")
    for line in config:
        line = f"Line:{line.rstrip()}"
        if line != "Line:":
            line = f"{line}\r\n"
            sendMessage(c,line)

def clearLEDStrip():
    debug("Called clearLEDStrip.",level="DEBUG")
# Turn off all LED on Strip
####    for i in range(0, NUMBER_PIXELS):
####        strip.set_pixel(i, off)
####    strip.show()
    led_strip.send_command(command="clear",ranges=allLEDs,duration=0,color=off)

def set_strip_color(ranges, color):
    # Iterate over the specified ranges
    for start, end in ranges:
        # Set the color for each LED within the range
        for i in range(start, end + 1):
            pass
####            strip[i] = color

def set_strip_color_show(ranges, color):
    pass
####    set_strip_color(ranges,color)
####    strip.show()

def stripScore(team):
    ranges = teamsLEDRanges[team]
    led_strip.send_command("score",ranges,.5)

def stripTimeOut(team):
#    set_strip_color_show(teamsLEDRanges[team],red)
    led_strip.send_command("timeout",teamsLEDRanges[team],delayPB)

def testLEDs(delay):
    led_strip.send_command("test",NUMBER_PIXELS,delay)
    led_strip.send_command("rainbowchase",NUMBER_PIXELS,delay*300)
    allBlink(6, .3)

def allBlink(blinks, duration):
    global skipBlinks
    if skipBlinks:
        return
    while blinks > 0:
            team1LED.value(True)
            team2LED.value(True)
            LED.value(True)
            time.sleep(duration)
            team1LED.value(False)
            team2LED.value(False)
            LED.value(False)
            time.sleep(duration)
            blinks = blinks - 1

def sendFoosOBSPlusScreen(line,foosOBSLines):
    foosOBSLines[0] = foosOBSLines[1]
    foosOBSLines[1] = foosOBSLines[2]
    foosOBSLines[2] = foosOBSLines[3]
    foosOBSLines[3] = line
    debug("{}",line,level="INFO")
    updateFoosOBSScreen(foosOBSLines)
    return foosOBSLines
    
def updateFoosOBSScreen(foosOBSLines):
    x = 0
    for line in foosOBSLines:
        lcd.move_to(0,x)
        lcd.putstr(f"{line:<{lcdDisplayWidth}}")
        x+=1

def updateScoreScreen():
    if not isTestMode and not isMenuOn:
        lines = ["Mode: Stand Alone",
                 f"{teamColors[0]}: G{teamGames[TEAM1]} P{teamScore[TEAM1]} T{teamTO[TEAM1]}",
                 f"{teamColors[1]}: G{teamGames[TEAM2]} P{teamScore[TEAM2]} T{teamTO[TEAM2]}",
                 f"Last Scored: {lastScored}"]
        x = 0
        for line in lines:
            lcd.move_to(0,x)
            lcd.putstr(f"{line:<{lcdDisplayWidth}}")
            x+=1

def resetGamesScoresTOs():
    global teamScore,teamGames,teamTO,lastScored,teamGameWon,teamMatchWon,newMatchReady
    teamScore = [0,0]
    teamGames = [0,0]
    teamTO = [0,0]
    lastScored = "-"
    teamGameWon = [False,False]
    teamMatchWon = [False,False]
    newMatchReady = False
    updateScoreScreen()
    
def handleTeamScored(c,teamNumber,foosOBSLines):
    global teamScore,teamGames,teamGameWon,teamMatchWon,newMatchReady,lastScored,teamTO,sensorPinNbr
    teamScored[teamNumber] = False
    line = f"Team{teamNumber+1} Scored/Pin {sensorPinNbr}"
    debug(line,level="DEBUG")
    if(isConnected):
        sendScore(c,f"{teamNumber+1},{sensorPinNbr}")
    if not isTestMode:
        stripScore(teamNumber)
        if isStandAloneMode:
            if newMatchReady:
                resetGamesScoresTOs()
            teamScore[teamNumber] += 1
            lastScored = f"{teamColors[teamNumber]}"
            if teamScore[teamNumber] >= pointsToWin:
                teamGames[teamNumber] += 1
                teamGameWon[teamNumber] = True
                if teamGames[teamNumber] >= gamesToWin:
                    teamMatchWon[teamNumber] = True
                    newMatchReady = True
                else:
                    teamScore = [0,0]
                    teamTO = [0,0]
            updateScoreScreen()
        elif isFoosOBSMode:
            foosOBSLines = sendFoosOBSPlusScreen(line,foosOBSLines)
    return foosOBSLines

def handleTimeOut(c,teamNumber,foosOBSLines,changeValueMode):
    teamTimeOut[teamNumber] = False
    line = f"Team{teamNumber + 1} TimeOut/Pin {pushbuttonPinNbr}"
    debug(line,level="DEBUG")
    if isMenuOn:
        if changeValueMode:
            if teamNumber == TEAM1:
                decrementValue()
            else:
                incrementValue()
        else:
            if teamNumber == TEAM1:
                decrementCursor(lcd)
            else:
                incrementCursor(lcd)
    else:
        if(isConnected):
            sendTimeOut(c,f"{teamNumber + 1},{pushbuttonPinNbr}")
        if not isTestMode:
            stripTimeOut(teamNumber)
            if isStandAloneMode:
                teamTO[teamNumber] += 1
                updateScoreScreen()
            elif isFoosOBSMode:
                foosOBSLines = sendFoosOBSPlusScreen(line,foosOBSLines)
    return foosOBSLines

def checkSocket(s,isConnected,connectCount):
    global c
    try:
        r, w, err = select.select((s,), (), (), .001)
    except select.error as ex:
        s.close()
        isConnected = False
        debug("connection error. Aborting..",level="ERROR",exc=ex)
        sys.exit(1)
    if r:
        for readable in r:
            c, addr = s.accept()
            connectCount += 1
            timeoutCount = 0
            recvCount = 0
            ipAddr = addr[0]
            ipName = addr[1]
            isConnected = True
            debug("Connected to : {} : {}",ipAddr,ipName,level="INFO")
            debug("Connection number: {}",connectCount,level="DEBUG")
            tempFoosOBSLines = [f"Connect on: {ipName}",f"{ipAddr}",f"Connection# {connectCount}",'']
            updateFoosOBSScreen(tempFoosOBSLines)
            c.settimeout(.01)
            blink(3,.15)
    return s,isConnected,connectCount

def decrementValue():
    global menuItems,pointsToWin,maxPointsToWin,minPointsToWin
    global gamesToWin,maxGamesToWin,minGamesToWin
    global ballsInRack,maxBallsInRack,minBallsInRack
    global isRackMode,rackMode,tourneyMode
    if action[0:13] == "Points To Win":
        pointsToWin = pointsToWin - 1
        if pointsToWin < minPointsToWin:
            pointsToWin = minPointsToWin
        menuItems[1][0] = f"Points To Win  {pointsToWin}"
    elif action[0:12] == "Games To Win":
        gamesToWin = gamesToWin - 1
        if gamesToWin < minGamesToWin:
            gamesToWin = minGamesToWin
        menuItems[1][1] = f"Games To Win  {gamesToWin}"
    elif action[0:13] == "Balls In Rack":
        ballsInRack = ballsInRack - 1
        if ballsInRack < minBallsInRack:
            ballsInRack = minBallsInRack
        menuItems[1][2] = f"Balls In Rack  {ballsInRack}"
    elif action[0:9] == "Rack Mode":
        if rackMode == "On":
            isRackMode = False
            rackMode = "Off"
            tourneyMode = "On"
        else:
            isRackMode = True
            rackMode = "On"
            tourneyMode = "Off"
        menuItems[1][3] = f"Rack Mode  {rackMode}"
        menuItems[1][4] = f"Tourney Mode  {tourneyMode}"
    elif action[0:12] == "Tourney Mode":
        if tourneyMode == "On":
            tourneyMode = "Off"
            isRackMode = True
            rackMode = "On"
        else:
            tourneyMode = "On"
            isRackMode = False
            rackMode = "Off"
        menuItems[1][3] = f"Rack Mode  {rackMode}"
        menuItems[1][4] = f"Tourney Mode  {tourneyMode}"
    printMenuLCD(lcd)

def incrementValue():
    global menuItems,pointsToWin,maxPointsToWin,minPointsToWin
    global gamesToWin,maxGamesToWin,minGamesToWin
    global ballsInRack,maxBallsInRack,minBallsInRack
    global isRackMode,rackMode,tourneyMode
    if action[0:13] == "Points To Win":
        pointsToWin = pointsToWin + 1
        if pointsToWin > maxPointsToWin:
            pointsToWin = maxPointsToWin
        menuItems[1][0] = f"Points To Win  {pointsToWin}"
    elif action[0:12] == "Games To Win":
        gamesToWin = gamesToWin + 1
        if gamesToWin > maxGamesToWin:
            gamesToWin = maxGamesToWin
        menuItems[1][1] = f"Games To Win  {gamesToWin}"
    elif action[0:13] == "Balls In Rack":
        ballsInRack = ballsInRack + 1
        if ballsInRack > maxBallsInRack:
            ballsInRack = maxBallsInRack
        menuItems[1][2] = f"Balls In Rack  {ballsInRack}"
    elif action[0:9] == "Rack Mode":
        if rackMode == "On":
            isRackMode = False
            rackMode = "Off"
            tourneyMode = "On"
        else:
            isRackMode = True
            rackMode = "On"
            tourneyMode = "Off"
        menuItems[1][3] = f"Rack Mode  {rackMode}"
        menuItems[1][4] = f"Tourney Mode  {tourneyMode}"
    elif action[0:12] == "Tourney Mode":
        if tourneyMode == "On":
            tourneyMode = "Off"
            rackMode = "On"
        else:
            tourneyMode = "Off"
            rackMode = "On"
        menuItems[1][3] = f"Rack Mode  {rackMode}"
        menuItems[1][4] = f"Tourney Mode  {tourneyMode}"
    printMenuLCD(lcd)

def handleMenuAction(action, obs_lines):
    global menuLevel,cursorLine,menuFirstLine,isMenuOn,isFoosOBSMode,isStandAloneMode,isTestMode,keepRunning,changeValueMode
    global pointsToWin,minPointsToWin,maxPointsToWin
    global gamesToWin,maxGamesToWin,minGamesToWin
    global ballsInRack,maxBallsInRack,minBallsInRack
    global rackMode,tourneyMode
    if action[:4] == "Exit":
        if menuLevel == 2 or menuLevel == 3:
            menuLevel = 0
        else:
            menuLevel -= 1
        if menuLevel < 0:
            menuLevel = 0
            debug(f'Exited{action[4:]}',level="INFO")
            lcd.clear()
            isMenuOn = False
            if isFoosOBSMode:
                line = f'Exited{action[4:]}'
                sendFoosOBSPlusScreen(line,foosOBSLines)
            else:
                updateScoreScreen()
        else:
            cursorLine = 0
            menuFirstLine = 0
            mainMenu()
    elif action == "End Program":
        debug("program ending",level="INFO")
        keepRunning = False
    elif action == "Reset All":
        debug("reset All selected",level="INFO")
        resetAll()
        menuLevel = 0
        lcd.clear()
        line = 'FoosOBS+Mode Enabled'
        foosOBSLines[0] = ''
        foosOBSLines[1] = ''
        foosOBSLines[2] = ''
        foosOBSLines[3] = 'System Reset'
        sendFoosOBSPlusScreen(line,foosOBSLines)
    elif action == "New Match":
        debug("New Match",level="INFO")
        isMenuOn = False
        isStandAloneMode = True
        isFoosOBSMode = False
        resetGamesScoresTOs()
    elif action == "Settings":
        menuLevel = 1
        menuFirstLine = 0
        cursorLine = 0
        mainMenu()
        debug("Settings selected",level="INFO")
    elif action == "Adjust":
        menuLevel = 2
        menuFirstLine = 0
        cursorLine = 0
        mainMenu()
    elif action == "Test LEDs":
        menuLevel = 3
        menuFirstLine = 0
        cursorLine = 0
        mainMenu()
    elif action == "Test Inputs":
        debug("Test Inputs selected",level="INFO")
        isTestMode = True
        isMenuOn = False
        lcd.clear()
        lcd.move_to(0,0)
        lcd.putstr("Mode: Test Inputs")
        lcd.move_to(0,1)
        line = "L1  L2  L3  PB1 PB2"
        lcd.putstr(line)
        lcd.move_to(0,2)
        line = f"P{pins[0]} P{pins[1]} P{pins[2]} P{pushbuttonPins[0]} P{pushbuttonPins[1]}"
        lcd.putstr(line)
    elif action == "FoosOBS+Mode":
        line = f"{action} Enabled"
        debug(line,level="INFO")
        isFoosOBSMode = True
        isTestMode = False
        isStandAloneMode = False
        isMenuOn = False
        foosOBSLines[0] = ''
        foosOBSLines[1] = ''
        foosOBSLines[2] = ''
        foosOBSLines[3] = ''
        sendFoosOBSPlusScreen(line,foosOBSLines)
    elif action == "StandAlone Mode":
        debug("{} Enabled",action,level="INFO")
        isFoosOBSMode = False
        isTestMode = False
        isStandAloneMode = True
        isMenuOn = False
        updateScoreScreen()
    elif action == "T1 Score+":
        teamScore[TEAM1] += 1
        isMenuOn = False
        updateScoreScreen()
    elif action == "T1 Score-":
        teamScore[TEAM1] -= 1
        if teamScore[TEAM1] < 0:
            teamScore[TEAM1] = 0
        isMenuOn = False
        updateScoreScreen()
    elif action == "T2 Score+":
        teamScore[TEAM2] += 1
        isMenuOn = False
        updateScoreScreen()
    elif action == "T2 Score-":
        teamScore[TEAM2] -= 1
        if teamScore[TEAM2] < 0:
            teamScore[TEAM2] = 0
        isMenuOn = False
        updateScoreScreen()
    elif action == "T1 Game+":
        teamGames[TEAM1] += 1
        isMenuOn = False
        updateScoreScreen()
    elif action == "T1 Game-":
        teamGames[TEAM1] -= 1
        if teamGames[TEAM1] < 0:
            teamGames[TEAM1] = 0
        isMenuOn = False
        updateScoreScreen()
    elif action == "T2 Game+":
        teamGames[TEAM2] += 1
        isMenuOn = False
        updateScoreScreen()
    elif action == "T2 Game-":
        teamGames[TEAM2] -= 1
        if teamGames[TEAM2] < 0:
            teamGames[TEAM2] = 0
        isMenuOn = False
        updateScoreScreen()
    elif action == "T1 TO+":
        teamTO[TEAM1] += 1
        isMenuOn = False
        updateScoreScreen()
    elif action == "T1 TO-":
        teamTO[TEAM1] -= 1
        if teamTO[TEAM1] < 0:
            teamTO[TEAM1] = 0
        isMenuOn = False
        updateScoreScreen()
    elif action == "T2 TO+":
        teamTO[TEAM2] += 1
        isMenuOn = False
        updateScoreScreen()
    elif action == "T2 TO-":
        teamTO[TEAM2] -= 1
        if teamTO[TEAM2] < 0:
            teamTO[TEAM2] = 0
        isMenuOn = False
        updateScoreScreen()
    elif action[0:13] == "Points To Win":
        if changeValueMode:
            changeValueMode = False
        else:
            changeValueMode = True
            value = pointsToWin
            maxValue = maxPointsToWin
            minValue = minPointsToWin
    elif action[0:12] == "Games To Win":
        if changeValueMode:
            changeValueMode = False
        else:
            changeValueMode = True
            value = gamesToWin
            maxValue = maxGamesToWin
            minValue = minGamesToWin
    elif action[0:13] == "Balls In Rack":
        if changeValueMode:
            changeValueMode = False
        else:
            changeValueMode = True
            value = ballsInRack
            maxValue = maxBallsInRack
            minValue = minBallsInRack
    elif action[0:9] == "Rack Mode":
        if changeValueMode:
            changeValueMode = False
        else:
            changeValueMode = True
            value = rackMode
    elif action[0:12] == "Tourney Mode":
        if changeValueMode:
            changeValueMode = False
        else:
            changeValueMode = True
            value = tourneyMode
    elif action == "Show Host":
        if wlan.isconnected():
            hostLine = host
        else:
            hostLine = "No IP Address"
        portLine = f"Port: {port}"
        if isConnected:
            connectLine = "Client Connected"
        else:
            connectLine = "No Client Connected"
        debug("connectLine {}",connectLine,level="DEBUG")
        debug("hostLine {}",hostLine,level="DEBUG")
        debug("portLine {}",portLine,level="DEBUG")
        tempFoosOBSLines = [connectLine,hostLine,portLine,'']
        updateFoosOBSScreen(tempFoosOBSLines)
        time.sleep(3)
        debug("Show Host delay done",level="DEBUG")
        mainMenu()
    elif action == "Test":
        testLEDs(.1)
    elif action == "Solid":
        led_strip.send_command("solid",allLEDs,green)
        time.sleep(3)
        clearLEDStrip()
    elif action == "Time Out Team 1":
        stripTimeOut(0)
    elif action == "Time Out Team 2":
        stripTimeOut(1)
    elif action == "Score Team 1":
        stripScore(0)
    elif action == "Score Team 2":
        stripScore(1)
    elif action == "Fade":
        led_strip.send_command("fade",allLEDs,3,green)
        clearLEDStrip()
    elif action == "Rainbow Chase":
        led_strip.send_command("rainbowchase",allLEDs,200)
    elif action == "Blink":
        led_strip.send_command("blink",allLEDs,3,green)
    elif action == "Clear":
        clearLEDStrip()
    else:
        if isTestMode:
            isTestMode = False
            isMenuOn = True
            menuFirstLine = 0
            cursorLine = 0
            mainMenu()
#
# Main Program Starts Here
#
resetAll()
skipBlinks = False
FORMAT = 'utf-8'
LED = Pin("LED",Pin.OUT)
isConnected = False
CONFIGFILE = "config.py"
REQUIREDCONFIGFILE = "requiredConfigItems.py"
menuPtr = 0
menuLevel = 0
menuItems = [["Show Host","StandAlone Mode","FoosOBS+Mode","Adjust","New Match","Reset All","Show Host","Test Inputs","Test LEDs","Settings","Exit Menu","End Program"],
             [f"Points To Win  {pointsToWin}",f"Games To Win  {gamesToWin}",f"Balls In Rack  {ballsInRack}",f"Rack Mode  {rackMode}",f"Tourney Mode  {tourneyMode}","Exit Settings"],
             ["T1 Score+","T2 Score+","T1 Score-","T2 Score-","T1 Game+","T2 Game+","T1 Game-","T2 Game-","T1 TO+","T2 TO+","T1 TO-","T2 TO-","Exit Adjust"],
             ["Test","Solid","Time Out Team 1","Time Out Team 2","Score Team 1","Score Team 2","Fade","Rainbow Chase","Blink","Clear","Exit Test LEDs"]]
menuLength = len(menuItems[0])
menuFirstRow = 0
menuLastRow = 3
menuFirstLine = 0
lcdDisplayWidth = 20
cursorLine = 0 # line the cursor is on
isPBBlocked = [False, False, False]
isActionPBPressed = False
sensorPinNbr = "-1"
debug("Validating configuration file...",level="INFO")
success,requiredConfigNames,requiredConfigTests,validPins,validSDAs,validSCLs,validI2Cs,validStateMachines = configHelper.loadRequired(REQUIREDCONFIGFILE)
if not success:
    debug("Invalid config file: {}",REQUIREDCONFIGFILE,level="ERROR")
    sys.exit(1)
if not configHelper.validateConfig(configHelper.readConfigFile(CONFIGFILE),requiredConfigNames,requiredConfigTests,validPins,validSDAs,validSCLs,validI2Cs,validStateMachines):
    debug("Invalid config file: {}",CONFIGFILE,level="ERROR")
    sys.exit(1)
port          = config.PORT
SENSOR1       = config.SENSOR1
SENSOR2       = config.SENSOR2
SENSOR3       = config.SENSOR3
LED1          = config.LED1
LED2          = config.LED2
delaySensor   = config.DELAY_SENSOR
delayPB       = config.DELAY_PB
delayActionPB = config.DELAY_ACTION_PB
PB1           = config.PB1
PB2           = config.PB2
PB3           = config.PB3
SDA1          = config.SDA
SCL1          = config.SCL
I2C1          = config.I2C
LEDSTRIP      = config.LEDSTRIP
NUMBER_PIXELS = config.NUMBER_PIXELS
STATE_MACHINE = config.STATE_MACHINE
TEAM1LEDS     = config.TEAM1LEDS
TEAM2LEDS     = config.TEAM2LEDS
DEBUGMODE     = config.DEBUGMODE
debug("Validation successful",level="INFO")
debug("Configuration:",level="INFO")
for attr_name in dir(config):
    if attr_name.isupper():
        attr_value = getattr(config, attr_name)
        debug("{:<20} {:<10}", f"{attr_name}:", str(attr_value), level="INFO")
debug("Settings:")
debug("{:<20} {:<10}",f"Balls In Rack:", str(ballsInRack))
debug("{:<20} {:<10}",f"Score To Win:", str(pointsToWin))
debug("{:<20} {:<10}",f"Games To Win:", str(gamesToWin))
debug("{:<20} {:<10}",f"Rack Mode On:", isRackMode)
debug("{:<20} {:<10}",f"FoosOBS+Mode On:", isFoosOBSMode)
debug("{:<20} {:<10}",f"Stand Alone Mode On:", isStandAloneMode)
debug("{:<20} {:<10}",f"Test Mode On:", isTestMode)
debug("{:<20} {:<10}",f"Menu On:", isMenuOn)
teamsLEDRanges = []
allLEDs = []
teamLEDs = [str(TEAM1LEDS),str(TEAM2LEDS)]
for teamLED in teamLEDs:
    ranges = []
    groups = teamLED.split(';')
    for group in groups:
        start, end = group.split('-')
        ranges.append((int(start),int(end)))
        allLEDs.append((int(start),int(end)))
    teamsLEDRanges.append(ranges)
#set freq=400000 if start to see issues with display
i2c = I2C(id=I2C1,scl=Pin(SCL1),sda=Pin(SDA1),freq=400000)
lcd = I2cLcd(i2c, 0x27, 4, 20)
#lcd2 = I2cLcd(i2c, 0x23, 4, 20)
wlan = network.WLAN(network.STA_IF)
wlan.active(True)
isConnected = False
forceStandAloneMode = False
wlanCount = 0
maxWlanCount = 1
foosOBSLines = ['','','','']
while (wlan.isconnected()==False and wlanCount <= maxWlanCount and skipNetwork==False):
    wlanCount += 1
    if not(isHome):
        foosOBSLines = sendFoosOBSPlusScreen(f"Trying {secretsHP.SSID}",foosOBSLines)
        wlan.connect(secretsHP.SSID, secretsHP.PASSWORD)
        blink(3,.25)
        time.sleep(2)
    if(wlan.isconnected()==False):
        foosOBSLines = sendFoosOBSPlusScreen(f"Trying {secretsHome.SSID}",foosOBSLines)
        wlan.connect(secretsHome.SSID, secretsHome.PASSWORD)
        blink(3,.25)
        time.sleep(2)
led_strip = LEDStrip(LEDSTRIP,NUMBER_PIXELS,STATE_MACHINE,"GRB")
led_strip.initialize()
#led_strip.send_command("fast","",50)
####strip = Neopixel(NUMBER_PIXELS, STATE_MACHINE, LEDSTRIP, "GRB")
clearLEDStrip()
led_strip.send_command("solid",allLEDs,1,softred)
teamColors = ['Yellow','Black ']
lcd.clear()
line = 'Initializing...'
foosOBSLines = sendFoosOBSPlusScreen(line,foosOBSLines)
line = 'Looking for host'
foosOBSLines = sendFoosOBSPlusScreen(line,foosOBSLines)
c = ""
if (wlanCount > maxWlanCount) or skipNetwork:
    led_strip.send_command("solid",allLEDs,1,red)
    blink(4,.25)
    line = 'Unable to connect to host'
    foosOBSLines = sendFoosOBSPlusScreen(line,foosOBSLines)
    forceStandAloneMode = True
else:
    led_strip.send_command("solid",allLEDs,1,softyellow)
    blink(2,.25)
    host = wlan.ifconfig()[0]
    line = 'Connected. Host:'
    foosOBSLines = sendFoosOBSPlusScreen(line,foosOBSLines)
    line = host
    foosOBSLines = sendFoosOBSPlusScreen(line,foosOBSLines)
if forceStandAloneMode:
    debug('forcing standalonemode',level="WARNING")
    isFoosOBSMode = False
    isTestMode = False
    isStandAloneMode = True
    isMenuOn = False
    updateScoreScreen()
else:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        s.bind((host, port))
    except:
        s.close()
        try:
            s.bind((host, port))
        except:
            line = 'Could not bind  '
            foosOBSLines = sendFoosOBSPlusScreen(line,foosOBSLines)
            line = 'aborting........'
            foosOBSLines = sendFoosOBSPlusScreen(line,foosOBSLines)
            led_strip.send_command("solid",allLEDs,1,red)
            sys.exit(1)
    line = f"Socket {port} bound."
    foosOBSLines = sendFoosOBSPlusScreen(line,foosOBSLines)
    s.listen(1)
led_strip.send_command("solid",allLEDs,1,softgreen)
blink(2,.15)
team1LED = Pin(LED1,Pin.OUT)
team2LED = Pin(LED2,Pin.OUT)
timeOutLED = Pin("LED",Pin.OUT)
leds = [team1LED, team2LED, team2LED]
blockingScoreTimer = Timer(period = 1, mode = Timer.ONE_SHOT, callback = timerDone)
delayPBTime = delayPB
blockingPBTimer = [Timer(period = 1, mode = Timer.ONE_SHOT, callback = lambda b: timerPBDone(0)),
                   Timer(period = 1, mode = Timer.ONE_SHOT, callback = lambda b: timerPBDone(1)),
                   Timer(period = 1, mode = Timer.ONE_SHOT, callback = lambda b: timerPBDone(2))]
onState = False
offState = True
x = 0
sensorStates = [0,0,0]
pins = [SENSOR1, SENSOR2, SENSOR3]
sensors = [Pin(p, Pin.IN) for p in pins]
for sensor in sensors:
    sensorStates[x] = not(sensor.value())
    sensor.irq(trigger=Pin.IRQ_RISING | Pin.IRQ_FALLING, handler=sensorInterrupt)
    x+=1
onPBState = True
offPBState = False
x = 0
pushbuttonPins = [PB1, PB2, PB3]
pushbuttons = [Pin(p, Pin.IN) for p in pushbuttonPins]
for pushbutton in pushbuttons:
    pushbutton.irq(trigger=Pin.IRQ_RISING | Pin.IRQ_FALLING, handler=pushbuttonInterrupt)
    x+=1
isBlocked = False
teamScored = [0,0]
teamTimeOut = [0,0]
teams = [1,2,2]
x=0
for team in teams:
    if (team == 1):
        leds[x] = team1LED
    else:
        leds[x] = team2LED
    x+=1
allBlink(3,.3)
isConnected = False
if not(forceStandAloneMode):
   foosOBSLines = sendFoosOBSPlusScreen("FoosOBS+Mode Active",foosOBSLines)
clearLEDStrip()
connectCount = 0
ipAddr = ''
ipName = ''
activitycnt = 0
skipcnt = 0
led_strip.send_command("rainbowchase",allLEDs,100)
while keepRunning:
    if DEBUGMODE:
        if skipcnt > 1000:
            print(activitycnt)
            activitycnt += 1
            if activitycnt > 10000:
                activitycnt = 0
            skipcnt = 0
        skipcnt += 1
    if teamScored[TEAM1]:
        foosOBSLines = handleTeamScored(c,TEAM1,foosOBSLines)
    elif teamScored[TEAM2]:
        foosOBSLines = handleTeamScored(c,TEAM2,foosOBSLines)
    if teamTimeOut[TEAM1]:
        foosOBSLines = handleTimeOut(c,TEAM1,foosOBSLines,changeValueMode)
    elif teamTimeOut[TEAM2]:
        foosOBSLines = handleTimeOut(c,TEAM2,foosOBSLines,changeValueMode)
    if isActionPBPressed:
        debug("actionPBPressed!",level="INFO")
        isActionPBPressed = False
        if isMenuOn:
            if changeValueMode:
                printCursorLCD(lcd)
            else:
                invertCursorLCD(lcd)
            action = menuItems[menuLevel][menuFirstLine+cursorLine]
            debug("Action: {}",action,level="INFO")
            handleMenuAction(action, foosOBSLines)
        elif isTestMode:
            isTestMode = False
            isMenuOn = True
            menuFirstLine = 0
            cursorLine = 0
            mainMenu()
        else:
            isMenuOn = True
            menuFirstLine = 0
            cursorLine = 0
            mainMenu()
    if isTestMode:
        lcd.move_to(0,3)
        line = f" {sensors[0].value()}   {sensors[1].value()}   {sensors[2].value()}   {pushbuttons[0].value()}   {pushbuttons[1].value()}"
        lcd.putstr(line)
    if(isConnected):
        data = False
        try:
            data = c.recv(500)
        except Exception as TimeoutException:
            pass
        if data:
            raw = data.decode(FORMAT)
            cmd = raw.rsplit(":")
            debug("Read from socket:{}",raw,level="INFO")
            debug("Command: [{}]",cmd[0],level="INFO")
            if cmd[0]=="reset":
                debug("Resetting...",level="INFO")
                machine.reset()
            if cmd[0]=="read":
                debug("Reading config...",level="INFO")
                sendConfigFile(CONFIGFILE)
            if cmd[0]=="save":
                debug("Saving config...",level="INFO")
                parseSave()
    if not(forceStandAloneMode):
        s,isConnected,connectCount = checkSocket(s,isConnected,connectCount)
if not(forceStandAloneMode):
    s.close()
team1LED.value(False)
team2LED.value(False)
LED.value(False)
blockingScoreTimer.deinit()
blockingPBTimer[0].deinit()
blockingPBTimer[1].deinit()
blockingPBTimer[2].deinit()
#timeOutWarnTimer.deinit()
for sensor in sensors:
    sensor.irq(handler=None)
for pushbutton in pushbuttons:
    pushbutton.irq(handler=None)
lcd.display_off()
lcd.backlight_off()
debug("Sensors and Display Deactivated.",level="INFO")