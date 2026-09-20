#Copyright 2022-2026 Hugh Garner
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
#
#v3.16 09/20/2026
#See CHANGELOG.md for the full revision history.

import network
import config
import time
import sys
import socket
import select
import machine
import _thread
from machine import Pin
from machine import I2C
from machine import SPI
from machine import WDT
from pico_i2c_lcd import I2cLcd
from ST7735 import TFT
from sysfont import sysfont

from colors import red,green,softgreen,blue,yellow,softyellow,off,orange,indigo,violet
from eventqueue import pushEvent,popEvent,takeDropped,EVENT_GOAL,EVENT_TIMEOUT,EVENT_ACTION
import debuglog
from debuglog import debug
import netmsg
from netmsg import sendMessage,sendScore,sendTimeOut,sendConfigFile,FORMAT
import configHelper
from configHelper import readConfigFile,validateConfig,parseSave,CONFIGFILE
from ledstrip import LEDStrip
from iref import IrefClient

#ssl is frozen into current Pico W/2W MicroPython firmware; older builds name it ussl.
try:
    import ssl
except ImportError:
    try:
        import ussl as ssl
    except ImportError:
        ssl = None

try:
    import secrets
except ImportError:
    debug("secrets.py not found - skipping automatic Wi-Fi connect. Use the on-device menu's "
          "\"Wi-Fi Setup\" item to create one.",level="WARNING")
    class secrets:
        NETWORKS = []
        ADMINPASSWORD = ""

try:
    import secretsIref
except ImportError:
    secretsIref = None

TEAM1 = 0
TEAM2 = 1
#Set to a real machine.WDT once the main loop starts (see "Main Program Starts Here") -
#None until then so startup code (WiFi connect retries, etc, which can legitimately run
#past the RP2040's ~8.3s max WDT timeout) doesn't need to feed it. blink()/allBlink()/
#blinkDigit()/blinkTableNumber()/identFlash() all feed it where they run long enough to
#matter, since those can be triggered mid-game (table-number report, identify) once armed.
wdt = None
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
rtMode = "Rack" #[Rack] or [Tour]nament mode
changeValueMode = False
allLEDs = []
skipNetwork = 0
skipBlinks = False

currentPageSPILCD = -1
currentLevelSPILCD = -1
prevBoxPtrSPILCD = -1
currentPageI2CLCD = -1
currentLevelI2CLCD = -1
prevBoxPtrI2CLCD = -1

LED = Pin("LED",Pin.OUT)
TABLEFILE = "table.txt"
ACTION_PB_IDX = 2  #index of PB3 within pushbuttonPins/pushbuttons - the menu "Action" button
HOSTMAC_LEVEL = 5   #menuLevel for the "Show Host/MAC" submenu (picks between the Show Host
                     #and Show MAC info screens below)
SHOWHOST_LEVEL = 6  #menuLevel for the Show Host screen - handleMenuAction() special-cases this
                     #and SHOWMAC_LEVEL so Action returns to HOSTMAC_LEVEL from any of their
                     #lines, not just the last one (see the comment at the top of handleMenuAction).
SHOWMAC_LEVEL = 7   #menuLevel for the Show MAC screen - see SHOWHOST_LEVEL above
NETWORK_LEVEL = 8   #menuLevel for the Network submenu (Connect/Disconnect/Wi-Fi Setup)
MODE_LEVEL = 9       #menuLevel for the Mode submenu (StandAlone Mode/FoosOBS+Mode)
DIAGNOSTICS_LEVEL = 10  #menuLevel for the Diagnostics submenu (Test Inputs/Test LEDs)
#[connect count, host, port] for the Show Host screen - refreshed each time that screen is
#entered (see the "Show Host" branch in handleMenuAction); getMenuItems() is called from
#startup before wlan/host/clients exist, so those can't be read inline here.
showHostLines = ["","",""]
#[title, MAC address, blank] for the Show MAC screen - same refresh timing as showHostLines.
showMacLines = ["","",""]

def getMenuItems():
    return [["Exit Menu","New Match","Adjust","Mode","Network","Settings","Diagnostics","End Program"],
            [f"Points To Win  {pointsToWin}",f"Games To Win  {gamesToWin}",f"Balls In Rack  {ballsInRack}",f"RackTour Mode {rtMode}","Reset All","Start Web Config","Exit Settings"],
            [f"Team 1 Score  {teamScore[TEAM1]}",f"Team 2 Score  {teamScore[TEAM2]}",f"Team 1 Games  {teamGames[TEAM1]}",f"Team 2 Games  {teamGames[TEAM2]}",f"Team 1 TimeOuts  {teamTO[TEAM1]}",f"Team 2 TimeOuts  {teamTO[TEAM2]}","Exit Adjust"],
            ["Test","Solid","Time Out Team 1","Time Out Team 2","Score Team 1","Score Team 2","Fade","Rainbow Chase","Blink","Set Color","Clear","Exit Test LEDs"],
            ["Red","Green","Yellow","Blue","Orange","Indigo","Violet","Clear","Exit Set Color"],
            ["Show Host","Show MAC","Exit Show Host/MAC"],
            [showHostLines[0],showHostLines[1],showHostLines[2],"Return to Menu"],
            [showMacLines[0],showMacLines[1],showMacLines[2],"Return to Menu"],
            ["Connect","Disconnect","Show Host/MAC","Wi-Fi Setup","Exit Network"],
            ["StandAlone Mode","FoosOBS+Mode","Exit Mode"],
            ["Test Inputs","Test LEDs","Exit Diagnostics"]
            ]

def resetAll():
    global teamScore,teamGames,teamTO,lastScored,teamGameWon,teamMatchWon,newMatchReady,ballsInRack,pointsToWin,gamesToWin,isRackMode,isFoosOBSMode,isStandAloneMode,isTestMode,isMenuOn
    teamScore = [0,0]
    teamGames = [0,0]
    teamTO = [0,0]
    lastScored = "-"
    teamGameWon = [False,False]
    teamMatchWon = [False,False]
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
    global isMenuOn
    isMenuOn = True
    menuItems = getMenuItems()
    showMenuSPILCD(menuItems,menuLevel,menuPtr)
    printMenuI2CLCD(i2cLCD1)

def updateCurrentMenuItem():
    updateCurrentMenuItemI2CLCD(i2cLCD1)
    updateCurrentMenuItemSPILCD()

def updateCurrentMenuItemSPILCD():
    if not tftEnabled:
        return
    menuItems = getMenuItems()
    boxPtrSPILCD = menuPtr % maxRowSPILCD
    tft.fillrect((3,3 + boxPtrSPILCD * lineHeight),(156,lineHeight - 1),backgroundColor)
    tft.text((7,3 + boxPtrSPILCD * lineHeight),menuItems[menuLevel][menuPtr],txtColor,sysfont,txtSize)
    boxLineSPILCD(boxPtrSPILCD,selectColor)

def updateCurrentMenuItemI2CLCD(i2cLCD1):
    menuItems = getMenuItems()
    boxPtrI2CLCD = menuPtr % maxRowI2CLCD
    printI2CLCD(i2cLCD1,0,boxPtrI2CLCD,f" {menuItems[menuLevel][menuPtr]}",True)
    if changeValueMode:
        invertCursorI2CLCD(i2cLCD1,boxPtrI2CLCD)
    else:
        printCursorI2CLCD(i2cLCD1,boxPtrI2CLCD)

def boxLineSPILCD(lineNbr,color):
    if not tftEnabled:
        return
    tft.rect((2,2 + lineNbr * lineHeight),(158,lineHeight+1),color)

def showMenuSPILCD(menuItems,menuLevel,menuPtr):
    if not tftEnabled:
        return
    global currentPageSPILCD,currentLevelSPILCD,prevBoxPtrSPILCD
    menuPageSPILCD = menuPtr // maxRowSPILCD
    boxPtrSPILCD = menuPtr % maxRowSPILCD
    pageChangedSPILCD = (menuPageSPILCD != currentPageSPILCD) or (menuLevel != currentLevelSPILCD)
    if pageChangedSPILCD:
        tft.fill(backgroundColor)
        startIdx = menuPageSPILCD * maxRowSPILCD
        endIdx = min(startIdx + maxRowSPILCD,len(menuItems[menuLevel]))
        displayRow = 0
        for idx in range(startIdx,endIdx):
            tft.text((7,3 + displayRow * lineHeight),menuItems[menuLevel][idx],txtColor,sysfont,txtSize)
            displayRow += 1
        currentPageSPILCD = menuPageSPILCD
        currentLevelSPILCD = menuLevel
        prevBoxPtrSPILCD = -1
    else:
        if prevBoxPtrSPILCD >= 0:
            boxLineSPILCD(prevBoxPtrSPILCD,backgroundColor)
    boxLineSPILCD(boxPtrSPILCD,cursorColor)
    prevBoxPtrSPILCD = boxPtrSPILCD

