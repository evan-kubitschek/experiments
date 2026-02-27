#!/usr/bin/env python3
"""Process Fathom call transcripts through the Anthropic API using the MP3 content
framework and push extracted content ideas to a Notion database.

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
SCRIPT_DIR = Path(__file__).parent

# ──────────────────────────────────────────────────────────────────────
# MP3 system prompt (embedded from mp3_extraction_prompt.md)
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

**Market the Problem** — Content that articulates the pain, frustration, and emotional reality of broken marketing operations. Look for:
- Moments where a client describes their frustration or confusion
- Problems Evan diagnoses that the client didn't know they had
- Patterns of dysfunction Evan has seen repeatedly
- "Aha moment" reactions when a root cause is revealed
- Industry myths or "best practices" that are actually causing harm
- Hidden costs the client hadn't considered
- False solutions the client tried before engaging Evan

**Market the Process** — Content that shows how Evan thinks, diagnoses, and solves problems. Look for:
- How Evan explains his diagnostic approach
- Decision frameworks or mental models he uses
- Analogies or metaphors that make complex ops concepts click
- Moments where he walks through his reasoning step-by-step
- Contrasts between his approach and what the client was doing before
- Behind-the-scenes of how he prioritizes what to fix first
- Tower of Power layers being applied in real-time

**Market the Proof** — Content that demonstrates results, transformation, or tangible progress. Look for:
- Before/after comparisons (even partial or in-progress)
- Specific metrics, numbers, or improvements mentioned
- Client reactions to seeing something work correctly for the first time
- Turning points where chaos became clarity
- Screenshots or dashboards worth referencing
- Moments where a fix in one layer unlocked progress in another

## OUTPUT FORMAT

Return a JSON array of content ideas. Extract as many strong ideas as the transcript supports (typically 3-8 per call). Each idea should be a JSON object with these fields:

```json
[
  {
    "mp3_category": "problem" | "process" | "proof",
    "title": "A compelling, specific content hook (not generic). This should read like a LinkedIn post opening line.",
    "core_insight": "The key insight or observation in 2-3 sentences. What makes this worth talking about?",
    "content_angle": "How to frame this as content. What's the narrative structure? What's the tension?",
    "hook_options": ["Option 1 for opening line", "Option 2 for opening line", "Option 3 for opening line"],
    "supporting_evidence": "The specific example, anecdote, or data point from the call that supports this (anonymized — never use client names, use descriptors like 'a Series B SaaS company' or 'a B2B marketplace')",
    "tower_layer": "database_health" | "segmentation" | "lifecycle" | "prioritization" | "speed_to_lead" | "general" | "cross_layer",
    "mp3_sub_type": "For problem: 'silent_struggle' | 'challenge_wisdom' | 'hidden_cost' | 'false_solution' | 'root_cause' | 'future_implication' | 'permission'. For process: 'decision_filter' | 'how_i_think' | 'internal_questions' | 'contrast_approach' | 'open_source_process' | 'client_insight' | 'experiment_lesson'. For proof: 'before_after' | 'specific_numbers' | 'screenshot_evidence' | 'success_story' | 'implementation_example'.",
    "quotable_moment": "A direct quote or near-quote from Evan in the transcript that captures the insight in his natural voice. This should sound like him — direct, slightly irreverent, and clear.",
    "content_types": ["linkedin_post", "newsletter", "video_script", "thread"],
    "confidence": "high" | "medium" | "low",
    "reasoning": "Brief explanation of why this is a strong content idea and what makes it resonate with Evan's target audience."
  }
]
```

## RULES

1. **Anonymize everything.** Never include client names, company names, specific product names, or identifying details. Use descriptors like "a mid-market B2B SaaS company" or "a franchise business scaling to 40 locations."
2. **Prioritize specificity over generality.** "Most companies have dirty data" is weak. "This company had 47,000 contacts and couldn't tell you which ones were customers" is strong.
3. **Capture Evan's actual voice.** The quotable_moment should sound like a real person talking, not a LinkedIn thought leader. Evan says things like "you're automating chaos" and "this is a dumpster fire" — preserve that energy.
4. **Look for the problem behind the problem.** Go five layers deep, as the MP3 framework instructs. The surface complaint is rarely the real content angle.
5. **Don't force ideas.** If a transcript is mostly administrative or scheduling, it's fine to return fewer ideas or even an empty array. Quality over quantity.
6. **Tag cross-layer insights.** Some of the best content comes from showing how a problem in one Tower of Power layer cascades into failures in others. Tag these as "cross_layer."
7. **Favor "Market the Problem" slightly.** Per the MP3 framework, problem content creates the most magnetic resonance and is the easiest to produce consistently. But don't ignore process and proof when they're clearly present.
8. **Multiple content types per idea.** A single insight might work as a LinkedIn post AND a newsletter section AND a video talking point. Tag all applicable types.
9. **TARGET AUDIENCE IS B2B TECH MARKETING LEADERS — NOT CONSULTANTS.** Evan's audience is VPs of Marketing, CMOs, Heads of Marketing Ops, Directors of Demand Gen, and RevOps leaders at B2B technology companies. Every content idea must be framed for THEIR pain points: broken automation, bad data, misaligned sales and marketing, poor attribution, slow lead response. Do NOT extract ideas aimed at consultants, freelancers, or agency owners. If a transcript discusses consulting business strategy (pricing, referrals, networking), only extract it if it can be reframed as insight FOR marketing leaders (e.g., "how to evaluate an ops consultant" or "why your consultant should push back on your punch list")."""

