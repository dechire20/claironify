from flask import Flask, render_template, request, jsonify, Response
from flask_cors import CORS
from google import genai
from google.genai import types
import yt_dlp
import os, json, re, time, threading, uuid, tempfile, shutil, subprocess
import urllib.parse, urllib.request


# CONFIG
app = Flask(__name__)
CORS(app)

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY") or os.environ.get("GEMNI_API_KEY")
if not GEMINI_API_KEY:
    raise ValueError("GEMINI_API_KEY not set")

SERPAPI_KEY  = os.environ.get("SERPAPI_KEY", "")
MODEL        = "gemini-2.5-flash"
MAX_DURATION = 180
TRIM_TO      = 90

gemini = genai.Client(api_key=GEMINI_API_KEY)

JOBS      = {}
JOBS_LOCK = threading.Lock()

CREDIBLE_DOMAINS = {
    "reuters.com","apnews.com","bbc.com","bbc.co.uk","theguardian.com",
    "nytimes.com","washingtonpost.com","cnn.com","nbcnews.com","abcnews.go.com",
    "cbsnews.com","npr.org","politifact.com","factcheck.org","snopes.com",
    "fullfact.org","afp.com","france24.com","dw.com","aljazeera.com",
    "straitstimes.com","scmp.com","abs-cbn.com","rappler.com","inquirer.net",
    "philstar.com","mb.com.ph","gmanetwork.com","7news.com.au","abc.net.au",
    "smh.com.au","theage.com.au","channelnewsasia.com","theatlantic.com",
    "time.com","newsweek.com","forbes.com","economist.com","ft.com",
    "bloomberg.com","wsj.com","usatoday.com","latimes.com","chicagotribune.com",
    "msnbc.com","sky.com","independent.co.uk","telegraph.co.uk","thetimes.co.uk",
    "icc-cpi.int","un.org","who.int","gov.uk","gov.au","senate.gov",
}

NEGATIVE_VERDICTS = {"POSSIBLY MISLEADING", "LIKELY FAKE"}


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


# HELPERS
def detect_platform(url):
    u = url.lower()
    if "tiktok.com"    in u: return "TikTok"
    if "instagram.com" in u: return "Instagram"
    if "youtube.com"   in u or "youtu.be" in u: return "YouTube"
    if "twitter.com"   in u or "x.com"    in u: return "X/Twitter"
    if "facebook.com"  in u: return "Facebook"
    return "Unknown"

def domain_of(url):
    try:    return urllib.parse.urlparse(url).netloc.lower().lstrip("www.")
    except: return ""

def is_credible(url):
    d = domain_of(url)
    return any(d == c or d.endswith("."+c) for c in CREDIBLE_DOMAINS)

def parse_json(text):
    text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.MULTILINE)
    text = re.sub(r"\s*```\s*$",        "", text, flags=re.MULTILINE)
    m = re.search(r"\{.*\}", text, re.DOTALL)
    return json.loads(m.group() if m else text)

def trim_video(path, out_dir):
    out = os.path.join(out_dir, "trimmed.mp4")
    try:
        r = subprocess.run([
            "ffmpeg", "-i", path,
            "-t", str(TRIM_TO),
            "-vf", "fps=0.5",
            "-c:v", "libx264",
            "-crf", "28",
            "-preset", "ultrafast",
            "-c:a", "aac",
            "-y", out
        ], capture_output=True, timeout=60)
        if r.returncode == 0 and os.path.exists(out):
            orig_mb  = os.path.getsize(path) / 1024 / 1024
            small_mb = os.path.getsize(out)  / 1024 / 1024
            print(f"[Trim] {orig_mb:.1f}MB -> {small_mb:.1f}MB at 0.5fps")
            return out
    except Exception as e:
        print(f"[Trim] ffmpeg failed: {e}")
    return path