def printMenuI2CLCD(i2cLCD1):
    global menuLength,currentPageI2CLCD,currentLevelI2CLCD,prevBoxPtrI2CLCD
    menuItems = getMenuItems()
    menuPageI2CLCD = menuPtr // maxRowI2CLCD
    boxPtrI2CLCD = menuPtr % maxRowI2CLCD
    pageChangedI2CLCD = (menuPageI2CLCD != currentPageI2CLCD) or (menuLevel != currentLevelI2CLCD)
    menuLength = len(menuItems[menuLevel])
    if pageChangedI2CLCD:
        startIdx = menuPageI2CLCD * maxRowI2CLCD
        endIdx = min(startIdx + maxRowI2CLCD,len(menuItems[menuLevel]))
        displayRow = 0
        for idx in range(startIdx,endIdx):
            printI2CLCD(i2cLCD1,0,displayRow,f" {menuItems[menuLevel][idx]}",True)
            displayRow += 1
        if displayRow < maxRowI2CLCD:
            for idx in range (displayRow,maxRowI2CLCD):
                printI2CLCD(i2cLCD1,0,idx," ",True)
        currentPageI2CLCD = menuPageI2CLCD
        currentLevelI2CLCD = menuLevel
        prevBoxPtrI2CLCD = -1
    else:
        if prevBoxPtrI2CLCD >= 0:
            clearCursorI2CLCD(i2cLCD1,prevBoxPtrI2CLCD)
    #Cursor is drawn once here regardless of which branch ran above - it used to also be
    #drawn inside both branches, doubling the I2C traffic on every page-boundary redraw
    #(the exact presses most likely to trip an I2C bus glitch mid-burst).
    if changeValueMode:
        invertCursorI2CLCD(i2cLCD1,boxPtrI2CLCD)
    else:
        printCursorI2CLCD(i2cLCD1,boxPtrI2CLCD)
    prevBoxPtrI2CLCD = boxPtrI2CLCD

def decrementCursor(i2cLCD1):
    global menuPtr
    menuItems = getMenuItems()
    menuPtr -= 1
    if menuPtr < 0:
        menuPtr = len(menuItems[menuLevel])-1
    mainMenu()

def incrementCursor(i2cLCD1):
    global menuPtr
    menuItems = getMenuItems()
    menuPtr += 1
    if menuPtr >= len(menuItems[menuLevel]):
        menuPtr = 0
    mainMenu()

def printI2CLCD(i2cLCD1,col,row,line,clearRow):
    i2cLCD1.move_to(col,row)
    i2cLCD1.putstr(f"{line:<{lcdDisplayWidth}}")

def printCursorI2CLCD(i2cLCD1,boxPtrI2CLCD):
    i2cLCD1.move_to(0,boxPtrI2CLCD)
    i2cLCD1.putstr("<")
    i2cLCD1.move_to(lcdDisplayWidth-1,boxPtrI2CLCD)
    i2cLCD1.putstr(">")

def invertCursorI2CLCD(i2cLCD1,boxPtrI2CLCD):
    i2cLCD1.move_to(0,boxPtrI2CLCD)
    i2cLCD1.putstr(">")
    i2cLCD1.move_to(lcdDisplayWidth-1,boxPtrI2CLCD)
    i2cLCD1.putstr("<")

def clearCursorI2CLCD(i2cLCD1,prevBoxPtrI2CLCD):
    i2cLCD1.move_to(0,prevBoxPtrI2CLCD)
    i2cLCD1.putstr(" ")
    i2cLCD1.move_to(lcdDisplayWidth-1,prevBoxPtrI2CLCD)
    i2cLCD1.putstr(" ")

def sleepFeedWdt(duration):
    #Menu actions with a multi-second pause (Show Host, End Program, Solid test) can run mid-game
    #once wdt is armed, same as blink() et al - a plain time.sleep() here leaves no slack for the
    #I2C/SPI writes around it, so an unlucky bus delay can tip the total past the WDT timeout.
    remaining = duration
    step = .25
    while remaining > 0:
        if wdt: wdt.feed()
        time.sleep(min(step,remaining))
        remaining -= step

def blink(blinks,duration):
    if skipBlinks:
        return
    while blinks > 0:
            if wdt: wdt.feed()
            LED.value(True)
            time.sleep(duration)
            LED.value(False)
            time.sleep(duration)
            blinks = blinks - 1

def allBlink(blinks,duration):
    if skipBlinks:
        return
    while blinks > 0:
            if wdt: wdt.feed()
            team1LED.value(True)
            team2LED.value(True)
            LED.value(True)
            time.sleep(duration)
            team1LED.value(False)
            team2LED.value(False)
            LED.value(False)
            time.sleep(duration)
            blinks = blinks - 1

def blinkDigit(led,digit):
        #A zero is shown as one long blink
        if wdt: wdt.feed()
        if digit == 0:
                led.value(True)
                time.sleep(1)
                led.value(False)
        else:
                blinks = digit
                while blinks > 0:
                        if wdt: wdt.feed()
                        led.value(True)
                        time.sleep(.25)
                        led.value(False)
                        time.sleep(.25)
                        blinks = blinks - 1

