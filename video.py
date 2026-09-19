def trim_video(path, out_dir):
    try:
        size_mb = os.path.getsize(path) / 1024 / 1024
    except Exception:
        return path

    if size_mb < 5:
        print(f"[Trim] Skipped — source is only {size_mb:.2f}MB", flush=True)
        return path

    out = os.path.join(out_dir, "trimmed.mp4")
    try:
        r = subprocess.run([
            "ffmpeg", "-i", path,
            "-t", str(TRIM_TO),
            "-vf", "fps=0.5",
            "-threads", "1",
            "-c:v", "libx264",
            "-crf", "28",
            "-preset", "ultrafast",
            "-c:a", "aac",
            "-y", out
        ], capture_output=True, timeout=60)
        if r.returncode == 0 and os.path.exists(out):
            orig_mb  = os.path.getsize(path) / 1024 / 1024
            small_mb = os.path.getsize(out)  / 1024 / 1024
            print(f"[Trim] {orig_mb:.1f}MB -> {small_mb:.1f}MB at 0.5fps", flush=True)
            return out
        else:
            print(f"[Trim] ffmpeg rc={r.returncode} stderr={r.stderr[-300:]}", flush=True)
    except Exception as e:
        print(f"[Trim] ffmpeg failed: {e}", flush=True)
    return path
