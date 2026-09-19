import threading

JOBS      = {}
JOBS_LOCK = threading.Lock()


def make_job():
    return {
        "status":       "queued",
        "message":      "Starting...",
        "progress_pct": 0,
        "error":        None,
        "meta":               None,
        "visual_analysis":    None,
        "key_claims":         None,
        "red_flags":          None,
        "verification_points":None,
        "recommendation":     None,
        "verdict":            None,
        "confidence":         None,
        "summary":            None,
        "sources":            None,
    }


def job_set(task_id, **kw):
    with JOBS_LOCK:
        JOBS[task_id].update(kw)