# DOWNLOAD
def download_video(url, out_dir):
    if re.search(r'tiktok\.com/.+/photo/', url):
        raise ValueError(
            "That's a TikTok photo slideshow, not a video. "
            "DeepCheck only works with video posts."
        )
    opts = {
        "quiet": True, "no_warnings": True,
        "format": "best[height<=360][ext=mp4]/best[height<=360]/worst[ext=mp4]/worst",
        "merge_output_format": "mp4",
        "outtmpl": os.path.join(out_dir, "video.%(ext)s"),
        "writeinfojson": False, "writethumbnail": False, "socket_timeout": 15,
    }
    with yt_dlp.YoutubeDL(opts) as ydl:
        try:
            info = ydl.extract_info(url, download=True)
        except Exception as e:
            msg = str(e)
            if "Unsupported URL" in msg:
                raise ValueError("This URL isn't supported.")
            if "Private video" in msg or "private" in msg.lower():
                raise ValueError("This video is private and can't be accessed.")
            if "removed" in msg.lower() or "deleted" in msg.lower():
                raise ValueError("This video has been removed or deleted.")
            raise ValueError(f"Couldn't download video: {msg[:120]}")

        dur = info.get("duration", 0) or 0
        if dur > MAX_DURATION:
            raise ValueError(f"Video is {int(dur)}s — please use clips under {MAX_DURATION//60} minutes.")
        fp = ydl.prepare_filename(info)
        if not os.path.exists(fp):
            fp = os.path.join(out_dir, "video.mp4")
        meta = {
            "title":      info.get("title", ""),
            "description":(info.get("description") or "")[:600],
            "uploader":   info.get("uploader") or info.get("channel", ""),
            "duration":   dur,
            "platform":   detect_platform(url),
            "thumbnail":  info.get("thumbnail", ""),
            "view_count": info.get("view_count"),
            "like_count": info.get("like_count"),
        }
        return fp, meta


# GEMINI
def gemini_call(prompt, video_file=None):
    parts = []
    if video_file:
        parts.append(types.Part(file_data=types.FileData(
            file_uri=video_file.uri, mime_type="video/mp4"
        )))
    parts.append(types.Part(text=prompt))
    resp = gemini.models.generate_content(
        model=MODEL,
        contents=[types.Content(parts=parts)],
    )
    return resp.text.strip()

def upload_to_gemini(path):
    vf = gemini.files.upload(file=path, config=types.UploadFileConfig(mime_type="video/mp4"))
    while vf.state.name == "PROCESSING":
        time.sleep(1)
        vf = gemini.files.get(name=vf.name)
    if vf.state.name == "FAILED":
        raise RuntimeError("Gemini file processing failed")
    return vf


# STAGE 1: DESCRIBE
def stage_describe(video_file):
    print("[Stage 1] Describing...")
    text = gemini_call(
        "Watch this video and provide a structured description with four sections.\n\n"
        "SECTION A — UNDERLYING EVENT:\n"
        "Describe the real-world event being filmed — what actually happened, who the real people are, "
        "what they did or said, where it takes place. Focus on the raw footage itself.\n\n"
        "SECTION B — PRESENTATION LAYER (editorial additions):\n"
        "List everything added ON TOP of the original footage by whoever posted it: meme text, "
        "overlaid graphics, reaction gauges, humour captions, labels, commentary, music, or any "
        "post-production edits. These are NOT part of the original event.\n\n"
        "SECTION C — AUDIO & SPEECH:\n"
        "Quote key spoken statements verbatim. Note speaker identity and credentials if shown.\n\n"
        "SECTION D — ORIGINAL FOOTAGE QUALITY:\n"
        "Is the underlying footage professional broadcast, amateur phone footage, AI-generated, "
        "screen recording, etc.? Note any news org branding on the ORIGINAL footage only.\n\n"
        "Be as detailed and verbatim as possible.",
        video_file
    )
    print(f"[Stage 1] Done: {text[:80]}...")
    return text


