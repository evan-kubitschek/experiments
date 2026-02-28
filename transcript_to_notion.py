#!/usr/bin/env python3
"""End-to-end pipeline: Extract content ideas from Fathom call transcripts,
draft full LinkedIn posts/newsletters, and push finished drafts to Notion.

Pipeline per transcript:
1. Extract content ideas via Anthropic API (MP3 framework)
2. Filter to high-confidence, post-worthy ideas
3. Draft each idea into a full LinkedIn post or newsletter
4. Push the idea metadata + full draft to Notion

Environment variables (can be set in .env):
    ANTHROPIC_API_KEY  — Anthropic API key
    NOTION_API_KEY     — Notion integration token
    NOTION_DATABASE_ID — Target Notion database ID
"""

import argparse
import json
import os
import re
import sys
import time
from datetime import datetime
from pathlib import Path

import anthropic
import requests
from dotenv import load_dotenv

# ──────────────────────────────────────────────────────────────────────
# Constants
# ──────────────────────────────────────────────────────────────────────

CLAUDE_MODEL = "claude-sonnet-4-5-20250929"
TRANSCRIPT_CHUNK_LIMIT = 100_000  # characters
CHUNK_OVERLAP = 2_000
ANTHROPIC_DELAY = 2.0  # seconds between API calls
NOTION_API_BASE = "https://api.notion.com/v1"
NOTION_API_VERSION = "2022-06-28"
NOTION_DELAY = 0.35  # ~3 requests/second
MIN_TRANSCRIPT_CHARS = 2_000  # Skip transcripts shorter than this
VOICE_SAMPLE_COUNT = 5  # LinkedIn samples for voice calibration
SCRIPT_DIR = Path(__file__).parent

# ──────────────────────────────────────────────────────────────────────
# MP3 extraction system prompt
# ──────────────────────────────────────────────────────────────────────

MP3_SYSTEM_PROMPT = r"""You are a content strategist extracting LinkedIn content ideas from consulting call transcripts for Evan Kubitschek, founder of Grow Rogue — a Revenue Operations consultancy specializing in foundational marketing operations for B2B tech companies.

## EVAN'S POSITIONING

Evan's core thesis: Most B2B marketing operations failures stem from treating symptoms rather than addressing root infrastructure problems. Companies "automate chaos instead of fixing it." His methodology — the Tower of Power — emphasizes fixing people and process before implementing platform solutions.

**Tower of Power Layers (bottom-up foundation):**
1. Database Health — Clean data, proper field architecture, deduplication, data governance
2. Segmentation — Meaningful audience segments based on clean data
3. Customer Lifecycle — Defined stages, proper stage definitions, transition criteria
4. Prioritization — Lead scoring, MQL/SQL definitions, routing logic
5. Speed to Lead — Response time optimization, handoff automation, SLA enforcement

**Evan's voice characteristics:**
- Anti-corporate, direct, no-BS
- Uses analogies and metaphors to explain technical concepts
- Comfortable calling out industry dysfunction ("dumpster fire" situations)
- Values "slow ambition" — sustainable growth over hustle culture
- Contrarian to the "platform-first" approach the industry defaults to
- Empathetic toward ops practitioners stuck cleaning up messes they didn't create

**Evan's key themes:**
- The "foundational operations gap" — invisible infrastructure problems that cause automation to fail
- Fixing what's broken before building what's new
- People and process before platform
- The hidden cost of skipping foundations
- Why "best practices" fail when your data is garbage
- Marketing ops as strategic function, not ticket-taking

## YOUR TASK

Analyze the provided transcript and extract content ideas using the MP3 Framework:

**Market the Problem** — Content that articulates the pain, frustration, and emotional reality of broken marketing operations.

**Market the Process** — Content that shows how Evan thinks, diagnoses, and solves problems.

**Market the Proof** — Content that demonstrates results, transformation, or tangible progress.

## OUTPUT FORMAT

Return a JSON array of content ideas. Only extract ideas strong enough to become full LinkedIn posts — skip weak or generic ideas. Each idea:

```json
[
  {
    "mp3_category": "problem" | "process" | "proof",
    "title": "A compelling, specific content hook — should read like a LinkedIn post opening line.",
    "core_insight": "The key insight in 2-3 sentences.",
    "content_angle": "How to frame this as content. Narrative structure and tension.",
    "hook_options": ["Option 1", "Option 2", "Option 3"],
    "supporting_evidence": "Specific anonymized example from the call.",
    "tower_layer": "database_health" | "segmentation" | "lifecycle" | "prioritization" | "speed_to_lead" | "general" | "cross_layer",
    "mp3_sub_type": "silent_struggle|challenge_wisdom|hidden_cost|false_solution|root_cause|future_implication|permission|decision_filter|how_i_think|internal_questions|contrast_approach|open_source_process|client_insight|experiment_lesson|before_after|specific_numbers|screenshot_evidence|success_story|implementation_example",
    "quotable_moment": "A direct quote from Evan in his natural voice.",
    "content_types": ["linkedin_post", "newsletter", "video_script", "thread"],
    "confidence": "high" | "medium" | "low",
    "reasoning": "Why this is a strong content idea for Evan's audience."
  }
]
```

## RULES

1. **Anonymize everything.** Use descriptors like "a mid-market B2B SaaS company."
2. **Prioritize specificity over generality.**
3. **Capture Evan's actual voice** in quotable_moment.
4. **Look for the problem behind the problem.**
5. **Don't force ideas.** Return fewer or empty array for administrative calls.
6. **Tag cross-layer insights.**
7. **Favor "Market the Problem" slightly.**
8. **Multiple content types per idea.**
9. **TARGET AUDIENCE IS B2B TECH MARKETING LEADERS — NOT CONSULTANTS.** Frame everything for VPs of Marketing, CMOs, Heads of Marketing Ops, Directors of Demand Gen. Do NOT extract ideas aimed at consultants or freelancers.
10. **Only extract post-worthy ideas.** Every idea must be strong enough for a standalone LinkedIn post."""

