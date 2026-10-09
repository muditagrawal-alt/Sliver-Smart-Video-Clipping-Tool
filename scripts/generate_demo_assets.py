"""
scripts/generate_demo_assets.py
Generates:
1. assets/demo/sliver_project_demo.mp4 (720p master demo video with floating subtitles, title card, 3s execution cut, output recap, stock background music, using the NEW dark-mode UI)
2. assets/demo/architecture.gif (Animated pipeline dataflow architecture diagram)
3. assets/demo/quickstart.gif (Terminal walkthrough showing clone, setup, and launch)
"""

import math
import os
import subprocess
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont
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
        fill=(13, 17, 26, 225),          # Dark translucent slate
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
        for r in range(420, 40, -30):
            alpha = int(18 * (1.0 - r / 420))
            draw.ellipse(
                [(640 - r, 340 - r), (640 + r, 340 + r)],
                fill=(45, 95, 220, alpha)
            )

        # Title Card Content
        font_eyebrow = get_font(15, bold=True)
        font_title = get_font(42, bold=True)
        font_author = get_font(24, bold=True)

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

        # Subtitle
        sub_text = "Sliver: A Smart Video Clipping Tool — Engineered by Mudit Agrawal"
        draw_floating_subtitle(img, sub_text, font_size=18)

        # Fade in first 15 frames, fade out last 15 frames
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

def render_ui_showcase(screenshot_path: Path, subtitle: str, duration_sec: float = 3.5) -> list[Image.Image]:
    """Renders high-res UI overview with smooth motion and floating subtitle."""
    total_frames = int(duration_sec * 30)
    frames = []

    src_img = Image.open(screenshot_path).convert("RGB")
    sw, sh = src_img.size

    for i in range(total_frames):
        canvas = Image.new("RGB", (1280, 720), (10, 14, 23))
        scale = 1280 / sw
        scaled_h = int(sh * scale)
        scaled = src_img.resize((1280, scaled_h), Image.Resampling.LANCZOS)

        # Subtle slow pan
        max_scroll = max(0, scaled_h - 720)
        progress = i / max(1, total_frames - 1)
        progress = 0.5 - 0.5 * math.cos(progress * math.pi)
        scroll_y = int(progress * min(max_scroll, 120))

        crop = scaled.crop((0, scroll_y, 1280, min(scaled_h, scroll_y + 720)))
        canvas.paste(crop, (0, 0))

        draw_floating_subtitle(canvas, subtitle, font_size=18)
        frames.append(canvas)

    return frames

