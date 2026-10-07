# mars-rover

Raspberry Pi rover server: camera/color detection, motion capture, Pico serial
comms, WiFi management, VNC over websocket, and an nginx front end.

## Layout

```
rpi-server/            Everything that runs on the Pi
  install.sh           One-shot setup (run on the Pi, as the `space` user)
  uninstall.sh         Removes services/configs installed by install.sh
  supervisord.conf     /etc/supervisor/supervisord.conf
  colordetect.py/.conf Colour detection on the motion stream, HTTP :9003
  picocoms.py/.conf    Pico serial bridge over HTTP, :8080
  netconman.py/.conf   Keeps the Pi on the honorX5b WiFi network
  motion.cfg/.conf     motion daemon (webcontrol :9001, stream :9002)
  websockify.conf      noVNC -> VNC bridge, :6080 -> localhost:5900
  nginx/               Stock-equivalent nginx.conf + default site
```

## Setup on the Pi

```sh
rsync -a --exclude .venv rpi-server/ space@raspberrypi:~/rpi-server/
ssh -t space@raspberrypi 'cd ~/rpi-server && bash install.sh'
```

`install.sh` apt-installs `supervisor nginx motion`, installs [uv](https://docs.astral.sh/uv/),
runs `uv sync` (Python deps: opencv, numpy, pyserial, websockify, supervisor),
installs the supervisor + nginx configs, and enables both services.

Run `bash install.sh` as `space` — it uses `sudo` internally. Running the whole
script with `sudo` breaks the venv's permissions.

Check state:

```sh
sudo supervisorctl status
systemctl status nginx supervisor
```

## Services

| Program      | Command source              | Notes                          |
|--------------|-----------------------------|--------------------------------|
| colordetect  | `colordetect.py`            | autostart, :9003               |
| picocoms     | `picocoms.py`               | autostart, :8080, /dev/serial0 |
| netconman    | `netconman.py`              | autostart, wifi watchdog       |
| websockify   | uv venv `websockify`        | autostart, :6080 -> :5900      |
| motion       | system `motion`             | autostart=false, start manually |

Ad-hoc start of motion: `sudo supervisorctl start motion`.

## Pico UART test

See `~/Workspace/uart-test/` on the Pi (`pico_main.py`, `uart_test.py`,
README). Wiring: Pi GPIO14/GPIO15 cross to Pico GPIO1/GPIO0, common GND,
115200 baud.

## Teardown

```sh
ssh -t space@raspberrypi 'cd ~/rpi-server && sudo bash uninstall.sh'
```

Stops/disables supervisor, removes the conf.d programs and nginx default site.
System packages remain; purge with `sudo apt-get purge supervisor nginx motion`.
