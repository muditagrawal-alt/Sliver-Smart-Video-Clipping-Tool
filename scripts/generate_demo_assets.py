"""
scripts/generate_demo_assets.py
Generates:
1. assets/demo/sliver_project_demo.mp4 (720p master demo video with floating subtitles, title card, 3s execution cut, output recap, stock background music)
2. assets/demo/architecture.gif (Animated pipeline dataflow architecture diagram)
3. assets/demo/quickstart.gif (Terminal walkthrough showing clone, setup, and launch)
"""

import math
import os
import subprocess
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont, ImageFilter
import cv2
import numpy as np

ROOT_DIR = Path(__file__).resolve().parents[1]
ASSETS_DIR = ROOT_DIR / "assets"
DEMO_DIR = ASSETS_DIR / "demo"
DEMO_DIR.mkdir(parents=True, exist_ok=True)

FONT_REGULAR = "/System/Library/Fonts/Supplemental/Arial.ttf"
FONT_BOLD = "/System/Library/Fonts/Supplemental/Arial Bold.ttf"

def get_font(size: int, bold: bool = False):
    font_path = FONT_BOLD if bold else FONT_REGULAR
    try:
        return ImageFont.truetype(font_path, size)
    except Exception:
        return ImageFont.load_default()

def draw_floating_subtitle(img: Image.Image, text: str, font_size: int = 20) -> Image.Image:
    """
    Renders a floating, centered pill subtitle with rounded corners and subtle border.
    Elevated 40px above bottom edge, NOT a full-width taskbar.
    """
    if not text:
        return img

    font = get_font(font_size, bold=True)
    draw = ImageDraw.Draw(img, "RGBA")
    
    # Calculate text bounding box
    bbox = draw.textbbox((0, 0), text, font=font)
    tw = bbox[2] - bbox[0]
    th = bbox[3] - bbox[1]

    pad_x = 24
    pad_y = 10
    pill_w = tw + pad_x * 2
    pill_h = th + pad_y * 2

    # Center horizontally, float 40px above bottom
    x0 = (1280 - pill_w) // 2
    y0 = 720 - pill_h - 40
    x1 = x0 + pill_w
    y1 = y0 + pill_h

    # Draw floating pill background
    draw.rounded_rectangle(
        [x0, y0, x1, y1],
        radius=14,
        fill=(13, 17, 26, 215),          # Dark translucent slate
        outline=(255, 255, 255, 45),     # Subtle glassmorphism border
        width=1
    )

    # Draw centered text
    text_x = x0 + pad_x - bbox[0]
    text_y = y0 + pad_y - bbox[1]
    draw.text((text_x, text_y), text, font=font, fill=(255, 255, 255, 245))
    return img

def render_title_card() -> list[Image.Image]:
    """Generates frames for the opening title card (3.5 seconds = 105 frames)."""
    frames = []
    total_frames = 105

    for i in range(total_frames):
        img = Image.new("RGBA", (1280, 720), (10, 14, 23, 255))
        draw = ImageDraw.Draw(img, "RGBA")

        # Subtle background radial glow
        for r in range(400, 50, -30):
            alpha = int(18 * (1.0 - r / 400))
            draw.ellipse(
                [(640 - r, 340 - r), (640 + r, 340 + r)],
                fill=(45, 95, 220, alpha)
            )

        # Title Card Content
        font_eyebrow = get_font(15, bold=True)
        font_title = get_font(42, bold=True)
        font_author = get_font(24, bold=True)
        font_meta = get_font(16, bold=False)

        # Eyebrow badge
        badge_text = "PRODUCTION VIDEO INTELLIGENCE"
        draw.text((640, 190), badge_text, font=font_eyebrow, fill=(96, 165, 250), anchor="mm")

        # Main Title
        title_text = "SLIVER: A SMART VIDEO CLIPPING TOOL"
        draw.text((640, 260), title_text, font=font_title, fill=(255, 255, 255), anchor="mm")

        # Author Name (Explicitly requested by user)
        author_text = "Engineered by Mudit Agrawal"
        draw.text((640, 335), author_text, font=font_author, fill=(226, 232, 240), anchor="mm")

        # Divider line
        draw.line([(480, 385), (800, 385)], fill=(255, 255, 255, 40), width=1)

        # Tech Stack Badges
        tags = ["YOLO11m Human Tracking", "YOLOv8-Face Salience", "Zero-Shot CLIP", "Sample-Accurate Audio Cuts"]
        tag_x = 640 - (len(tags) * 160) // 2 + 80
        for idx, tag in enumerate(tags):
            x = 220 + idx * 215
            draw.rounded_rectangle([x - 90, 420, x + 90, 452], radius=8, fill=(25, 33, 50, 200), outline=(59, 130, 246, 80))
            draw.text((x, 436), tag, font=get_font(11, bold=True), fill=(190, 215, 255), anchor="mm")

        # Fade in first 15 frames, fade out last 15 frames
        sub_text = "Sliver: A Smart Video Clipping Tool — Engineered by Mudit Agrawal"
        draw_floating_subtitle(img, sub_text, font_size=18)

        if i < 15:
            fade = i / 15.0
            black = Image.new("RGBA", (1280, 720), (0, 0, 0, int(255 * (1.0 - fade))))
            img = Image.alpha_composite(img, black)
        elif i > total_frames - 15:
            fade = (total_frames - i) / 15.0
            black = Image.new("RGBA", (1280, 720), (0, 0, 0, int(255 * (1.0 - fade))))
            img = Image.alpha_composite(img, black)

        frames.append(img.convert("RGB"))
    return frames