# STAGE 2: SIGNALS + VERDICT
def stage_signals_and_verdict(observation, meta):
    print("[Stage 2] Signals + verdict...")
    prompt = f"""You are a senior fact-checker. You have received a detailed observation of a video.
Return a signal inventory AND a verdict in one JSON response.

VIDEO METADATA:
Title: {meta.get('title','Unknown')}
Uploader: {meta.get('uploader','Unknown')}
Platform: {meta.get('platform','Unknown')}
Duration: {meta.get('duration','Unknown')}s
Description: {meta.get('description','None')}
User context: {meta.get('user_context','None')}

OBSERVATION:
{observation}

CRITICAL DISTINCTION:
PRESENTATION LAYER (meme text, overlaid gauges, humour captions, reaction graphics,
added labels, commentary edits) = editorial framing by whoever POSTED the video.
Do NOT count presentation layer elements as manipulation of the original footage.

ACTUAL MANIPULATION = fabricated footage, deepfaked people, events that never happened,
false captions that directly contradict the underlying footage.

VERDICT LOGIC:
1. Evaluate the UNDERLYING EVENT (Section A) — is the original footage real?
2. Post-production overlays (Section B) are framing, not fabrication.
3. observed_manipulation_evidence = "none observed" means POSSIBLY MISLEADING and LIKELY FAKE are forbidden.
4. Real footage + misleading presentation layer = NEEDS CONTEXT.
5. topic_sensitivity is NOT manipulation evidence.

VERDICTS:
LIKELY AUTHENTIC    Underlying event is real, no fabrication. Confidence 72-88%.
NEEDS CONTEXT       Real footage but presentation layer misleads. Max 65%.
POSSIBLY MISLEADING Presentation layer makes specific false factual claims. Max 55%.
LIKELY FAKE         Underlying event itself is fabricated/AI-generated. Max 88%.
CANNOT DETERMINE    Genuinely insufficient evidence. 30-55%.

Respond ONLY with valid JSON — no markdown, no code fences:
{{
  "signals": {{
    "news_org_branding": "...",
    "production_quality": "professional broadcast | semi-professional | amateur phone footage | AI-generated | unknown",
    "presenter_credentials": "...",
    "post_production_framing": "List all overlays/edits added by poster.",
    "observed_manipulation_evidence": "ONLY fabrication of UNDERLYING EVENT. If nothing: 'none observed'.",
    "topic_sensitivity": "yes | no",
    "authenticity_positive_signals": "...",
    "authenticity_negative_signals": "...",
    "summary_signal_balance": "one sentence about underlying event authenticity"
  }},
  "verdict": "LIKELY FAKE|POSSIBLY MISLEADING|NEEDS CONTEXT|LIKELY AUTHENTIC|CANNOT DETERMINE",
  "confidence": 75,
  "summary": "2-3 sentences: underlying event, verdict, any misleading framing.",
  "key_claims": ["Claim 1", "Claim 2", "Claim 3"],
  "red_flags": [],
  "visual_analysis": "What was observed.",
  "verification_points": ["Checkable fact and how to verify"],
  "recommendation": "Balanced advice for the viewer."
}}"""

    text   = gemini_call(prompt)
    parsed = parse_json(text)
    signals = parsed.pop("signals", {})
    print(f"[Stage 2] Verdict: {parsed.get('verdict')} ({parsed.get('confidence')}%)")
    return signals, parsed


# STAGE 3: CHALLENGE (conditional)
def stage_challenge(result, signals):
    verdict    = result.get("verdict")
    confidence = result.get("confidence", 0)
    if verdict not in NEGATIVE_VERDICTS or confidence <= 40:
        print(f"[Stage 3] Skipped ({verdict})")
        return result

    print("[Stage 3] Challenging...")
    prompt = f"""A fact-checker gave this verdict. Evaluate whether it is justified.

VERDICT: {verdict}  CONFIDENCE: {confidence}
SUMMARY: {result.get('summary')}
RED FLAGS: {json.dumps(result.get('red_flags',[]))}

SIGNALS:
- observed_manipulation_evidence: {signals.get('observed_manipulation_evidence','none observed')}
- authenticity_positive_signals: {signals.get('authenticity_positive_signals','none observed')}
- production_quality: {signals.get('production_quality','unknown')}
- news_org_branding: {signals.get('news_org_branding','none observed')}
- topic_sensitivity: {signals.get('topic_sensitivity','unknown')} NOT manipulation evidence

RULES:
1. observed_manipulation_evidence = "none observed" MUST downgrade verdict.
2. Strong positive signals should push toward LIKELY AUTHENTIC.
3. topic_sensitivity is irrelevant to verdict.

Respond ONLY with valid JSON:
{{
  "verdict": "LIKELY FAKE|POSSIBLY MISLEADING|NEEDS CONTEXT|LIKELY AUTHENTIC|CANNOT DETERMINE",
  "confidence": 70,
  "summary": "2-3 sentences.",
  "key_claims": {json.dumps(result.get('key_claims',[]))},
  "red_flags": [],
  "visual_analysis": {json.dumps(result.get('visual_analysis',''))},
  "verification_points": {json.dumps(result.get('verification_points',[]))},
  "recommendation": "Balanced advice."
}}"""
    try:
        challenged = parse_json(gemini_call(prompt))
        print(f"[Stage 3] After challenge: {challenged.get('verdict')} ({challenged.get('confidence')}%)")
        return challenged
    except Exception as e:
        print(f"[Stage 3] Failed: {e}")
        return result


