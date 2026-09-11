import base64
import ipaddress
import json
import os
import shutil
import socket
import subprocess
import tempfile
from pathlib import Path
from urllib.parse import urlparse

import requests
import runpod

REAL_ESRGAN_DIR = Path(os.getenv("REAL_ESRGAN_DIR", "/app/Real-ESRGAN"))
MAX_DOWNLOAD_BYTES = int(os.getenv("MAX_DOWNLOAD_BYTES", str(2 * 1024 * 1024 * 1024)))  # 2 GiB
MAX_BASE64_OUTPUT_BYTES = int(os.getenv("MAX_BASE64_OUTPUT_BYTES", str(20 * 1024 * 1024)))  # 20 MiB
REQUEST_TIMEOUT = int(os.getenv("REQUEST_TIMEOUT", "120"))

ALLOWED_MODELS = {
    "RealESRGAN_x2plus",
    "RealESRGAN_x4plus",
    "RealESRNet_x4plus",
    "RealESRGAN_x4plus_anime_6B",
    "realesr-animevideov3",
    "realesr-general-x4v3",
}

TARGETS = {
    "720p": (1280, 720),
    "1080p": (1920, 1080),
    "2160p": (3840, 2160),
}


def run_cmd(cmd, cwd=None):
    proc = subprocess.run(
        cmd,
        cwd=cwd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"Command failed ({proc.returncode}): {' '.join(map(str, cmd))}\n{proc.stdout[-8000:]}")
    return proc.stdout


def _reject_private_url(url: str):
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        raise ValueError("video_url must use http:// or https://")
    if not parsed.hostname:
        raise ValueError("video_url is missing a hostname")

    # Basic SSRF protection for a public-facing worker.
    try:
        infos = socket.getaddrinfo(parsed.hostname, None)
        for info in infos:
            ip = ipaddress.ip_address(info[4][0])
            if (
                ip.is_private
                or ip.is_loopback
                or ip.is_link_local
                or ip.is_multicast
                or ip.is_reserved
                or ip.is_unspecified
            ):
                raise ValueError("video_url may not resolve to a private/local network address")
    except socket.gaierror as exc:
        raise ValueError(f"Could not resolve video_url host: {exc}") from exc


def download_file(url: str, dest: Path):
    _reject_private_url(url)
    with requests.get(url, stream=True, timeout=REQUEST_TIMEOUT, allow_redirects=True) as r:
        r.raise_for_status()
        total = 0
        with dest.open("wb") as f:
            for chunk in r.iter_content(chunk_size=1024 * 1024):
                if not chunk:
                    continue
                total += len(chunk)
                if total > MAX_DOWNLOAD_BYTES:
                    raise ValueError(f"Input video exceeds {MAX_DOWNLOAD_BYTES} bytes")
                f.write(chunk)
    return total


def probe(path: Path):
    out = run_cmd([
        "ffprobe", "-v", "error", "-show_entries",
        "format=duration,size:stream=index,codec_type,codec_name,width,height,avg_frame_rate",
        "-of", "json", str(path)
    ])
    return json.loads(out)


def post_resize(src: Path, dst: Path, width: int, height: int):
    # Preserve aspect ratio and pad only if necessary; do not stretch faces/geometry.
    vf = (
        f"scale={width}:{height}:force_original_aspect_ratio=decrease," 
        f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2"
    )
    run_cmd([
        "ffmpeg", "-y", "-i", str(src),
        "-vf", vf,
        "-c:v", "libx264", "-preset", "medium", "-crf", "18",
        "-pix_fmt", "yuv420p", "-c:a", "copy", "-movflags", "+faststart",
        str(dst),
    ])


def upload_put(url: str, path: Path):
    # output_upload_url should normally be a presigned HTTPS PUT URL from your storage provider.
    parsed = urlparse(url)
    if parsed.scheme != "https":
        raise ValueError("output_upload_url must use https://")
    with path.open("rb") as f:
        r = requests.put(
            url,
            data=f,
            headers={"Content-Type": "video/mp4"},
            timeout=REQUEST_TIMEOUT,
            allow_redirects=True,
        )
    r.raise_for_status()
    return {"status_code": r.status_code}