# ──────────────────────────────────────────────────────────────────────
# Business profile loader
# ──────────────────────────────────────────────────────────────────────

def load_business_profile() -> str:
    """Load the business profile for injection into the extraction prompt."""
    path = SCRIPT_DIR / "business_profile" / "profile.md"
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8")


def build_system_prompt(base_prompt: str, business_profile: str) -> str:
    """Inject the business profile into the extraction system prompt."""
    if not business_profile:
        return base_prompt
    # Insert the business profile right after the positioning section header
    # as additional context for better audience targeting
    profile_section = f"""

## BUSINESS PROFILE (PRIMARY REFERENCE)

The following is Evan's complete business profile. Use this as the primary reference for audience targeting, positioning, and content framing. Every extracted idea must align with this profile.

{business_profile}
"""
    # Append to the end of the system prompt, before the closing rules
    return base_prompt + "\n" + profile_section


# ──────────────────────────────────────────────────────────────────────
# Mapping helpers
# ──────────────────────────────────────────────────────────────────────

MP3_CATEGORY_MAP = {
    "problem": "Market the Problem",
    "process": "Market the Process",
    "proof": "Market the Proof",
}

TOWER_LAYER_MAP = {
    "database_health": "Database Health",
    "segmentation": "Segmentation",
    "lifecycle": "Customer Lifecycle",
    "prioritization": "Prioritization",
    "speed_to_lead": "Speed to Lead",
    "general": "General",
    "cross_layer": "Cross-Layer",
}

MP3_SUB_TYPE_MAP = {
    # Problem
    "silent_struggle": "Silent Struggle",
    "challenge_wisdom": "Challenge Wisdom",
    "hidden_cost": "Hidden Cost",
    "false_solution": "False Solution",
    "root_cause": "Root Cause",
    "future_implication": "Future Implication",
    "permission": "Permission",
    # Process
    "decision_filter": "Decision Filter",
    "how_i_think": "How I Think",
    "internal_questions": "Internal Questions",
    "contrast_approach": "Contrast Approach",
    "open_source_process": "Open Source Process",
    "client_insight": "Client Insight",
    "experiment_lesson": "Experiment & Lesson",
    # Proof
    "before_after": "Before/After",
    "specific_numbers": "Specific Numbers",
    "screenshot_evidence": "Screenshot Evidence",
    "success_story": "Success Story",
    "implementation_example": "Implementation Example",
}

CONTENT_TYPE_MAP = {
    "linkedin_post": "LinkedIn Post",
    "newsletter": "Newsletter",
    "video_script": "Video Script",
    "thread": "Thread",
}


# ──────────────────────────────────────────────────────────────────────
# Transcript reading
# ──────────────────────────────────────────────────────────────────────

def parse_source_info(filepath: Path) -> tuple[str, str | None]:
    """Extract source call title and date from filename like 2025-03-15_weekly_sync.md."""
    stem = filepath.stem
    match = re.match(r"^(\d{4}-\d{2}-\d{2})_(.+)$", stem)
    if match:
        date_str = match.group(1)
        title_part = match.group(2).replace("_", " ").title()
        return f"{title_part} — {date_str}", date_str
    return stem.replace("_", " ").title(), None


