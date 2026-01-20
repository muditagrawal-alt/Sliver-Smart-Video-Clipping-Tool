import subprocess
from pathlib import Path
from typing import List, Dict


def extract_audio(video_path: str, audio_path: str):
    """
    Extracts the original audio stream from a video without re-encoding.
    """
    audio_path = Path(audio_path)
    audio_path.parent.mkdir(parents=True, exist_ok=True)

    cmd = [
        "ffmpeg",
        "-y",
        "-i", video_path,
        "-vn",
        "-acodec", "copy",
        audio_path.as_posix()
    ]

    subprocess.run(cmd, check=True)


def cut_audio_segments(
    audio_path: str,
    segments: List[Dict],
    fps: float,
    output_dir: Path
) -> List[Path]:
    """
    Cuts audio segments corresponding to selected video frames.
    Returns list of segment file paths.
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    audio_path = Path(audio_path)
    segment_files = []

    for idx, seg in enumerate(segments):
        start_time = seg["start"] / fps
        duration = seg["length"] / fps

        out_file = output_dir / f"audio_segment_{idx}.aac"

        cmd = [
            "ffmpeg",
            "-y",
            "-ss", f"{start_time:.3f}",
            "-t", f"{duration:.3f}",
            "-i", audio_path.as_posix(),
            "-acodec", "copy",
            out_file.as_posix()
        ]

        subprocess.run(cmd, check=True)
        segment_files.append(out_file.resolve())

    return segment_files


def concat_audio(segments: List[Path], output_audio: str) -> Path:
    """
    Concatenates multiple audio segments into one continuous audio file (m4a).
    Returns final audio path.
    """
    output_audio = Path(output_audio)
    output_audio.parent.mkdir(parents=True, exist_ok=True)

    list_file = output_audio.parent / "audio_list.txt"

    # Use absolute paths for concat
    with open(list_file, "w") as f:
        for seg in segments:
            f.write(f"file '{seg.resolve().as_posix()}'\n")

    temp_concat = output_audio.parent / "temp_concat.aac"

    # Step 1: concat without re-encoding
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-f", "concat",
            "-safe", "0",
            "-i", list_file.as_posix(),
            "-c", "copy",
            temp_concat.as_posix()
        ],
        check=True
    )

    # Step 2: convert to m4a for smoother MP4 muxing
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-i", temp_concat.as_posix(),
            "-c", "copy",
            output_audio.as_posix()
        ],
        check=True
    )

    list_file.unlink()
    temp_concat.unlink()
    return output_audio.resolve()


def mux_audio_video(video_path: str, audio_path: str, output_path: str):
    """
    Merges final audio with the generated video clip without re-encoding.
    """
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    cmd = [
        "ffmpeg",
        "-y",
        "-i", video_path,
        "-i", audio_path,
        "-c:v", "copy",
        "-c:a", "copy",
        output_path.as_posix()
    ]

    subprocess.run(cmd, check=True)