def render_ui_showcase(screenshot_path: Path, subtitle: str, duration_sec: float = 4.0, crop_mode: str = "fit") -> list[Image.Image]:
    """Renders high-res UI overview with smooth motion and floating subtitle."""
    total_frames = int(duration_sec * 30)
    frames = []

    src_img = Image.open(screenshot_path).convert("RGB")
    sw, sh = src_img.size

    for i in range(total_frames):
        # Create 1280x720 canvas
        canvas = Image.new("RGB", (1280, 720), (10, 14, 23))

        # Scale to fit width while keeping aspect ratio
        scale = 1280 / sw
        scaled_h = int(sh * scale)
        scaled = src_img.resize((1280, scaled_h), Image.Resampling.LANCZOS)

        # Subtle slow pan
        max_scroll = max(0, scaled_h - 720)
        progress = i / max(1, total_frames - 1)
        # Ease in-out
        progress = 0.5 - 0.5 * math.cos(progress * math.pi)
        scroll_y = int(progress * min(max_scroll, 180))

        crop = scaled.crop((0, scroll_y, 1280, scroll_y + 720))
        canvas.paste(crop, (0, 0))

        # Add floating subtitle
        draw_floating_subtitle(canvas, subtitle, font_size=19)
        frames.append(canvas)

    return frames