def read_transcripts(transcripts_dir: Path) -> list[dict]:
    """Read all .md files and return a list of {path, text, source_call, source_date}."""
    files = sorted(transcripts_dir.glob("*.md"))
    transcripts = []
    for f in files:
        text = f.read_text(encoding="utf-8")
        source_call, source_date = parse_source_info(f)
        transcripts.append({
            "path": f,
            "text": text,
            "source_call": source_call,
            "source_date": source_date,
        })
    return transcripts


# ──────────────────────────────────────────────────────────────────────
# Anthropic API — extraction
# ──────────────────────────────────────────────────────────────────────

def extract_json_from_response(text: str) -> list[dict]:
    """Parse JSON from a Claude response, handling markdown code fences."""
    # Strip markdown code blocks if present
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*\n?", "", text)
    text = re.sub(r"\n?```\s*$", "", text)
    text = text.strip()

    parsed = json.loads(text)
    if isinstance(parsed, dict):
        # Sometimes the model wraps in {"ideas": [...]}
        for key in ("ideas", "content_ideas", "results"):
            if key in parsed and isinstance(parsed[key], list):
                return parsed[key]
        return [parsed]
    return parsed


def chunk_transcript(text: str) -> list[str]:
    """Split a long transcript into overlapping chunks."""
    if len(text) <= TRANSCRIPT_CHUNK_LIMIT:
        return [text]

    chunks = []
    start = 0
    while start < len(text):
        end = start + TRANSCRIPT_CHUNK_LIMIT
        chunks.append(text[start:end])
        start = end - CHUNK_OVERLAP
    return chunks


def deduplicate_ideas(ideas: list[dict]) -> list[dict]:
    """Remove near-duplicate ideas by comparing titles."""
    seen_titles: set[str] = set()
    unique = []
    for idea in ideas:
        title_key = re.sub(r"\W+", "", idea.get("title", "").lower())
        if title_key not in seen_titles:
            seen_titles.add(title_key)
            unique.append(idea)
    return unique


MIN_TRANSCRIPT_CHARS = 2_000  # Skip transcripts shorter than this (admin/scheduling calls)


def process_transcript(client: anthropic.Anthropic, transcript: dict,
                       system_prompt: str) -> list[dict]:
    """Send a transcript to Claude and extract content ideas."""
    text = transcript["text"]

    # Skip tiny transcripts — they're almost always admin/scheduling calls
    if len(text) < MIN_TRANSCRIPT_CHARS:
        return []

    chunks = chunk_transcript(text)

    all_ideas: list[dict] = []

    # Build cached system prompt — identical across all calls, so Anthropic
    # caches it after the first request (~90% cost reduction on input tokens)
    cached_system = [
        {
            "type": "text",
            "text": system_prompt,
            "cache_control": {"type": "ephemeral"},
        }
    ]

    for chunk_idx, chunk in enumerate(chunks):
        prefix = "Analyze this call transcript and extract content ideas using the MP3 framework. Return only valid JSON.\n\n---\n\n"
        if len(chunks) > 1:
            prefix = f"Analyze this call transcript (part {chunk_idx + 1}/{len(chunks)}) and extract content ideas using the MP3 framework. Return only valid JSON.\n\n---\n\n"

        max_retries = 3
        for attempt in range(max_retries):
            try:
                response = client.messages.create(
                    model=CLAUDE_MODEL,
                    max_tokens=8192,
                    system=cached_system,
                    messages=[{"role": "user", "content": prefix + chunk}],
                )
                response_text = response.content[0].text
                ideas = extract_json_from_response(response_text)
                all_ideas.extend(ideas)
                break

            except json.JSONDecodeError as e:
                print(f"    Warning: Could not parse JSON from response (attempt {attempt + 1}): {e}")
                if attempt == max_retries - 1:
                    print(f"    Skipping chunk after {max_retries} failed attempts.")

            except anthropic.RateLimitError:
                wait = 2 ** (attempt + 2)
                print(f"    Rate limited, waiting {wait}s...")
                time.sleep(wait)

            except anthropic.APIError as e:
                wait = 2 ** (attempt + 1)
                print(f"    API error (attempt {attempt + 1}): {e}. Retrying in {wait}s...")
                time.sleep(wait)
                if attempt == max_retries - 1:
                    print(f"    Skipping chunk after {max_retries} failed attempts.")

        # Delay between chunks / calls
        if chunk_idx < len(chunks) - 1:
            time.sleep(ANTHROPIC_DELAY)

    if len(chunks) > 1:
        all_ideas = deduplicate_ideas(all_ideas)

    # Attach source info to each idea
    for idea in all_ideas:
        idea["_source_call"] = transcript["source_call"]
        idea["_source_date"] = transcript["source_date"]
        idea["_source_file"] = transcript["path"].name

    return all_ideas