# ──────────────────────────────────────────────────────────────────────
# Drafting system prompt
# ──────────────────────────────────────────────────────────────────────

DRAFTING_SYSTEM_PROMPT = """You are a ghostwriter for Evan Kubitschek, founder of Grow Rogue — a Revenue Operations consultancy specializing in foundational marketing operations for B2B tech companies.

You will be given:
1. **BUSINESS PROFILE** — THE PRIMARY ANCHOR. Every draft must align with this profile.
2. **VOICE SAMPLES** — Evan's published posts. Match style, tone, formatting, and rhythm precisely.
3. **BUSINESS CONTEXT (POSITIONING ONLY)** — How Evan talks about his business in service of clients. Use ONLY for positioning. NOT a content source.
4. **CONTENT IDEA** — The ONLY source for what the post is about. Extracted from CLIENT call transcripts.

## TARGET AUDIENCE — CRITICAL

Evan's primary audience is **B2B tech marketing leaders** — VPs of Marketing, CMOs, Heads of Marketing Ops, Directors of Demand Gen, and RevOps leaders.

**Write TO these people, not to consultants, freelancers, or agency owners.**

If an idea is fundamentally about consulting/freelancing and cannot be reframed for marketing leaders, return: {"skip": true, "reason": "..."}

## YOUR TASK

Write a complete, publish-ready draft that:
- Is built entirely around the CONTENT IDEA (from client calls)
- Speaks directly to B2B tech marketing leaders
- Sounds exactly like Evan — direct, slightly irreverent, technical but accessible
- Uses the same formatting patterns as voice samples

## EVAN'S VOICE RULES

**Structure:** Hook opening → short paragraphs → emoji bullets (💸 ❌ 😐) → CTA or question
**Tone:** Anti-corporate, no-BS, humor and metaphors, comfortable with mild profanity, empathetic
**Patterns:** Leads with anonymized client story, reveals problem behind the problem, natural Tower of Power references
**Never:** Generic platitudes, "5 tips" listicles, corporate jargon, excessive hedging, "leverage" as a verb

## OUTPUT FORMAT

```json
{
  "content_type": "linkedin_post" or "newsletter",
  "title": "A title/subject line for the piece",
  "draft": "The full draft text with newlines for formatting.",
  "editing_notes": "2-3 sentences for Evan: what to check, personalize, or verify.",
  "word_count": 123
}
```

## RULES

1. Match the voice samples exactly.
2. Anonymize everything.
3. LinkedIn posts: 200-500 words. Newsletters: 800-2000 words.
4. Don't force the Tower of Power.
5. Use provided hook options or write a better one.
6. Draft should be 95% done."""


