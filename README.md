# Sliver — Smart Video Clipping Tool
Sliver is an AI-powered smart video clipping tool that automatically generates short highlight clips from long-form videos. It analyzes faces, objects, motion, timestamps, and audio segments to identify high-impact moments, then stitches the selected scenes back together into a concise summary video.
The project is designed as a full-stack local web application with user authentication, video upload, live progress tracking, generated clip storage, and downloadable outputs.
---
## Features
- Upload long-form videos through a web workspace
- Choose the desired summary duration
- Detect important scenes using computer vision
- Use YOLOv8n for face detection
- Use YOLO11m for person/object detection
- Score scenes using custom timestamp-based logic
- Extract and process audio using FFmpeg
- Stitch selected video/audio segments into a final highlight clip
- Track generation progress in real time
- Store generated clip records in SQLite
- Download previously generated clips from the profile page
- Includes an older Gradio prototype and a newer web-based interface
---
## Tech Stack
### Backend
- Python
- WSGI server
- Jinja2 templates
- SQLite
- Threading for background processing
### AI / Computer Vision
- YOLOv8n Face
- YOLO11m
- OpenCV
- Ultralytics
### Video & Audio Processing
- FFmpeg
- Frame extraction
- Audio extraction
- Audio segment cutting
- Video/audio muxing
### Frontend
- HTML
- CSS
- JavaScript
- Jinja2 templates
### Prototype UI
- Gradio
---
## Project Architecture
```text
User Upload
    ↓
Video stored locally
    ↓
Background processing job created
    ↓
OpenCV reads frames
    ↓
YOLO11m detects people/objects
    ↓
YOLOv8n detects faces
    ↓
Custom scoring logic ranks scenes
    ↓
Top scenes are selected by duration target
    ↓
FFmpeg extracts and cuts audio
    ↓
Selected video scenes are stitched
    ↓
Final highlight clip is generated
    ↓
Clip record saved in SQLite
    ↓
User downloads output from workspace/profile

⸻

Repository Structure

Sliver-Smart-Video-Clipping-Tool/
│
├── app.py                         # Main Python web application
├── requirements.txt               # Python dependencies
├── README.md                      # Project documentation
│
├── face_clip/
│   ├── gradio_ui.py               # Early Gradio prototype
│   ├── run_pipeline.py            # Experimental/legacy pipeline script
│   └── pipeline/
│       ├── process_video.py       # Main video processing pipeline
│       ├── scene_scoring.py       # Scene scoring logic
│       ├── scene_buffer.py        # Scene buffering logic
│       ├── scene_understanding.py # Scene selection logic
│       ├── clip_writer.py         # Video writing utility
│       └── audio_utils.py         # FFmpeg-based audio utilities
│
├── templates/
│   ├── base.html                  # Base layout
│   ├── home.html                  # Landing page
│   ├── auth.html                  # Login/signup page
│   ├── workspace.html             # Video upload and generation workspace
│   └── profile.html               # User profile and saved clips
│
├── static/                        # Static frontend assets
├── tests/                         # Test files
└── web_data/                      # Runtime uploads, generated clips, SQLite DB

⸻

How It Works

1. Video Upload

The user uploads a source video from the workspace page and selects the target duration for the summary clip.

2. Job Creation

The backend creates a background processing job and tracks progress using an in-memory job dictionary.

3. Frame Analysis

OpenCV reads the input video frame by frame. Each frame is passed through the detection models.

4. Face and Object Detection

Sliver uses:

* YOLOv8n Face for face detection
* YOLO11m for person/object detection

These detections help identify visually important moments.

5. Scene Scoring

A custom scoring system ranks scenes based on detected faces, people, objects, motion, and timestamp-based scene buffers.

6. Scene Selection

The highest-scoring scenes are selected according to the target clip duration provided by the user.

7. Audio Processing

FFmpeg extracts the original audio, cuts the matching audio segments, joins them, and muxes the final audio with the generated video clip.

8. Output Generation

The final summary clip is saved locally and made available for preview/download.

⸻

Installation

1. Clone the repository

git clone https://github.com/muditagrawal-alt/Sliver-Smart-Video-Clipping-Tool.git
cd Sliver-Smart-Video-Clipping-Tool

2. Create and activate a virtual environment

python3 -m venv venv
source venv/bin/activate

For Windows:

python -m venv venv
venv\Scripts\activate

3. Install Python dependencies

pip install -r requirements.txt

4. Install FFmpeg

FFmpeg must be installed separately.

macOS:

brew install ffmpeg

Ubuntu/Debian:

sudo apt update
sudo apt install ffmpeg

Windows:

Download FFmpeg from the official website and add it to your system PATH.

⸻

Running the Web App

Start the app:

python3 app.py

Open in browser:

http://127.0.0.1:8000

If port 8000 is busy:

SLIVER_PORT=8001 python3 app.py

⸻

Environment Variables

Optional environment variables:

SLIVER_HOST=127.0.0.1
SLIVER_PORT=8000
SLIVER_SECRET_KEY=your-secret-key

For development, the app uses a default local secret key. For production-style deployment, set SLIVER_SECRET_KEY.

⸻

User Flow

Home Page
   ↓
Login / Signup
   ↓
Workspace
   ↓
Upload Video
   ↓
Choose Summary Duration
   ↓
Generate Highlight Clip
   ↓
Preview / Download Output
   ↓
Profile Page
   ↓
View Saved Clips

⸻

Data Storage

Sliver stores runtime data locally under:

web_data/

This includes:

web_data/
├── uploads/        # Uploaded source videos
├── generated/      # Generated highlight clips
└── sliver.sqlite3  # SQLite database

The SQLite database stores:

* User accounts
* Generated clip records
* Clip metadata

⸻

Current Limitations

* Runs locally by default
* Generated files are stored on disk
* No cloud storage integration yet
* No real OAuth integration yet
* Processing speed depends on local CPU/GPU resources
* Large videos may take significant time to process
* GitHub Pages cannot run the Python backend

⸻

Future Improvements

* Cloud storage for generated clips
* Google/Microsoft OAuth login
* User dashboard with search and filters
* Clip deletion and management
* Thumbnail generation
* Batch video uploads
* Better scene classification labels
* GPU-accelerated deployment
* Docker support
* Production deployment using Render, Railway, or a similar Python backend host

⸻

Why This Project Matters

Manual video editing is time-consuming, especially when working with long-form footage. Sliver reduces that effort by automatically identifying the most meaningful moments and generating short highlight clips. This makes it useful for media teams, content reviewers, editors, analysts, and anyone who needs faster video summarization.

⸻

Author

Mudit Agrawal
B.Tech CSE (AI/ML)

⸻

License

This project is currently shared as a portfolio and learning project. Add a license file before using it for public distribution or commercial use.