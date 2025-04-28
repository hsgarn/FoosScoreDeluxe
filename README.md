# FoosScoreDeluxe
Deluxe version of FoosScore that has a LCD display and a stand alone mode that does not require FoosOBSPlus.

FoosScoreDeluxe is a program used for a foosball auto scoring system. The system can work in stand alone more or in conjunction with FoosOBSPlus.  It requires a Raspberry Pico 2 W. The hardware consists of 3 lasers (DAOKI model DR-US-583) and corresponding receivers, two LEDs, two push buttons, 7 resistors (5x10M ohm, 2x330 ohm), 3 capacitors (KGM 104), an 4x20 LCD display, and an optional LED Strip.

A config.py file is used to designate which pins the LEDs, Push Buttons and Laser Receivers are connected to, as well as the Port number to connect for communication and separate delay times for laser and push button debounce.  Config items related to the LCD display and the LED Strip are in there too.

A secretsHP.py and secretsHome.py are used to store the wifi connection SSID and PASSWORD. The connection in secretsHP.py is tried first followed by secretsHome.  Stand alone mode does not require a network connection.
