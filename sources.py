import json
import re
import urllib.parse
import urllib.request

from config import SERPAPI_KEY
from gemini_client import gemini_call
from video import domain_of


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
    except Exception:
        return " ".join((title + " " + (key_claims[0] if key_claims else ""))[:80].split()[:10])


def pick_subreddits(key_claims, title):
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
    name_lower = post_name.lower()
    words = [w.lower() for w in query_terms.split() if len(w) > 3]
    if not words:
        return 0
    return sum(1 for w in words if w in name_lower) / len(words)


def _fetch_reddit_sources(key_claims, title, subreddits):
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
            relevant = [p for p in posts if _relevance_score(p["name"], query_terms) > 0]
            all_posts.extend(relevant)
            print(f"[Reddit] r/{sub}: {len(posts)} results, {len(relevant)} relevant")
        except Exception as e:
            print(f"[Reddit] r/{sub} failed: {e}")

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
    params = urllib.parse.urlencode({"q": query, "api_key": SERPAPI_KEY, "num": 10, "hl": "en"})
    req = urllib.request.Request(
        f"https://serpapi.com/search.json?{params}",
        headers={"User-Agent": "deepcheck/1.0"}
    )
    with urllib.request.urlopen(req, timeout=8) as r:
        data = json.loads(r.read().decode())
    return [
        {"name": i.get("title", domain_of(i.get("link", ""))),
         "url": i.get("link", ""),
         "description": i.get("snippet", "")}
        for i in data.get("organic_results", []) if i.get("link")
    ]


def _duckduckgo(query):
    req = urllib.request.Request(
        f"https://html.duckduckgo.com/html/?q={urllib.parse.quote_plus(query)}",
        headers={"User-Agent": "Mozilla/5.0 (compatible; deepcheck/1.0)",
                 "Accept-Language": "en-US,en;q=0.9"}
    )
    with urllib.request.urlopen(req, timeout=8) as r:
        html = r.read().decode("utf-8", errors="replace")

    up = re.compile(r'class="result__a"[^>]*href="([^"]+)"[^>]*>(.*?)</a>', re.DOTALL)
    sp = re.compile(r'class="result__snippet"[^>]*>(.*?)</a>', re.DOTALL)
    snippets = [re.sub(r"<[^>]+>", "", s).strip() for s in sp.findall(html)]

    results = []
    for i, (href, th) in enumerate(up.findall(html)):
        m = re.search(r"uddg=([^&]+)", href)
        if m:
            href = urllib.parse.unquote(m.group(1))
        t = re.sub(r"<[^>]+>", "", th).strip()
        s = snippets[i] if i < len(snippets) else ""
        if href.startswith("http"):
            results.append({"name": t or domain_of(href), "url": href, "description": s})
    return results


def fetch_sources(key_claims, title):
    reddit_sources = []
    news_sources   = []

    try:
        subreddits     = pick_subreddits(key_claims, title)
        reddit_sources = _fetch_reddit_sources(key_claims, title, subreddits)
        print(f"[Sources] Reddit: {len(reddit_sources)} posts")
    except Exception as e:
        print(f"[Sources] Reddit failed: {e}")

    query = build_query(key_claims, title)
    raw = []
    if SERPAPI_KEY:
        try:
            raw = _serpapi(query)
            print(f"[Sources] SerpAPI: {len(raw)}")
        except Exception as e:
            print(f"[Sources] SerpAPI failed: {e}")
    if not raw:
        try:
            raw = _duckduckgo(query)
            print(f"[Sources] DDG: {len(raw)}")
        except Exception as e:
            print(f"[Sources] DDG failed: {e}")

    seen_domains = set()
    for r in raw:
        d = domain_of(r["url"])
        if d and d not in seen_domains:
            seen_domains.add(d)
            news_sources.append(r)
        if len(news_sources) >= 3:
            break

    combined = reddit_sources + news_sources
    print(f"[Sources] Total: {len(combined)}")
    return combined[:6] if combined else []