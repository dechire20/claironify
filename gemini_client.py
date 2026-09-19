import json
import re
import time
from google.genai import types

from config import get_gemini_client, MODEL


def parse_json(text):
    text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.MULTILINE)
    text = re.sub(r"\s*```\s*$",        "", text, flags=re.MULTILINE)
    m = re.search(r"\{.*\}", text, re.DOTALL)
    return json.loads(m.group() if m else text)


def gemini_call(prompt, video_file=None):
    parts = []
    if video_file:
        parts.append(types.Part(file_data=types.FileData(
            file_uri=video_file.uri, mime_type="video/mp4"
        )))
    parts.append(types.Part(text=prompt))
    resp = get_gemini_client().models.generate_content(
        model=MODEL,
        contents=[types.Content(parts=parts)],
    )
    return resp.text.strip()


def upload_to_gemini(path):
    client = get_gemini_client()
    vf = client.files.upload(
        file=path,
        config=types.UploadFileConfig(mime_type="video/mp4")
    )
    while vf.state.name == "PROCESSING":
        time.sleep(1)
        vf = client.files.get(name=vf.name)
    if vf.state.name == "FAILED":
        raise RuntimeError("Gemini file processing failed")
    return vf