def blinkTableNumber(nbr):
        #Team 1 LED blinks the tens digit, Team 2 LED blinks the ones digit.
        if nbr > 99:
                allBlink(4,.2)
                return
        repeats = 2
        while repeats > 0:
                if wdt: wdt.feed()
                LED.value(True)
                time.sleep(.5)
                LED.value(False)
                time.sleep(.5)
                blinkDigit(team1LED,nbr // 10)
                time.sleep(.5)
                blinkDigit(team2LED,nbr % 10)
                time.sleep(.5)
                repeats = repeats - 1
        LED.value(True)
        time.sleep(.5)
        LED.value(False)

def identFlash():
        flashes = 10
        while flashes > 0:
                if wdt: wdt.feed()
                team1LED.value(True)
                team2LED.value(False)
                LED.value(True)
                time.sleep(.15)
                team1LED.value(False)
                team2LED.value(True)
                LED.value(False)
                time.sleep(.15)
                flashes = flashes - 1
        team2LED.value(False)

def sendIdent(kind,pin):
        if identMode and identAddr:
                try:
                        udp.sendto(f"IDENT:{mac}:{kind}:{pin}".encode(),identAddr)
                except OSError:
                        pass

def dedupClientSessions(clientList):
    #A client that reconnects (network blip, app restart) before the Pico notices its old
    #socket died would otherwise sit alongside the new one, both live in `clients` - every
    #broadcast then goes to that client twice. hello:<id>/ping:<id> let a reconnecting
    #client identify itself; when two entries share an id, keep only the most recently
    #registered one (later in list order - clients are appended in connection order) and
    #close the older, now-stale socket. Entries with no id yet (haven't sent hello/ping
    #this tick) are left alone.
    seen = {}
    result = []
    for client in clientList:
        sessionId = client["sessionId"]
        if sessionId:
            prior = seen.get(sessionId)
            if prior is not None:
                print(f"Session {sessionId}: closing stale connection from {prior['addr']}")
                try:
                    prior["sock"].close()
                except OSError:
                    pass
                result.remove(prior)
            seen[sessionId] = client
        result.append(client)
    return result

#Each sensor/pushbutton pin gets its own block flag and debounce deadline so one pin's
#debounce window never masks another pin's IRQ - including PB3, the menu Action button.
#Deadlines are plain ticks_ms() ints set from the ISR (allocation-free) and polled from the
#main loop via serviceDebounce() - a machine.Timer armed with .init() from inside a pin IRQ
#allocates internally, which MicroPython's rp2 port raises OSError 12 (ENOMEM) for: hard-IRQ
#context can't safely allocate since the interrupt may have landed mid-GC. That exception
#used to abort pushbuttonInterrupt partway through, before pushbuttonStates[idx]/
#pushbuttonBlocked[idx] were reset - leaving that pin stuck ignoring presses.
def sensorInterrupt(pin):
    global sensorStates
    global laserGroupBlocked
    idx = sensors.index(pin)
    sensor = sensors[idx]
    isLaser = sensorTypes[idx] == "LASER"
    #Gate LASER sensors on the shared laserGroupBlocked flag instead of their own
    #sensorBlocked[idx] - see the comment where laserGroupBlocked is declared.
    blocked = laserGroupBlocked if isLaser else sensorBlocked[idx]
    if (sensor.value() == onState) and (sensorStates[idx] == 0):
        if not(blocked):
            sensorStates[idx] = 1
            sensorBlocked[idx] = True
            if isLaser:
                laserGroupBlocked = True
            leds[idx].value(1)
            pushEvent(EVENT_GOAL,teams[idx],pins[idx])
    elif (sensor.value() == offState) and (sensorStates[idx] == 1):
        sensorUnblockAt[idx] = time.ticks_add(time.ticks_ms(),delaySensor)
        sensorStates[idx] = 0

def pushbuttonInterrupt(pin):
    global pushbuttonStates
    idx = pushbuttons.index(pin)
    pushbutton = pushbuttons[idx]
    #PB1/PB2 need the full gameplay debounce (delayPBTime, several seconds - a single
    #physical time-out press must never register as more than one) outside the menu, but
    #that same window applied to menu up/down navigation makes a second press within it a
    #silent no-op. Borrow PB3's shorter action debounce while the menu is on screen instead.
    if idx == ACTION_PB_IDX or isMenuOn:
        timeDelay = delayActionPB
    else:
        timeDelay = delayPBTime
    if (pushbutton.value() == onPBState) and (pushbuttonStates[idx] == 0):
        if not(pushbuttonBlocked[idx]):
            pushbuttonStates[idx] = 1
            pushbuttonBlocked[idx] = True
            timeOutLED.value(1)
            if idx == ACTION_PB_IDX:
                pushEvent(EVENT_ACTION,None,pushbuttonPins[idx])
            else:
                pushEvent(EVENT_TIMEOUT,pushbuttonTeams[idx],pushbuttonPins[idx])
    elif (pushbutton.value() == offPBState) and (pushbuttonStates[idx] == 1):
        pushbuttonUnblockAt[idx] = time.ticks_add(time.ticks_ms(),timeDelay)
        pushbuttonStates[idx] = 0

def serviceDebounce():
    #Called once per main-loop iteration (never from IRQ context) to clear a pin's block flag
    #once its debounce window has passed - the allocation-safe replacement for what the
    #Timer.ONE_SHOT callbacks used to do.
    global laserGroupBlocked
    now = time.ticks_ms()
    for idx in range(len(sensorUnblockAt)):
        deadline = sensorUnblockAt[idx]
        if deadline is not None and time.ticks_diff(now,deadline) >= 0:
            sensorBlocked[idx] = False
            leds[idx].value(0)
            sensorUnblockAt[idx] = None
            if sensorTypes[idx] == "LASER":
                laserGroupBlocked = False
    for idx in range(len(pushbuttonUnblockAt)):
        deadline = pushbuttonUnblockAt[idx]
        if deadline is not None and time.ticks_diff(now,deadline) >= 0:
            pushbuttonBlocked[idx] = False
            timeOutLED.value(0)
            pushbuttonUnblockAt[idx] = None

def clearLEDStrip():
    led_strip.send_command(command="clear",ranges=allLEDs,duration=0,color=off)

def stripScore(team):
    ranges = teamsLEDRanges[team]
    led_strip.send_command("score",ranges,.5)

def stripTimeOut(team):
    led_strip.send_command("timeout",teamsLEDRanges[team],delayPB)

def testLEDs(delay):
    led_strip.send_command("test",NUMBER_PIXELS,delay)
    led_strip.send_command("rainbowchase",NUMBER_PIXELS,delay*300)
    allBlink(6,.3)

def sendFoosOBSPlusScreen(line,foosOBSLines):
    foosOBSLines.pop(0)
    foosOBSLines.append(line)
    debug("{}",line,level="INFO")
    updateFoosOBSScreen(foosOBSLines)
    return foosOBSLines

def updateFoosOBSScreen(foosOBSLines):
    global currentPageI2CLCD
    currentPageI2CLCD = -1
    x = 0
    for line in foosOBSLines:
        i2cLCD1.move_to(0,x)
        i2cLCD1.putstr(f"{line:<{lcdDisplayWidth}}")
        x+=1

def showWifiSetupScreen(ssid,ip):
    #on_ready callback for wifi_setup.run_captive_portal() - shows the setup AP's name and
    #address on the I2C LCD once it's up, since this board (unlike base FoosScorePlus) has a
    #display to read them from instead of needing a fixed, pre-documented IP. The generated
    #SSID (see wifi_setup.py's "FoosScoreSetup-<mac6>") always runs longer than one
    #lcdDisplayWidth-wide line, so it's wrapped across the two middle lines rather than
    #truncated - a customer needs the exact full name to find and join it on their phone.
    lines = ['','','','']
    lines = sendFoosOBSPlusScreen("Wi-Fi Setup Mode",lines)
    lines = sendFoosOBSPlusScreen(ssid[:lcdDisplayWidth],lines)
    lines = sendFoosOBSPlusScreen(ssid[lcdDisplayWidth:2*lcdDisplayWidth],lines)
    lines = sendFoosOBSPlusScreen(f"http://{ip}/",lines)

def updateScoreScreen():
    global currentPageI2CLCD
    currentPageI2CLCD = -1
    if not (isTestMode or isMenuOn):
        lines = ["Mode: Stand Alone",
                 f"{teamColors[0]}: G{teamGames[TEAM1]} P{teamScore[TEAM1]} T{teamTO[TEAM1]}",
                 f"{teamColors[1]}: G{teamGames[TEAM2]} P{teamScore[TEAM2]} T{teamTO[TEAM2]}",
                 f"Last Scored: {lastScored}"]
        x = 0
        for line in lines:
            i2cLCD1.move_to(0,x)
            i2cLCD1.putstr(f"{line:<{lcdDisplayWidth}}")
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

def handleTeamScored(team,pin,foosOBSLines):
    #team is 1 or 2 (matches the event ring buffer / network wire format); teamNumber is the
    #0-indexed form used by the local game-state arrays (teamScore/teamGames/teamTO/teamColors).
    global teamScore,teamGames,teamGameWon,teamMatchWon,newMatchReady,lastScored,teamTO,clients
    teamNumber = team - 1
    line = f"Team{team} Scored/Pin {pin}"
    debug(line,level="DEBUG")
    survivors = []
    for client in clients:
        if sendScore(client["sock"],f"{team},{pin}"):
            survivors.append(client)
        else:
            print(f"Disconnected {client['addr']} (send failed)")
    clients = survivors
    iref.enqueue(team)
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

def handleTimeOut(team,pin,foosOBSLines,changeValueMode):
    global clients
    teamNumber = team - 1
    line = f"Team{team} TimeOut/Pin {pin}"
    debug(line,level="DEBUG")
    if isMenuOn:
        if changeValueMode:
            if teamNumber == TEAM1:
                decrementValue()
            else:
                incrementValue()
        else:
            if teamNumber == TEAM1:
                decrementCursor(i2cLCD1)
            else:
                incrementCursor(i2cLCD1)
    else:
        survivors = []
        for client in clients:
            if sendTimeOut(client["sock"],f"{team},{pin}"):
                survivors.append(client)
            else:
                print(f"Disconnected {client['addr']} (send failed)")
        clients = survivors
        if not isTestMode:
            stripTimeOut(teamNumber)
            if isStandAloneMode:
                teamTO[teamNumber] += 1
                updateScoreScreen()
            elif isFoosOBSMode:
                foosOBSLines = sendFoosOBSPlusScreen(line,foosOBSLines)
    return foosOBSLines

def _update_value(delta):
    global pointsToWin,gamesToWin,ballsInRack,teamScore,teamGames,teamTO,isRackMode,rtMode
    menuItems = getMenuItems()
    action = menuItems[menuLevel][menuPtr]
    if action.startswith("RackTour"):
        isRackMode = rtMode != "Rack"
        rtMode = "Tour" if rtMode == "Rack" else "Rack"
    elif action.startswith("Points To Win"):
        pointsToWin = max(minPointsToWin,min(maxPointsToWin,pointsToWin + delta))
    elif action.startswith("Games To Win"):
        gamesToWin = max(minGamesToWin,min(maxGamesToWin,gamesToWin + delta))
    elif action.startswith("Balls In Rack"):
        ballsInRack = max(minBallsInRack,min(maxBallsInRack,ballsInRack + delta))
    elif action.startswith("Team 1 Score"):
        teamScore[TEAM1] = max(0,min(maxPointsToWin,teamScore[TEAM1] + delta))
    elif action.startswith("Team 2 Score"):
        teamScore[TEAM2] = max(0,min(maxPointsToWin,teamScore[TEAM2] + delta))
    elif action.startswith("Team 1 Games"):
        teamGames[TEAM1] = max(0,min(maxGamesToWin,teamGames[TEAM1] + delta))
    elif action.startswith("Team 2 Games"):
        teamGames[TEAM2] = max(0,min(maxGamesToWin,teamGames[TEAM2] + delta))
    elif action.startswith("Team 1 TimeOuts"):
        teamTO[TEAM1] = max(0,min(2,teamTO[TEAM1] + delta))
    elif action.startswith("Team 2 TimeOuts"):
        teamTO[TEAM2] = max(0,min(2,teamTO[TEAM2] + delta))
    updateCurrentMenuItem()

def decrementValue():
    _update_value(-1)

def incrementValue():
    _update_value(1)

def attemptReconnect():
    #Called from the menu (Network > Connect, or FoosOBS+Mode selected while offline) to give
    #the network one more try instead of requiring a reboot to get out of standalone mode - same
    #connect+socket-setup path as boot, just triggered on demand. Returns whether it connected.
    global forceStandAloneMode
    if connectWifi():
        forceStandAloneMode = False
        led_strip.send_command("solid",allLEDs,1,softyellow)
        blink(2,.25)
        bindSockets()
        sleepFeedWdt(5)
        clearLEDStrip()
        return True
    led_strip.send_command("solid",allLEDs,1,red)
    blink(4,.25)
    sendFoosOBSPlusScreen('Unable to connect to host',foosOBSLines)
    debug('Network reconnect failed - staying in standalone mode',level="WARNING")
    sleepFeedWdt(5)
    clearLEDStrip()
    return False

def handleMenuAction(action,obs_lines):
    global menuLevel,cursorLineI2CLCD,menuPtr,isMenuOn,isFoosOBSMode,isStandAloneMode,isTestMode,keepRunning,changeValueMode,currentPageI2CLCD,forceStandAloneMode,clients,listenCount
    #The Show Host and Show MAC screens are read-only info, not a set of distinct actions like
    #every other menu level - Action should return to the Show Host/MAC submenu no matter which
    #of its 4 lines the cursor happens to be on, so this is checked by level before the usual
    #text-matching below (which would otherwise only recognize the "Return to Menu" line itself).
    if menuLevel == SHOWHOST_LEVEL or menuLevel == SHOWMAC_LEVEL:
        menuLevel = HOSTMAC_LEVEL
        menuPtr = 0
        currentPageI2CLCD = -1
        mainMenu()
        return
    if any(action.startswith(prefix) for prefix in toggleActions):
        changeValueMode = not changeValueMode
    elif action[:4] == "Exit":
        if menuLevel == HOSTMAC_LEVEL:
            menuLevel = NETWORK_LEVEL  #nested under Network, not the main menu
        elif menuLevel == 3:
            menuLevel = DIAGNOSTICS_LEVEL  #nested under Diagnostics, not the main menu
        elif menuLevel == 2 or menuLevel == NETWORK_LEVEL or menuLevel == MODE_LEVEL or menuLevel == DIAGNOSTICS_LEVEL:
            menuLevel = 0
        else:
            menuLevel -= 1
        if menuLevel < 0:
            menuLevel = 0
            debug(f'Exited{action[4:]}',level="INFO")
            i2cLCD1.clear()
            currentPageI2CLCD = -1
            isMenuOn = False
            if isFoosOBSMode:
                line = f'Exited{action[4:]}'
                sendFoosOBSPlusScreen(line,foosOBSLines)
            else:
                updateScoreScreen()
        else:
            currentPageI2CLCD = -1
            menuPtr = 0
            mainMenu()
    elif action == "End Program":
        debug("program ending",level="INFO")
        foosOBSLines[0] = 'Bye Bye'
        foosOBSLines[1] = 'Midsouth Foosball'
        foosOBSLines[2] = 'wishes you a'
        foosOBSLines[3] = 'pleasant day!'
        sendFoosOBSPlusScreen(foosOBSLines[0],foosOBSLines)
        led_strip.send_command("rainbowchase",allLEDs,100)
        keepRunning = False
        sleepFeedWdt(5)
        i2cLCD1.clear()
    elif action == "Reset All":
        debug("reset All selected",level="INFO")
        resetAll()
        menuLevel = 0
        i2cLCD1.clear()
        currentPageI2CLCD = -1
        foosOBSLines[:] = ['','','','System Reset']
        sendFoosOBSPlusScreen('FoosOBS+Mode Enabled',foosOBSLines)
    elif action == "Start Web Config":
        #Writes the flag main.py checks for at the very top of its next boot (before even
        #validating config.py - see that check's comment) and reboots into it immediately.
        #No menu-state cleanup needed beyond what's shown here, since nothing after this
        #point in the current boot ever runs again.
        debug("Start Web Config selected",level="INFO")
        with open(CONFIGWEBFLAG,"w") as f:
            f.write("1")
        isMenuOn = False
        currentPageI2CLCD = -1
        i2cLCD1.clear()
        sendFoosOBSPlusScreen("Starting Config Web...",foosOBSLines)
        sleepFeedWdt(1)
        machine.reset()
    elif action == "New Match":
        debug("New Match",level="INFO")
        isMenuOn = False
        isStandAloneMode = True
        isFoosOBSMode = False
        currentPageI2CLCD = -1
        resetGamesScoresTOs()
    elif action == "Settings":
        menuLevel = 1
        menuPtr = 0
        mainMenu()
    elif action == "Adjust":
        menuLevel = 2
        menuPtr = 0
        mainMenu()
    elif action == "Test LEDs":
        menuLevel = 3
        menuPtr = 0
        mainMenu()
    elif action == "Set Color":
        menuLevel = 4
        menuPtr = 0
        mainMenu()
    elif action == "Test Inputs":
        debug("Test Inputs selected",level="INFO")
        isTestMode = True
        isMenuOn = False
        currentPageI2CLCD = -1
        i2cLCD1.clear()
        i2cLCD1.move_to(0,0)
        i2cLCD1.putstr("Mode: Test Inputs")
        i2cLCD1.move_to(0,1)
        sensorHeaders = " ".join(f"L{i+1}" for i in range(len(pins)))
        pbHeaders = " ".join(f"PB{i+1}" for i in range(len(pushbuttonPins)))
        i2cLCD1.putstr(f"{sensorHeaders} {pbHeaders}")
        i2cLCD1.move_to(0,2)
        sensorLabels = " ".join(f"P{p}" for p in pins)
        pbLabels = " ".join(f"P{p}" for p in pushbuttonPins)
        i2cLCD1.putstr(f"{sensorLabels} {pbLabels}")
    elif action == "FoosOBS+Mode":
        enterMode = True
        resetBuffer = True
        if forceStandAloneMode:
            enterMode = attemptReconnect()
            resetBuffer = False  #attemptReconnect() already left a status message on screen
                                 #(connected-host info on success, "Unable to connect" on
                                 #failure) - don't clobber it with a blank reset before showing
                                 #the "Enabled" line below.
        if enterMode:
            line = f"{action} Enabled"
            debug(line,level="INFO")
            isFoosOBSMode = True
            isTestMode = False
            isStandAloneMode = False
            isMenuOn = False
            currentPageI2CLCD = -1
            if resetBuffer:
                foosOBSLines[:] = ['','','','']
            sendFoosOBSPlusScreen(line,foosOBSLines)
        else:
            currentPageI2CLCD = -1
            menuPtr = 0
            mainMenu()
    elif action == "StandAlone Mode":
        debug("{} Enabled",action,level="INFO")
        isFoosOBSMode = False
        isTestMode = False
        isStandAloneMode = True
        isMenuOn = False
        updateScoreScreen()
    elif action == "Show Host/MAC":
        menuLevel = HOSTMAC_LEVEL
        menuPtr = 0
        mainMenu()
    elif action == "Network":
        menuLevel = NETWORK_LEVEL
        menuPtr = 0
        mainMenu()
    elif action == "Mode":
        menuLevel = MODE_LEVEL
        menuPtr = 0
        mainMenu()
    elif action == "Diagnostics":
        menuLevel = DIAGNOSTICS_LEVEL
        menuPtr = 0
        mainMenu()
    elif action == "Connect":
        if forceStandAloneMode:
            debug("Connect selected",level="INFO")
            attemptReconnect()
        else:
            sendFoosOBSPlusScreen("Already Connected",foosOBSLines)
        menuPtr = 0
        mainMenu()
    elif action == "Disconnect":
        if forceStandAloneMode:
            sendFoosOBSPlusScreen("Not Connected",foosOBSLines)
        else:
            debug("Disconnect selected",level="INFO")
            for client in clients:
                try:
                    client["sock"].close()
                except:
                    pass
            clients = []
            try:
                s.close()
            except:
                pass
            try:
                udp.close()
            except:
                pass
            wlan.disconnect()
            forceStandAloneMode = True
            listenCount = 0
            if isFoosOBSMode:
                isFoosOBSMode = False
                isStandAloneMode = True
            led_strip.send_command("solid",allLEDs,1,red)
            blink(2,.25)
            sendFoosOBSPlusScreen("Disconnected",foosOBSLines)
            sleepFeedWdt(5)
            clearLEDStrip()
        menuPtr = 0
        mainMenu()
    elif action == "Wi-Fi Setup":
        #Blocks until the customer submits new credentials (saved to secrets.py, then
        #machine.reset()) - standalone/FoosOBS+ mode resume normally on the reboot that
        #follows. Unlike the base FoosScorePlus project, this is never entered automatically
        #on a failed connection - a table that's intentionally offline stays in standalone
        #mode, exactly as it does today. Pressing Action instead cancels back out here (see
        #wifi_setup.py) without a submit/reset - station mode is left active but not
        #reconnected (this menu can be reached even while already connected, and switching to
        #AP mode to run the portal already dropped that connection the moment it started), so
        #forceStandAloneMode is set the same as if every network in the list had failed,
        #rather than leaving other code trusting a connection that's actually gone. Re-running
        #Wi-Fi Setup or rebooting are both still available from here to reconnect for real.
        debug("Wi-Fi Setup selected",level="INFO")
        isMenuOn = False
        currentPageI2CLCD = -1
        i2cLCD1.clear()
        import wifi_setup
        wifi_setup.run_captive_portal(wlan,secrets.NETWORKS,team1LED,team2LED,on_ready=showWifiSetupScreen,wdt=wdt,
                                       action_pressed=lambda: pushbuttons[ACTION_PB_IDX].value() == onPBState,
                                       existing_admin_password=getattr(secrets,"ADMINPASSWORD",""))
        debug("Wi-Fi Setup cancelled",level="INFO")
        forceStandAloneMode = True
        menuLevel = NETWORK_LEVEL
        menuPtr = 0
        currentPageI2CLCD = -1
        mainMenu()
    elif action == "Show Host":
        showHostLines[0] = f"{len(clients)} Client(s)" if clients else "No Client Connected"
        showHostLines[1] = host if (not forceStandAloneMode and wlan.isconnected()) else "No IP Address"
        showHostLines[2] = f"Port: {port}" if not forceStandAloneMode else "Standalone Mode"
        menuLevel = SHOWHOST_LEVEL
        menuPtr = len(getMenuItems()[SHOWHOST_LEVEL]) - 1  #default cursor to "Return to Menu"
        mainMenu()
    elif action == "Show MAC":
        showMacLines[0] = "MAC Address"
        showMacLines[1] = ":".join(mac[i:i+2] for i in range(0,len(mac),2))
        showMacLines[2] = ""
        menuLevel = SHOWMAC_LEVEL
        menuPtr = len(getMenuItems()[SHOWMAC_LEVEL]) - 1  #default cursor to "Return to Menu"
        mainMenu()
    elif action == "Test":
        testLEDs(.1)
    elif action == "Solid":
        led_strip.send_command("solid",allLEDs,3,green)
        sleepFeedWdt(3)
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
    elif action == "Red":
        led_strip.send_command("solid",allLEDs,3,red)
    elif action == "Orange":
        led_strip.send_command("solid",allLEDs,3,orange)
    elif action == "Yellow":
        led_strip.send_command("solid",allLEDs,3,yellow)
    elif action == "Green":
        led_strip.send_command("solid",allLEDs,3,green)
    elif action == "Blue":
        led_strip.send_command("solid",allLEDs,3,blue)
    elif action == "Indigo":
        led_strip.send_command("solid",allLEDs,3,indigo)
    elif action == "Violet":
        led_strip.send_command("solid",allLEDs,3,violet)
    else:
        if isTestMode:
            isTestMode = False
            isMenuOn = True
            cursorLineI2CLCD = 0
            menuPtr = 0
            mainMenu()

def core1Worker():
    #Runs forever on core 1, owning both the NeoPixel LED-strip command queue and the iRefFoos
    #HTTPS worker - MicroPython's _thread only supports one additional thread on this hardware,
    #so the two workloads (each independently threaded in the source projects) now share this
    #single loop. LED commands are serviced first each iteration since they're the more
    #latency-sensitive, user-visible feedback tied directly to a physical goal/timeout; a queued
    #iRef report is serviced next. Neither is broken into resumable steps, so a long-running LED
    #animation or a slow iRef HTTP call can still delay the other by its full duration in the
    #worst case - an accepted tradeoff (see README) rather than something this merge attempts to
    #fully solve.
    while True:
        try:
            ledCmd = None
            led_strip.command_lock.acquire()
            try:
                if led_strip.command:
                    ledCmd = led_strip.command.popleft()
            finally:
                led_strip.command_lock.release()
            if ledCmd:
                command,ranges,duration,color = ledCmd
                led_strip._execute_command(command,ranges,duration,color)
                continue
            if irefEnabled:
                iref.service_one()
                if iref.queue_depth() > 0:
                    continue
            led_strip._non_blocking_sleep(0.03)
        except Exception as ex:
            print("core1Worker error: " + str(ex))
            time.sleep(1)

#
# Main Program Starts Here
#

#A configweb.flag left by the Settings menu's "Start Web Config" item means: skip the rest
#of normal boot entirely and serve the full config-editing captive portal instead. Checked
#before configHelper.validateConfig() below (unlike every other startup step) so a config.py
#broken badly enough to fail that check can still be reached and fixed from here. Plain
#try/except OSError, same pattern as the table.txt read further down.
CONFIGWEBFLAG = "configweb.flag"
enteringConfigWeb = False
try:
    with open(CONFIGWEBFLAG,"r"):
        enteringConfigWeb = True
except OSError:
    pass

if enteringConfigWeb:
    import os
    os.remove(CONFIGWEBFLAG)
    debug("configweb.flag present - entering Config Web portal instead of normal boot.",level="INFO")
    configWlan = network.WLAN(network.STA_IF)
    import configweb
    configweb.run(configWlan,Pin(getattr(config,"LED1",26),Pin.OUT),Pin(getattr(config,"LED2",27),Pin.OUT))
    #configweb.run() never returns - it only exits via machine.reset()

resetAll()
menuPtr = 0
menuLevel = 0
menuLength = len(getMenuItems()[0])
toggleActions = ["Team 1 Score","Team 2 Score","Team 1 Games","Team 2 Games","Team 1 TimeOuts","Team 2 TimeOuts","Points To Win","Games To Win","Balls In Rack","RackTour"]
lcdDisplayWidth = 20
cursorLineI2CLCD = 0
foosOBSLines = ['','','','']

print("Validating configuration file...")
configText = configHelper.linesToText(readConfigFile())
if not validateConfig(configText):
    print("Invalid config file: " + CONFIGFILE + ".  Aborting.")
    sys.exit()

port          = config.PORT
DPORT         = config.DPORT
SENSOR1       = config.SENSOR1
SENSOR2       = config.SENSOR2
SENSOR3       = getattr(config,"SENSOR3",None)
SENSOR1_TYPE  = config.SENSOR1_TYPE
SENSOR2_TYPE  = config.SENSOR2_TYPE
SENSOR3_TYPE  = getattr(config,"SENSOR3_TYPE",None)
LED1          = config.LED1
LED2          = config.LED2
delaySensor   = config.DELAY_SENSOR
delayPB       = config.DELAY_PB
delayActionPB = config.DELAY_ACTION_PB
PB1           = config.PB1
PB2           = config.PB2
PB3           = config.PB3
TEAMS         = config.TEAMS
table_nbr     = config.TABLE
SDA           = config.SDA
SCL           = config.SCL
I2C1          = config.I2C
LEDSTRIP      = config.LEDSTRIP
NUMBER_PIXELS = config.NUMBER_PIXELS
STATE_MACHINE = config.STATE_MACHINE
TEAM1LEDS     = config.TEAM1LEDS
TEAM2LEDS     = config.TEAM2LEDS
#SPI color TFT is optional - a board with only the I2C LCD wired up can omit all seven of
#these from config.py; tftEnabled gates every place main.py touches the TFT.
SPIBLOCK          = getattr(config,"SPIBLOCK",None)
SPI_SCK_CLK_SCK   = getattr(config,"SPI_SCK_CLK_SCK",None)
SPI_TX_DIN_MOSI   = getattr(config,"SPI_TX_DIN_MOSI",None)
SPI_RX_DC_ADC     = getattr(config,"SPI_RX_DC_ADC",None)
SPI_RX_RST_ARESET = getattr(config,"SPI_RX_RST_ARESET",None)
SPI_CSN_CS_ACS    = getattr(config,"SPI_CSN_CS_ACS",None)
TFT_ROTATION      = getattr(config,"TFT_ROTATION",None)
tftEnabled = None not in (SPIBLOCK,SPI_SCK_CLK_SCK,SPI_TX_DIN_MOSI,SPI_RX_DC_ADC,SPI_RX_RST_ARESET,SPI_CSN_CS_ACS,TFT_ROTATION)

IREF           = getattr(config,"IREF",0)
IREF_DEVICE    = getattr(config,"IREF_DEVICE","table{n}")
IREF_HOME_TEAM = getattr(config,"IREF_HOME_TEAM",1)
IREF_URL       = getattr(config,"IREF_URL","https://ireffoos.com")
irefApiKey     = getattr(secretsIref,"APIKEY","") if secretsIref else ""
irefEnabled    = bool(IREF) and irefApiKey != "" and ssl is not None
DEBUGMODE      = bool(getattr(config,"DEBUGMODE",0))
DEBUG          = DEBUGMODE
netmsg.DEBUG   = DEBUG
debuglog.LOG_LEVEL = "DEBUG" if DEBUGMODE else "INFO"
#Flip to 0 in config.py to run with no watchdog at all - trades away auto-recovery from a
#genuine hang (an unrelated hardware/firmware freeze would then need a manual power cycle
#instead of self-recovering) for no more resets from a feed-timing gap not yet found/fixed.
WDT_ENABLED    = bool(getattr(config,"WDT_ENABLED",1))

#A remotely assigned table number in table.txt takes precedence over config.TABLE
try:
    with open(TABLEFILE,"r") as file:
        table_nbr = int(file.read().strip())
except (OSError,ValueError):
    pass

if (DPORT == ""):
    DPORT = 5051
if (TEAMS == ""):
    TEAMS = [1,1,2]

print("Configuration:")
for attr_name in dir(config):
    if attr_name.isupper():
        print("{:<20} {}".format(attr_name,getattr(config,attr_name)))
print("{:<20} {}".format("TABLE (effective):",table_nbr))
print("{:<20} {}".format("DEBUG:",DEBUGMODE))
print("{:<20} {}".format("IREF enabled:",irefEnabled))
if IREF and not irefEnabled:
    if irefApiKey == "":
        print("iRefFoos reporting disabled - no APIKEY in secretsIref.py.")
    else:
        print("iRefFoos reporting disabled - no ssl module in this firmware.")

if SENSOR1 + SENSOR2 + (SENSOR3 or 0) < 1:
    print("Not enough sensors configured in " + CONFIGFILE + ".  Aborting.")
    sys.exit()

#Every configured pin is cross-checked in one pass so no two of them collide - covers the full
#set (sensors/LEDs/pushbuttons plus the display/LED-strip/SPI pins), replacing the pairwise
#checks both source files used when there were far fewer pins to cover.
pinAssignments = {"SENSOR1": SENSOR1,"SENSOR2": SENSOR2,"LED1": LED1,"LED2": LED2,
                   "PB1": PB1,"PB2": PB2,"PB3": PB3,"SDA": SDA,"SCL": SCL,"LEDSTRIP": LEDSTRIP}
if SENSOR3 is not None:
    pinAssignments["SENSOR3"] = SENSOR3
if tftEnabled:
    pinAssignments["SPI_SCK_CLK_SCK"] = SPI_SCK_CLK_SCK
    pinAssignments["SPI_TX_DIN_MOSI"] = SPI_TX_DIN_MOSI
    pinAssignments["SPI_RX_DC_ADC"] = SPI_RX_DC_ADC
    pinAssignments["SPI_RX_RST_ARESET"] = SPI_RX_RST_ARESET
    pinAssignments["SPI_CSN_CS_ACS"] = SPI_CSN_CS_ACS
seenPins = {}
pinCollision = False
for pinName,pinNbr in pinAssignments.items():
    if pinNbr in seenPins:
        print("ERROR: " + pinName + " and " + seenPins[pinNbr] + " both use pin " + str(pinNbr) + " in " + CONFIGFILE + ".  Aborting.")
        pinCollision = True
    else:
        seenPins[pinNbr] = pinName
if pinCollision:
    sys.exit()

#Display hardware - I2C LCD (always) + SPI color TFT (only if tftEnabled)
#Back to the 400kHz fast-mode default (was dropped to 100kHz in v3.03 as a mitigation for
#suspected RP2040 errata E14 - a bus noise glitch permanently wedging the I2C peripheral -
#but the actual cause of the freezes/unreliable menu response turned out to be the
#Timer-in-ISR ENOMEM bug fixed in v3.06, not I2C speed).
i2c = I2C(id=I2C1,scl=Pin(SCL),sda=Pin(SDA),freq=400000)
i2cLCD1 = I2cLcd(i2c,0x27,4,20)
maxRowI2CLCD = 4
txtSize = 1.5
txtColor = None
backgroundColor = None
cursorColor = None
selectColor = None
lineHeight = None
maxRowSPILCD = None
if tftEnabled:
    spi = SPI(SPIBLOCK,baudrate=20000000,polarity=0,phase=0,sck=Pin(SPI_SCK_CLK_SCK),mosi=Pin(SPI_TX_DIN_MOSI),miso=None)
    tft = TFT(spi,SPI_RX_DC_ADC,SPI_RX_RST_ARESET,SPI_CSN_CS_ACS)
    tft.initr()
    tft.rgb(True)
    tft.fill(TFT.BLACK)
    tft.rotation(TFT_ROTATION)
    txtColor = TFT.WHITE
    backgroundColor = TFT.BLACK
    cursorColor = TFT.YELLOW
    selectColor = TFT.RED
    tft.fill(backgroundColor)
    baseLineHeight = 8
    lineHeight = int(baseLineHeight * txtSize)
    screenHeight = 128
    maxRowSPILCD = screenHeight // lineHeight
    showMenuSPILCD(getMenuItems(),menuLevel,menuPtr)
else:
    debug("No SPI TFT configured - running with I2C LCD only.",level="INFO")

#WiFi - tries every network in secrets.NETWORKS (bounded attempts each), repeating the whole
#list up to WLAN_LIST_PASSES times (a connection can fail on the first try even when the network
#is fine - a weak signal, an AP still booting, etc.) before falling back to standalone mode,
#which keeps the table fully playable via the display/menu/LED-strip alone.
wlan = network.WLAN(network.STA_IF)
wlan.active(True)
time.sleep(2)  #let the CYW43 radio's firmware finish settling before the first connect() -
               #firing connect() immediately after active(True) can lose that race and fail the
               #very first attempt even against a network that's otherwise fine.
mac = "".join("%02x" % b for b in wlan.config('mac'))

#Callers may send MACs as "2C-CF-67-9B-97-14" or "2c:cf:67:9b:97:14" - normalize
#before comparing against mac (always lowercase, no separators) so those variants
#are accepted rather than silently ignored.
def normalizeMac(s):
    return s.replace("-", "").replace(":", "").lower()

forceStandAloneMode = False
WLAN_ATTEMPTS_PER_NETWORK = 1
WLAN_LIST_PASSES = 2
WLAN_CONNECT_TIMEOUT = 20  #seconds to wait for one connect() attempt to resolve - a mesh
                            #network's extra roaming/backhaul negotiation can leave a connect()
                            #attempt sitting in STAT_CONNECTING well past a single AP's usual
                            #8s, so this needs enough slack for that rather than the plain
                            #associate-and-DHCP case alone
WLAN_POLL_INTERVAL = .25
WLAN_FAIL_STATUSES = set(s for s in (getattr(network,name,None) for name in
                          ("STAT_WRONG_PASSWORD","STAT_NO_AP_FOUND","STAT_CONNECT_FAIL")) if s is not None)
#Reverse lookup so a failed attempt's wlan.status() can be logged by name (STAT_WRONG_PASSWORD,
#STAT_NO_AP_FOUND, etc) instead of a bare int - the only way to tell those apart from a plain
#timeout (still STAT_CONNECTING/STAT_IDLE when the deadline hits) without this.
WLAN_STATUS_NAMES = {}
for _name in ("STAT_IDLE","STAT_CONNECTING","STAT_WRONG_PASSWORD","STAT_NO_AP_FOUND","STAT_CONNECT_FAIL","STAT_GOT_IP"):
    _val = getattr(network,_name,None)
    if _val is not None:
        WLAN_STATUS_NAMES[_val] = _name
def connectWifi():
    #Tries every network in secrets.NETWORKS (bounded attempts each), repeating the whole list
    #up to WLAN_LIST_PASSES times, same as the original boot-time-only logic this was extracted
    #from. Also reused by FoosOBS+Mode's on-demand reconnect from the menu (see there) so a
    #table that failed to connect at boot can get another shot without a reboot - that call
    #happens after wdt is armed, unlike the boot call, so the poll loop below feeds it too (a
    #no-op at boot, where wdt is still None).
    if not skipNetwork:
        listPass = 0
        while not wlan.isconnected() and listPass < WLAN_LIST_PASSES:
            listPass += 1
            for ssid,password in secrets.NETWORKS:
                if wlan.isconnected():
                    break
                attempts = 0
                while not wlan.isconnected() and attempts < WLAN_ATTEMPTS_PER_NETWORK:
                    attempts += 1
                    sendFoosOBSPlusScreen(f"Trying {ssid}",foosOBSLines)
                    wlan.connect(ssid,password)
                    blink(3,.25)
                    #Poll status instead of a flat sleep: bails out early on a definitive failure
                    #(wrong password/no AP found/connect fail) so a dead network in the list doesn't
                    #eat the same fixed wait every pass, but keeps waiting (up to the timeout) for a
                    #real network that's just being slow to associate.
                    deadline = time.ticks_add(time.ticks_ms(),int(WLAN_CONNECT_TIMEOUT * 1000))
                    while time.ticks_diff(deadline,time.ticks_ms()) > 0:
                        if wdt: wdt.feed()
                        if wlan.isconnected() or wlan.status() in WLAN_FAIL_STATUSES:
                            break
                        time.sleep(WLAN_POLL_INTERVAL)
                    if not wlan.isconnected():
                        status = wlan.status()
                        debug(f"{ssid}: connect failed (status={WLAN_STATUS_NAMES.get(status,status)})",level="WARNING")
    return wlan.isconnected()

if not connectWifi():
    forceStandAloneMode = True

teamsLEDRanges = []
allLEDs = []
teamLEDs = [str(TEAM1LEDS),str(TEAM2LEDS)]
for teamLED in teamLEDs:
    ranges = []
    groups = teamLED.split(';')
    for group in groups:
        start,end = group.split('-')
        ranges.append((int(start),int(end)))
        allLEDs.append((int(start),int(end)))
    teamsLEDRanges.append(ranges)

led_strip = LEDStrip(LEDSTRIP,NUMBER_PIXELS,STATE_MACHINE,"GRB")
led_strip.all_ranges = allLEDs
teamColors = ['Yellow','Black ']

def bindSockets():
    #Binds/listens the TCP command socket and the UDP discovery socket once wlan is connected,
    #setting host/s/udp for the rest of the program to use. Shared by the boot-time connect and
    #by FoosOBS+Mode's on-demand reconnect from the menu, since both need the exact same setup
    #once a connection exists. A bind failure aborts the whole program either way - it means the
    #port's already in use, not something a menu retry can fix.
    global host,s,udp
    host = wlan.ifconfig()[0]
    sendFoosOBSPlusScreen('Connected. Host:',foosOBSLines)
    sendFoosOBSPlusScreen(host,foosOBSLines)
    s = socket.socket(socket.AF_INET,socket.SOCK_STREAM)
    s.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1)
    try:
        s.bind((host,port))
    except:
        s.close()
        try:
            s.bind((host,port))
        except:
            sendFoosOBSPlusScreen('Could not bind  ',foosOBSLines)
            sendFoosOBSPlusScreen('aborting........',foosOBSLines)
            led_strip.send_command("solid",allLEDs,1,red)
            sys.exit(1)
    sendFoosOBSPlusScreen(f"Socket {port} bound.",foosOBSLines)
    s.listen(4)
    udp = socket.socket(socket.AF_INET,socket.SOCK_DGRAM)
    udp.bind(('0.0.0.0',DPORT))
    udp.settimeout(0.1)

