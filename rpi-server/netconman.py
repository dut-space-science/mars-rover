import subprocess
import time
import sys

TARGET_SSID = "honorX5b"
CHECK_INTERVAL = 30

def log(msg):
    print(f"[netconman] {msg}", flush=True)
    sys.stdout.flush()

def run(cmd):
    return subprocess.run(cmd, shell=True, capture_output=True, text=True)

def is_connected(ssid):
    result = run("nmcli -t -f NAME,DEVICE con show --active | grep '^honorX5b:'")
    return bool(result.stdout.strip())

def scan_available():
    result = run("nmcli -t -f SSID dev wifi list --rescan yes | grep -E '^honorX5b$'")
    return bool(result.stdout.strip())

def ensure_wifi_up():
    run("nmcli radio wifi on")
    run("nmcli dev set wlan0 managed yes")

def connect():
    log("Target SSID found, connecting...")
    result = run(f'nmcli con up "{TARGET_SSID}"')
    if result.returncode == 0:
        log("Connected to wifi")
    else:
        log(f"Connect failed: {result.stderr}")

def main():
    log(f"Starting netconman, target={TARGET_SSID}, interval={CHECK_INTERVAL}s")
    ensure_wifi_up()
    
    while True:
        if scan_available():
            if not is_connected(TARGET_SSID):
                connect()
            else:
                log("Already connected to target")
        else:
            log("Target SSID not in range")
        
        time.sleep(CHECK_INTERVAL)

if __name__ == "__main__":
    main()
