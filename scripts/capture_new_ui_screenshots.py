"""
scripts/capture_new_ui_screenshots.py
Captures fresh, pixel-perfect high-DPI screenshots of the new dark-mode Obsidian UI.
Overwrites old screenshots in assets/screenshots/.
"""

import os
import signal
import subprocess
import time
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
SCREENSHOTS_DIR = ROOT_DIR / "assets" / "screenshots"
SCREENSHOTS_DIR.mkdir(parents=True, exist_ok=True)

CHROME_BIN = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
SESSION_TOKEN = "eyJpc3N1ZWRfYXQiOjE3OTE1NTk4NzkuMzgzNzYzLCJ1c2VyX2lkIjoxfQ%3D%3D.3ed0fbcdf9e9f1138900945abd74438a549e644edec85526e9e365c0e211c862"

PAGES = [
    ("home.png", "http://127.0.0.1:8008/"),
    ("workspace.png", f"http://127.0.0.1:8008/workspace?sliver_session={SESSION_TOKEN}"),
    ("profile.png", f"http://127.0.0.1:8008/profile?sliver_session={SESSION_TOKEN}"),
    ("signup.png", "http://127.0.0.1:8008/auth"),
]

def capture_page(name: str, url: str):
    out_file = SCREENSHOTS_DIR / name
    if out_file.exists():
        out_file.unlink()

    print(f"[*] Capturing {name} from {url}...")
    user_data = f"/tmp/chrome_ss_{name.split('.')[0]}"

    cmd = [
        CHROME_BIN,
        "--headless=new",
        "--disable-gpu",
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-background-networking",
        "--disable-component-update",
        "--disable-sync",
        "--force-device-scale-factor=2",
        "--window-size=1470,920",
        "--hide-scrollbars",
        f"--user-data-dir={user_data}",
        f"--screenshot={out_file}",
        url,
    ]

    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        preexec_fn=os.setsid,
    )

    # Wait until file is created and has nonzero size, or timeout after 8s
    start_time = time.time()
    while time.time() - start_time < 8.0:
        if out_file.exists() and out_file.stat().st_size > 10000:
            time.sleep(0.5)  # allow write flush
            break
        time.sleep(0.3)

    try:
        os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
        proc.wait(timeout=2.0)
    except Exception:
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
        except Exception:
            pass

    if out_file.exists() and out_file.stat().st_size > 0:
        print(f"[+] Success: {name} saved ({out_file.stat().st_size // 1024} KB)")
    else:
        print(f"[-] Error: Failed to capture {name}")

def main():
    for name, url in PAGES:
        capture_page(name, url)

if __name__ == "__main__":
    main()