# ──────────────────────────────────────────────────────────────────────
# Loaders
# ──────────────────────────────────────────────────────────────────────

def load_business_profile() -> str:
    path = SCRIPT_DIR / "business_profile" / "profile.md"
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8")


def load_voice_samples(content_type: str = "linkedin_post") -> str:
    samples = []
    if content_type == "newsletter":
        nl_dir = SCRIPT_DIR / "voice_samples" / "newsletters"
        if nl_dir.exists():
            for f in sorted(nl_dir.glob("*.txt")):
                samples.append(f"--- NEWSLETTER: {f.stem} ---\n{f.read_text(encoding='utf-8')}")
    li_dir = SCRIPT_DIR / "voice_samples" / "linkedin"
    if li_dir.exists():
        li_files = sorted(li_dir.glob("*.txt"))
        if len(li_files) > VOICE_SAMPLE_COUNT:
            li_files = li_files[:VOICE_SAMPLE_COUNT]
        for f in li_files:
            samples.append(f"--- LINKEDIN POST: {f.stem} ---\n{f.read_text(encoding='utf-8')}")
    return "\n\n".join(samples)


def load_business_context() -> str:
    path = SCRIPT_DIR / "output" / "business_context_brief.md"
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8")


def build_extraction_system(base_prompt: str, business_profile: str) -> list[dict]:
    full = base_prompt
    if business_profile:
        full += f"\n\n## BUSINESS PROFILE (PRIMARY REFERENCE)\n\n{business_profile}\n"
    return [{"type": "text", "text": full, "cache_control": {"type": "ephemeral"}}]


def build_drafting_system(voice_samples: str, business_context: str,
                          business_profile: str) -> list[dict]:
    parts = [DRAFTING_SYSTEM_PROMPT]
    if business_profile:
        parts.append(f"\n\n## BUSINESS PROFILE (PRIMARY ANCHOR)\n\n{business_profile}")
    parts.append(f"\n\n## VOICE SAMPLES\n\n{voice_samples}")
    if business_context:
        parts.append(
            f"\n\n## BUSINESS CONTEXT (POSITIONING ONLY — NOT A CONTENT SOURCE)\n\n"
            f"Use ONLY for positioning. Do NOT use as source material.\n\n{business_context}"
        )
    return [{"type": "text", "text": "\n".join(parts), "cache_control": {"type": "ephemeral"}}]


# ──────────────────────────────────────────────────────────────────────
# Mapping helpers
# ──────────────────────────────────────────────────────────────────────

MP3_CATEGORY_MAP = {"problem": "Market the Problem", "process": "Market the Process", "proof": "Market the Proof"}
TOWER_LAYER_MAP = {"database_health": "Database Health", "segmentation": "Segmentation", "lifecycle": "Customer Lifecycle", "prioritization": "Prioritization", "speed_to_lead": "Speed to Lead", "general": "General", "cross_layer": "Cross-Layer"}
MP3_SUB_TYPE_MAP = {"silent_struggle": "Silent Struggle", "challenge_wisdom": "Challenge Wisdom", "hidden_cost": "Hidden Cost", "false_solution": "False Solution", "root_cause": "Root Cause", "future_implication": "Future Implication", "permission": "Permission", "decision_filter": "Decision Filter", "how_i_think": "How I Think", "internal_questions": "Internal Questions", "contrast_approach": "Contrast Approach", "open_source_process": "Open Source Process", "client_insight": "Client Insight", "experiment_lesson": "Experiment & Lesson", "before_after": "Before/After", "specific_numbers": "Specific Numbers", "screenshot_evidence": "Screenshot Evidence", "success_story": "Success Story", "implementation_example": "Implementation Example"}
CONTENT_TYPE_MAP = {"linkedin_post": "LinkedIn Post", "newsletter": "Newsletter", "video_script": "Video Script", "thread": "Thread"}