# ──────────────────────────────────────────────────────────────────────
# Notion API — page creation
# ──────────────────────────────────────────────────────────────────────

def notion_headers(api_key: str) -> dict:
    return {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "Notion-Version": NOTION_API_VERSION,
    }


def check_existing_source(notion_key: str, database_id: str, source_call: str) -> bool:
    """Check if a page with this source_call already exists in the database."""
    payload = {
        "filter": {
            "property": "Source Call",
            "rich_text": {"equals": source_call},
        },
    }
    resp = requests.post(
        f"{NOTION_API_BASE}/databases/{database_id}/query",
        headers=notion_headers(notion_key),
        json=payload,
        timeout=30,
    )
    if resp.status_code == 200:
        return len(resp.json().get("results", [])) > 0
    return False


def build_page_body_blocks(idea: dict) -> list[dict]:
    """Build Notion block children for the page body."""
    blocks = []

    sections = [
        ("Core Insight", idea.get("core_insight", "")),
        ("Content Angle", idea.get("content_angle", "")),
    ]

    for heading, text in sections:
        if text:
            blocks.append({
                "object": "block",
                "type": "heading_2",
                "heading_2": {
                    "rich_text": [{"type": "text", "text": {"content": heading}}],
                },
            })
            blocks.append({
                "object": "block",
                "type": "paragraph",
                "paragraph": {
                    "rich_text": [{"type": "text", "text": {"content": text}}],
                },
            })

    # Hook Options
    hooks = idea.get("hook_options", [])
    if hooks:
        blocks.append({
            "object": "block",
            "type": "heading_2",
            "heading_2": {
                "rich_text": [{"type": "text", "text": {"content": "Hook Options"}}],
            },
        })
        for hook in hooks:
            blocks.append({
                "object": "block",
                "type": "bulleted_list_item",
                "bulleted_list_item": {
                    "rich_text": [{"type": "text", "text": {"content": hook}}],
                },
            })

    # Supporting Evidence
    evidence = idea.get("supporting_evidence", "")
    if evidence:
        blocks.append({
            "object": "block",
            "type": "heading_2",
            "heading_2": {
                "rich_text": [{"type": "text", "text": {"content": "Supporting Evidence"}}],
            },
        })
        blocks.append({
            "object": "block",
            "type": "paragraph",
            "paragraph": {
                "rich_text": [{"type": "text", "text": {"content": evidence}}],
            },
        })

    # Quotable Moment
    quote = idea.get("quotable_moment", "")
    if quote:
        blocks.append({
            "object": "block",
            "type": "heading_2",
            "heading_2": {
                "rich_text": [{"type": "text", "text": {"content": "Quotable Moment"}}],
            },
        })
        blocks.append({
            "object": "block",
            "type": "quote",
            "quote": {
                "rich_text": [{"type": "text", "text": {"content": quote}}],
            },
        })

    # Reasoning
    reasoning = idea.get("reasoning", "")
    if reasoning:
        blocks.append({
            "object": "block",
            "type": "heading_2",
            "heading_2": {
                "rich_text": [{"type": "text", "text": {"content": "Reasoning"}}],
            },
        })
        blocks.append({
            "object": "block",
            "type": "paragraph",
            "paragraph": {
                "rich_text": [{"type": "text", "text": {"content": reasoning}}],
            },
        })

    return blocks