def render_execution_clip(duration_sec: float = 3.0) -> list[Image.Image]:
    """
    Renders the first 3 seconds of execution:
    Shows the workspace with real-time progressing checklist and status percentages.
    """
    total_frames = int(duration_sec * 30)
    frames = []

    workspace_img = Image.open(ASSETS_DIR / "screenshots" / "workspace.png").convert("RGB")
    sw, sh = workspace_img.size
    scale = 1280 / sw
    scaled = workspace_img.resize((1280, int(sh * scale)), Image.Resampling.LANCZOS)
    base_frame = scaled.crop((0, 40, 1280, 760))

    sub_text = "First 3s of execution: Multi-stage detection, face tracking & salience scoring"

    for i in range(total_frames):
        canvas = base_frame.copy()
        draw = ImageDraw.Draw(canvas, "RGBA")

        # Simulate dynamic progress bar animating from 3% to 55%
        pct = 3 + int((i / total_frames) * 52)
        stage_names = [
            "1. Ingestion & frame extraction",
            "2. Object & face detection (YOLO11m)",
            "3. Scene scoring & context selection",
            "4. Audio synchronization",
            "5. Video encoding & export"
        ]

        active_idx = 1 if pct < 20 else (2 if pct < 45 else 3)

        # Progress overlay card
        ox, oy, ow, oh = 670, 140, 560, 230
        draw.rounded_rectangle([ox, oy, ox + ow, oy + oh], radius=10, fill=(17, 24, 39, 245), outline=(59, 130, 246, 120), width=1)
        
        draw.text((ox + 20, oy + 16), "JOB STATUS", font=get_font(12, bold=True), fill=(148, 163, 184))
        draw.text((ox + ow - 60, oy + 16), f"{pct}%", font=get_font(18, bold=True), fill=(96, 165, 250))
        
        status_msg = f"Analyzing scenes and motion... ({pct}%)"
        draw.text((ox + 20, oy + 42), status_msg, font=get_font(15, bold=True), fill=(255, 255, 255))

        # Progress bar track & fill
        draw.rounded_rectangle([ox + 20, oy + 76, ox + ow - 20, oy + 86], radius=5, fill=(31, 41, 55))
        fill_w = int((ow - 40) * (pct / 100.0))
        if fill_w > 0:
            draw.rounded_rectangle([ox + 20, oy + 76, ox + 20 + fill_w, oy + 86], radius=5, fill=(59, 130, 246))

        # Checklist stages
        for s_idx, s_text in enumerate(stage_names[:3]):
            sy = oy + 105 + s_idx * 36
            is_done = s_idx < active_idx
            is_active = s_idx == active_idx
            
            icon_color = (34, 197, 94) if is_done else ((59, 130, 246) if is_active else (100, 116, 139))
            draw.ellipse([ox + 22, sy, ox + 36, sy + 14], fill=icon_color)
            txt_color = (241, 245, 249) if (is_done or is_active) else (148, 163, 184)
            draw.text((ox + 45, sy), s_text, font=get_font(13, bold=is_active), fill=txt_color)

        draw_floating_subtitle(canvas, sub_text, font_size=19)
        frames.append(canvas)

    return frames

def render_output_playback(video_path: Path, duration_sec: float = 6.0) -> list[Image.Image]:
    """
    Renders output playback:
    Embeds real frames from scratch/demo_run/clip.mp4 into the workspace output deck!
    """
    total_frames = int(duration_sec * 30)
    frames = []

    cap = cv2.VideoCapture(str(video_path))
    sub_text = "Summary ready: Sample-accurate audio cuts & web-ready H.264 export"

    # Base workspace layout
    workspace_img = Image.open(ASSETS_DIR / "screenshots" / "workspace.png").convert("RGB")
    sw, sh = workspace_img.size
    scale = 1280 / sw
    scaled = workspace_img.resize((1280, int(sh * scale)), Image.Resampling.LANCZOS)
    base_frame = scaled.crop((0, 40, 1280, 760))

    # Video display box in the right panel
    target_x, target_y = 665, 390
    target_w, target_h = 570, 240

    for i in range(total_frames):
        ret, v_frame = cap.read()
        if not ret:
            cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
            ret, v_frame = cap.read()

        canvas = base_frame.copy()

        if ret and v_frame is not None:
            # Resize clip frame to fit output player
            v_rgb = cv2.cvtColor(v_frame, cv2.COLOR_BGR2RGB)
            v_pil = Image.fromarray(v_rgb).resize((target_w, target_h), Image.Resampling.LANCZOS)
            canvas.paste(v_pil, (target_x, target_y))

        draw = ImageDraw.Draw(canvas, "RGBA")
        # Video badge overlay
        draw.rounded_rectangle([target_x + 12, target_y + 12, target_x + 120, target_y + 36], radius=6, fill=(15, 23, 42, 220))
        draw.text((target_x + 66, target_y + 24), "15s Highlight", font=get_font(11, bold=True), fill=(255, 255, 255), anchor="mm")

        draw_floating_subtitle(canvas, sub_text, font_size=19)
        frames.append(canvas)

    cap.release()
    return frames

