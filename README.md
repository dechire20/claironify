# claironly

A fact checker for social media videos.

Paste a link from TikTok, Instagram, YouTube, X/Twitter, or Facebook. 
Claironly tells you whether the video is authentic, misleading, or fake, 
with the reasoning and live sources behind the verdict.

Note: this is the original version. It has been superseded by claironlyv2, 
which is faster, lighter, and uses fewer external services. This repo is 
kept for reference.

## What it does

1. Downloads the video from the link you paste.
2. Watches it and separates the real event from any edits added on top 
   (meme text, captions, reaction graphics, and so on).
3. Pulls out the key claims being made.
4. Forms a verdict with a confidence score.
5. Searches live sources (Reddit and news) to cross-check the verdict.
6. Corrects itself if the live sources disagree with its first pass.

## What you get back

- Verdict — one of:
  - Likely Authentic — real footage, no fabrication
  - Needs Context — real footage, but the framing misleads
  - Possibly Misleading — presentation makes false factual claims
  - Likely Fake — the underlying event itself is fabricated or AI-generated
  - Cannot Determine — not enough evidence
- Confidence — how sure the system is (capped per verdict so it can't 
  overstate certainty)
- Summary — 2 to 3 sentences in plain language
- Key claims — what the video is actually asserting
- Red flags — specific concerns found
- Verification points — what you'd check to confirm yourself
- Sources — Reddit discussions and news articles fetched live
- Recommendation — balanced advice for the viewer

## How it works

1. Download the video. Clips only, under 3 minutes.
2. First pass: an AI watches the video and writes a detailed observation, 
   separating the original event from any editorial overlay.
3. Verdict pass: the AI weighs the signals and issues a verdict. Strict 
   rules stop it from mistaking meme framing for deepfake manipulation.
4. Challenge pass: if the verdict is negative, a second AI call 
   challenges it to reduce false positives.
5. Live sources: Reddit communities and a news search are queried for 
   real-world discussion of the claims.
6. Correction pass: the verdict is re-checked against the live sources. 
   If sources contradict the AI's prior knowledge, sources win.

## Limits

- Videos only. TikTok photo slideshows, image posts, and text-only 
  posts aren't supported.
- Under 3 minutes. Longer clips are rejected, and only the first 
  90 seconds are analysed.
- Public content only. Private or removed videos can't be fetched.
- Not a replacement for professional fact-checkers. A fast first pass.

## Supported platforms

TikTok, Instagram, YouTube, X/Twitter, Facebook, and most public 
video URLs.

## Speed

- Short clips: roughly 30 to 90 seconds end-to-end.
- Longer clips and heavier source searches take longer.
- Slower than claironlyv2 because it runs more separate AI calls and 
  relies on older search paths.

## Setup

Environment variables:

| Variable | Required | Purpose |
|---|---|---|
| GEMINI_API_KEY | yes | Powers the video analysis and verdicts |
| SERPAPI_KEY | no | News search. Falls back to DuckDuckGo if missing |
| PORT | no | Server port. Defaults to 8080 |

Also requires ffmpeg installed on the host, used to trim and compress 
video before analysis.

Run:

    pip install flask flask-cors google-genai yt-dlp
    export GEMINI_API_KEY=your_key_here
    python app.py

Then open http://localhost:8080.

## API

POST /upload — submit a video

    { "url": "https://...", "context": "optional note" }

Returns { "task_id": "..." }.

GET /status/<task_id> — poll progress and results

Returns the job's current status (queued, downloading, analyzing, 
partial, done, error) plus all fields above as they become available.

## Notes on accuracy

- The system is deliberately cautious. Verdicts like Possibly Misleading 
  and Likely Fake are blocked unless actual manipulation of the 
  underlying footage is observed. Editorial overlays alone don't count.
- Recognised news organisations are treated as strong authenticity 
  signals unless specific tampering is visible.
- Live sources override the model's training data. If a source confirms 
  something the model thought was false, the source wins.
