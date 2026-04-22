# Sliver

Sliver is a postcard-themed web app for generating short video summaries from longer source videos.

## Run locally

1. Install Python dependencies:

```bash
pip install -r requirements.txt
```

2. Make sure `ffmpeg` is installed on your machine.

3. Start the site:

```bash
python3 app.py
```

4. Open:

```text
http://127.0.0.1:8000
```

If port `8000` is busy, run:

```bash
SLIVER_PORT=8001 python3 app.py
```

## What the app includes

- Homepage
- Login / signup
- Workspace with live progress tracking
- Profile page with saved output clips and download buttons

## Data storage

The database stores:

- user accounts
- generated clip records

Uploads and output video files are stored on disk under `web_data/`.

## Hosting note

GitHub Pages is only for static frontend assets, so it cannot run this Python backend.

If you want someone else to fully use Sliver, they should either:

- run the repo locally on their machine
- or use a hosting platform that supports a Python backend