def render_outro_card() -> list[Image.Image]:
    """Renders closing card (3.0 seconds = 90 frames)."""
    frames = []
    total_frames = 90

    for i in range(total_frames):
        img = Image.new("RGBA", (1280, 720), (10, 14, 23, 255))
        draw = ImageDraw.Draw(img, "RGBA")

        # Subtle background glow
        draw.ellipse([(640 - 250, 320 - 250), (640 + 250, 320 + 250)], fill=(37, 99, 235, 15))

        font_title = get_font(38, bold=True)
        font_sub = get_font(20, bold=False)
        font_repo = get_font(18, bold=True)

        draw.text((640, 250), "SLIVER: A SMART VIDEO CLIPPING TOOL", font=font_title, fill=(255, 255, 255), anchor="mm")
        draw.text((640, 310), "Production Video Summarization Engine", font=font_sub, fill=(148, 163, 184), anchor="mm")
        
        draw.rounded_rectangle([420, 370, 860, 415], radius=10, fill=(30, 41, 59, 220), outline=(59, 130, 246, 120))
        draw.text((640, 392), "Engineered by Mudit Agrawal", font=font_repo, fill=(96, 165, 250), anchor="mm")

        draw.text((640, 460), "100% Local & Offline · Production Ready · MIT License", font=get_font(14, bold=False), fill=(100, 116, 139), anchor="mm")

        draw_floating_subtitle(img, "Production-grade video intelligence — 100% offline & local", font_size=18)

        if i > total_frames - 15:
            fade = (total_frames - i) / 15.0
            black = Image.new("RGBA", (1280, 720), (0, 0, 0, int(255 * (1.0 - fade))))
            img = Image.alpha_composite(img, black)

        frames.append(img.convert("RGB"))
    return frames

def build_demo_video():
    """Assembles all frames, writes video, and mixes stock music with fading."""
    print("1. Assembling video scenes...")
    all_frames = []

    # Scene 1: Title Card (3.5s)
    all_frames.extend(render_title_card())

    # Scene 2: Landing Page Overview (4.0s)
    all_frames.extend(render_ui_showcase(
        ASSETS_DIR / "screenshots" / "home.png",
        "Local AI video summarizer engineered for high-impact scene extraction.",
        duration_sec=4.0
    ))

    # Scene 3: Workspace Parameter Configuration (4.0s)
    all_frames.extend(render_ui_showcase(
        ASSETS_DIR / "screenshots" / "workspace.png",
        "Configurable duration targets and semantic zero-shot guidance via CLIP.",
        duration_sec=4.0
    ))

    # Scene 4: First 3s of Execution (3.0s)
    all_frames.extend(render_execution_clip(duration_sec=3.0))

    # Scene 5: Output Playback with Real Footage (6.0s)
    all_frames.extend(render_output_playback(
        ROOT_DIR / "scratch" / "demo_run" / "clip.mp4",
        duration_sec=6.0
    ))

    # Scene 6: Video Library (3.5s)
    all_frames.extend(render_ui_showcase(
        ASSETS_DIR / "screenshots" / "profile.png",
        "Export library: Instant MP4 downloads & local SQLite persistence.",
        duration_sec=3.5
    ))

    # Scene 7: Outro Card (3.0s)
    all_frames.extend(render_outro_card())

    total_duration = len(all_frames) / 30.0
    print(f"Total video frames: {len(all_frames)} ({total_duration:.1f} seconds)")

    raw_video_path = DEMO_DIR / "temp_demo_raw.mp4"
    final_video_path = DEMO_DIR / "sliver_project_demo.mp4"

    # Write video frames
    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    writer = cv2.VideoWriter(str(raw_video_path), fourcc, 30.0, (1280, 720))

    for frame in all_frames:
        bgr = cv2.cvtColor(np.array(frame), cv2.COLOR_RGB2BGR)
        writer.write(bgr)
    writer.release()

    # Mix stock audio with smooth volume and fades
    music_path = ASSETS_DIR / "audio" / "stock_music.mp3"
    print("2. Muxing with stock background music and H.264 encoding...")

    audio_filter = f"volume=0.32,afade=t=in:ss=0:d=1.5,afade=t=out:st={total_duration - 2.0:.2f}:d=2.0"

    cmd = [
        "ffmpeg", "-y",
        "-i", str(raw_video_path),
        "-i", str(music_path),
        "-filter:a", audio_filter,
        "-c:v", "libx264",
        "-pix_fmt", "yuv420p",
        "-preset", "fast",
        "-crf", "20",
        "-c:a", "aac",
        "-b:a", "192k",
        "-t", f"{total_duration:.2f}",
        "-movflags", "+faststart",
        str(final_video_path)
    ]
    subprocess.run(cmd, check=True)
    raw_video_path.unlink(missing_ok=True)
    print(f"SUCCESS: Demo video created at {final_video_path} ({os.path.getsize(final_video_path) / 1024 / 1024:.2f} MB)")

