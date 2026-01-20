import subprocess

def merge_audio(video_file: str, audio_file: str, output_file: str):
    cmd = [
        "ffmpeg", "-y",
        "-i", video_file,
        "-i", audio_file,
        "-c:v", "copy",
        "-c:a", "aac",
        "-map", "0:v:0?",
        "-map", "1:a:0?",
        "-shortest",
        output_file
    ]
    subprocess.run(cmd, check=True)