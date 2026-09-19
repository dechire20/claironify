import json

from config import NEGATIVE_VERDICTS, VERDICT_CONFIDENCE_CAPS
from gemini_client import gemini_call, parse_json


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


def _apply_caps(parsed):
    verdict = parsed.get("verdict", "")
    conf    = parsed.get("confidence", 50)
    if verdict in VERDICT_CONFIDENCE_CAPS:
        parsed["confidence"] = min(conf, VERDICT_CONFIDENCE_CAPS[verdict])
    return parsed


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
6. Your knowledge has a cutoff date. Do NOT flag political roles, cabinet positions, or official titles as errors unless certain. Government positions change frequently and your data may be outdated — mark as unverifiable rather than a red flag.
7. Recognised news organisations (BBC, CNN, Reuters, AP, ABS-CBN, GMA News, GMA Integrated News, Rappler, Inquirer, PhilStar, One News, CNN Philippines) should be rated LIKELY AUTHENTIC unless you observe SPECIFIC evidence of manipulation in the underlying footage. Professional broadcast production, news graphics, and consistent branding are strong positive signals.
8. Do NOT penalise a video for being dramatic, emotional, or one-sided — this is standard journalism.

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

    text    = gemini_call(prompt)
    parsed  = parse_json(text)
    signals = parsed.pop("signals", {})
    parsed  = _apply_caps(parsed)

    print(f"[Stage 2] Verdict: {parsed.get('verdict')} ({parsed.get('confidence')}%)")
    return signals, parsed


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
        challenged = _apply_caps(challenged)
        print(f"[Stage 3] After challenge: {challenged.get('verdict')} ({challenged.get('confidence')}%)")
        return challenged
    except Exception as e:
        print(f"[Stage 3] Failed: {e}")
        return result


def stage_source_correction(result, sources):
    if not sources:
        print("[Stage 5] Skipped - no sources")
        return result

    source_snippets = "\n".join(
        f"- [{s.get('name','')}]: {s.get('description','')}"
        for s in sources if s.get("description")
    )
    if not source_snippets.strip():
        print("[Stage 5] Skipped - no snippets")
        return result

    print("[Stage 5] Correcting verdict against live sources...")
    red_flags      = result.get("red_flags", [])
    red_flags_text = "\n".join(f"- {f}" for f in red_flags) if red_flags else "none"

    prompt = f"""You are a fact-checker reviewing a verdict that was made WITHOUT access to live sources.
You now have current, real-world sources. Your job is to correct the verdict using ONLY what the sources say.

PREVIOUS VERDICT: {result.get('verdict')} ({result.get('confidence')}%)
PREVIOUS SUMMARY: {result.get('summary')}

RED FLAGS THE PREVIOUS CHECKER RAISED:
{red_flags_text}

LIVE SOURCES (fetched RIGHT NOW — more current than your training data):
{source_snippets}

YOUR TASK:
Go through each red flag. For each one, check if the live sources CONFIRM or DENY it.
If a source confirms a claim the previous checker called false → that red flag is INVALID. Remove it.
If sources confirm the video's claims are accurate → upgrade verdict toward LIKELY AUTHENTIC.
If sources confirm the video IS misleading → keep or strengthen verdict.
If sources are mixed → use NEEDS CONTEXT.

CRITICAL RULES:
- Your training data has a cutoff and MAY BE WRONG about recent events
- Live sources are ALWAYS more authoritative than your prior knowledge
- If sources say something happened that you thought did not → believe the sources
- Do NOT use phrases like "according to my knowledge" — only use what the sources say
- A video from a legitimate news organisation reporting real events = LIKELY AUTHENTIC even if the topic is sensitive
- Meme overlays and editorial framing alone do NOT make a video misleading if the underlying facts are confirmed

Respond ONLY with valid JSON:
{{
  "verdict": "LIKELY FAKE|POSSIBLY MISLEADING|NEEDS CONTEXT|LIKELY AUTHENTIC|CANNOT DETERMINE",
  "confidence": 75,
  "summary": "2-3 sentences. State what the sources confirm, what they deny, and the corrected verdict.",
  "key_claims": {json.dumps(result.get("key_claims", []))},
  "red_flags": ["Only keep red flags that sources did NOT resolve. Remove any flag the sources confirmed as true."],
  "visual_analysis": {json.dumps(result.get("visual_analysis", ""))},
  "verification_points": {json.dumps(result.get("verification_points", []))},
  "recommendation": "Advice based on what the live sources confirm or deny."
}}"""

    try:
        corrected = parse_json(gemini_call(prompt))
        print(f"[Stage 5] Corrected: {corrected.get('verdict')} ({corrected.get('confidence')}%)")
        return corrected
    except Exception as e:
        print(f"[Stage 5] Failed: {e}")
        return result