def build_architecture_gif():
    """Generates an animated architecture flow GIF (880x480)."""
    print("3. Generating animated architecture GIF...")
    gif_path = DEMO_DIR / "architecture.gif"

    stages = [
        ("Source Video", "MP4 / MOV / MKV", (59, 130, 246)),
        ("YOLO11m & Face", "Person & Face Tracking", (168, 85, 247)),
        ("Profiler & CLIP", "Motion & Zero-Shot Vibe", (236, 72, 153)),
        ("Context Clustering", "Event Window Merging", (245, 158, 11)),
        ("Audio Synchronizer", "Lossless Stream Cuts", (16, 185, 129)),
        ("H.264 Web Muxer", "Faststart Highlight MP4", (14, 165, 233)),
    ]

    frames = []
    num_frames = 36

    for f_idx in range(num_frames):
        img = Image.new("RGBA", (960, 440), (10, 14, 23, 255))
        draw = ImageDraw.Draw(img, "RGBA")

        # Header
        draw.text((480, 40), "SLIVER PIPELINE ARCHITECTURE & DATA FLOW", font=get_font(18, bold=True), fill=(241, 245, 249), anchor="mm")
        draw.text((480, 68), "Automated Local Video Summarization with Context Preservation", font=get_font(12, bold=False), fill=(148, 163, 184), anchor="mm")

        # Two rows of 3 blocks
        block_w = 260
        block_h = 95

        positions = [
            (50, 110),   # 0
            (350, 110),  # 1
            (650, 110),  # 2
            (650, 260),  # 3
            (350, 260),  # 4
            (50, 260),   # 5
        ]

        # Draw connecting pipeline arrows with animated pulses
        # Flow: 0 -> 1 -> 2 -> 3 -> 4 -> 5
        connections = [(0, 1), (1, 2), (2, 3), (3, 4), (4, 5)]

        for c_idx, (src, dst) in enumerate(connections):
            p1 = positions[src]
            p2 = positions[dst]
            
            if src < 2:  # Right arrow
                x_start = p1[0] + block_w
                y_mid = p1[1] + block_h // 2
                x_end = p2[0]
                draw.line([(x_start, y_mid), (x_end, y_mid)], fill=(51, 65, 85), width=2)
                
                # Pulse packet
                pulse_t = (f_idx / num_frames + c_idx * 0.2) % 1.0
                px = int(x_start + (x_end - x_start) * pulse_t)
                draw.ellipse([px - 4, y_mid - 4, px + 4, y_mid + 4], fill=(96, 165, 250))
            elif src == 2:  # Down arrow
                x_mid = p1[0] + block_w // 2
                y_start = p1[1] + block_h
                y_end = p2[1]
                draw.line([(x_mid, y_start), (x_mid, y_end)], fill=(51, 65, 85), width=2)
                pulse_t = (f_idx / num_frames + c_idx * 0.2) % 1.0
                py = int(y_start + (y_end - y_start) * pulse_t)
                draw.ellipse([x_mid - 4, py - 4, x_mid + 4, py + 4], fill=(96, 165, 250))
            else:  # Left arrow
                x_start = p1[0]
                y_mid = p1[1] + block_h // 2
                x_end = p2[0] + block_w
                draw.line([(x_start, y_mid), (x_end, y_mid)], fill=(51, 65, 85), width=2)
                pulse_t = (f_idx / num_frames + c_idx * 0.2) % 1.0
                px = int(x_start - (x_start - x_end) * pulse_t)
                draw.ellipse([px - 4, y_mid - 4, px + 4, y_mid + 4], fill=(96, 165, 250))

        # Draw stage cards
        for idx, (title, desc, color) in enumerate(stages):
            bx, by = positions[idx]
            
            # Highlight border on pulse
            pulse_active = (f_idx % 6) == idx
            border_col = color if pulse_active else (51, 65, 85)
            
            draw.rounded_rectangle([bx, by, bx + block_w, by + block_h], radius=10, fill=(17, 24, 39, 240), outline=border_col, width=2 if pulse_active else 1)
            
            # Color pip
            draw.ellipse([bx + 14, by + 18, bx + 24, by + 28], fill=color)
            draw.text((bx + 32, by + 23), f"STAGE 0{idx+1}", font=get_font(10, bold=True), fill=color, anchor="lm")
            
            draw.text((bx + 16, by + 48), title, font=get_font(14, bold=True), fill=(255, 255, 255), anchor="lm")
            draw.text((bx + 16, by + 72), desc, font=get_font(11, bold=False), fill=(148, 163, 184), anchor="lm")

        frames.append(img.convert("RGB"))

    frames[0].save(
        str(gif_path),
        save_all=True,
        append_images=frames[1:],
        duration=65,
        loop=0,
        optimize=True
    )
    print(f"SUCCESS: Architecture GIF saved at {gif_path}")

