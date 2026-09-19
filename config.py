import os
from google import genai

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY") or os.environ.get("GEMNI_API_KEY")
SERPAPI_KEY    = os.environ.get("SERPAPI_KEY", "")
MODEL          = "gemini-2.5-flash"
MAX_DURATION   = 180
TRIM_TO        = 90

NEGATIVE_VERDICTS = {"POSSIBLY MISLEADING", "LIKELY FAKE"}

VERDICT_CONFIDENCE_CAPS = {
    "POSSIBLY MISLEADING": 55,
    "NEEDS CONTEXT":       65,
    "CANNOT DETERMINE":    55,
    "LIKELY AUTHENTIC":    88,
    "LIKELY FAKE":         88,
}

_gemini_client = None

def get_gemini_client():
    global _gemini_client
    if _gemini_client is None:
        if not GEMINI_API_KEY:
            raise ValueError("GEMINI_API_KEY not set")
        _gemini_client = genai.Client(api_key=GEMINI_API_KEY)
    return _gemini_client