if forceStandAloneMode:
    led_strip.send_command("solid",allLEDs,1,red)
    blink(4,.25)
    sendFoosOBSPlusScreen('Unable to connect to host',foosOBSLines)
    debug('forcing standalonemode',level="WARNING")
    isFoosOBSMode = False
    isTestMode = False
    isStandAloneMode = True
    isMenuOn = False
    updateScoreScreen()
else:
    led_strip.send_command("solid",allLEDs,1,softyellow)
    blink(2,.25)
    bindSockets()

led_strip.send_command("solid",allLEDs,1,softgreen)
blink(2,.15)

team1LED = Pin(LED1,Pin.OUT)
team2LED = Pin(LED2,Pin.OUT)
timeOutLED = Pin("LED",Pin.OUT)
delayPBTime = delayPB
onState = False
offState = True
pins = [SENSOR1,SENSOR2]
sensorTypes = [SENSOR1_TYPE,SENSOR2_TYPE]
if SENSOR3 is not None:
    pins.append(SENSOR3)
    sensorTypes.append(SENSOR3_TYPE)
sensorStates = [0] * len(pins)
sensorBlocked = [False] * len(pins)
sensorUnblockAt = [None] * len(pins)
#LASER sensors share one physical ball-return channel, so a single ball can trip more than
#one of them (another sensor on the same team, or the opposing team's sensor a moment later).
#laserGroupBlocked is a single flag shared by every "LASER"-type sensor so the first trip
#locks out the rest of the group until DELAY_SENSOR clears it - see sensorInterrupt() and
#serviceDebounce(). IR sensors are unaffected and keep independent per-pin sensorBlocked,
#since brackets already make that kind of cross-sensor trip physically impossible for them.
laserGroupBlocked = False
sensors = [Pin(p,Pin.IN,Pin.PULL_UP) if t == "IR" else Pin(p,Pin.IN) for p,t in zip(pins,sensorTypes)]
x = 0
for sensor in sensors:
    sensorStates[x] = not(sensor.value())
    sensor.irq(trigger=Pin.IRQ_RISING | Pin.IRQ_FALLING,handler=sensorInterrupt)
    x += 1

