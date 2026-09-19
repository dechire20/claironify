import os
import shutil
import tempfile

from jobs import job_set, make_job, JOBS, JOBS_LOCK
from video import download_video, trim_video
from gemini_client import upload_to_gemini
from analysis import (
    stage_describe,
    stage_signals_and_verdict,
    stage_challenge,
    stage_source_correction,
)
from sources import fetch_sources
from config import NEGATIVE_VERDICTS, get_gemini_client


def run_pipeline(task_id, video_path, meta):
    tmp_dir    = os.path.dirname(video_path)
    video_path = trim_video(video_path, tmp_dir)

    job_set(task_id, message="Uploading to Gemini...", progress_pct=12)
    vf = upload_to_gemini(video_path)
    job_set(task_id, message="Gemini is watching the video...", progress_pct=22)

    try:
        observation = stage_describe(vf)
    finally:
        try:
            gemini.files.delete(name=vf.name)
        except Exception:
            pass

    job_set(task_id, message="Analysing signals and forming verdict...", progress_pct=58)
    signals, result = stage_signals_and_verdict(observation, meta)

    job_set(
        task_id,
        progress_pct        = 72,
        message             = "Checking verdict...",
        visual_analysis     = result.get("visual_analysis", ""),
        key_claims          = result.get("key_claims", []),
        red_flags           = result.get("red_flags", []),
        verification_points = result.get("verification_points", []),
        recommendation      = result.get("recommendation", ""),
    )

    if result.get("verdict") in NEGATIVE_VERDICTS and result.get("confidence", 0) > 40:
        job_set(task_id, message="Double-checking verdict...", progress_pct=80)
        result = stage_challenge(result, signals)

    job_set(
        task_id,
        status       = "partial",
        message      = "Finding sources...",
        progress_pct = 88,
        verdict      = result.get("verdict"),
        confidence   = result.get("confidence"),
        summary      = result.get("summary"),
    )

    sources = fetch_sources(result.get("key_claims", []) or [], meta.get("title", ""))

    job_set(task_id, message="Cross-checking with live sources...", progress_pct=94)
    result = stage_source_correction(result, sources)

    job_set(
        task_id,
        status         = "done",
        message        = "Done.",
        progress_pct   = 100,
        sources        = sources,
        verdict        = result.get("verdict"),
        confidence     = result.get("confidence"),
        summary        = result.get("summary"),
        red_flags      = result.get("red_flags", []),
        recommendation = result.get("recommendation", ""),
    )


def background_process(task_id, url, context):
    tmp = tempfile.mkdtemp()
    try:
        job_set(task_id, status="downloading", message="Downloading video...", progress_pct=5)
        video_path, meta = download_video(url, tmp)
        meta["user_context"] = context
        job_set(task_id, status="analyzing", message="Video ready...", progress_pct=10, meta=meta)
        run_pipeline(task_id, video_path, meta)
    except ValueError as e:
        job_set(task_id, status="error", error=str(e))
    except Exception as e:
        job_set(task_id, status="error", error=str(e))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