def render_execution_clip(duration_sec: float = 3.0) -> list[Image.Image]:
    """
    Renders the first 3 seconds of execution in the NEW Obsidian UI.
    Shows the workspace with real-time progressing checklist and status percentages.
    """
    total_frames = int(duration_sec * 30)
    frames = []

    workspace_img = Image.open(ASSETS_DIR / "screenshots" / "workspace.png").convert("RGB")
    sw, sh = workspace_img.size
    scale = 1280 / sw
    scaled = workspace_img.resize((1280, int(sh * scale)), Image.Resampling.LANCZOS)
    base_frame = scaled.crop((0, 30, 1280, 750))

    sub_text = "First 3s of execution: Multi-stage detection, face tracking & salience scoring"

    # In scaled image (crop y: 30..750):
    # Progress box is at x: 686..1138, y in crop: (248-30)..(445-30) = 218..415
    # Video player area is below: y in crop: 435..688
    ox, oy, ow, oh = 686, 218, 452, 195

    for i in range(total_frames):
        canvas = base_frame.copy()
        draw = ImageDraw.Draw(canvas, "RGBA")

        # Simulate dynamic progress bar animating from 6% to 58%
        pct = 6 + int((i / total_frames) * 52)
        stage_names = [
            "1. Ingestion & frame extraction",
            "2. Object & face detection (YOLO11m)",
            "3. Scene scoring & context selection",
            "4. Audio synchronization",
            "5. Video encoding & export"
        ]

        active_idx = 0 if pct < 18 else (1 if pct < 45 else 2)

        # Clear existing progress card area with dark surface
        draw.rounded_rectangle([ox, oy, ox + ow, oy + oh], radius=10, fill=(17, 24, 39, 255), outline=(59, 130, 246, 130), width=1)
        
        draw.text((ox + 18, oy + 14), "JOB STATUS", font=get_font(11, bold=True), fill=(148, 163, 184))
        draw.text((ox + ow - 55, oy + 14), f"{pct}%", font=get_font(16, bold=True), fill=(96, 165, 250))
        
        status_msg = "Ingesting video frames..." if pct < 18 else ("Detecting faces and people..." if pct < 45 else "Evaluating scene salience...")
        draw.text((ox + 18, oy + 36), status_msg, font=get_font(14, bold=True), fill=(255, 255, 255))

        # Progress bar track & fill
        draw.rounded_rectangle([ox + 18, oy + 65, ox + ow - 18, oy + 73], radius=4, fill=(31, 41, 55))
        fill_w = int((ow - 36) * (pct / 100.0))
        if fill_w > 0:
            draw.rounded_rectangle([ox + 18, oy + 65, ox + 18 + fill_w, oy + 73], radius=4, fill=(37, 99, 235))

        # Checklist stages
        for s_idx, s_text in enumerate(stage_names[:3]):
            sy = oy + 90 + s_idx * 30
            is_done = s_idx < active_idx
            is_active = s_idx == active_idx
            
            icon_color = (34, 197, 94) if is_done else ((59, 130, 246) if is_active else (75, 85, 99))
            draw.ellipse([ox + 20, sy + 3, ox + 30, sy + 13], fill=icon_color)
            txt_color = (241, 245, 249) if (is_done or is_active) else (156, 163, 175)
            draw.text((ox + 38, sy), s_text, font=get_font(12, bold=is_active), fill=txt_color)

        # Draw processing indicator over video player area during execution
        px, py, pw, ph = 686, 435, 452, 254
        draw.rounded_rectangle([px, py, px + pw, py + ph], radius=10, fill=(11, 15, 23, 245), outline=(37, 99, 235, 80))
        pulse_alpha = int(180 + 70 * math.sin(i * 0.4))
        draw.text((px + pw // 2, py + ph // 2 - 10), "⚡ Analyzing Model Streams...", font=get_font(14, bold=True), fill=(96, 165, 250, pulse_alpha), anchor="mm")
        draw.text((px + pw // 2, py + ph // 2 + 18), "YOLO11m + YOLOv8-Face Active", font=get_font(11, bold=False), fill=(148, 163, 184), anchor="mm")

        draw_floating_subtitle(canvas, sub_text, font_size=18)
        frames.append(canvas)

    return frames

def render_output_playback(video_path: Path, duration_sec: float = 6.0) -> list[Image.Image]:
    """
    Renders output playback in the NEW Obsidian UI:
    Embeds real frames from the generated highlight clip right into the new UI player!
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
    base_frame = scaled.crop((0, 30, 1280, 750))

    # Exact video player coordinates in the cropped new UI
    target_x, target_y = 686, 435
    target_w, target_h = 452, 254

    for i in range(total_frames):
        ret, v_frame = cap.read()
        if not ret:
            cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
            ret, v_frame = cap.read()

        canvas = base_frame.copy()

        if ret and v_frame is not None:
            v_rgb = cv2.cvtColor(v_frame, cv2.COLOR_BGR2RGB)
            v_pil = Image.fromarray(v_rgb).resize((target_w, target_h), Image.Resampling.LANCZOS)
            canvas.paste(v_pil, (target_x, target_y))

        draw = ImageDraw.Draw(canvas, "RGBA")
        # Video badge overlay
        draw.rounded_rectangle([target_x + 12, target_y + 12, target_x + 130, target_y + 36], radius=6, fill=(15, 23, 42, 220))
        draw.text((target_x + 71, target_y + 24), "15s Highlight Clip", font=get_font(11, bold=True), fill=(255, 255, 255), anchor="mm")

        draw_floating_subtitle(canvas, sub_text, font_size=18)
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
        draw.ellipse([(640 - 250, 320 - 250), (640 + 250, 320 + 250)], fill=(37, 99, 235, 18))

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
    print("1. Assembling video scenes with NEW UI screenshots...")
    all_frames = []

    # Scene 1: Title Card (3.5s)
    all_frames.extend(render_title_card())

    # Scene 2: Landing Page Overview with NEW Obsidian UI (3.5s)
    all_frames.extend(render_ui_showcase(
        ASSETS_DIR / "screenshots" / "home.png",
        "Local AI video summarizer engineered for high-impact scene extraction.",
        duration_sec=3.5
    ))

    # Scene 3: Workspace Parameter Configuration with NEW Obsidian UI (3.5s)
    all_frames.extend(render_ui_showcase(
        ASSETS_DIR / "screenshots" / "workspace.png",
        "Configurable duration targets and semantic zero-shot guidance via CLIP.",
        duration_sec=3.5
    ))

    # Scene 4: First 3s of Execution (3.0s)
    all_frames.extend(render_execution_clip(duration_sec=3.0))

    # Scene 5: Output Playback with Real Footage (6.0s)
    all_frames.extend(render_output_playback(
        ASSETS_DIR / "demo" / "output.mp4",
        duration_sec=6.0
    ))

    # Scene 6: Video Library / Profile with NEW Obsidian UI (3.0s)
    all_frames.extend(render_ui_showcase(
        ASSETS_DIR / "screenshots" / "profile.png",
        "Export library: Instant MP4 downloads & local SQLite persistence.",
        duration_sec=3.0
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
        "-preset", "medium",
        "-crf", "22",
        "-pix_fmt", "yuv420p",
        "-c:a", "aac",
        "-b:a", "192k",
        "-shortest",
        "-movflags", "+faststart",
        str(final_video_path)
    ]

    subprocess.run(cmd, check=True)
    if raw_video_path.exists():
        raw_video_path.unlink()

    print(f"SUCCESS: Master demo video rendered at {final_video_path} ({final_video_path.stat().st_size // 1024} KB)")

def build_architecture_gif():
    """Generates an animated GIF demonstrating the pipeline architecture flow."""
    print("3. Generating animated architecture GIF...")
    gif_path = DEMO_DIR / "architecture.gif"

    stages = [
        ("Input Decode", "OpenCV Decoder · 25-60 FPS", (59, 130, 246)),
        ("Visual AI", "YOLO11m + YOLOv8-Face", (168, 85, 247)),
        ("CLIP Zero-Shot", "Cosine Similarity Matrix", (236, 72, 153)),
        ("Context Clustering", "Temporal Buffer & Knapsack", (245, 158, 11)),
        ("Audio Synchronization", "FFmpeg Lossless AAC Concat", (16, 185, 129)),
        ("Production MP4", "H.264 Web-Ready Output", (6, 182, 212))
    ]

    frames = []
    width, height = 900, 360

    for step in range(30):
        img = Image.new("RGBA", (width, height), (10, 14, 23, 255))
        draw = ImageDraw.Draw(img, "RGBA")

        # Header
        draw.text((450, 40), "SLIVER PIPELINE DATAFLOW ARCHITECTURE", font=get_font(18, bold=True), fill=(255, 255, 255), anchor="mm")
        draw.text((450, 68), "Multi-Model Salience Engine · Dynamic Weight Allocation", font=get_font(12, bold=False), fill=(148, 163, 184), anchor="mm")

        box_w, box_h = 130, 130
        spacing = 16
        start_x = (width - (len(stages) * box_w + (len(stages) - 1) * spacing)) // 2

        for idx, (title, desc, color) in enumerate(stages):
            bx = start_x + idx * (box_w + spacing)
            by = 130

            is_active = (step % len(stages)) == idx
            pulse_radius = 8 if is_active else 4
            border_col = color if is_active else (255, 255, 255, 30)

            # Draw connector arrow to next box
            if idx < len(stages) - 1:
                ax0 = bx + box_w
                ax1 = ax0 + spacing
                ay = by + box_h // 2
                draw.line([(ax0, ay), (ax1, ay)], fill=(75, 85, 99, 150), width=2)
                
                # Moving particle
                particle_offset = ((step * 4 + idx * 8) % spacing)
                draw.ellipse([(ax0 + particle_offset - 2, ay - 2), (ax0 + particle_offset + 2, ay + 2)], fill=(96, 165, 250, 220))

            bg_alpha = 70 if is_active else 25
            draw.rounded_rectangle([bx, by, bx + box_w, by + box_h], radius=10, fill=(*color[:3], bg_alpha), outline=border_col, width=2 if is_active else 1)

            draw.ellipse([bx + 14, by + 18, bx + 22, by + 26], fill=color)
            draw.text((bx + 30, by + 22), f"STAGE 0{idx+1}", font=get_font(9, bold=True), fill=color, anchor="lm")
            
            draw.text((bx + 12, by + 52), title, font=get_font(12, bold=True), fill=(255, 255, 255), anchor="lm")
            
            words = desc.split(" · ")
            draw.text((bx + 12, by + 78), words[0], font=get_font(10, bold=False), fill=(203, 213, 225), anchor="lm")
            if len(words) > 1:
                draw.text((bx + 12, by + 94), words[1], font=get_font(9, bold=False), fill=(148, 163, 184), anchor="lm")

        frames.append(img.convert("RGB"))

    frames[0].save(
        str(gif_path),
        save_all=True,
        append_images=frames[1:],
        duration=70,
        loop=0,
        optimize=True
    )
    print(f"SUCCESS: Architecture GIF saved at {gif_path}")

def render_terminal_frame(lines: list[str]) -> Image.Image:
    width, height = 800, 480
    img = Image.new("RGBA", (width, height), (13, 17, 23, 255))
    draw = ImageDraw.Draw(img, "RGBA")

    # Title bar
    draw.rounded_rectangle([0, 0, width, height], radius=12, fill=(13, 17, 23, 255), outline=(48, 54, 61, 200), width=1)
    draw.rounded_rectangle([0, 0, width, 40], radius=12, fill=(22, 27, 34, 255))
    draw.rectangle([0, 24, width, 40], fill=(22, 27, 34, 255))
    draw.line([(0, 40), (width, 40)], fill=(48, 54, 61, 255), width=1)

    # Window traffic lights
    draw.ellipse([(16, 14), (28, 26)], fill=(255, 95, 86))
    draw.ellipse([(36, 14), (48, 26)], fill=(255, 189, 46))
    draw.ellipse([(56, 14), (68, 26)], fill=(39, 201, 63))

    draw.text((width // 2, 20), "bash — Sliver Quickstart", font=get_font(12, bold=True), fill=(139, 148, 158), anchor="mm")

    # Lines
    font_mono = get_font(13, bold=False)
    y = 60
    for line in lines[-14:]:
        if line.startswith("$ "):
            draw.text((24, y), "$ ", font=get_font(13, bold=True), fill=(88, 166, 255))
            draw.text((42, y), line[2:], font=font_mono, fill=(240, 246, 252))
        elif "(venv)" in line:
            draw.text((24, y), line, font=font_mono, fill=(126, 231, 135))
        elif "Successfully installed" in line:
            draw.text((24, y), line, font=font_mono, fill=(210, 153, 34))
        elif "Sliver running" in line:
            draw.text((24, y), line, font=get_font(13, bold=True), fill=(88, 166, 255))
        else:
            draw.text((24, y), line, font=font_mono, fill=(139, 148, 158))
        y += 26

    return img.convert("RGB")

def build_quickstart_gif():
    """Generates an animated terminal recording GIF for cloning and launching (800x480)."""
    print("4. Generating animated quickstart terminal GIF...")
    gif_path = DEMO_DIR / "quickstart.gif"

    terminal_lines = [
        ("$ git clone https://github.com/muditagrawal-alt/Sliver-Smart-Video-Clipping-Tool.git", "Cloning into 'Sliver-Smart-Video-Clipping-Tool'... done."),
        ("$ cd Sliver-Smart-Video-Clipping-Tool", ""),
        ("$ python3 -m venv .venv && source .venv/bin/activate", "(venv) active"),
        ("$ pip install -r requirements.txt", "Successfully installed Jinja2 ultralytics opencv-python torch..."),
        ("$ python app.py", "Sliver running on http://127.0.0.1:8000 (Engine Ready)")
    ]

    frames = []
    displayed_text = []

    for cmd, output in terminal_lines:
        for c_idx in range(1, len(cmd) + 1, 3):
            partial_cmd = cmd[:c_idx] + " █"
            img = render_terminal_frame(displayed_text + [partial_cmd])
            frames.append(img)

        displayed_text.append(cmd)
        if output:
            displayed_text.append(f"  {output}")
            img = render_terminal_frame(displayed_text)
            for _ in range(4):
                frames.append(img)

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

def main():
    build_demo_video()
    build_architecture_gif()
    build_quickstart_gif()
    print("\nAll demo visual assets regenerated successfully!")

if __name__ == "__main__":
    main()
