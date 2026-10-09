"""
audio_utils.py — FFmpeg-backed audio helpers.

FIX: All subprocess calls now suppress ffmpeg's verbose stderr output
     (captured but discarded) so it doesn't flood the server console.
FIX: extract_audio now tries codec-copy first and falls back to AAC
     re-encoding for incompatible source codecs (AC3, EAC3, DTS, …).
FIX: extract_audio accepted a Path object but was internally converting
     it again; signature now accepts str | Path uniformly via _str().
"""

import subprocess
from pathlib import Path
from typing import List, Dict, Union

_PathLike = Union[str, Path]


def _str(p: _PathLike) -> str:
    return Path(p).as_posix()


def _run(cmd: List[str]) -> subprocess.CompletedProcess:
    """Run an ffmpeg/ffprobe command, capturing stderr to avoid console flood."""
    return subprocess.run(
        cmd,
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )


def has_audio(video_path: _PathLike) -> bool:
    """Return True if the file contains at least one audio stream."""
    try:
        import json
        cmd = [
            "ffprobe", "-v", "error",
            "-select_streams", "a",
            "-show_entries", "stream=codec_type",
            "-of", "json",
            _str(video_path),
        ]
        result = subprocess.run(
            cmd,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        data = json.loads(result.stdout)
        return len(data.get("streams", [])) > 0
    except Exception:
        return False


def extract_audio(video_path: _PathLike, audio_path: _PathLike) -> bool:
    """
    Extract the audio stream from *video_path* and write it to *audio_path*
    (.aac).  Returns True on success, False if no audio is present.

    FIX: tries -acodec copy first; if that fails (incompatible codec such as
         AC3/EAC3/DTS), falls back to re-encoding as AAC so the pipeline
         never crashes on unusual source audio.
    """
    if not has_audio(video_path):
        return False

    out = Path(audio_path)
    out.parent.mkdir(parents=True, exist_ok=True)

    # First attempt: copy stream (fast, lossless)
    try:
        _run([
            "ffmpeg", "-y",
            "-i", _str(video_path),
            "-vn",
            "-acodec", "copy",
            _str(out),
        ])
        return True
    except subprocess.CalledProcessError:
        pass

    # Fallback: re-encode to AAC (handles AC3, EAC3, DTS, etc.)
    try:
        _run([
            "ffmpeg", "-y",
            "-i", _str(video_path),
            "-vn",
            "-acodec", "aac",
            "-b:a", "192k",
            _str(out),
        ])
        return True
    except subprocess.CalledProcessError:
        return False


def cut_audio_segments(
    audio_path: _PathLike,
    segments: List[Dict],
    fps: float,
    output_dir: _PathLike,
) -> List[Path]:
    """
    Cut one .aac file per segment.  Returns list of absolute Paths.

    FIX: stderr is now captured so ffmpeg messages don't pollute the console.
    """
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    segment_files: List[Path] = []

    for idx, seg in enumerate(segments):
        start_time = seg["start"] / fps
        duration   = seg["length"] / fps
        out_file   = out_dir / f"audio_segment_{idx}.aac"

        _run([
            "ffmpeg", "-y",
            "-ss", f"{start_time:.3f}",
            "-t",  f"{duration:.3f}",
            "-i",  _str(audio_path),
            "-acodec", "copy",
            _str(out_file),
        ])

        segment_files.append(out_file.resolve())

    return segment_files


def concat_audio(segments: List[Path], output_audio: _PathLike) -> Path:
    """
    Concatenate audio segments into a single .m4a.
    Tries lossless concat first; falls back to AAC re-encoding if bitstream
    packet timestamps are discontinuous.
    """
    out = Path(output_audio)
    out.parent.mkdir(parents=True, exist_ok=True)

    if not segments:
        raise ValueError("No audio segments provided for concatenation.")

    list_file   = out.parent / "audio_list.txt"
    temp_concat = out.parent / "temp_concat.aac"

    with open(list_file, "w") as f:
        for seg in segments:
            f.write(f"file '{seg.resolve().as_posix()}'\n")

    try:
        # Step 1 — concat AAC segments (no re-encode)
        _run([
            "ffmpeg", "-y",
            "-f", "concat",
            "-safe", "0",
            "-i", _str(list_file),
            "-c", "copy",
            _str(temp_concat),
        ])

        # Step 2 — remux to .m4a for clean MP4 muxing
        _run([
            "ffmpeg", "-y",
            "-i", _str(temp_concat),
            "-c", "copy",
            _str(out),
        ])
    except subprocess.CalledProcessError:
        # Fallback: re-encode directly through concat demuxer
        _run([
            "ffmpeg", "-y",
            "-f", "concat",
            "-safe", "0",
            "-i", _str(list_file),
            "-c:a", "aac",
            "-b:a", "192k",
            _str(out),
        ])
    finally:
        list_file.unlink(missing_ok=True)
        temp_concat.unlink(missing_ok=True)

    return out.resolve()


def mux_audio_video(
    video_path: _PathLike,
    audio_path: _PathLike | None,
    output_path: _PathLike,
) -> None:
    """
    Mux video + optional audio into a standards-compliant H.264 MP4.
    Encodes with libx264 (yuv420p) + faststart so output plays across all
    browsers (Chrome, Safari, iOS, Firefox) without format errors.
    Falls back to copy if libx264 is unavailable.
    """
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)

    # Web-friendly H.264 transcoding
    if audio_path and Path(audio_path).exists():
        try:
            _run([
                "ffmpeg", "-y",
                "-i", _str(video_path),
                "-i", _str(audio_path),
                "-c:v", "libx264",
                "-pix_fmt", "yuv420p",
                "-preset", "fast",
                "-crf", "22",
                "-c:a", "aac",
                "-b:a", "192k",
                "-movflags", "+faststart",
                _str(out),
            ])
            return
        except subprocess.CalledProcessError:
            pass

        # Fallback: stream copy
        _run([
            "ffmpeg", "-y",
            "-i", _str(video_path),
            "-i", _str(audio_path),
            "-c:v", "copy",
            "-c:a", "copy",
            "-movflags", "+faststart",
            _str(out),
        ])
    else:
        # Video-only (no audio stream)
        try:
            _run([
                "ffmpeg", "-y",
                "-i", _str(video_path),
                "-c:v", "libx264",
                "-pix_fmt", "yuv420p",
                "-preset", "fast",
                "-crf", "22",
                "-movflags", "+faststart",
                _str(out),
            ])
            return
        except subprocess.CalledProcessError:
            pass

        # Fallback copy
        _run([
            "ffmpeg", "-y",
            "-i", _str(video_path),
            "-c:v", "copy",
            "-movflags", "+faststart",
            _str(out),
        ])