def create_notion_page(notion_key: str, database_id: str, idea: dict) -> str | None:
    """Create a Notion page for one content idea. Returns page URL or None on failure."""
    # Map properties
    mp3_cat = MP3_CATEGORY_MAP.get(idea.get("mp3_category", ""), idea.get("mp3_category", ""))
    sub_type = MP3_SUB_TYPE_MAP.get(idea.get("mp3_sub_type", ""), idea.get("mp3_sub_type", ""))
    tower = TOWER_LAYER_MAP.get(idea.get("tower_layer", ""), idea.get("tower_layer", ""))
    confidence = idea.get("confidence", "medium").capitalize()
    content_types = [
        {"name": CONTENT_TYPE_MAP.get(ct, ct)}
        for ct in idea.get("content_types", [])
    ]

    title = idea.get("title", "Untitled Idea")

    properties = {
        "Title": {
            "title": [{"text": {"content": title[:2000]}}],
        },
        "MP3 Category": {
            "select": {"name": mp3_cat},
        },
        "MP3 Sub-Type": {
            "select": {"name": sub_type},
        },
        "Tower Layer": {
            "select": {"name": tower},
        },
        "Status": {
            "select": {"name": "Raw Idea"},
        },
        "Confidence": {
            "select": {"name": confidence},
        },
        "Source Call": {
            "rich_text": [{"text": {"content": idea.get("_source_call", "")[:2000]}}],
        },
    }

    if content_types:
        properties["Content Types"] = {"multi_select": content_types}

    source_date = idea.get("_source_date")
    if source_date:
        properties["Source Call Date"] = {"date": {"start": source_date}}

    # Build page body
    children = build_page_body_blocks(idea)

    payload = {
        "parent": {"database_id": database_id},
        "properties": properties,
        "children": children,
    }

    resp = requests.post(
        f"{NOTION_API_BASE}/pages",
        headers=notion_headers(notion_key),
        json=payload,
        timeout=30,
    )

    if resp.status_code == 200:
        return resp.json().get("url", "OK")
    else:
        print(f"    Notion error {resp.status_code}: {resp.text[:300]}")
        return None


# ──────────────────────────────────────────────────────────────────────
# Main pipeline
# ──────────────────────────────────────────────────────────────────────