# ──────────────────────────────────────────────────────────────────────
# Transcript reading
# ──────────────────────────────────────────────────────────────────────

def parse_source_info(filepath: Path) -> tuple[str, str | None]:
    stem = filepath.stem
    match = re.match(r"^(\d{4}-\d{2}-\d{2})_(.+)$", stem)
    if match:
        return f"{match.group(2).replace('_', ' ').title()} — {match.group(1)}", match.group(1)
    return stem.replace("_", " ").title(), None


def read_transcripts(transcripts_dir: Path) -> list[dict]:
    files = sorted(transcripts_dir.glob("*.md"))
    return [
        {"path": f, "text": f.read_text(encoding="utf-8"), **dict(zip(["source_call", "source_date"], parse_source_info(f)))}
        for f in files
    ]


# ──────────────────────────────────────────────────────────────────────
# JSON parsing (hardened against common edge cases)
# ──────────────────────────────────────────────────────────────────────

def _strip_fences(text: str) -> str:
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*\n?", "", text)
    text = re.sub(r"\n?```\s*$", "", text)
    return text.strip()


def extract_json_from_response(text: str) -> list[dict]:
    """Parse JSON array from extraction response, with fallbacks."""
    text = _strip_fences(text)

    # Try direct parse
    try:
        parsed = json.loads(text)
        if isinstance(parsed, dict):
            for key in ("ideas", "content_ideas", "results"):
                if key in parsed and isinstance(parsed[key], list):
                    return parsed[key]
            return [parsed]
        return parsed
    except json.JSONDecodeError:
        pass

    # Fallback: find first JSON array in the text
    match = re.search(r"\[[\s\S]*\]", text)
    if match:
        try:
            return json.loads(match.group())
        except json.JSONDecodeError:
            pass

    # Fallback: find first JSON object
    match = re.search(r"\{[\s\S]*?\}", text)
    if match:
        try:
            return [json.loads(match.group())]
        except json.JSONDecodeError:
            pass

    raise json.JSONDecodeError("No valid JSON found", text, 0)


def extract_draft_json(text: str) -> dict:
    """Parse single JSON object from drafting response."""
    text = _strip_fences(text)

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    match = re.search(r"\{[\s\S]*\}", text)
    if match:
        try:
            return json.loads(match.group())
        except json.JSONDecodeError:
            pass

    raise json.JSONDecodeError("No valid JSON found in draft", text, 0)


# ──────────────────────────────────────────────────────────────────────
# Anthropic API — extraction
# ──────────────────────────────────────────────────────────────────────

def chunk_transcript(text: str) -> list[str]:
    if len(text) <= TRANSCRIPT_CHUNK_LIMIT:
        return [text]
    chunks, start = [], 0
    while start < len(text):
        chunks.append(text[start:start + TRANSCRIPT_CHUNK_LIMIT])
        start += TRANSCRIPT_CHUNK_LIMIT - CHUNK_OVERLAP
    return chunks


def deduplicate_ideas(ideas: list[dict]) -> list[dict]:
    seen, unique = set(), []
    for idea in ideas:
        key = re.sub(r"\W+", "", idea.get("title", "").lower())
        if key not in seen:
            seen.add(key)
            unique.append(idea)
    return unique


