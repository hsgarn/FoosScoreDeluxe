import config
from pico_i2c_lcd import I2cLcd
from machine import I2C
from machine import Pin
import utime as time
menuItems = ["Reset All","New Game","Stand Alone Mode","Exit"]
menuLength = len(menuItems)
menuFirstLine = 0 #item in menuItems to display at top of menu
displayFirstRow = 1 #line on display to being showing menu items (0 - max display row)
displayLastRow = 3 #last line on display to show menu items (menuFirstRow+1 - max display row)
cursorLine = 0 # line the cursor is on
displayItems = menuItems
CLEAR_ROW = "                    "
menuFirstRow = 1
menuLastRow = 3
menuWindow = ["","","",""]
 
def printMenuLCD(lcd):
    global menuItems
    global menuLength
    global menuFirstLine
    global cursorLine
    global menuWindow
    global displayFirstRow
    global displayLastRow
    global displayItems
    
    row = 0
    menuPtr = menuFirstLine
    for x in range(menuFirstRow,menuLastRow):
        menuWindow[row] = menuItems[menuPtr]
        menuPtr += 1
        if menuPtr > menuLength:
            menuPtr = 0
    
    printLCD(lcd,0,0," " + menuItems[0],True)
    printLCD(lcd,0,1," " + menuItems[1],True)
    printLCD(lcd,0,2," " + menuItems[2],True)
    printLCD(lcd,0,3," " + menuItems[3],True)
    printCursorLCD(lcd)

def printLCD(lcd,col,row,line,clearRow):
    lcd.move_to(col,row)
    if clearRow:
        lcd.putstr(CLEAR_ROW)
    lcd.move_to(col,row)
    lcd.putstr(line)

def printCursorLCD(lcd):
    global cursorLine
    lcd.move_to(0,cursorLine)
    lcd.putstr("<")
    lcd.move_to(19,cursorLine)
    lcd.putstr(">")

def invertCursorLCD(lcd):
    global cursorLine
    lcd.move_to(0,cursorLine)
    lcd.putstr(">")
    lcd.move_to(19,cursorLine)
    lcd.putstr("<")

def decrementCursor(lcd):
    global cursorLine
    cursorLine -= 1
    if cursorLine < 0:
        cursorLine = 3
    printMenuLCD(lcd)
    return cursorLine
        
def incrementCursor(lcd):
    global cursorLine
    cursorLine += 1
    if cursorLine >= 4:
        cursorLine = 0
    printMenuLCD(lcd)
    return cursorLine

pb1 = Pin(config.PB1, Pin.IN)
pb2 = Pin(config.PB2, Pin.IN)
    
i2c = I2C(id=config.I2C,scl=Pin(config.SCL),sda=Pin(config.SDA),freq=400000)
lcd = I2cLcd(i2c, 0x27, 4, 20)
print("Initialized")


cursorLine = 0
printMenuLCD(lcd)
pb1Count = 0
pb2Count = 0
pb3Count = 0
pb12Count = 0
pb12Block = False
dbCount = 400
db12Count = 500
doloop = True
while doloop:
    if pb1.value() and not pb2.value():
        pb1Count += 1
    else:
        pb1Count = 0
    if pb1Count > dbCount:
        pb1Count = 0
        cursorLine = incrementCursor(lcd)
    if pb2.value() and not pb1.value():
        pb2Count += 1
    else:
        pb2Count = 0
    if pb2Count > dbCount:
        pb2Count = 0
        cursorLine = decrementCursor(lcd)
    if pb1.value() and pb2.value() and not pb12Block:
        pb12Count += 1
        pb1Count = 0
        pb2Count = 0
    else:
        pb12Count = 0
    if not pb1.value() and not pb2.value():
        pb12Block = False
    if pb12Count > db12Count:
        pb12Count = 0
        print(f"selected {menuItems[cursorLine]}")
        invertCursorLCD(lcd)
        pb12Block = True
        if menuItems[cursorLine] == "Exit":
            doloop = False

lcd.display_off()
lcd.backlight_off()
        
    