def main():
    load_dotenv(dotenv_path=Path(__file__).parent / ".env", override=True)

    parser = argparse.ArgumentParser(
        description="Extract content ideas from Fathom transcripts and push to Notion."
    )
    parser.add_argument("--transcripts-dir", default="./transcripts",
                        help="Path to transcript directory (default: ./transcripts/)")
    parser.add_argument("--prompt-file",
                        help="Path to custom system prompt file (optional, uses embedded default)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Process transcripts and save JSON but don't push to Notion")
    parser.add_argument("--limit", type=int, default=0,
                        help="Only process first N transcripts (0 = all)")
    parser.add_argument("--skip-existing", action="store_true",
                        help="Check Notion for existing pages with same source call before creating")
    parser.add_argument("--output-dir", default="./output",
                        help="Where to save JSON backups (default: ./output/)")
    args = parser.parse_args()

    # Validate env vars
    anthropic_key = os.environ.get("ANTHROPIC_API_KEY")
    notion_key = os.environ.get("NOTION_API_KEY")
    database_id = os.environ.get("NOTION_DATABASE_ID")

    if not anthropic_key:
        print("Error: ANTHROPIC_API_KEY not set.", file=sys.stderr)
        sys.exit(1)
    if not args.dry_run and (not notion_key or not database_id):
        print("Error: NOTION_API_KEY and NOTION_DATABASE_ID required (unless --dry-run).", file=sys.stderr)
        sys.exit(1)

    # Load system prompt
    system_prompt = MP3_SYSTEM_PROMPT
    if args.prompt_file:
        prompt_path = Path(args.prompt_file)
        if not prompt_path.exists():
            print(f"Error: Prompt file not found: {prompt_path}", file=sys.stderr)
            sys.exit(1)
        raw = prompt_path.read_text(encoding="utf-8")
        # Extract content between ``` fences if present
        fence_match = re.search(r"```\n(.*?)\n```", raw, re.DOTALL)
        system_prompt = fence_match.group(1) if fence_match else raw

    # Inject business profile into system prompt for better audience targeting
    business_profile = load_business_profile()
    if business_profile:
        system_prompt = build_system_prompt(system_prompt, business_profile)
        print(f"Business profile loaded ({len(business_profile):,} chars) — injected into extraction prompt.")

    # Read transcripts
    transcripts_dir = Path(args.transcripts_dir)
    if not transcripts_dir.exists():
        print(f"Error: {transcripts_dir} does not exist.", file=sys.stderr)
        sys.exit(1)

    transcripts = read_transcripts(transcripts_dir)
    if args.limit > 0:
        transcripts = transcripts[:args.limit]

    print(f"Found {len(transcripts)} transcripts to process.")
    if args.dry_run:
        print("DRY RUN — will extract ideas but will NOT push to Notion.")
    print()

    # Ensure output dir
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # Process transcripts
    client = anthropic.Anthropic(api_key=anthropic_key)
    all_results: list[dict] = []
    total_ideas = 0
    category_counts = {"problem": 0, "process": 0, "proof": 0}
    confidence_counts = {"high": 0, "medium": 0, "low": 0}
    skipped = 0
    errors = 0

    for idx, transcript in enumerate(transcripts, 1):
        filename = transcript["path"].name
        print(f"Processing transcript {idx}/{len(transcripts)}: {filename}")
        print(f"  WARNING: Client names in transcripts will be anonymized by the extraction prompt.")

        try:
            ideas = process_transcript(client, transcript, system_prompt)
        except Exception as e:
            print(f"  ERROR: {e}")
            errors += 1
            continue

        if not ideas:
            print(f"  -> Extracted 0 ideas (transcript may be administrative)")
            skipped += 1
        else:
            # Count by category
            cat_breakdown = {"problem": 0, "process": 0, "proof": 0}
            for idea in ideas:
                cat = idea.get("mp3_category", "")
                cat_breakdown[cat] = cat_breakdown.get(cat, 0) + 1
                category_counts[cat] = category_counts.get(cat, 0) + 1
                conf = idea.get("confidence", "medium").lower()
                confidence_counts[conf] = confidence_counts.get(conf, 0) + 1

            parts = [f"{v} {k.title()}" for k, v in cat_breakdown.items() if v > 0]
            print(f"  -> Extracted {len(ideas)} ideas ({', '.join(parts)})")

        total_ideas += len(ideas)
        all_results.append({
            "source_file": filename,
            "source_call": transcript["source_call"],
            "source_date": transcript["source_date"],
            "ideas": ideas,
        })

        # Delay between transcripts
        if idx < len(transcripts):
            time.sleep(ANTHROPIC_DELAY)

    # Save local JSON backup
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = output_dir / f"extraction_{timestamp}.json"
    with open(backup_path, "w", encoding="utf-8") as f:
        json.dump(all_results, f, indent=2, ensure_ascii=False)
    print(f"\nLocal backup saved: {backup_path}")

    # Push to Notion
    notion_created = 0
    notion_skipped = 0
    notion_errors = 0

    if not args.dry_run:
        print(f"\nPushing {total_ideas} ideas to Notion...")

        for result in all_results:
            for idea in result["ideas"]:
                # Skip existing check
                if args.skip_existing:
                    source = idea.get("_source_call", "")
                    if source and check_existing_source(notion_key, database_id, source):
                        notion_skipped += 1
                        time.sleep(NOTION_DELAY)
                        continue

                url = create_notion_page(notion_key, database_id, idea)
                if url:
                    notion_created += 1
                else:
                    notion_errors += 1

                time.sleep(NOTION_DELAY)

        print(f"  -> Created {notion_created} Notion pages")
        if notion_skipped:
            print(f"  -> Skipped {notion_skipped} (already existed)")
        if notion_errors:
            print(f"  -> Failed {notion_errors}")

    # Summary
    print(f"\n{'='*60}")
    print(f" EXTRACTION SUMMARY")
    print(f"{'='*60}")
    print(f" Transcripts processed:  {len(transcripts)}")
    print(f" Transcripts skipped:    {skipped} (no ideas extracted)")
    print(f" Transcripts errored:    {errors}")
    print(f" Total ideas extracted:  {total_ideas}")
    print(f"{'='*60}")
    print(f" MP3 CATEGORY BREAKDOWN")
    print(f"   Market the Problem:   {category_counts.get('problem', 0)}")
    print(f"   Market the Process:   {category_counts.get('process', 0)}")
    print(f"   Market the Proof:     {category_counts.get('proof', 0)}")
    print(f"{'='*60}")
    print(f" CONFIDENCE BREAKDOWN")
    print(f"   High:                 {confidence_counts.get('high', 0)}")
    print(f"   Medium:               {confidence_counts.get('medium', 0)}")
    print(f"   Low:                  {confidence_counts.get('low', 0)}")
    print(f"{'='*60}")
    if not args.dry_run:
        print(f" NOTION")
        print(f"   Pages created:        {notion_created}")
        if notion_skipped:
            print(f"   Pages skipped:        {notion_skipped}")
        if notion_errors:
            print(f"   Pages failed:         {notion_errors}")
        print(f"{'='*60}")


if __name__ == "__main__":
    main()
