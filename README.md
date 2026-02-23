# claironify


DeepCheck

Technical Documentation
Internal — Not for Distribution
Version 1.0 | February 2026

1. Overview

DeepCheck is a video fact-checking web application that uses AI vision to assess the authenticity of social media videos. A user submits a URL from TikTok, Instagram, or YouTube. The system downloads the video, sends it to Google Gemini for visual analysis, and returns a structured verdict with supporting sources.

The application runs as a progressive web app (PWA) with no user account required. Analysis completes in approximately 30 to 90 seconds depending on video length and server load.

2. Architecture
2.1 Stack
Component	Technology
Backend	Python 3 / Flask
AI Model	Google Gemini 2.5 Flash (gemini-2.5-flash)
Video Download	yt-dlp
Video Processing	ffmpeg (system binary)
Source Search	Reddit JSON API + DuckDuckGo HTML scrape / SerpAPI (optional)
Frontend	HTML/CSS/JS via Flask templates (PWA)
Deployment	Local: python app.py on port 8080
2.2 Request Lifecycle

Requests are processed asynchronously.

On submission, a UUID task_id is returned immediately.

Frontend polls GET /status/{task_id} every four seconds.

Job fields are published incrementally as each stage completes.

Frontend renders each field as soon as it is non-null.

2.3 Pipeline Stages

Stage 1 — Download & Trim

yt-dlp downloads the video at 360p maximum.

ffmpeg trims it to 90 seconds at 0.5fps to reduce upload size before sending to Gemini.

Stage 2 — Describe

Trimmed video is uploaded to Gemini Files API.

Gemini returns a four-section structured description:

Underlying event

Presentation layer additions

Verbatim speech

Footage quality

Stage 3 — Verdict

A second Gemini call receives the text description only (no video).

Returns JSON with: signals, verdict, confidence, key claims, red flags, verification points, and recommendation.

Stage 4 — Challenge (conditional)

If verdict is POSSIBLY MISLEADING or LIKELY FAKE with confidence >40%, a challenge call evaluates whether negative verdict is justified.

If manipulation evidence is absent, verdict is downgraded.

Stage 5 — Sources

Sources are fetched independently of verdict.

Gemini selects relevant subreddits; Reddit's public JSON API is queried.

DuckDuckGo (or SerpAPI if configured) retrieves news results.

Reddit posts appear first.

2.4 Job State Schema
Field	Description
status	queued | downloading | analyzing | partial | done | error
message	Human-readable progress string for the frontend
progress_pct	Integer 0–100
error	Error string or null
meta	title, uploader, platform, duration, thumbnail, view_count, like_count
visual_analysis	Prose description from Stage 3
key_claims	Array of strings extracted from the video
red_flags	Array of observed issues (empty if none)
verification_points	Array of checkable facts with suggested verification methods
recommendation	Prose advice for the viewer
verdict	One of five verdict strings — see Section 3
confidence	Integer 0–100
summary	2–3 sentence verdict summary
sources	Array of { name, url, description } objects
3. Verdict System

Gemini distinguishes between the underlying event (actual footage) and presentation layer (overlays, captions, music, meme text). Dramatic framing, emotional tone, and controversial subject matter do not constitute manipulation.

Verdict	Description	Confidence
LIKELY AUTHENTIC	Underlying event is real, no fabrication observed	72–88%
NEEDS CONTEXT	Footage is real but presentation layer misleads meaning	Max 65%
POSSIBLY MISLEADING	Presentation layer makes specific false claims	Max 55%
LIKELY FAKE	Underlying event is fabricated, staged, or AI-generated	Max 88%
CANNOT DETERMINE	Insufficient evidence to form verdict	30–55%

Constraint: POSSIBLY MISLEADING and LIKELY FAKE are forbidden when observed_manipulation_evidence is 'none observed'. Prevents false positives caused by editorial framing.

4. Source Retrieval
4.1 Reddit

Gemini selects 3–5 subreddits based on video's key claims/title.

Examples:

Streamer drama → LivestreamFail, dedicated streamer subs

Looksmaxxing → Looksmax, tiktokgossip

Celebrity gossip → Fauxmoi, ONTD

Generic fallbacks used only if no specific community applies.

Posts filtered by relevance: at least one query word in title.

Sorted by relevance, then upvote count.

4.2 News

Gemini generates query anchored to proper nouns. Named persons/brands must appear.

DuckDuckGo HTML endpoint queried; SerpAPI used if SERPAPI_KEY set.

Results prioritized by credible domains (Reuters, AP, BBC, etc.).

4.3 Result Order

Up to 3 Reddit posts first, then up to 3 news results.

Maximum 6 sources total.

5. Configuration
5.1 Environment Variables
Variable	Required	Purpose
GEMINI_API_KEY	Yes	Google Gemini API key (GEMNI_API_KEY accepted as legacy)
SERPAPI_KEY	No	If set, SerpAPI replaces DuckDuckGo for news retrieval
5.2 Constants (app.py)
Constant	Value	Description
MODEL	gemini-2.5-flash	AI model used
MAX_DURATION	180 seconds	Videos exceeding are rejected
TRIM_TO	90 seconds	Videos trimmed before Gemini upload
NEGATIVE_VERDICTS	{POSSIBLY MISLEADING, LIKELY FAKE}	Triggers Stage 4 challenge
6. API Reference
POST /upload

Submit video URL for analysis. Returns task_id for polling.
Request:

{ "url": "https://...", "context": "optional note" }

Response:

{ "task_id": "uuid-string" }
GET /status/{task_id}

Returns full job object. Poll every 3–4 seconds. Render fields as they become non-null. Terminal when status is 'done' or 'error'.

GET /sw.js

Serves PWA service worker for offline shell caching.

7. Supported Platforms
Platform	Notes
TikTok	Video posts only; photo slideshows rejected
Instagram	Reels and video posts
YouTube	Standard videos and Shorts
X / Twitter	Public video posts
Facebook	Public video posts
8. Known Limitations

Gemini has no real-time knowledge; cannot verify if a named person actually made a statement.

Theatrical reactions, dramatic sound effects, heavy post-production may result in NEEDS CONTEXT. Stage 4 challenge partially mitigates.

Reddit search may return zero results for obscure/recent events. News source quality depends on DuckDuckGo index freshness.

Jobs stored in memory only; server restart clears job state. Production should use Redis or a persistent database.

Videos over 180 seconds rejected due to cost/latency.

Single-threaded in development; long Gemini calls can block event loop. Use WSGI (Gunicorn) in production.

9. Dependencies
9.1 Python Packages

flask — Web framework and template serving

flask-cors — Cross-origin request handling

google-generativeai — Gemini API client (google.genai)

yt-dlp — Video download

9.2 System Dependencies

ffmpeg — Video trimming and re-encoding. Install via brew or apt. Trim skipped if unavailable.

Node.js / npm — Not required at runtime; used only for documentation generation.

10. Setup
export GEMINI_API_KEY=your_key_here
pip install flask flask-cors google-generativeai yt-dlp
brew install ffmpeg        # macOS
apt install ffmpeg         # Ubuntu/Debian
python app.py

Server starts on http://127.0.0.1:8080.

Frontend served from templates/index.html.

If ffmpeg is not found, trimming is skipped; original file sent to Gemini.