# STAGE 4: SOURCES (Reddit-first hybrid)
def build_query(key_claims, title):
    prompt = (
        "Write a single search query (max 10 words) to find news or discussion about these claims.\n"
        "RULES:\n"
        "- If a specific person, streamer, or influencer is named — their name MUST be in the query\n"
        "- Focus on proper nouns: names, usernames, brands, specific events\n"
        "- Do NOT use generic action words alone without attaching a name\n"
        "- No quotes, no operators\n\n"
        f"Title: {title}\nClaims:\n" +
        "\n".join(f"- {c}" for c in key_claims[:3]) +
        "\n\nReply with ONLY the query string."
    )
    try:
        q = gemini_call(prompt).strip().strip('"').strip("'")
        print(f"[Sources] Query: {q}")
        return q
    except:
        return " ".join((title+" "+(key_claims[0] if key_claims else ""))[:80].split()[:10])

def pick_subreddits(key_claims, title):
    """Ask Gemini to pick the most relevant subreddits dynamically based on content."""
    prompt = (
        "You are picking Reddit subreddits to find discussion about this specific video topic.\n\n"
        f"Video title: {title}\n"
        "Key topics/claims:\n" +
        "\n".join(f"- {c}" for c in key_claims[:3]) +
        "\n\n"
        "Pick 3-5 subreddits most likely to have ACTIVE recent discussion about this SPECIFIC topic.\n"
        "Be dynamic and specific — match the exact community:\n"
        "- Streamer drama → LivestreamFail, their dedicated sub (e.g. xqcow, Mizkif)\n"
        "- Looksmaxxing/appearance/glow-up → Looksmax, tiktokgossip, vindicta\n"
        "- Celebrity gossip → Fauxmoi, ONTD, popculturechat, CelebGossip\n"
        "- Influencer drama → BeautyGuruChatter, influencersnark, tiktokgossip\n"
        "- YouTube drama → youtubehaiku, youtube, YTDrama\n"
        "- Gaming drama → gaming or the specific game sub\n"
        "- Relationship/AITA drama → AITA, relationship_advice, AmItheAsshole\n"
        "- Political news → worldnews, news, politics\n"
        "- General internet drama → HobbyDrama, PublicFreakout, InternetIsBeautiful\n"
        "- NEVER default to OutOfTheLoop unless the topic is genuinely obscure\n"
        "- NEVER pick generic subs when a specific community exists\n\n"
        "Reply ONLY with a JSON array of subreddit names (no r/ prefix):\n"
        '["LivestreamFail", "xqcow"]'
    )
    try:
        raw = gemini_call(prompt).strip()
        raw = re.sub(r"^```(?:json)?\s*", "", raw, flags=re.MULTILINE)
        raw = re.sub(r"\s*```\s*$", "", raw, flags=re.MULTILINE)
        m = re.search(r"\[.*\]", raw, re.DOTALL)
        subs = json.loads(m.group() if m else raw)
        subs = [s.lstrip("r/").strip() for s in subs if isinstance(s, str)]
        print(f"[Reddit] Picked subreddits: {subs}")
        return subs[:5]
    except Exception as e:
        print(f"[Reddit] Subreddit pick failed: {e}")
        return ["PublicFreakout", "HobbyDrama"]

def _reddit_search(subreddit, query, limit=5):
    """Search a subreddit using Reddit's public JSON API. No key needed."""
    url = (
        f"https://www.reddit.com/r/{subreddit}/search.json"
        f"?q={urllib.parse.quote_plus(query)}"
        f"&restrict_sr=1&sort=relevance&t=year&limit={limit}"
    )
    req = urllib.request.Request(url, headers={"User-Agent": "deepcheck/1.0"})
    with urllib.request.urlopen(req, timeout=6) as r:
        data = json.loads(r.read().decode())
    results = []
    for post in data.get("data", {}).get("children", []):
        p = post.get("data", {})
        ptitle    = p.get("title", "")
        permalink = p.get("permalink", "")
        score     = p.get("score", 0)
        comments  = p.get("num_comments", 0)
        if permalink and score > 5:
            results.append({
                "name":        f"r/{subreddit}: {ptitle[:80]}",
                "url":         f"https://www.reddit.com{permalink}",
                "description": f"{score} upvotes · {comments} comments — community discussion",
                "_score":      score,
            })
    return results

