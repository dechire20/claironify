**Claironify**

Technical Documentation

*Internal --- Not for Distribution*

Version 1.0 \| February 2026

**1. Overview**

DeepCheck is a video fact-checking web application that uses AI vision
to assess the authenticity of social media videos. A user submits a URL
from TikTok, Instagram, or YouTube. The system downloads the video,
sends it to Google Gemini for visual analysis, and returns a structured
verdict with supporting sources.

The application runs as a progressive web app (PWA) with no user account
required. Analysis completes in approximately 30 to 90 seconds depending
on video length and server load.

**2. Architecture**

**2.1 Stack**

  ------------------- ---------------------------------------------------
  **Backend**         Python 3 / Flask

  **AI Model**        Google Gemini 2.5 Flash (gemini-2.5-flash)

  **Video Download**  yt-dlp

  **Video             ffmpeg (system binary)
  Processing**        

  **Source Search**   Reddit JSON API + DuckDuckGo HTML scrape / SerpAPI
                      (optional)

  **Frontend**        HTML/CSS/JS via Flask templates (PWA)

  **Deployment**      Local: python app.py on port 8080
  ------------------- ---------------------------------------------------

**2.2 Request Lifecycle**

Requests are processed asynchronously. On submission, a UUID task_id is
returned immediately. The frontend polls GET /status/{task_id} every
four seconds. Job fields are published incrementally as each stage
completes. The frontend renders each field as soon as it is non-null.

**2.3 Pipeline Stages**

  ------------------- ---------------------------------------------------
  **Stage 1 ---       yt-dlp downloads the video at 360p maximum. ffmpeg
  Download & Trim**   trims it to 90 seconds at 0.5fps to reduce upload
                      size before sending to Gemini.

  **Stage 2 ---       The trimmed video is uploaded to the Gemini Files
  Describe**          API. Gemini returns a four-section structured
                      description: (A) underlying event, (B) presentation
                      layer additions, (C) verbatim speech, (D) footage
                      quality.

  **Stage 3 ---       A second Gemini call receives the text description
  Verdict**           only (no video). It returns a JSON object with
                      signals, verdict, confidence, key claims, red
                      flags, verification points, and recommendation. No
                      live search occurs at this stage.

  **Stage 4 ---       If verdict is POSSIBLY MISLEADING or LIKELY FAKE
  Challenge           with confidence above 40%, a challenge call
  (conditional)**     evaluates whether the negative verdict is justified
                      by the signal inventory. If observed manipulation
                      evidence is absent, the verdict is downgraded.

  **Stage 5 ---       Sources are fetched independently of the verdict.
  Sources**           Gemini selects relevant subreddits based on
                      content. Reddit\'s public JSON API is searched per
                      subreddit. DuckDuckGo (or SerpAPI if configured)
                      retrieves news results. Reddit posts appear first.
  ------------------- ---------------------------------------------------

**2.4 Job State Schema**

  ------------------------- ---------------------------------------------------
  **status**                queued \| downloading \| analyzing \| partial \|
                            done \| error

  **message**               Human-readable progress string for the frontend

  **progress_pct**          Integer 0-100

  **error**                 Error string or null

  **meta**                  title, uploader, platform, duration, thumbnail,
                            view_count, like_count

  **visual_analysis**       Prose description from Stage 3

  **key_claims**            Array of strings extracted from the video

  **red_flags**             Array of observed issues (empty array if none)

  **verification_points**   Array of checkable facts with suggested
                            verification methods

  **recommendation**        Prose advice for the viewer

  **verdict**               One of five verdict strings --- see Section 3

  **confidence**            Integer 0-100

  **summary**               2-3 sentence verdict summary

  **sources**               Array of { name, url, description } objects
  ------------------------- ---------------------------------------------------

**3. Verdict System**

Gemini is instructed to distinguish between the underlying event (the
actual footage) and the presentation layer (overlays, captions, music,
meme text added by the uploader). These are assessed separately.
Dramatic framing, emotional tone, and controversial subject matter do
not constitute manipulation.

  ------------------- ---------------------------------------------------
  **LIKELY            Underlying event is real with no fabrication
  AUTHENTIC**         observed. Confidence range: 72-88%.

  **NEEDS CONTEXT**   Footage is real but the presentation layer misleads
                      about its meaning. Max confidence: 65%.

  **POSSIBLY          Presentation layer makes specific, verifiable false
  MISLEADING**        claims. Max confidence: 55%.

  **LIKELY FAKE**     The underlying event is fabricated, staged, or
                      AI-generated. Max confidence: 88%.

  **CANNOT            Insufficient observable evidence to form a verdict.
  DETERMINE**         Confidence range: 30-55%.
  ------------------- ---------------------------------------------------

Constraint: POSSIBLY MISLEADING and LIKELY FAKE are forbidden when
observed_manipulation_evidence is \'none observed\'. This prevents false
positives caused by editorial framing alone.

**4. Source Retrieval**

**4.1 Reddit**