teams = TEAMS
leds = [team1LED if t == 1 else team2LED for t in teams]

onPBState = True
offPBState = False
pushbuttonPins = [PB1,PB2,PB3]
pushbuttonTeams = [1,2]  #maps PB1/PB2 (idx 0/1) to a team; PB3 (ACTION_PB_IDX) has no team
pushbuttonStates = [0,0,0]
pushbuttonBlocked = [False,False,False]
pushbuttonUnblockAt = [None,None,None]
pushbuttons = [Pin(p,Pin.IN) for p in pushbuttonPins]
for pushbutton in pushbuttons:
    pushbutton.irq(trigger=Pin.IRQ_RISING | Pin.IRQ_FALLING,handler=pushbuttonInterrupt)

if forceStandAloneMode:
    irefEnabled = False
iref = IrefClient(IREF_URL,irefApiKey,IREF_HOME_TEAM,IREF_DEVICE,table_nbr)
if irefEnabled:
    if not iref.try_configure():
        print("iRefFoos reporting disabled - could not parse IREF_URL " + IREF_URL + ".")
        irefEnabled = False

_thread.start_new_thread(core1Worker,())
if irefEnabled:
    print("iRefFoos reporting active (device " + iref.device_id() + ").")

allBlink(3,.3)
clients = []
identMode = False
identAddr = None
lastClientAddr = ""
connectCount = 0
listenCount = 0
SELECT_TIMEOUT = .01