def _relevance_score(post_name, query_terms):
    """Score a post title by how many query words appear in it."""
    name_lower = post_name.lower()
    words = [w.lower() for w in query_terms.split() if len(w) > 3]
    if not words:
        return 0
    return sum(1 for w in words if w in name_lower) / len(words)

def _fetch_reddit_sources(key_claims, title, subreddits):
    """Build a tight query, search each subreddit, filter irrelevant results."""
    stop = {"that","this","they","have","with","from","were","been","about","which","their"}
    query_terms = " ".join(
        w for c in key_claims[:2]
        for w in c.split()
        if len(w) > 3 and w.lower() not in stop
    )[:80] or title[:60]
    print(f"[Reddit] Search query: {query_terms!r}")

    all_posts = []
    for sub in subreddits:
        try:
            posts = _reddit_search(sub, query_terms)
            # Filter: must have at least 1 query word in the title
            relevant = [p for p in posts if _relevance_score(p["name"], query_terms) > 0]
            all_posts.extend(relevant)
            print(f"[Reddit] r/{sub}: {len(posts)} results, {len(relevant)} relevant")
        except Exception as e:
            print(f"[Reddit] r/{sub} failed: {e}")

    # Sort by relevance score first, then upvote score
    all_posts.sort(key=lambda p: (
        _relevance_score(p["name"], query_terms),
        p.get("_score", 0)
    ), reverse=True)

    seen, out = set(), []
    for p in all_posts:
        if p["url"] not in seen:
            seen.add(p["url"])
            p.pop("_score", None)
            out.append(p)
    return out[:3]

def _serpapi(query):
    params = urllib.parse.urlencode({"q":query,"api_key":SERPAPI_KEY,"num":10,"hl":"en"})
    req = urllib.request.Request(
        f"https://serpapi.com/search.json?{params}",
        headers={"User-Agent":"deepcheck/1.0"}
    )
    with urllib.request.urlopen(req, timeout=8) as r:
        data = json.loads(r.read().decode())
    return [
        {"name":i.get("title",domain_of(i.get("link",""))),"url":i.get("link",""),"description":i.get("snippet","")}
        for i in data.get("organic_results",[]) if i.get("link")
    ]

def _duckduckgo(query):
    req = urllib.request.Request(
        f"https://html.duckduckgo.com/html/?q={urllib.parse.quote_plus(query)}",
        headers={"User-Agent":"Mozilla/5.0 (compatible; deepcheck/1.0)","Accept-Language":"en-US,en;q=0.9"}
    )
    with urllib.request.urlopen(req, timeout=8) as r:
        html = r.read().decode("utf-8", errors="replace")
    up = re.compile(r'class="result__a"[^>]*href="([^"]+)"[^>]*>(.*?)</a>', re.DOTALL)
    sp = re.compile(r'class="result__snippet"[^>]*>(.*?)</a>', re.DOTALL)
    snippets = [re.sub(r"<[^>]+>","",s).strip() for s in sp.findall(html)]
    results = []
    for i,(href,th) in enumerate(up.findall(html)):
        m = re.search(r"uddg=([^&]+)", href)
        if m: href = urllib.parse.unquote(m.group(1))
        t = re.sub(r"<[^>]+>","",th).strip()
        s = snippets[i] if i < len(snippets) else ""
        if href.startswith("http"):
            results.append({"name":t or domain_of(href),"url":href,"description":s})
    return results