def extract_ideas(api_client: anthropic.Anthropic, transcript: dict,
                  cached_system: list[dict]) -> list[dict]:
    text = transcript["text"]
    if len(text) < MIN_TRANSCRIPT_CHARS:
        return []

    chunks = chunk_transcript(text)
    all_ideas = []

    for ci, chunk in enumerate(chunks):
        prefix = "Analyze this call transcript and extract content ideas using the MP3 framework. Return only valid JSON.\n\n---\n\n"
        if len(chunks) > 1:
            prefix = f"Analyze this call transcript (part {ci+1}/{len(chunks)}) and extract content ideas. Return only valid JSON.\n\n---\n\n"

        for attempt in range(3):
            try:
                resp = api_client.messages.create(
                    model=CLAUDE_MODEL, max_tokens=8192, system=cached_system,
                    messages=[{"role": "user", "content": prefix + chunk}],
                )
                all_ideas.extend(extract_json_from_response(resp.content[0].text))
                break
            except json.JSONDecodeError as e:
                print(f"    Warning: JSON parse failed (attempt {attempt+1}): {e}")
                if attempt == 2:
                    print(f"    Skipping chunk after 3 failed attempts.")
            except anthropic.RateLimitError:
                time.sleep(2 ** (attempt + 2))
            except anthropic.APIError as e:
                print(f"    API error (attempt {attempt+1}): {e}")
                time.sleep(2 ** (attempt + 1))
                if attempt == 2:
                    print(f"    Skipping chunk after 3 failed attempts.")

        if ci < len(chunks) - 1:
            time.sleep(ANTHROPIC_DELAY)

    if len(chunks) > 1:
        all_ideas = deduplicate_ideas(all_ideas)

    for idea in all_ideas:
        idea["_source_call"] = transcript["source_call"]
        idea["_source_date"] = transcript["source_date"]
        idea["_source_file"] = transcript["path"].name

    return all_ideas


# ──────────────────────────────────────────────────────────────────────
# Anthropic API — drafting
# ──────────────────────────────────────────────────────────────────────

def draft_idea(api_client: anthropic.Anthropic, idea: dict,
               cached_system: list[dict], content_type: str) -> dict | None:
    idea_text = json.dumps(idea, indent=2)
    user_msg = f"## CONTENT IDEA TO DRAFT\n\nContent type: **{content_type}**\n\n```json\n{idea_text}\n```\n\nWrite the full draft now. Return only valid JSON."

    for attempt in range(3):
        try:
            resp = api_client.messages.create(
                model=CLAUDE_MODEL, max_tokens=4096, system=cached_system,
                messages=[{"role": "user", "content": user_msg}],
            )
            result = extract_draft_json(resp.content[0].text)
            if result.get("skip"):
                return None
            return result
        except json.JSONDecodeError as e:
            print(f"      Warning: Draft parse failed (attempt {attempt+1}): {e}")
            if attempt == 2:
                return None
        except anthropic.RateLimitError:
            time.sleep(2 ** (attempt + 2))
        except anthropic.APIError as e:
            print(f"      API error: {e}")
            if attempt == 2:
                return None
            time.sleep(2 ** (attempt + 1))
    return None


# ──────────────────────────────────────────────────────────────────────
# Notion API
# ──────────────────────────────────────────────────────────────────────

