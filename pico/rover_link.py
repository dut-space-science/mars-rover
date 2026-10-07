"""
rover_link - serial protocol between the Raspberry Pi (API/UI) and the Pico firmware.

Firmware owns the motor/LED code; this module owns parsing and replies so both
sides agree on the wire format. MicroPython. If you write the firmware in C,
implement the same contract.

WIRING (UART, 3.3 V logic, 115200 8N1)
  Pi GPIO14 TXD (pin 8)   ->  Pico GP1 UART0 RX (pin 2)
  Pi GPIO15 RXD (pin 10)  <-  Pico GP0 UART0 TX (pin 1)
  Pi GND                  --  Pico GND
  On the Pi this is /dev/serial0 (raspi-config: serial console OFF, serial port ON).

REQUESTS (Pi -> Pico)
  One command per line, ASCII, terminated by "\n". Upper-case name, args separated
  by single spaces. These are the commands the UI/API sends today:

    FORWARD <speed>    drive forward       speed: integer 0-100 (percent)
    BACKWARD <speed>   drive backward
    LEFT <speed>       turn left on the spot
    RIGHT <speed>      turn right on the spot
    STOP [<speed>]     stop all motors. The UI appends the speed ("STOP 50"); ignore it.
    PING               liveness check
    HELLO              identify firmware
    LED_ON / LED_OFF   onboard LED, for bench testing

  Drive commands are latched: the UI sends one command per button press, not a
  stream. Keep doing the last drive command until STOP or another drive command
  arrives. Do not ramp or block inside a handler; start the motion and return.

RESPONSES (Pico -> Pi)
  Exactly one line per request, sent as soon as the command is accepted (< 50 ms):

    OK <CMD> [data]           e.g. "OK FORWARD 50", "OK PING PONG", "OK HELLO rover-fw 0.1"
    ERR <CODE> <detail>       CODE: UNKNOWN | BAD_ARGS | FAILED

  The Pi returns every line it reads back to the UI as {"cmd": ..., "response": [lines]}.
  It stops reading after <timeout> seconds of silence (default 2 s), so:
    - reply within that window, or the UI sees an empty response;
    - never print debug output on this UART (use USB serial / print() for that);
    - don't send unsolicited messages: the Pi clears its input buffer before every
      command, so anything sent between commands is dropped.
"""

from machine import UART, Pin

BAUD = 115200
DRIVE = ("FORWARD", "BACKWARD", "LEFT", "RIGHT")
MAX_LINE = 64


class RoverLink:
    def __init__(self, uart_id=0, tx=0, rx=1):
        self.uart = UART(uart_id, baudrate=BAUD, tx=Pin(tx), rx=Pin(rx))
        self._buf = b""
        self._handlers = {}

    def on(self, name):
        """Register a handler: @link.on("FORWARD") def forward(speed): ...

        Drive handlers get speed as an int 0-100. STOP gets no args. Others get the
        raw string args. Return None for a plain "OK <CMD>", or a value to append.
        """
        def register(fn):
            self._handlers[name] = fn
            return fn
        return register

    def poll(self):
        """Call from the main loop as often as possible. Handles complete lines only."""
        n = self.uart.any()
        if n:
            self._buf += self.uart.read(n)
        while b"\n" in self._buf:
            raw, self._buf = self._buf.split(b"\n", 1)
            try:
                line = raw.decode().strip()  # tolerates "\r\n"
            except UnicodeError:
                self._reply("ERR BAD_ARGS undecodable line")
                continue
            if line:
                self._dispatch(line)
        if len(self._buf) > MAX_LINE:  # no newline in sight: drop garbage
            self._buf = b""

    def _dispatch(self, line):
        name, *args = line.split()
        name = name.upper()
        fn = self._handlers.get(name)
        if fn is None:
            return self._reply("ERR UNKNOWN " + name)
        try:
            if name in DRIVE:
                args = [parse_speed(args)]
            elif name == "STOP":
                args = []
            result = fn(*args)
        except ValueError as e:
            return self._reply("ERR BAD_ARGS " + name + " " + str(e))
        except Exception as e:
            return self._reply("ERR FAILED " + name + " " + str(e))
        if name in DRIVE and result is None:
            result = args[0]  # echo the applied speed: "OK FORWARD 50"
        self._reply("OK " + name if result is None else "OK " + name + " " + str(result))

    def _reply(self, line):
        self.uart.write((line + "\n").encode())


def parse_speed(args):
    if len(args) != 1:
        raise ValueError("expected <speed>")
    speed = int(args[0])  # raises ValueError on junk
    if not 0 <= speed <= 100:
        raise ValueError("speed must be 0-100")
    return speed


# Example main.py for the firmware team:
#
#   from rover_link import RoverLink
#   import motors                      # yours
#
#   link = RoverLink()
#
#   @link.on("FORWARD")
#   def forward(speed): motors.set(speed, speed)
#   @link.on("BACKWARD")
#   def backward(speed): motors.set(-speed, -speed)
#   @link.on("LEFT")
#   def left(speed): motors.set(-speed, speed)
#   @link.on("RIGHT")
#   def right(speed): motors.set(speed, -speed)
#   @link.on("STOP")
#   def stop(): motors.set(0, 0)
#   @link.on("PING")
#   def ping(): return "PONG"         # -> "OK PING PONG"
#   @link.on("HELLO")
#   def hello(): return "rover-fw 0.1"
#
#   while True:
#       link.poll()
#       # other non-blocking work (sensors, motor ramping) goes here