def fetch_sources(key_claims, title):
    """
    Reddit-first hybrid:
    1. Gemini picks relevant subreddits dynamically based on content
    2. Reddit JSON API fetches real community discussion (no API key)
    3. News sources from DuckDuckGo/SerpAPI as supplement
    """
    reddit_sources = []
    news_sources   = []

    # Reddit — dynamic, content-aware
    try:
        subreddits     = pick_subreddits(key_claims, title)
        reddit_sources = _fetch_reddit_sources(key_claims, title, subreddits)
        print(f"[Sources] Reddit: {len(reddit_sources)} posts")
    except Exception as e:
        print(f"[Sources] Reddit failed: {e}")

    # News — DuckDuckGo / SerpAPI
    query = build_query(key_claims, title)
    raw = []
    if SERPAPI_KEY:
        try: raw = _serpapi(query); print(f"[Sources] SerpAPI: {len(raw)}")
        except Exception as e: print(f"[Sources] SerpAPI failed: {e}")
    if not raw:
        try: raw = _duckduckgo(query); print(f"[Sources] DDG: {len(raw)}")
        except Exception as e: print(f"[Sources] DDG failed: {e}")

    seen_domains = set()
    for r in [x for x in raw if is_credible(x["url"])] + [x for x in raw if not is_credible(x["url"])]:
        d = domain_of(r["url"])
        if d and d not in seen_domains:
            seen_domains.add(d)
            news_sources.append(r)
        if len(news_sources) >= 3:
            break

    # Reddit first (community context), then news
    combined = reddit_sources + news_sources
    print(f"[Sources] Total: {len(combined)}")
    return combined[:6] if combined else []


# PIPELINE
def run_pipeline(task_id, video_path, meta):
    tmp_dir    = os.path.dirname(video_path)
    video_path = trim_video(video_path, tmp_dir)

    job_set(task_id, message="Uploading to Gemini...", progress_pct=12)
    vf = upload_to_gemini(video_path)
    job_set(task_id, message="Gemini is watching the video...", progress_pct=22)

    try:
        observation = stage_describe(vf)
    finally:
        try: gemini.files.delete(name=vf.name)
        except: pass

    job_set(task_id, message="Analysing signals and forming verdict...", progress_pct=58)
    signals, result = stage_signals_and_verdict(observation, meta)

    job_set(task_id,
        progress_pct        = 72,
        message             = "Checking verdict...",
        visual_analysis     = result.get("visual_analysis",""),
        key_claims          = result.get("key_claims",[]),
        red_flags           = result.get("red_flags",[]),
        verification_points = result.get("verification_points",[]),
        recommendation      = result.get("recommendation",""),
    )

    if result.get("verdict") in NEGATIVE_VERDICTS and result.get("confidence",0) > 40:
        job_set(task_id, message="Double-checking verdict...", progress_pct=80)
        result = stage_challenge(result, signals)

    job_set(task_id,
        status      = "partial",
        message     = "Finding sources...",
        progress_pct= 88,
        verdict     = result.get("verdict"),
        confidence  = result.get("confidence"),
        summary     = result.get("summary"),
    )

    sources = fetch_sources(result.get("key_claims",[]) or [], meta.get("title",""))
    job_set(task_id,
        status      = "done",
        message     = "Done.",
        progress_pct= 100,
        sources     = sources,
    )


# BACKGROUND WORKER
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


# ROUTES
@app.route("/")
def index():
    return render_template("index.html")

@app.route("/upload", methods=["POST"])
def upload():
    body    = request.json or {}
    url     = body.get("url","").strip()
    context = body.get("context","").strip()
    if not url:
        return jsonify({"error":"Please provide a video URL"}), 400
    task_id = str(uuid.uuid4())
    with JOBS_LOCK:
        JOBS[task_id] = make_job()
    threading.Thread(target=background_process, args=(task_id,url,context), daemon=True).start()
    return jsonify({"task_id":task_id})

@app.route("/status/<task_id>")
def status(task_id):
    with JOBS_LOCK:
        job = JOBS.get(task_id)
        if not job: return jsonify({"error":"Unknown task_id"}), 404
        return jsonify(job)

@app.route("/sw.js")
def service_worker():
    return Response("""
const CACHE='deepcheck-v12';
self.addEventListener('install',e=>e.waitUntil(caches.open(CACHE).then(c=>c.addAll(['/']))));
self.addEventListener('fetch',e=>{if(e.request.method!=='GET')return;e.respondWith(fetch(e.request).catch(()=>caches.match(e.request)));});
""", mimetype="application/javascript")

if __name__ == "__main__":
    app.run(host="127.0.0.1", port=8080, debug=True)