def handler(job):
    inp = job.get("input") or {}

    video_url = inp.get("video_url")
    if not video_url:
        return {"error": "Missing required input.video_url"}

    model = inp.get("model", "RealESRGAN_x2plus")
    if model not in ALLOWED_MODELS:
        return {"error": f"Unsupported model: {model}", "allowed_models": sorted(ALLOWED_MODELS)}

    try:
        scale = float(inp.get("scale", 2))
    except (TypeError, ValueError):
        return {"error": "scale must be a number"}
    if not (1.0 <= scale <= 4.0):
        return {"error": "scale must be between 1.0 and 4.0"}

    face_enhance = bool(inp.get("face_enhance", False))
    tile = int(inp.get("tile", 0) or 0)
    if tile < 0:
        return {"error": "tile must be 0 or a positive integer"}

    num_process_per_gpu = int(inp.get("num_process_per_gpu", 1) or 1)
    if num_process_per_gpu < 1 or num_process_per_gpu > 4:
        return {"error": "num_process_per_gpu must be between 1 and 4"}

    target_resolution = inp.get("target_resolution")
    target_width = inp.get("target_width")
    target_height = inp.get("target_height")

    if target_resolution:
        if target_resolution not in TARGETS:
            return {"error": f"target_resolution must be one of: {', '.join(TARGETS)}"}
        target_width, target_height = TARGETS[target_resolution]
    elif target_width is not None or target_height is not None:
        if target_width is None or target_height is None:
            return {"error": "target_width and target_height must be supplied together"}
        target_width, target_height = int(target_width), int(target_height)
        if target_width < 64 or target_height < 64:
            return {"error": "target dimensions are too small"}

    output_upload_url = inp.get("output_upload_url")

    workdir = Path(tempfile.mkdtemp(prefix="kinovi_upscale_"))
    try:
        input_path = workdir / "input.mp4"
        output_dir = workdir / "realesrgan_output"
        output_dir.mkdir(parents=True, exist_ok=True)

        input_bytes = download_file(video_url, input_path)
        before = probe(input_path)

        cmd = [
            "python", "inference_realesrgan_video.py",
            "-i", str(input_path),
            "-n", model,
            "-o", str(output_dir),
            "-s", str(scale),
            "--suffix", "upscaled",
            "--num_process_per_gpu", str(num_process_per_gpu),
        ]
        if tile:
            cmd += ["--tile", str(tile)]
        if face_enhance:
            cmd.append("--face_enhance")

        run_cmd(cmd, cwd=REAL_ESRGAN_DIR)

        produced = output_dir / "input_upscaled.mp4"
        if not produced.exists():
            candidates = list(output_dir.glob("*.mp4"))
            if not candidates:
                raise RuntimeError("Real-ESRGAN finished but no MP4 output was found")
            produced = candidates[0]

        final_path = workdir / "final.mp4"
        if target_width and target_height:
            post_resize(produced, final_path, int(target_width), int(target_height))
        else:
            shutil.copy2(produced, final_path)

        after = probe(final_path)
        output_bytes = final_path.stat().st_size

        result = {
            "ok": True,
            "model": model,
            "scale": scale,
            "face_enhance": face_enhance,
            "input_bytes": input_bytes,
            "output_bytes": output_bytes,
            "input_probe": before,
            "output_probe": after,
        }

        if output_upload_url:
            upload_put(output_upload_url, final_path)
            result["delivery"] = "uploaded"
            # Do not echo a presigned URL back; it may contain credentials/signatures.
            return result

        if output_bytes > MAX_BASE64_OUTPUT_BYTES:
            return {
                **result,
                "ok": False,
                "error": (
                    f"Output is {output_bytes} bytes, larger than this worker's base64 return limit "
                    f"({MAX_BASE64_OUTPUT_BYTES} bytes). Supply input.output_upload_url as a presigned HTTPS PUT URL."
                ),
            }

        result["delivery"] = "base64"
        result["video_base64"] = base64.b64encode(final_path.read_bytes()).decode("ascii")
        return result

    except Exception as exc:
        return {"ok": False, "error": str(exc)}
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


runpod.serverless.start({"handler": handler})