def build_quickstart_gif():
    """Generates an animated terminal recording GIF for cloning and launching (800x480)."""
    print("4. Generating animated quickstart terminal GIF...")
    gif_path = DEMO_DIR / "quickstart.gif"

    terminal_lines = [
        ("$ git clone https://github.com/muditagrawal-alt/Smart-Video-Clipping-Tool.git", "Cloning into 'Smart-Video-Clipping-Tool'... done."),
        ("$ cd Smart-Video-Clipping-Tool", ""),
        ("$ python3 -m venv .venv && source .venv/bin/activate", "(venv) active"),
        ("$ pip install -r requirements.txt", "Successfully installed Jinja2 ultralytics opencv-python torch..."),
        ("$ python app.py", "Sliver running on http://127.0.0.1:8000 (Engine Ready)")
    ]

    frames = []
    displayed_text = []

    for cmd, output in terminal_lines:
        # Type the command character by character
        for c_idx in range(1, len(cmd) + 1, 3):
            partial_cmd = cmd[:c_idx] + " █"
            img = render_terminal_frame(displayed_text + [partial_cmd])
            frames.append(img)

        displayed_text.append(cmd)
        if output:
            displayed_text.append(f"  {output}")
            img = render_terminal_frame(displayed_text)
            for _ in range(4):  # Pause on output
                frames.append(img)

    # Final hold
    final_img = render_terminal_frame(displayed_text + ["$ █"])
    for _ in range(15):
        frames.append(final_img)

    frames[0].save(
        str(gif_path),
        save_all=True,
        append_images=frames[1:],
        duration=70,
        loop=0,
        optimize=True
    )
    print(f"SUCCESS: Quickstart GIF saved at {gif_path}")

def render_terminal_frame(lines: list[str]) -> Image.Image:
    w, h = 840, 480
    img = Image.new("RGB", (w, h), (10, 14, 23))
    draw = ImageDraw.Draw(img)

    # Window Chrome
    draw.rounded_rectangle([15, 15, w - 15, h - 15], radius=12, fill=(13, 17, 23), outline=(48, 54, 61), width=1)
    
    # Title bar
    draw.rounded_rectangle([15, 15, w - 15, 52], radius=12, fill=(22, 27, 34))
    draw.rectangle([15, 45, w - 15, 52], fill=(22, 27, 34))
    draw.line([(15, 52), (w - 15, 52)], fill=(48, 54, 61), width=1)

    # Window dots
    draw.ellipse([32, 28, 44, 40], fill=(239, 68, 68))    # Close
    draw.ellipse([52, 28, 64, 40], fill=(234, 179, 8))   # Min
    draw.ellipse([72, 28, 84, 40], fill=(34, 197, 94))   # Max
    draw.text((w // 2, 34), "terminal — bash", font=get_font(12, bold=True), fill=(139, 148, 158), anchor="mm")

    # Content
    y = 75
    font = get_font(13, bold=False)
    for line in lines[-14:]:
        if line.startswith("$"):
            draw.text((40, y), line, font=font, fill=(56, 189, 248))
        elif "http://" in line or "Ready" in line:
            draw.text((40, y), line, font=font, fill=(74, 222, 128))
        else:
            draw.text((40, y), line, font=font, fill=(156, 163, 175))
        y += 24

    return img

if __name__ == "__main__":
    print("=== Generating Production Demo Assets ===")
    build_architecture_gif()
    build_quickstart_gif()
    build_demo_video()
    print("=== All Assets Created Successfully ===")
