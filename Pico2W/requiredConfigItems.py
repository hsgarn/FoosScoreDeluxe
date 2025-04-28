PORT,SENSOR1,SENSOR2,SENSOR3,LED1,LED2,DELAY_SENSOR,DELAY_PB,DELAY_ACTION_PB,PB1,PB2,PB3,SDA,SCL,I2C,LEDSTRIP,NUMBER_PIXELS,STATE_MACHINE,TEAM1LEDS,TEAM2LEDS,DEBUGMODE
PORT,PIN,PIN,PIN,PIN,PIN,TIME,TIME,TIME,PIN,PIN,PIN,SDA,SCL,I2C,PIN,INT,SM,LEDS,LEDS,TOGGLE
0,1,2,3,4,5,6,7,8,9,10,11,12,13,14,15,16,17,18,19,20,21,22,26,27,28
0,4,8,12,16,20;2,6,10,14,18,26
1,5,9,13,17,21;3,7,11,15,19,27
0,1
0,1

#Line Number:  Description
#1: Required Config Items that must be in the config.py file.
#2: Test type for each config item.
#3: Valid Pin numbers for the PIN test type.
#4: Valid SDA numbers for SDA test type.  SDA0 numbers; SDA1 numbers
#5: Valid SCL numbers for SCL test type.  SCL0 numbers; SCL1 numbers
#6: Valid I2C numbers for I2C test type.
#7: Valid State Machine numbers for SM test type.