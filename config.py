TABLE = 1
PORT = 5050
DPORT = 5051
SENSOR1 = 21
SENSOR2 = 20
SENSOR3 = 19
SENSOR1_TYPE = "IR"
SENSOR2_TYPE = "IR"
SENSOR3_TYPE = "IR"
TEAMS = [1,1,2]
LED1 = 26
LED2 = 27
DELAY_SENSOR = 3000
DELAY_PB = 5000
DELAY_ACTION_PB = 1000
PB1 = 17
PB2 = 16
PB3 = 18
DEBUGMODE = 0
WDT_ENABLED = 0
IREF = 0
IREF_DEVICE = "table{n}"
IREF_HOME_TEAM = 1
IREF_URL = "https://ireffoos.com"

#Display (I2C LCD - required) and LED-strip hardware - integrated board only
SDA = 4
SCL = 5
I2C = 0
LEDSTRIP = 28
NUMBER_PIXELS = 30
STATE_MACHINE = 0
TEAM1LEDS = "0-14"
TEAM2LEDS = "15-29"

#SPI color TFT - optional second display. Delete all seven of these lines entirely on a board
#that only has the I2C LCD wired up; main.py falls back to running with the I2C LCD alone.
SPIBLOCK = 0
SPI_SCK_CLK_SCK = 10
SPI_TX_DIN_MOSI = 11
SPI_RX_DC_ADC = 12
SPI_RX_RST_ARESET = 13
SPI_CSN_CS_ACS = 14
TFT_ROTATION = 3