def notion_headers(api_key: str) -> dict:
    return {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json", "Notion-Version": NOTION_API_VERSION}


def check_existing_source(notion_key: str, database_id: str, source_call: str) -> bool:
    resp = requests.post(
        f"{NOTION_API_BASE}/databases/{database_id}/query",
        headers=notion_headers(notion_key),
        json={"filter": {"property": "Source Call", "rich_text": {"equals": source_call}}},
        timeout=30,
    )
    return resp.status_code == 200 and len(resp.json().get("results", [])) > 0


NOTION_TEXT_LIMIT = 1900  # Notion limit is 2000 but leave margin for Unicode


def _text_block(btype: str, text: str) -> dict:
    return {"object": "block", "type": btype, btype: {"rich_text": [{"type": "text", "text": {"content": text[:NOTION_TEXT_LIMIT]}}]}}


def _long_text_blocks(text: str, btype: str = "paragraph") -> list[dict]:
    return [_text_block(btype, text[i:i+NOTION_TEXT_LIMIT]) for i in range(0, len(text), NOTION_TEXT_LIMIT)]


def build_page_body(idea: dict, draft: dict | None) -> list[dict]:
    blocks = []

    # ── Full draft (main content) ──
    if draft:
        draft_text = draft.get("draft", "")
        if draft_text:
            blocks.append(_text_block("heading_2", "Full Draft"))
            blocks.extend(_long_text_blocks(draft_text))

        notes = draft.get("editing_notes", "")
        if notes:
            blocks.append(_text_block("heading_2", "Editing Notes"))
            blocks.append(_text_block("paragraph", notes))

        blocks.append(_text_block("paragraph", "───────────────────────────────"))

    # ── Idea details (supporting context below the draft) ──
    for heading, text in [("Core Insight", idea.get("core_insight", "")), ("Content Angle", idea.get("content_angle", ""))]:
        if text:
            blocks.append(_text_block("heading_2", heading))
            blocks.append(_text_block("paragraph", text))

    hooks = idea.get("hook_options", [])
    if hooks:
        blocks.append(_text_block("heading_2", "Hook Options"))
        for h in hooks:
            blocks.append(_text_block("bulleted_list_item", h))

    evidence = idea.get("supporting_evidence", "")
    if evidence:
        blocks.append(_text_block("heading_2", "Supporting Evidence"))
        blocks.append(_text_block("paragraph", evidence))

    quote = idea.get("quotable_moment", "")
    if quote:
        blocks.append(_text_block("heading_2", "Quotable Moment"))
        blocks.append({"object": "block", "type": "quote", "quote": {"rich_text": [{"type": "text", "text": {"content": quote[:NOTION_TEXT_LIMIT]}}]}})

    reasoning = idea.get("reasoning", "")
    if reasoning:
        blocks.append(_text_block("heading_2", "Reasoning"))
        blocks.append(_text_block("paragraph", reasoning))

    return blocks


def create_notion_page(notion_key: str, database_id: str,
                       idea: dict, draft: dict | None) -> str | None:
    mp3_cat = MP3_CATEGORY_MAP.get(idea.get("mp3_category", ""), idea.get("mp3_category", ""))
    sub_type = MP3_SUB_TYPE_MAP.get(idea.get("mp3_sub_type", ""), idea.get("mp3_sub_type", ""))
    tower = TOWER_LAYER_MAP.get(idea.get("tower_layer", ""), idea.get("tower_layer", ""))
    title = (draft or {}).get("title", idea.get("title", "Untitled"))

    properties = {
        "Title": {"title": [{"text": {"content": title[:NOTION_TEXT_LIMIT]}}]},
        "MP3 Category": {"select": {"name": mp3_cat}},
        "MP3 Sub-Type": {"select": {"name": sub_type}},
        "Tower Layer": {"select": {"name": tower}},
        "Status": {"select": {"name": "Draft Ready" if draft else "Raw Idea"}},
        "Confidence": {"select": {"name": idea.get("confidence", "medium").capitalize()}},
        "Source Call": {"rich_text": [{"text": {"content": idea.get("_source_call", "")[:NOTION_TEXT_LIMIT]}}]},
    }

    ctypes = [{"name": CONTENT_TYPE_MAP.get(ct, ct)} for ct in idea.get("content_types", [])]
    if ctypes:
        properties["Content Types"] = {"multi_select": ctypes}
    if idea.get("_source_date"):
        properties["Source Call Date"] = {"date": {"start": idea["_source_date"]}}

    resp = requests.post(
        f"{NOTION_API_BASE}/pages",
        headers=notion_headers(notion_key),
        json={"parent": {"database_id": database_id}, "properties": properties, "children": build_page_body(idea, draft)},
        timeout=30,
    )
    if resp.status_code == 200:
        return resp.json().get("url", "OK")
    print(f"    Notion error {resp.status_code}: {resp.text[:300].encode('ascii', 'replace').decode()}")
    return None


# ──────────────────────────────────────────────────────────────────────
# Main pipeline
# ──────────────────────────────────────────────────────────────────────

def main():
    load_dotenv(dotenv_path=Path(__file__).parent / ".env", override=True)

    parser = argparse.ArgumentParser(description="Extract → Draft → Notion pipeline")
    parser.add_argument("--transcripts-dir", default="./transcripts")
    parser.add_argument("--content-type", choices=["linkedin_post", "newsletter"], default="linkedin_post")
    parser.add_argument("--prompt-file", help="Custom extraction prompt file")
    parser.add_argument("--dry-run", action="store_true", help="Extract and draft but don't push to Notion")
    parser.add_argument("--extract-only", action="store_true", help="Extract ideas only, skip drafting")
    parser.add_argument("--limit", type=int, default=0, help="Process first N transcripts (0 = all)")
    parser.add_argument("--min-confidence", choices=["high", "medium", "low"], default="high")
    parser.add_argument("--skip-existing", action="store_true")
    parser.add_argument("--output-dir", default="./output")
    args = parser.parse_args()

    anthropic_key = os.environ.get("ANTHROPIC_API_KEY")
    notion_key = os.environ.get("NOTION_API_KEY")
    database_id = os.environ.get("NOTION_DATABASE_ID")

    if not anthropic_key:
        print("Error: ANTHROPIC_API_KEY not set.", file=sys.stderr); sys.exit(1)
    if not args.dry_run and not args.extract_only and (not notion_key or not database_id):
        print("Error: NOTION_API_KEY and NOTION_DATABASE_ID required.", file=sys.stderr); sys.exit(1)

    # Load extraction prompt
    extraction_prompt = MP3_SYSTEM_PROMPT
    if args.prompt_file:
        p = Path(args.prompt_file)
        if not p.exists():
            print(f"Error: {p} not found.", file=sys.stderr); sys.exit(1)
        raw = p.read_text(encoding="utf-8")
        m = re.search(r"```\n(.*?)\n```", raw, re.DOTALL)
        extraction_prompt = m.group(1) if m else raw

    # Load shared resources
    bp = load_business_profile()
    if bp:
        print(f"Business profile: {len(bp):,} chars")

    cached_extraction = build_extraction_system(extraction_prompt, bp)

    vs = load_voice_samples(args.content_type)
    bc = load_business_context()
    cached_drafting = build_drafting_system(vs, bc, bp)
    print(f"Voice samples: {len(vs):,} chars | Business context: {len(bc):,} chars")
    print(f"Drafting prompt: {sum(len(b['text']) for b in cached_drafting):,} chars (cached)")

    conf_rank = {"high": 3, "medium": 2, "low": 1}
    min_rank = conf_rank[args.min_confidence]

    # Read transcripts
    tdir = Path(args.transcripts_dir)
    if not tdir.exists():
        print(f"Error: {tdir} not found.", file=sys.stderr); sys.exit(1)
    transcripts = read_transcripts(tdir)
    if args.limit > 0:
        transcripts = transcripts[:args.limit]

    print(f"\n{len(transcripts)} transcripts to process" +
          (" (DRY RUN)" if args.dry_run else "") +
          (" (EXTRACT ONLY)" if args.extract_only else "") + "\n")

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # ── MAIN LOOP ──
    api_client = anthropic.Anthropic(api_key=anthropic_key)
    all_results = []
    s = {"tx": 0, "skip_tiny": 0, "skip_empty": 0, "err": 0,
         "ideas": 0, "drafted": 0, "skip_conf": 0, "skip_aud": 0,
         "notion_ok": 0, "notion_skip": 0, "notion_err": 0,
         "cat": {"problem": 0, "process": 0, "proof": 0}}

    for idx, tx in enumerate(transcripts, 1):
        fname = tx["path"].name
        s["tx"] += 1
        print(f"[{idx}/{len(transcripts)}] {fname}")

        # Step 1: Extract
        try:
            ideas = extract_ideas(api_client, tx, cached_extraction)
        except Exception as e:
            print(f"  ERROR: {e}"); s["err"] += 1; continue

        if not ideas:
            if len(tx["text"]) < MIN_TRANSCRIPT_CHARS:
                print(f"  -> Skipped (too short)"); s["skip_tiny"] += 1
            else:
                print(f"  -> 0 ideas"); s["skip_empty"] += 1
            continue

        for i in ideas:
            s["cat"][i.get("mp3_category", "")] = s["cat"].get(i.get("mp3_category", ""), 0) + 1
        s["ideas"] += len(ideas)

        # Step 2: Filter
        worthy = [i for i in ideas if conf_rank.get(i.get("confidence", "low"), 0) >= min_rank]
        dropped = len(ideas) - len(worthy)
        s["skip_conf"] += dropped

        cat_str = ", ".join(f"{sum(1 for i in ideas if i.get('mp3_category')==c)} {c}"
                           for c in ["problem", "process", "proof"]
                           if any(i.get("mp3_category")==c for i in ideas))
        print(f"  -> {len(ideas)} ideas ({cat_str}), {len(worthy)} post-worthy" +
              (f", {dropped} below {args.min_confidence}" if dropped else ""))

        if args.extract_only:
            all_results.append({"source_file": fname, "source_call": tx["source_call"],
                                "source_date": tx["source_date"], "ideas": ideas})
            if idx < len(transcripts): time.sleep(ANTHROPIC_DELAY)
            continue

        # Step 3: Draft + Step 4: Notion
        tx_results = []
        for idea in worthy:
            title = idea.get("title", "Untitled")[:60]
            print(f"    Drafting: {title}...")

            draft = draft_idea(api_client, idea, cached_drafting, args.content_type)
            if draft is None:
                s["skip_aud"] += 1
                print(f"      -> Skipped (not suitable or failed)")
                continue

            s["drafted"] += 1
            print(f"      -> Drafted ({draft.get('word_count', '?')} words)")

            if not args.dry_run:
                if args.skip_existing:
                    src = idea.get("_source_call", "")
                    if src and check_existing_source(notion_key, database_id, src):
                        s["notion_skip"] += 1
                        print(f"      -> Notion: skipped (exists)"); time.sleep(NOTION_DELAY); continue

                url = create_notion_page(notion_key, database_id, idea, draft)
                if url:
                    s["notion_ok"] += 1; print(f"      -> Notion: created")
                else:
                    s["notion_err"] += 1; print(f"      -> Notion: FAILED")
                time.sleep(NOTION_DELAY)

            tx_results.append({"idea": idea, "draft": draft})
            time.sleep(ANTHROPIC_DELAY)

        all_results.append({"source_file": fname, "source_call": tx["source_call"],
                            "source_date": tx["source_date"],
                            "ideas": [r["idea"] for r in tx_results],
                            "drafts": [r["draft"] for r in tx_results]})

        if idx < len(transcripts):
            time.sleep(ANTHROPIC_DELAY)

    # Save backup
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup = output_dir / f"pipeline_{ts}.json"
    with open(backup, "w", encoding="utf-8") as f:
        json.dump(all_results, f, indent=2, ensure_ascii=False)
    print(f"\nBackup: {backup}")

    # Save markdown drafts
    if not args.extract_only:
        ddir = output_dir / "drafts"; ddir.mkdir(exist_ok=True)
        n = 0
        for r in all_results:
            for d in r.get("drafts", []):
                if not d: continue
                n += 1
                slug = re.sub(r"[\s_]+", "_", re.sub(r"[^\w\s-]", "", d.get("title", "draft")).lower())[:60]
                p = ddir / f"{ts}_{n:03d}_{slug}.md"
                p.write_text(
                    f"# {d.get('title','Untitled')}\n\n*Type: {d.get('content_type','linkedin_post')}*\n"
                    f"*Word count: {d.get('word_count','?')}*\n\n---\n\n{d.get('draft','')}\n\n---\n\n"
                    f"**Editing notes:** {d.get('editing_notes','None')}\n", encoding="utf-8")

    # Summary
    print(f"\n{'='*60}")
    print(f" PIPELINE SUMMARY")
    print(f"{'='*60}")
    print(f" Transcripts: {s['tx']}  (skipped: {s['skip_tiny']} tiny, {s['skip_empty']} empty, {s['err']} errors)")
    print(f" Ideas: {s['ideas']}  (problem: {s['cat'].get('problem',0)}, process: {s['cat'].get('process',0)}, proof: {s['cat'].get('proof',0)})")
    print(f" Below confidence: {s['skip_conf']}")
    if not args.extract_only:
        print(f" Drafts: {s['drafted']}  (skipped: {s['skip_aud']} audience/fail)")
    if not args.dry_run and not args.extract_only:
        print(f" Notion: {s['notion_ok']} created" +
              (f", {s['notion_skip']} skipped" if s['notion_skip'] else "") +
              (f", {s['notion_err']} failed" if s['notion_err'] else ""))
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