Gemini selects 3-5 subreddits based on the video\'s key claims and
title. Selection is content-specific: streamer drama uses LivestreamFail
or dedicated streamer subs; looksmaxxing content uses Looksmax or
tiktokgossip; celebrity gossip uses Fauxmoi or ONTD. Generic fallbacks
are used only when no specific community applies.

Each subreddit is searched via Reddit\'s public API (no authentication
required). Posts are filtered by relevance: a result is only included if
at least one word from the search query appears in the post title.
Results are sorted by relevance first, then by upvote count.

**4.2 News**

Gemini generates a search query anchored to proper nouns. If a named
person, streamer, or brand is present in the claims, their name must
appear in the query. Generic action words alone are not permitted.

The query is sent to DuckDuckGo\'s HTML endpoint. If SERPAPI_KEY is set,
SerpAPI is used instead and results are prioritised by a hardcoded list
of credible domains (Reuters, AP, BBC, and similar).

**4.3 Result Order**

Up to 3 Reddit posts appear first in the sources list, followed by up to
3 news results. Maximum 6 sources total.

**5. Configuration**

**5.1 Environment Variables**

  -------------------- ---------------------------------------------------
  **GEMINI_API_KEY**   Required. Google Gemini API key. GEMNI_API_KEY
                       accepted as legacy alias.

  **SERPAPI_KEY**      Optional. If set, SerpAPI replaces DuckDuckGo for
                       news source retrieval.
  -------------------- ---------------------------------------------------

**5.2 Constants (app.py)**

  ----------------------- ---------------------------------------------------
  **MODEL**               gemini-2.5-flash

  **MAX_DURATION**        180 seconds. Videos exceeding this are rejected
                          with a user-facing error.

  **TRIM_TO**             90 seconds. Videos are trimmed to this length at
                          0.5fps before Gemini upload.

  **NEGATIVE_VERDICTS**   { POSSIBLY MISLEADING, LIKELY FAKE } --- these
                          trigger the Stage 4 challenge.
  ----------------------- ---------------------------------------------------

**6. API Reference**

**POST /upload**

Submits a video URL for analysis. Returns a task_id for polling.

> Request: { \"url\": \"https://\...\", \"context\": \"optional note\" }
>
> Response: { \"task_id\": \"uuid-string\" }

**GET /status/{task_id}**

Returns the full job object. Poll every 3-4 seconds. Render fields as
they become non-null. Job is terminal when status is \'done\' or
\'error\'.

**GET /sw.js**

Serves the PWA service worker for offline shell caching.

**7. Supported Platforms**

  ------------------- ---------------------------------------------------
  **TikTok**          Video posts only. Photo slideshows (URLs containing
                      /photo/) are rejected.

  **Instagram**       Reels and video posts.

  **YouTube**         Standard videos and Shorts.

  **X / Twitter**     Public video posts.

  **Facebook**        Public video posts.
  ------------------- ---------------------------------------------------

**8. Known Limitations**

-   Gemini has no real-time knowledge. It cannot verify whether a named
    person actually made a statement --- it can only assess visual and
    audio authenticity of what is observable in the footage.

-   Theatrical reactions, dramatic sound effects, and heavy
    post-production editing may result in NEEDS CONTEXT rather than
    LIKELY AUTHENTIC. The Stage 4 challenge partially mitigates this.

-   Reddit search returns zero results for obscure or very recent
    events. News source quality is dependent on DuckDuckGo\'s index
    freshness.

-   Jobs are stored in memory only. A server restart clears all job
    state. Production deployment should migrate job storage to Redis or
    a persistent database.

-   Videos over 180 seconds are rejected. This is a cost and latency
    constraint, not a technical one.

-   The application runs single-threaded in development mode. Under
    concurrent load, long-running Gemini calls may block the event loop.
    Production deployment should use a WSGI server such as Gunicorn.

**9. Dependencies**

**9.1 Python Packages**

  ------------------------- ---------------------------------------------------
  **flask**                 Web framework and template serving

  **flask-cors**            Cross-origin request handling

  **google-generativeai**   Gemini API client (google.genai)

  **yt-dlp**                Video download from TikTok, Instagram, YouTube, and
                            others
  ------------------------- ---------------------------------------------------

**9.2 System Dependencies**

  ------------------- ---------------------------------------------------
  **ffmpeg**          Video trimming and re-encoding. Install via brew or
                      apt. If unavailable, trim is skipped.

  **Node.js / npm**   Not required at runtime. Used for documentation
                      generation only.
  ------------------- ---------------------------------------------------

**10. Setup**

> export GEMINI_API_KEY=your_key_here
>
> pip install flask flask-cors google-generativeai yt-dlp
>
> brew install ffmpeg \# macOS
>
> apt install ffmpeg \# Ubuntu/Debian
>
> python app.py

The server starts on http://127.0.0.1:8080. The frontend is served from
templates/index.html. If ffmpeg is not found, trim is skipped and the
original downloaded file is passed to Gemini directly.