if not forceStandAloneMode:
    foosOBSLines = sendFoosOBSPlusScreen("FoosOBS+Mode Active",foosOBSLines)
clearLEDStrip()
led_strip.send_command("rainbowchase",allLEDs,100)
showMenuSPILCD(getMenuItems(),0,0)

#Armed only now - startup (WiFi connect retries, etc) can legitimately run past the
#RP2040's ~8.3s max WDT timeout and isn't fed. From here on, an unfed board (e.g. a wedged
#I2C peripheral) reboots itself instead of staying frozen until someone finds the power
#switch. Set WDT_ENABLED = 0 in config.py to run without it entirely - every feed() call
#below is already guarded with `if wdt:` since wdt is None until this point, so leaving it
#None permanently is enough; nothing else needs to change.
wdt = WDT(timeout=8000) if WDT_ENABLED else None

while keepRunning:
    if wdt: wdt.feed()
    serviceDebounce()
    readable = []
    if not forceStandAloneMode:
        if not clients:
            if listenCount == 0:
                debug(f"Listening for Discovery Requests on {host}:{DPORT}...",level="INFO")
            listenCount = 1

        #A single blocking select() waits on every socket that might have work at once, with a
        #short timeout so the loop still wakes on its own cadence to notice hardware-triggered
        #(IRQ-pushed) events, which don't arrive through a socket.
        watchSockets = [udp,s] + [client["sock"] for client in clients]
        try:
            readable,_,_ = select.select(watchSockets,(),(),SELECT_TIMEOUT)
        except OSError:
            readable = []
            try:
                select.select((s,),(),(),0)
            except OSError:
                s.close()
                listenCount = 0
                debug("connection error. Aborting..",level="ERROR")
                sys.exit(1)

        #UDP discovery/management protocol - polled even while clients are connected so the
        #table manager can tell a busy board from a dead one.
        data = None
        if udp in readable:
            try:
                data,addr = udp.recvfrom(1024)
            except OSError:
                data = None
        if data:
            if DEBUG:
                print(f"Got data from {addr}: {data}")
            try:
                msg = data.decode(FORMAT)
            except:
                msg = ""
            if msg == "DISCOVER_PICO":
                status = ("BUSY:" + ",".join(client["addr"] for client in clients)) if clients else "FREE"
                response = f"Table {table_nbr}:{host}:{port}:{mac}:{status}".encode()
                udp.sendto(response,addr)
                if DEBUG:
                    print(f"Sent {response} to {addr}")
            elif msg == "ENTER_IDENT":
                if clients:
                    udp.sendto(f"BUSY:{mac}".encode(),addr)
                else:
                    identMode = True
                    identAddr = addr
                    udp.sendto(f"IDENT_ON:{mac}:{table_nbr}".encode(),addr)
                    print(f"Identify mode on. Reporting inputs to {addr}.")
            elif msg == "EXIT_IDENT":
                if identMode:
                    identMode = False
                    identAddr = None
                    udp.sendto(f"IDENT_OFF:{mac}".encode(),addr)
                    print("Identify mode off.")
            elif msg[0:7] == "ASSIGN:":
                parts = msg.split(":")
                if len(parts) == 3 and normalizeMac(parts[1]) == mac and parts[2].isdigit():
                    if clients:
                        udp.sendto(f"BUSY:{mac}".encode(),addr)
                        print("ASSIGN refused - game connection active.")
                    else:
                        table_nbr = int(parts[2])
                        iref.update_table(table_nbr)
                        with open(TABLEFILE,"w") as file:
                            file.write(str(table_nbr))
                        udp.sendto(f"ASSIGNED:{mac}:{table_nbr}".encode(),addr)
                        print(f"Table number {table_nbr} assigned and saved to {TABLEFILE}.")
                        blinkTableNumber(table_nbr)
            elif msg[0:6] == "FLASH:":
                parts = msg.split(":")
                if len(parts) == 2 and normalizeMac(parts[1]) == mac:
                    if clients:
                        udp.sendto(f"BUSY:{mac}".encode(),addr)
                        print("FLASH refused - game connection active.")
                    else:
                        udp.sendto(f"FLASHING:{mac}".encode(),addr)
                        identFlash()
            elif msg[0:13] == "REPORT_TABLE:":
                parts = msg.split(":")
                if len(parts) == 2 and normalizeMac(parts[1]) == mac:
                    if clients:
                        udp.sendto(f"BUSY:{mac}".encode(),addr)
                        print("REPORT_TABLE refused - game connection active.")
                    else:
                        udp.sendto(f"REPORTING:{mac}:{table_nbr}".encode(),addr)
                        print(f"Reporting table number {table_nbr} via LEDs.")
                        blinkTableNumber(table_nbr)
    else:
        time.sleep(SELECT_TIMEOUT)

    #Drain every event queued since the last iteration - not just one - so a burst of closely
    #spaced goals/timeouts/menu-presses is reported/handled in full. That burst is exactly the
    #case with no slack against the WDT: each event's handler does I2C writes and can iterate
    #every connected client's socket, and up to EVENT_BUFFER_SIZE events can be processed here
    #without returning to the top of the main loop, so this loop feeds the watchdog itself
    #rather than relying on the feed at the top of the next iteration.
    while True:
        if wdt: wdt.feed()
        event = popEvent()
        if event is None:
            break
        evtType,team,pin = event
        if evtType == EVENT_GOAL:
            sendIdent("GOAL",pin)
            foosOBSLines = handleTeamScored(team,pin,foosOBSLines)
        elif evtType == EVENT_TIMEOUT:
            sendIdent("PB",pin)
            foosOBSLines = handleTimeOut(team,pin,foosOBSLines,changeValueMode)
        elif evtType == EVENT_ACTION:
            debug("actionPBPressed!",level="INFO")
            if isMenuOn:
                if changeValueMode:
                    printCursorI2CLCD(i2cLCD1,prevBoxPtrI2CLCD)
                    boxLineSPILCD(prevBoxPtrSPILCD,cursorColor)
                else:
                    invertCursorI2CLCD(i2cLCD1,prevBoxPtrI2CLCD)
                    boxLineSPILCD(prevBoxPtrSPILCD,selectColor)
                action = getMenuItems()[menuLevel][menuPtr]
                debug("Action: {}",action,level="INFO")
                handleMenuAction(action,foosOBSLines)
            elif isTestMode:
                isTestMode = False
                isMenuOn = True
                menuPtr = 0
                cursorLineI2CLCD = 0
                mainMenu()
            else:
                isMenuOn = True
                menuPtr = 0
                cursorLineI2CLCD = 0
                mainMenu()
    dropped = takeDropped()
    if dropped:
        print(str(dropped) + " event(s) dropped - event buffer full.")

    if isTestMode:
        i2cLCD1.move_to(0,3)
        sensorVals = "   ".join(str(sensor.value()) for sensor in sensors)
        pbVals = "   ".join(str(pushbutton.value()) for pushbutton in pushbuttons)
        i2cLCD1.putstr(f" {sensorVals}   {pbVals}")

    if not forceStandAloneMode:
        #Service every connected client's socket - each keeps its own rxBuffer since TCP is a
        #byte stream and one client's partial command must never be spliced with another's.
        hadClients = bool(clients)
        survivors = []
        for client in clients:
            sock = client["sock"]
            keep = True
            data = False
            if sock in readable:
                try:
                    data = sock.recv(255)
                    if data == b'':
                        print(f"Connection closed by {client['addr']}")
                        sock.close()
                        keep = False
                        data = False
                except OSError as e:
                    if hasattr(e,'errno') and e.errno == 110:
                        pass
                    elif hasattr(e,'errno') and e.errno == 104:
                        print(f"Connection dropped: {client['addr']}")
                        sock.close()
                        keep = False
                    else:
                        print("Socket error: ",e)
                        sock.close()
                        keep = False
            if keep and data:
                client["rxBuffer"] += data.decode(FORMAT)
                if DEBUG:
                    print("Read from socket:",data.decode(FORMAT))
                cmd = client["rxBuffer"].split(":",1)
                if cmd[0]=="reset":
                    debug("Resetting...",level="INFO")
                    machine.reset()
                elif cmd[0]=="read":
                    sendConfigFile(sock)
                    client["rxBuffer"] = ""
                elif cmd[0]=="ping":
                    if len(cmd) > 1 and cmd[1].strip():
                        client["sessionId"] = cmd[1].strip()
                    sendMessage(sock,"pong\r\n")
                    client["rxBuffer"] = ""
                elif cmd[0]=="hello":
                    #Sent once right after a client connects, carrying an id it keeps across
                    #its own reconnects (also echoed in every "ping:<id>"). Lets a fresh
                    #connection be recognized as superseding a stale one the Pico hasn't
                    #noticed died yet - see dedupClientSessions().
                    if len(cmd) > 1 and cmd[1].strip():
                        client["sessionId"] = cmd[1].strip()
                    client["rxBuffer"] = ""
                elif cmd[0]=="save":
                    if len(cmd) > 1 and "End" in cmd[1]:
                        parseSave(cmd)
                        client["rxBuffer"] = ""
                elif ":" in client["rxBuffer"]:
                    print("Unknown command: [" + cmd[0] + "]")
                    client["rxBuffer"] = ""
            if keep:
                survivors.append(client)
        clients = dedupClientSessions(survivors)
        if hadClients and not clients:
            listenCount = 0

        if s in readable:
            newSock,addr = s.accept()
            connectCount += 1
            newSock.settimeout(.01)
            clients.append({"sock": newSock,"addr": addr[0],"rxBuffer": "","sessionId": None})
            identMode = False
            identAddr = None
            lastClientAddr = addr[0]
            debug("Connected to : {} : {}",addr[0],addr[1],level="INFO")
            debug("Connection number: {}",connectCount,level="DEBUG")
            tempFoosOBSLines = [f"Connect on: {addr[1]}",f"{addr[0]}",f"Connection# {connectCount}",f"Active: {len(clients)}"]
            updateFoosOBSScreen(tempFoosOBSLines)
            blink(3,.15)

if not forceStandAloneMode:
    for client in clients:
        try:
            client["sock"].close()
        except OSError:
            pass
    s.close()
team1LED.value(False)
team2LED.value(False)
LED.value(False)
for sensor in sensors:
    sensor.irq(handler=None)
for pushbutton in pushbuttons:
    pushbutton.irq(handler=None)
i2cLCD1.display_off()
i2cLCD1.backlight_off()
debug("Sensors and Display Deactivated.",level="INFO")
