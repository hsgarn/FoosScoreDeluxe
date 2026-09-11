# FoosScorePlusDeluxe

MicroPython firmware for a Raspberry Pi Pico W/2W integrated into a foosball
table with its own I2C character LCD, SPI color TFT, and NeoPixel LED strip -
in addition to the goal sensors, team LEDs, and time-out pushbuttons that
[FoosScorePlus](https://github.com/hsgarn) boards use. It can run fully
standalone (no PC required) with on-device scoring/menu, or report goals/
time-outs over TCP to one or more FoosOBSPlus clients, answer UDP discovery
and management commands from a table-manager tool, and optionally report
goals directly to the [iRefFoos](https://ireffoos.com) Remote Command API.

The firmware logic is split across `main.py` and a handful of small modules
it imports (`colors.py`, `eventqueue.py`, `debuglog.py`, `netmsg.py`,
`ledstrip.py`, `iref.py`) - see [Files](#files) below. It's split this way
because MicroPython compiles each `.py` file on-device before running it, and
a single ~68KB/1750-line file was enough to exhaust the RP2040's heap during
that compile step (`MemoryError` at boot, before any of the code actually
ran). Splitting the code into several independently-compiled modules keeps
every single compile unit small; everything else in this repo is
configuration.

## Relationship to FoosScorePlus

This board's `main.py` merges FoosScorePlus's networking/reliability layer
(multi-client TCP, the UDP discovery/management protocol, an IRQ-safe event
ring buffer, per-pin debounce, a single unified `select()` main loop,
threaded iRefFoos reporting) underneath this project's own display/LED-strip/
standalone-mode feature set. See [Hardware differences](#hardware--requirements)
and [Core-1 worker](#core-1-worker-led-strip--irefFoos) below for what's
different from a plain FoosScorePlus board.

## Files

| File | Purpose |
|---|---|
| [main.py](main.py) | The firmware entry point and orchestration: config loading, hardware init, the on-device menu/display, game logic, and the main `select()` loop. Runs on boot, never returns until `keepRunning` is cleared (End Program) or a fatal socket error. |
| [colors.py](colors.py) | RGB color constants used by the LED strip and menu. |
| [eventqueue.py](eventqueue.py) | The IRQ-safe sensor/pushbutton event ring buffer. |
| [debuglog.py](debuglog.py) | The leveled console logger (`debug()`). |
| [netmsg.py](netmsg.py) | TCP message sending (`sendMessage`/`sendScore`/`sendTimeOut`) and config-file transfer/validation (`read`/`save` commands). |
| [ledstrip.py](ledstrip.py) | The `LEDStrip` class - NeoPixel command queue and animation patterns. |
| [iref.py](iref.py) | The `IrefClient` class - iRefFoos Remote Command API HTTP client and its report queue. |
| [config.py](config.py) | Per-table hardware/network configuration (pins, ports, delays, table number, display/LED-strip pins, iRefFoos settings). |
| [wifi_setup.py](wifi_setup.py) | Wi-Fi setup captive portal, entered from the on-device menu's "Wi-Fi Setup" item (see [Wi-Fi setup portal](#wi-fi-setup-portal)). Ported from FoosScorePlus. |
| [secrets.py](secrets.py) | WiFi SSID/password list (`NETWORKS`), tried in order until one connects. Can also be written by the Wi-Fi setup portal instead of over USB. |
| [secretsIref.py](secretsIref.py) | iRefFoos API key. Optional - only needed if `IREF = 1` in `config.py`. |
| `table.txt` | Written/read at runtime by `main.py`. Holds a remotely assigned table number that overrides `config.TABLE`. Not checked into the repo. |

`main.py` imports `colors.py`/`eventqueue.py`/`debuglog.py`/`netmsg.py`/
`ledstrip.py`/`iref.py` by name at startup, so all six must be copied to the
board's filesystem alongside `main.py` and `config.py` - a missing one fails
as an `ImportError`, not a syntax or memory error.

## Hardware / requirements

- Raspberry Pi Pico W or Pico 2W running MicroPython.
- 2 or 3 goal sensors (IR break-beam or laser), one or two team LEDs, and a
  **third** pushbutton (`PB3`) in addition to the two time-out pushbuttons -
  `PB3` is the on-device menu "Action" button (select/back).
- An I2C 20x4 character LCD and an SPI color TFT (ST7735), both driving the
  same on-device menu.
- A NeoPixel/WS2812 LED strip, split into per-team pixel ranges.
- IR break sensors require the external pull-down resistor removed and rely
  on the Pico's internal pull-up; laser sensors need an external 10K
  pull-down.
- **Vendored driver libraries required on the device but not part of this
  repo**: `pico_i2c_lcd.py`, `neopixel.py`, `ST7735.py`, `sysfont.py` (and
  their own dependencies). Deploy these to the board's filesystem alongside
  `main.py` before flashing - `main.py` will fail to import otherwise.

## Configuration (`config.py`)

Read once at startup and validated against `REQUIREDCONFIGNAMES` before
anything else runs - an invalid or incomplete config aborts boot with an
error printed over serial.

| Name | Required | Meaning |
|---|---|---|
| `TABLE` | yes | This table's number. Overridden at runtime if `table.txt` exists. |
| `PORT` | yes | TCP port FoosOBSPlus clients connect to for scoring. |
| `DPORT` | yes | UDP port for discovery/identify/assign/flash/report-table commands. |
| `SENSOR1`, `SENSOR2` | yes | GPIO pins for the two required goal sensors. |
| `SENSOR3` | no | GPIO pin for an optional third sensor (2-sensor tables are fine without it). |
| `SENSOR1_TYPE`, `SENSOR2_TYPE` | yes | `"IR"` or `"LASER"`. |
| `SENSOR3_TYPE` | no | `"IR"` or `"LASER"`, only if `SENSOR3` is set. |
| `LED1`, `LED2` | yes | GPIO pins for the two team LEDs. |
| `DELAY_SENSOR` | yes | Debounce time (ms, 1-60000) after a sensor's LED-on edge before it can trigger again. For `"LASER"` sensors this block is shared across *all* configured laser sensors (any team), not just the one that fired - since a laser table's sensors typically sit along one shared ball-return channel, where a single ball can otherwise trip more than one of them and register extra goals. `"IR"` sensors keep independent per-sensor debounce, since break-beam brackets already make that kind of cross-sensor trip physically impossible. |
| `DELAY_PB` | yes | Debounce time (ms, 1-60000) for the time-out pushbuttons (`PB1`/`PB2`). |
| `DELAY_ACTION_PB` | yes | Debounce time (ms, 1-60000) for the menu Action button (`PB3`). |
| `PB1`, `PB2` | yes | GPIO pins for the two time-out pushbuttons. |
| `PB3` | yes | GPIO pin for the on-device menu Action button. |
| `TEAMS` | yes | List mapping each sensor index to a team, e.g. `[1,1,2]`. Values must be `1` or `2`. |
| `DEBUGMODE` | no | `0`/`1`. Verbose per-event logging and the `debug()` logger's minimum level (`DEBUG` vs `INFO`) when set. |
| `SDA`, `SCL`, `I2C` | yes | I2C pins/bus id for the character LCD. |
| `LEDSTRIP`, `NUMBER_PIXELS`, `STATE_MACHINE` | yes | NeoPixel data pin, pixel count, and PIO state machine. |
| `TEAM1LEDS`, `TEAM2LEDS` | yes | Per-team pixel ranges, `"start-end;start-end"` (e.g. `"0-14"`). |
| `SPIBLOCK`, `SPI_SCK_CLK_SCK`, `SPI_TX_DIN_MOSI`, `SPI_RX_DC_ADC`, `SPI_RX_RST_ARESET`, `SPI_CSN_CS_ACS` | no | SPI bus/pins for the color TFT. Omit all seven of these (and `TFT_ROTATION`) together on a board that only has the I2C LCD wired up - `main.py` sets `tftEnabled = False` and skips TFT init and every menu/screen draw to it, running on the I2C LCD alone. |
| `TFT_ROTATION` | no | TFT rotation (0-3) passed to `tft.rotation()`. See above - optional along with the SPI fields. |
| `IREF` | no | `0`/`1`. Enables direct goal reporting to iRefFoos. Forced off automatically in standalone mode (no network). |
| `IREF_DEVICE` | no | iRefFoos device id template; `{n}` is replaced with the current table number. Defaults to `"table{n}"`. |
| `IREF_HOME_TEAM` | no | Which team (`1` or `2`) is iRefFoos's home team. Defaults to `1`. |
| `IREF_URL` | no | Base URL of the iRefFoos API. Defaults to `"https://ireffoos.com"`. |

Every pin in the config (sensors, LEDs, pushbuttons, `SDA`/`SCL`,
`LEDSTRIP`, and the SPI pins) is cross-checked at boot in one pass so no two
of them share a GPIO, and every pin must be in the Pico's valid GPIO set.

## Secrets

- **`secrets.py`** - `NETWORKS`, a list of `(ssid, password)` tuples tried in
  order until one connects, or until each has been tried once - after that
  the board falls back to [standalone mode](#standalone-mode--wifi-fallback).
- **`secretsIref.py`** - `APIKEY`, the iRefFoos Remote Command API key. An
  empty key (or `IREF = 0`) disables iRefFoos reporting.

## Startup sequence

1. Validate `config.py`; abort on failure.
2. Load config values, apply defaults for optional ones, print a summary.
3. Cross-check every configured pin for collisions.
4. Initialize the I2C LCD and SPI TFT and show the boot menu.
5. Try each `secrets.NETWORKS` entry once; if none connect, force
   **standalone mode**.
6. If not standalone: bind the TCP scoring socket, start listening, and bind
   the UDP discovery socket.
7. Set up sensor/pushbutton (including `PB3`) GPIO pins and interrupts.
8. Start `core1Worker` on the second core (LED-strip + iRefFoos, see below).
9. Enter the main loop.

## Standalone mode / WiFi fallback

If none of `secrets.NETWORKS` connects, the board sets `forceStandAloneMode`
and skips the TCP/UDP sockets and iRefFoos entirely - the table is still
fully playable through the on-device display, menu, and LED strip, with its
own match logic (points-to-win, games-to-win, balls-in-rack, game/match-win
detection, rack-vs-tournament mode). The menu's "StandAlone Mode"/
"FoosOBS+Mode" items can also switch modes manually at any time when network
is available.

This is a deliberate, fully-supported mode - a table can run standalone
forever on purpose - so unlike FoosScorePlus, an unreachable network does
*not* automatically open the Wi-Fi setup portal below; it only opens when
someone chooses "Wi-Fi Setup" from the menu.

## Wi-Fi setup portal

Lets a customer get a table onto their own network without connecting to the
Pico over USB. Ported from FoosScorePlus's [wifi_setup.py](wifi_setup.py),
and reached from the main menu's "Wi-Fi Setup" item:

1. The board opens its own open access point named `FoosScoreSetup-<last 6
   hex digits of the MAC>` and starts a minimal DNS server that resolves
   every hostname to itself, so a phone or laptop that joins it gets the
   normal "sign in to network" captive-portal prompt.
2. The AP's name and setup address are also shown on the I2C LCD - unlike the
   base project, this board has a display, so there's no need to memorize a
   fixed IP ahead of time.
3. Opening that prompt (or browsing to the address shown) shows a one-field
   setup page - type in the network name and password (no nearby-network
   scan/dropdown, since that's an unbounded call that risks tripping the
   watchdog in an RF-dense area; see the comment in `wifi_setup.py`).
4. Submitting a network name and password writes it into `secrets.py` (added
   to, not replacing, any networks already listed there) and reboots the
   board.
5. On reboot the normal connect sequence runs again with the new
   credentials. If they're wrong, standalone mode kicks in as usual - "Wi-Fi
   Setup" from the menu tries again.

The two team LEDs (`team1LED`/`team2LED`) alternate every half second while
the portal is waiting for a submission, on the same GPIOs already wired for
them - the LED strip isn't used for this since it's driven from `core1Worker`,
which the portal's blocking wait doesn't service.

## Main loop

When not in standalone mode, a single `select()` call each iteration waits
on the UDP socket, the TCP listen socket, and every connected client socket
at once, with a short (10ms) timeout so the loop still wakes on its own
cadence to notice hardware-triggered events. In standalone mode the loop
just paces itself with an equivalent sleep. Each iteration:

1. Services one pending UDP packet, if any (discovery/management protocol).
2. Drains **every** goal/time-out/menu-action event queued since the last
   iteration - not just one.
3. Updates the Test Inputs live sensor readout, if that mode is active.
4. Services every connected TCP client's socket and accepts new connections
   (skipped entirely in standalone mode).

### Sensor/pushbutton events

Sensor and pushbutton (`PB1`/`PB2`/`PB3`) GPIO interrupts push
`(event_type, team, pin)` records into a small fixed-size ring buffer
(IRQ-safe, non-allocating) that the main loop drains every iteration. Each
pin has its own debounce flag and one-shot `Timer`, so one pin's debounce
window can never mask another's interrupt. `PB3` pushes an `ACTION` event
(no team) instead of a `PB` event - the main loop routes it to menu
navigation instead of goal/time-out handling.

For each drained `GOAL`/`PB` event the main loop:
- Forwards it to the table manager if a UDP identify-mode session is active.
- For goals, enqueues it for iRefFoos reporting (if enabled).
- Broadcasts it to every connected TCP client (multiple FoosOBSPlus clients
  may be connected at once; a client whose send fails is dropped, the others
  still receive the event).
- Updates the LED strip (`stripScore`/`stripTimeOut`) and, depending on
  mode, the on-device score screen or the FoosOBS+ status lines.

`ACTION` events drive the on-device menu: opening it, moving the cursor, or
confirming a selection, depending on whether the menu/change-value mode is
currently active.

## TCP scoring protocol (`PORT`)

Multiple FoosOBSPlus clients may connect to the same table at once; each
gets its own receive buffer so one client's partial command is never spliced
with another's.

**Outbound (Pico → every connected client):**

| Message | Meaning |
|---|---|
| `Team:<team>,<pin>\r\n` | A goal was scored by `<team>` on sensor pin `<pin>`. |
| `TO:<team>,<pin>\r\n` | `<team>` pressed the time-out pushbutton on pin `<pin>`. |
| `Read:\r\n` then `Line:<text>\r\n` per line | Response to `read`; dumps `config.py`. |
| `pong\r\n` | Response to `ping`. |

**Inbound (client → Pico), colon-prefixed, `\r\n`-terminated:**

| Command | Effect |
|---|---|
| `reset:` | Calls `machine.reset()`. |
| `read:` | Sends the current `config.py` back to the requesting client. |
| `hello:<sessionId>` | Registers this connection's session id. Sent once, right after connecting. |
| `ping:<sessionId>` | Replies `pong\r\n`. Also (re-)registers the session id, same as `hello`. |
| `save:<new config lines>...End` | Validates and writes a new `config.py`, backing up the old one first. Aborted (with a serial message) on invalid config, a missing `date` line, or an unchanged config. |

Any other command name is discarded once a full `name:` prefix has been
received, so a corrupt/unrecognized command can't wedge a client's buffer.

**Session ids and stale-connection cleanup:** a client picks its own session id once
(e.g. a UUID) and reuses it across every reconnect it makes on its own, sending it with
`hello` right after connecting and with every `ping`. If a client disconnects without the
Pico noticing (no FIN/RST ever arrives - see the main loop's socket handling) and then
reconnects, the Pico would otherwise end up with two live entries for the same logical
client, broadcasting every score/time-out to both. Instead, whenever a `hello`/`ping`
carries a session id matching an existing connection's, the Pico closes that older
connection and keeps only the new one. A client that never sends a session id (or an older
client build) is left alone - this is additive, not required. There's still no general
liveness timeout: a connection that goes silent and is never superseded by a same-session
reconnect stays tracked until the OS-level socket itself reports an error.

## UDP discovery/management protocol (`DPORT`)

Same protocol as FoosScorePlus. `ENTER_IDENT`, `ASSIGN`, `FLASH`, and
`REPORT_TABLE` refuse to run while a game (TCP) client is connected, replying
`BUSY:<mac>`, since they block the main loop for team-LED animations that
would otherwise delay score reporting.

`<mac>` in a request is matched case- and separator-insensitively against
this board's MAC (`-` and `:` are stripped, then lowercased) before
comparing, so `2C-CF-67-9B-97-14`, `2c:cf:67:9b:97:14`, and `2ccf679b9714`
are all accepted as the same address.

| Request | Reply | Effect |
|---|---|---|
| `DISCOVER_PICO` | `Table <n>:<ip>:<port>:<mac>:<status>` | Always answered. `<status>` is `FREE` or `BUSY:<client ip>[,<client ip>...]`. |
| `ENTER_IDENT` | `IDENT_ON:<mac>:<n>` or `BUSY:<mac>` | Every subsequent sensor/pushbutton trigger is reported as `IDENT:<mac>:<GOAL\|PB>:<pin>` until `EXIT_IDENT` or a game client connects. |
| `EXIT_IDENT` | `IDENT_OFF:<mac>` | Leaves identify mode. |
| `ASSIGN:<mac>:<n>` | `ASSIGNED:<mac>:<n>` or `BUSY:<mac>` | Sets and persists the table number to `table.txt`, blinks it on the team LEDs. |
| `FLASH:<mac>` | `FLASHING:<mac>` or `BUSY:<mac>` | Flashes the team/onboard LEDs so the board can be located. |
| `REPORT_TABLE:<mac>` | `REPORTING:<mac>:<n>` or `BUSY:<mac>` | Blinks the *current* table number without changing it. |

This protocol is unavailable in standalone mode (no UDP socket is bound).

## Core-1 worker: LED strip + iRefFoos

MicroPython's `_thread` only supports one additional thread on the
RP2040/RP2350's second core. The NeoPixel LED-strip animation queue and the
iRefFoos HTTPS worker - each independently threaded in the source
projects this board was merged from - now share a single `core1Worker`
loop instead:

1. If an LED-strip command is queued, execute it (priority - LED feedback is
   the more latency-sensitive, user-visible signal tied to a physical goal/
   time-out).
2. Otherwise, if iRefFoos is enabled and a report is queued, send it (over a
   keep-alive HTTPS socket, reconnecting only when the server closes it or a
   request fails).
3. Otherwise, sleep briefly and check again.

**Known limitation**: neither an LED animation (up to a few seconds) nor an
iRefFoos HTTP request (up to ~10s across both retry attempts) is broken into
resumable steps, so one can delay the other by its full duration in the
worst case - e.g. a goal that triggers both a strip animation and an iRef
report while a slow iRef request from a *previous* goal is still in flight.
This is an accepted tradeoff, not something this merge fully solves; making
`irefRequest` properly non-blocking would be a larger follow-up.

## Versioning

`main.py` keeps its own changelog as dated comments at the top of the file
(newest first), including the two source projects' full histories prior to
the v3.00 merge.
