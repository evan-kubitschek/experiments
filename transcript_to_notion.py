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
import io
import json
import logging
import os
import re
import sys
import time
from datetime import datetime
from pathlib import Path


class CreditExhaustedError(Exception):
    """Raised when the Anthropic API key has no remaining credits."""


# Fix Windows cp1252 console encoding for Unicode output
if sys.stdout.encoding and sys.stdout.encoding.lower().startswith("cp"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

# File logger — always flushed, readable for progress checks
_LOG_PATH = Path(__file__).parent / "output" / "pipeline.log"
_LOG_PATH.parent.mkdir(exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(message)s",
    handlers=[
        logging.FileHandler(_LOG_PATH, mode="w", encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger(__name__)


def _print(msg: str = ""):
    """Print to both console and log file with immediate flush."""
    log.info(msg)

import anthropic
import requests
from dotenv import load_dotenv

# ──────────────────────────────────────────────────────────────────────
# Constants
# ──────────────────────────────────────────────────────────────────────

CLAUDE_MODEL = "claude-sonnet-4-5-20250929"
CLAUDE_DRAFT_MODEL = "claude-sonnet-4-5-20250929"
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

- **Business:** Revenue Operations consultancy specializing in foundational marketing operations for B2B tech companies.
- **Core work:** HubSpot implementations, CRM integrations, lead scoring, attribution tracking, marketing automation — usually cleaning up inherited systems that lack documentation or governance.
- **Philosophy:** Fix people and process before platform. Stop automating chaos.
- **Signature framework:** The Tower of Power — five sequential foundational layers that must be built in order. Skipping layers is why things break.
- **Audience:** Marketing leaders, RevOps managers, and founders at B2B tech companies (typically Series A-C) who are dealing with operational messes they inherited or created and need someone to fix the foundation before anything else works.
- **Voice:** Authentic, anti-corporate, direct. Uses real client war stories. Doesn't sugarcoat. Talks like a person, not a brand. Comfortable with profanity when it lands. No jargon for jargon's sake. No LinkedIn-bro energy. No "Here's the thing..." or "Let me be honest..." cliches.
- **Newsletter:** "The Ops Gap" — focused on the foundational operations problems nobody wants to talk about.

**Tower of Power Layers (bottom-up foundation):**
1. Database Health — Clean data, proper field architecture, deduplication, data governance
2. Segmentation — Meaningful audience segments based on clean data
3. Customer Lifecycle — Defined stages, proper stage definitions, transition criteria
4. Prioritization — Lead scoring, MQL/SQL definitions, routing logic
5. Speed to Lead — Response time optimization, handoff automation, SLA enforcement

**Evan's key themes:**
- The "foundational operations gap" — invisible infrastructure problems that cause automation to fail
- Fixing what's broken before building what's new
- People and process before platform
- The hidden cost of skipping foundations
- Why "best practices" fail when your data is garbage
- Marketing ops as strategic function, not ticket-taking

## YOUR TASK

Analyze the provided transcript and extract content ideas using the MP3 Framework. Aim for a rough pillar mix of **40% Problem / 35% Process / 25% Proof** over time.

---

### PILLAR 1: Market the Problem

**Goal:** Show that you understand their pain better than they do. Meet them in the mess.

**7 Content Angles for Problem Posts:**

1. **Name silent struggles out loud.** Surface the thoughts your audience has but doesn't say — like "I don't even know what half these lifecycle stages mean, but they were here when I got here" or "We have 47 lead statuses and nobody can explain why."
2. **Challenge accepted wisdom.** Push back on industry defaults — "Best practice says implement lead scoring immediately. Best practice is wrong if your database is full of garbage." Question the playbook.
3. **Point out hidden costs.** Show the downstream damage of foundational neglect — wasted ad spend, broken attribution, sales blaming marketing, executives making decisions on bad data. Go beyond the obvious.
4. **Identify false solutions.** Name the things companies try that don't work — buying another tool, hiring another agency, "just migrating to a new CRM." Explain why these are bandaids on a broken bone.
5. **Articulate root causes.** Connect the dots between seemingly separate problems. Bad lead routing, inaccurate reporting, and low email deliverability often trace back to the same root: nobody fixed the database.
6. **Frame future implications.** Where does the current path lead? Paint the picture of compounding operational debt — each shortcut today creates three problems next quarter.
7. **Create permission.** Normalize the mess. "It's not your fault the last agency didn't document anything. But it is your problem now. Here's how to start." Remove shame. Make the first step feel possible.

**Problem Post Checklist:**
- Focuses on ONE specific problem, not a laundry list
- Uses a specific example or scenario (not generic)
- Shows empathy before offering direction
- Goes beneath the surface symptom to the real issue
- Ends with hope or a path forward (not just doom)

---

### PILLAR 2: Market the Process

**Goal:** Show HOW you think and work. Make the invisible visible. Build buy-in before the sales call.

**7 Content Angles for Process Posts:**

1. **Show your decision filters.** "Here's how I evaluate whether a company's marketing ops is actually broken vs. just messy." Share the criteria you use to prioritize.
2. **Share "how I think about X" posts.** "How I think about attribution when nobody has UTMs set up." These aren't how-tos — they're how-you-thinks. Show your reasoning, not just steps.
3. **Break down your internal questions.** "When I'm auditing a HubSpot portal, the first three things I look at are..." Help the audience self-diagnose while demonstrating expertise.
4. **Contrast your approach with others.** "Most consultants start with automation. I start with the database. Here's why." Sharpen your positioning by showing what makes your method different.
5. **Open-source a small piece of your process.** Share a checklist, a diagnostic question, a simple framework. Give real value while reinforcing the larger Tower of Power methodology.
6. **Debrief a client insight or turning point.** "On a call last week, a VP of Marketing said something that stopped me cold..." Use anonymized real moments that show how you think on your feet.
7. **Share experiments and lessons.** "I tried building lead scoring before fixing lifecycle stages for a client. Here's what happened and why I'll never do it again." Show the learning loop.

**Additional Process Content Ideas:**
- Tower of Power deep dives: each layer broken vs. built right
- Behind the scenes of a decision: why you fired a tool, changed a process, or pushed back on a client request
- Client experiments: what they tried, what broke, how you course-corrected together
- Frameworks and systems: checklists, diagnostic templates, workflow SOPs (anonymized)

**Process Post Checklist:**
- Reveals thinking, not just conclusions
- Makes the work feel structured but not rigid
- Connects back to a real problem the audience faces
- Demonstrates expertise without being preachy
- Gives the reader something they can reflect on or apply immediately

---

### PILLAR 3: Market the Proof

**Goal:** Show that the transformation is real. Answer "will this work for me?" before they ask.

**5 Content Formats for Proof Posts:**

1. **Before/After examples.** Show the contrast: "Before: 47 lifecycle stages, no documentation, 30% email bounce rate. After: 5 clean stages, full playbook, 2.1% bounce rate." Collapse the timeline. Make the transformation visible.
2. **Specific results with numbers.** Use real, specific numbers — not rounded marketing claims. "$62,000 engagement over 9 months" is more believable than "helped scale their ops." Odd numbers feel true. Connect metrics to outcomes that matter (pipeline, revenue, time saved).
3. **Screenshot evidence.** Dashboard before/after, Slack messages from happy clients, HubSpot portal snapshots showing clean vs. chaotic setups. Raw and unpolished beats curated and perfect. Always get permission.
4. **Client success stories.** Structure: The protagonist (relatable marketing leader), the struggle (inherited mess, no visibility), the turning point (your engagement), the transformation (specific results), the ripple effect (what changed beyond the immediate fix). Make the reader think "that's me."
5. **Implementation examples.** Show how a framework or recommendation played out in reality. Walk through a specific decision, the options considered, and why you went the direction you did.

**Proof Post Checklist:**
- Includes specific, concrete details (not vague claims)
- Ties results back to foundational methodology (Tower of Power)
- Makes the reader see themselves in the story
- Shows the messy middle, not just the polished outcome
- Builds belief that transformation is possible for them too

---

## WHAT TO LOOK FOR IN TRANSCRIPTS

When processing raw material, extract post ideas by looking for:

- **Moments of surprise or friction** in client calls — things that made Evan pause or push back
- **Patterns across clients** — the same mistake showing up in different companies
- **Specific before/after transformations** — measurable changes from engagement work
- **Counterintuitive insights** — things Evan knows that his audience doesn't expect
- **Emotional moments** — frustration, relief, breakthrough, confusion — these are the hooks
- **Myths or bad advice** being repeated in the market that Evan can challenge with real experience

## OUTPUT FORMAT

Return a JSON array of content ideas. Only extract ideas strong enough to become full LinkedIn posts — skip weak or generic ideas. Each idea:

```json
[
  {
    "mp3_category": "problem" | "process" | "proof",
    "title": "A compelling, specific content hook — should read like a LinkedIn post opening line.",
    "core_insight": "The key insight in 2-3 sentences.",
    "content_angle": "Which numbered angle from the pillar above, and how to frame it.",
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
2. **Prioritize specificity over generality.** Lead with specific scenarios, numbers, tools (HubSpot, Marketo, Salesforce), and job titles (VP of Marketing, RevOps Manager, Head of Demand Gen).
3. **Capture Evan's actual voice** in quotable_moment.
4. **The "five layers deeper" test.** For every problem idea, push past the surface symptom. If the first instinct is "their data is messy," ask why five times until you hit the root cause. That root cause is the idea.
5. **Don't force ideas.** Return fewer or empty array for administrative calls.
6. **Tag cross-layer insights.**
7. **Aim for 40% Problem / 35% Process / 25% Proof** across ideas.
8. **Multiple content types per idea.**
9. **TARGET AUDIENCE IS B2B TECH MARKETING LEADERS — NOT CONSULTANTS.** Frame everything for VPs of Marketing, CMOs, Heads of Marketing Ops, Directors of Demand Gen. Do NOT extract ideas aimed at consultants or freelancers.
10. **Only extract post-worthy ideas.** Every idea must be strong enough for a standalone LinkedIn post.
11. **Use the pillar checklists above** to validate each idea before including it."""

# ──────────────────────────────────────────────────────────────────────
# Drafting system prompt
# ──────────────────────────────────────────────────────────────────────

DRAFTING_SYSTEM_PROMPT = """You are a ghostwriter for Evan Kubitschek, founder of Grow Rogue — a Revenue Operations consultancy specializing in foundational marketing operations for B2B tech companies. His newsletter is called "The Ops Gap" — focused on the foundational operations problems nobody wants to talk about.

You will be given:
1. **BUSINESS PROFILE** — THE PRIMARY ANCHOR. Every draft must align with this profile.
2. **VOICE SAMPLES** — Evan's published posts. Match style, tone, formatting, and rhythm precisely.
3. **BUSINESS CONTEXT (POSITIONING ONLY)** — How Evan talks about his business in service of clients. Use ONLY for positioning. NOT a content source.
4. **CONTENT IDEA** — The ONLY source for what the post is about. Extracted from CLIENT call transcripts.

## TARGET AUDIENCE — CRITICAL

Evan's primary audience is **B2B tech marketing leaders** — VPs of Marketing, CMOs, Heads of Marketing Ops, Directors of Demand Gen, and RevOps leaders at B2B tech companies (typically Series A-C).

**Write TO these people, not to consultants, freelancers, or agency owners.**

If an idea is fundamentally about consulting/freelancing and cannot be reframed for marketing leaders, return: {"skip": true, "reason": "..."}

## POST GENERATION RULES

1. **Every post maps to exactly one pillar.** Problem, Process, or Proof.
2. **Write in Evan's voice.** Direct, conversational, anti-corporate. Short sentences. Real talk. Profanity is fine when it lands naturally — don't force it. No LinkedIn-bro energy. No "Here's the thing..." or "Let me be honest..." cliches.
3. **Lead with specificity.** Vague posts get vague engagement. Use real scenarios, real numbers, real tools (HubSpot, Marketo, Salesforce), and real job titles (VP of Marketing, RevOps Manager, Head of Demand Gen).
4. **The "five layers deeper" test.** For every problem post, push past the surface symptom. If the first instinct is "their data is messy," ask why five times until you hit the root cause. That root cause is the post.
5. **Show, don't pitch.** Never end with a CTA like "DM me to learn more." The post itself should demonstrate expertise. If people want to work with you, they'll find you. End with insight, not a sales pitch.
6. **One idea per post.** Don't try to cover everything. Pick one angle and do it justice.
7. **Use the Tower of Power as a recurring anchor.** Not every post needs to reference it explicitly, but the philosophy should be present — foundations first, sequential layers, people-process-platform order of operations.
8. **Source material matters.** The best posts come from real client interactions, discovery calls, audit findings, and engagement war stories.

## PILLAR QUALITY CHECKLISTS

**Problem Post Checklist:**
- Focuses on ONE specific problem, not a laundry list
- Uses a specific example or scenario (not generic)
- Shows empathy before offering direction
- Goes beneath the surface symptom to the real issue
- Ends with hope or a path forward (not just doom)

**Process Post Checklist:**
- Reveals thinking, not just conclusions
- Makes the work feel structured but not rigid
- Connects back to a real problem the audience faces
- Demonstrates expertise without being preachy
- Gives the reader something they can reflect on or apply immediately

**Proof Post Checklist:**
- Includes specific, concrete details (not vague claims)
- Ties results back to foundational methodology (Tower of Power)
- Makes the reader see themselves in the story
- Shows the messy middle, not just the polished outcome
- Builds belief that transformation is possible for them too

## EVAN'S VOICE RULES

**Structure:** Hook opening → short paragraphs → emoji bullets (💸 ❌ 😐) → closing insight or question
**Tone:** Anti-corporate, no-BS, humor and metaphors, comfortable with profanity when it lands, empathetic toward ops practitioners stuck cleaning up messes they didn't create
**Patterns:** Leads with anonymized client story, reveals problem behind the problem, natural Tower of Power references
**Never:** Generic platitudes, "5 tips" listicles, corporate jargon, excessive hedging, "leverage" as a verb

## WHAT NOT TO DO

- No generic marketing advice that could come from anyone
- No "5 tips to improve your marketing ops" listicles unless each tip is brutally specific
- No thought leadership that doesn't lead back to a real problem, process, or proof point
- No content that sounds like it was written by an AI trying to sound like a LinkedIn influencer
- No "I'm so grateful" or humble-brag framing
- No posts about posting (meta-content about content strategy)
- No jargon walls — if you use a technical term, make sure the surrounding context makes it clear why someone should care
- No CTAs like "DM me" or "link in comments" — end with insight, not a sales pitch

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
3. LinkedIn posts: 150-300 words. Newsletters: 800-2000 words.
4. Don't force the Tower of Power — let it emerge naturally.
5. Use provided hook options or write a better one.
6. Draft should be 95% done.
7. Validate your draft against the relevant pillar checklist above before returning."""


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


def _extract_fathom_url(text: str) -> str:
    """Extract fathom_url from YAML frontmatter."""
    m = re.search(r"^fathom_url:\s*(.+)$", text, re.MULTILINE)
    return m.group(1).strip() if m else ""


def read_transcripts(transcripts_dir: Path) -> list[dict]:
    files = sorted(transcripts_dir.glob("*.md"))
    results = []
    for f in files:
        text = f.read_text(encoding="utf-8")
        source_call, source_date = parse_source_info(f)
        results.append({
            "path": f, "text": text,
            "source_call": source_call, "source_date": source_date,
            "fathom_url": _extract_fathom_url(text),
        })
    return results


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
                _print(f"    Warning: JSON parse failed (attempt {attempt+1}): {e}")
                if attempt == 2:
                    _print(f"    Skipping chunk after 3 failed attempts.")
            except anthropic.RateLimitError:
                time.sleep(2 ** (attempt + 2))
            except anthropic.APIError as e:
                if "credit balance is too low" in str(e):
                    raise CreditExhaustedError(str(e))
                _print(f"    API error (attempt {attempt+1}): {e}")
                time.sleep(2 ** (attempt + 1))
                if attempt == 2:
                    _print(f"    Skipping chunk after 3 failed attempts.")

        if ci < len(chunks) - 1:
            time.sleep(ANTHROPIC_DELAY)

    if len(chunks) > 1:
        all_ideas = deduplicate_ideas(all_ideas)

    for idea in all_ideas:
        idea["_source_call"] = transcript["source_call"]
        idea["_source_date"] = transcript["source_date"]
        idea["_source_file"] = transcript["path"].name
        idea["_fathom_url"] = transcript.get("fathom_url", "")

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
                model=CLAUDE_DRAFT_MODEL, max_tokens=4096, system=cached_system,
                messages=[{"role": "user", "content": user_msg}],
            )
            result = extract_draft_json(resp.content[0].text)
            if result.get("skip"):
                return None
            return result
        except json.JSONDecodeError as e:
            _print(f"      Warning: Draft parse failed (attempt {attempt+1}): {e}")
            if attempt == 2:
                return None
        except anthropic.RateLimitError:
            time.sleep(2 ** (attempt + 2))
        except anthropic.APIError as e:
            if "credit balance is too low" in str(e):
                raise CreditExhaustedError(str(e))
            _print(f"      API error: {e}")
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
    for attempt in range(3):
        try:
            resp = requests.post(
                f"{NOTION_API_BASE}/databases/{database_id}/query",
                headers=notion_headers(notion_key),
                json={"filter": {"property": "Source Call", "rich_text": {"equals": source_call}}},
                timeout=30,
            )
            return resp.status_code == 200 and len(resp.json().get("results", [])) > 0
        except (requests.exceptions.Timeout, requests.exceptions.ConnectionError) as e:
            if attempt == 2:
                _print(f"    Notion query timeout after 3 attempts: {e}")
                return False
            time.sleep(2 ** (attempt + 1))


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
    if idea.get("_fathom_url"):
        properties["Fathom Recording"] = {"url": idea["_fathom_url"]}

    body = {"parent": {"database_id": database_id}, "properties": properties, "children": build_page_body(idea, draft)}
    for attempt in range(3):
        try:
            resp = requests.post(
                f"{NOTION_API_BASE}/pages",
                headers=notion_headers(notion_key),
                json=body,
                timeout=60,
            )
            if resp.status_code == 200:
                return resp.json().get("url", "OK")
            _print(f"    Notion error {resp.status_code}: {resp.text[:300].encode('ascii', 'replace').decode()}")
            if resp.status_code == 429:  # rate limited
                time.sleep(2 ** (attempt + 1))
                continue
            return None
        except (requests.exceptions.Timeout, requests.exceptions.ConnectionError) as e:
            if attempt == 2:
                _print(f"    Notion create timeout after 3 attempts: {e}")
                return None
            time.sleep(2 ** (attempt + 1))
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
    parser.add_argument("--offset", type=int, default=0, help="Skip first N transcripts")
    parser.add_argument("--min-confidence", choices=["high", "medium", "low"], default="high")
    parser.add_argument("--skip-existing", action="store_true")
    parser.add_argument("--output-dir", default="./output")
    args = parser.parse_args()

    anthropic_key = os.environ.get("ANTHROPIC_API_KEY")
    notion_key = os.environ.get("NOTION_API_KEY")
    database_id = os.environ.get("NOTION_DATABASE_ID")

    if not anthropic_key:
        _print("Error: ANTHROPIC_API_KEY not set."); sys.exit(1)
    if not args.dry_run and not args.extract_only and (not notion_key or not database_id):
        _print("Error: NOTION_API_KEY and NOTION_DATABASE_ID required."); sys.exit(1)

    # Load extraction prompt
    extraction_prompt = MP3_SYSTEM_PROMPT
    if args.prompt_file:
        p = Path(args.prompt_file)
        if not p.exists():
            _print(f"Error: {p} not found."); sys.exit(1)
        raw = p.read_text(encoding="utf-8")
        m = re.search(r"```\n(.*?)\n```", raw, re.DOTALL)
        extraction_prompt = m.group(1) if m else raw

    # Load shared resources
    bp = load_business_profile()
    if bp:
        _print(f"Business profile: {len(bp):,} chars")

    cached_extraction = build_extraction_system(extraction_prompt, bp)

    vs = load_voice_samples(args.content_type)
    bc = load_business_context()
    cached_drafting = build_drafting_system(vs, bc, bp)
    _print(f"Voice samples: {len(vs):,} chars | Business context: {len(bc):,} chars")
    _print(f"Drafting prompt: {sum(len(b['text']) for b in cached_drafting):,} chars (cached)")

    conf_rank = {"high": 3, "medium": 2, "low": 1}
    min_rank = conf_rank[args.min_confidence]

    # Read transcripts
    tdir = Path(args.transcripts_dir)
    if not tdir.exists():
        _print(f"Error: {tdir} not found."); sys.exit(1)
    transcripts = read_transcripts(tdir)
    if args.offset > 0:
        transcripts = transcripts[args.offset:]
    if args.limit > 0:
        transcripts = transcripts[:args.limit]

    _print(f"\n{len(transcripts)} transcripts to process" +
          (f" (offset {args.offset})" if args.offset else "") +
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
        _print(f"[{idx}/{len(transcripts)}] {fname}")

        # Early skip: check Notion before burning API tokens
        if args.skip_existing and not args.dry_run and not args.extract_only:
            src = tx.get("source_call", "")
            if src and check_existing_source(notion_key, database_id, src):
                _print(f"  -> Skipped (already in Notion)")
                s["notion_skip"] += 1
                continue

        # Step 1: Extract
        try:
            ideas = extract_ideas(api_client, tx, cached_extraction)
        except CreditExhaustedError:
            _print(f"  STOPPING: Anthropic API credits exhausted. Top up at console.anthropic.com")
            break
        except Exception as e:
            _print(f"  ERROR: {e}"); s["err"] += 1; continue

        if not ideas:
            if len(tx["text"]) < MIN_TRANSCRIPT_CHARS:
                _print(f"  -> Skipped (too short)"); s["skip_tiny"] += 1
            else:
                _print(f"  -> 0 ideas"); s["skip_empty"] += 1
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
        _print(f"  -> {len(ideas)} ideas ({cat_str}), {len(worthy)} post-worthy" +
              (f", {dropped} below {args.min_confidence}" if dropped else ""))

        if args.extract_only:
            all_results.append({"source_file": fname, "source_call": tx["source_call"],
                                "source_date": tx["source_date"], "ideas": ideas})
            if idx < len(transcripts): time.sleep(ANTHROPIC_DELAY)
            continue

        # Step 3: Draft + Step 4: Notion
        tx_results = []
        credits_exhausted = False
        for idea in worthy:
            title = idea.get("title", "Untitled")[:60]
            _print(f"    Drafting: {title}...")

            try:
                draft = draft_idea(api_client, idea, cached_drafting, args.content_type)
            except CreditExhaustedError:
                _print(f"      STOPPING: Anthropic API credits exhausted. Top up at console.anthropic.com")
                credits_exhausted = True
                break
            if draft is None:
                s["skip_aud"] += 1
                _print(f"      -> Skipped (not suitable or failed)")
                continue

            s["drafted"] += 1
            _print(f"      -> Drafted ({draft.get('word_count', '?')} words)")

            if not args.dry_run:
                url = create_notion_page(notion_key, database_id, idea, draft)
                if url:
                    s["notion_ok"] += 1; _print(f"      -> Notion: created")
                else:
                    s["notion_err"] += 1; _print(f"      -> Notion: FAILED")
                time.sleep(NOTION_DELAY)

            tx_results.append({"idea": idea, "draft": draft})
            time.sleep(ANTHROPIC_DELAY)

        all_results.append({"source_file": fname, "source_call": tx["source_call"],
                            "source_date": tx["source_date"],
                            "ideas": [r["idea"] for r in tx_results],
                            "drafts": [r["draft"] for r in tx_results]})

        if credits_exhausted:
            break

        if idx < len(transcripts):
            time.sleep(ANTHROPIC_DELAY)

    # Save backup
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup = output_dir / f"pipeline_{ts}.json"
    with open(backup, "w", encoding="utf-8") as f:
        json.dump(all_results, f, indent=2, ensure_ascii=False)
    _print(f"\nBackup: {backup}")

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
    _print(f"\n{'='*60}")
    _print(f" PIPELINE SUMMARY")
    _print(f"{'='*60}")
    _print(f" Transcripts: {s['tx']}  (skipped: {s['skip_tiny']} tiny, {s['skip_empty']} empty, {s['err']} errors)")
    _print(f" Ideas: {s['ideas']}  (problem: {s['cat'].get('problem',0)}, process: {s['cat'].get('process',0)}, proof: {s['cat'].get('proof',0)})")
    _print(f" Below confidence: {s['skip_conf']}")
    if not args.extract_only:
        _print(f" Drafts: {s['drafted']}  (skipped: {s['skip_aud']} audience/fail)")
    if not args.dry_run and not args.extract_only:
        _print(f" Notion: {s['notion_ok']} created" +
              (f", {s['notion_skip']} skipped" if s['notion_skip'] else "") +
              (f", {s['notion_err']} failed" if s['notion_err'] else ""))
    _print(f"{'='*60}")


if __name__ == "__main__":
    main()
