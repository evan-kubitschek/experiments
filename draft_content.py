#!/usr/bin/env python3
"""Draft fully written LinkedIn posts and newsletters from extracted content ideas.

Combines four layers:
1. Business profile (core identity, audience, methodology, POV)
2. Voice samples (published LinkedIn posts + newsletters)
3. Business context brief (distilled from coaching calls)
4. Extracted content ideas (from transcript_to_notion.py)

Produces ready-to-edit drafts in Evan's voice.
"""

import argparse
import json
import os
import random
import re
import sys
import time
from datetime import datetime
from pathlib import Path

import anthropic
from dotenv import load_dotenv

CLAUDE_MODEL = "claude-sonnet-4-5-20250929"
SCRIPT_DIR = Path(__file__).parent

# ──────────────────────────────────────────────────────────────────────
# Drafting system prompt
# ──────────────────────────────────────────────────────────────────────

DRAFTING_SYSTEM_PROMPT = """You are a ghostwriter for Evan Kubitschek, founder of Grow Rogue — a Revenue Operations consultancy specializing in foundational marketing operations for B2B tech companies.

You will be given:
1. **BUSINESS PROFILE** — The foundational document defining who Evan is, what he does, who he serves, how he solves problems, and his unique point of view. THIS IS THE PRIMARY ANCHOR. Every draft must align with this profile. If anything in the other inputs conflicts with the business profile, the profile wins.
2. **VOICE SAMPLES** — Evan's published LinkedIn posts and newsletters. These define his style, tone, formatting, and rhythm. Match these precisely.
3. **BUSINESS CONTEXT (POSITIONING ONLY)** — A strategic brief distilled from Evan's coaching calls. This reflects how Evan talks about his own business IN RELATION TO HOW HE SERVES CLIENTS. Use it ONLY to understand his positioning, messaging, and how he frames his value to clients. Do NOT use it as a source for post topics, stories, or content ideas. The business context is background — the CONTENT IDEA is the only source for what the post is actually about.
4. **CONTENT IDEA** — The ONLY source for what the post is about. These are extracted from CLIENT call transcripts — real conversations with real clients about real problems. The draft must be built around this idea.

## TARGET AUDIENCE — THIS IS CRITICAL

Evan's primary audience is **B2B tech marketing leaders** — VPs of Marketing, CMOs, Heads of Marketing Ops, Directors of Demand Gen, and RevOps leaders at B2B technology companies (SaaS, data platforms, cybersecurity, etc.).

These are the people who:
- Inherited broken marketing automation systems and are trying to fix them
- Are under pressure to show pipeline and attribution results
- Have teams running on Marketo, HubSpot, or Salesforce and know something is wrong but can't pinpoint what
- Are evaluating whether to hire someone like Evan to fix their foundational ops

**Write TO these people, not to other consultants, freelancers, or agency owners.**

When the content idea references a consulting/business-building concept (referral networks, pricing strategies, agency growth), REFRAME it through the lens of what it means for the marketing leader. For example:
- "How I built a referral network" → NOT relevant. Skip or reframe as "Why your ops consultant's network matters when evaluating who to hire"
- "Automating chaos" → VERY relevant. Write directly to the marketing leader living this pain.
- "Fixing foundations before automating" → VERY relevant. This is their daily reality.

If a content idea is fundamentally about consulting/freelancing and cannot be reframed for B2B marketing leaders, say so in the editing_notes and suggest an alternative angle — or flag it as "not suitable for primary audience."

## YOUR TASK

Write a complete, publish-ready draft that:
- Is built entirely around the CONTENT IDEA (from client calls) — this is the only source for post topics and stories
- Speaks directly to B2B tech marketing leaders and their pain points
- Sounds exactly like Evan wrote it — direct, slightly irreverent, technical but accessible
- Uses the same formatting patterns as his voice samples (line breaks between sentences, emoji bullets, bold text, etc.)
- Uses the business profile and business context ONLY for positioning and framing — never as content source
- Goes beyond the content idea — add depth, add Evan's signature style

## EVAN'S VOICE RULES (extracted from his published work)

**Structure:**
- Opens with a hook — punchy, specific, sometimes provocative
- Short paragraphs, often single sentences on their own line
- Uses emoji bullets (💸 ❌ 😐) for lists, not generic dashes
- Ends with a call-to-action or thought-provoking question
- Signs newsletters with "May your data be clean and your workflows documented, Evan"

**Tone:**
- Anti-corporate, no-BS, but not mean
- Uses humor and metaphors freely ("dumpster fire," "duct tape and prayers," "automating chaos")
- Comfortable with mild profanity ("shitstorm," "what the hell," "garbage")
- Empathetic toward ops people stuck cleaning up messes
- Contrarian to "best practices" that assume clean foundations

**Content patterns:**
- Leads with a specific client story (always anonymized)
- Reveals the problem behind the problem — goes deeper than the surface
- References the Tower of Power framework naturally (not forced)
- Contrasts junior execution vs. senior strategy
- Ends with a choice: keep treating symptoms, or fix the disease

**Things Evan NEVER does:**
- Generic LinkedIn thought leader platitudes
- "5 tips to optimize your funnel" style content
- Corporate jargon without calling it out
- Hedge or qualify his opinions excessively
- Use "leverage" as a verb (pet peeve)

## OUTPUT FORMAT

Return a JSON object with these fields:

```json
{
  "content_type": "linkedin_post" or "newsletter",
  "title": "A title/subject line for the piece",
  "draft": "The full draft text, ready to copy-paste and publish. Use newlines for formatting.",
  "editing_notes": "2-3 sentences of notes for Evan: what to double-check, what he might want to personalize, any facts to verify.",
  "word_count": 123
}
```

## RULES

1. **Match the voice samples exactly.** If you're unsure about tone, err on the side of more direct, more specific, and more Evan.
2. **Anonymize everything.** Never use real client names, company names, or identifying details from the content idea. Use descriptors like "a Series B SaaS company" or "a franchise business scaling to 40 locations."
3. **LinkedIn posts should be 200-500 words.** Newsletters should be 800-2000 words.
4. **Don't force the Tower of Power.** Only reference it if it naturally fits the content angle.
5. **Use one of the provided hook options** or write a better one that matches the style.
6. **The draft should be 95% done.** Evan should only need to tweak a few words, not rewrite."""


# ──────────────────────────────────────────────────────────────────────
# Loaders
# ──────────────────────────────────────────────────────────────────────

def load_voice_samples(content_type: str = "linkedin_post") -> str:
    """Load voice samples appropriate for the content type."""
    samples = []

    if content_type == "newsletter":
        # Prefer newsletters, supplement with LinkedIn
        nl_dir = SCRIPT_DIR / "voice_samples" / "newsletters"
        if nl_dir.exists():
            for f in sorted(nl_dir.glob("*.txt")):
                text = f.read_text(encoding="utf-8")
                samples.append(f"--- NEWSLETTER: {f.stem} ---\n{text}")

    li_dir = SCRIPT_DIR / "voice_samples" / "linkedin"
    if li_dir.exists():
        li_files = sorted(li_dir.glob("*.txt"))
        # For LinkedIn posts, use all. For newsletters, use a subset for voice reference
        if content_type == "newsletter":
            li_files = li_files[:5]  # Just a few for voice calibration
        for f in li_files:
            text = f.read_text(encoding="utf-8")
            samples.append(f"--- LINKEDIN POST: {f.stem} ---\n{text}")

    return "\n\n".join(samples)


def load_business_profile() -> str:
    """Load the business profile — the primary anchor for all content generation."""
    path = SCRIPT_DIR / "business_profile" / "profile.md"
    if not path.exists():
        print("Warning: No business profile found at business_profile/profile.md")
        print("Drafting will proceed without business profile (content targeting may be weaker).")
        return ""
    return path.read_text(encoding="utf-8")


def load_business_context() -> str:
    """Load the business context brief."""
    path = SCRIPT_DIR / "output" / "business_context_brief.md"
    if not path.exists():
        print("Warning: No business context brief found. Run extract_coaching_context.py first.")
        print("Drafting will proceed without business context.")
        return ""
    return path.read_text(encoding="utf-8")


def load_ideas(ideas_path: Path) -> list[dict]:
    """Load extracted ideas from a JSON file."""
    with open(ideas_path, encoding="utf-8") as f:
        data = json.load(f)

    # Flatten: the JSON has [{source_file, ideas: [...]}, ...]
    all_ideas = []
    for entry in data:
        source = entry.get("source_file", "")
        for idea in entry.get("ideas", []):
            idea["_source_file"] = source
            all_ideas.append(idea)
    return all_ideas


# ──────────────────────────────────────────────────────────────────────
# Drafting
# ──────────────────────────────────────────────────────────────────────

def draft_idea(client: anthropic.Anthropic, idea: dict, voice_samples: str,
               business_context: str, business_profile: str,
               content_type: str) -> dict | None:
    """Draft a single content piece from an idea."""

    idea_text = json.dumps(idea, indent=2)

    # Business profile comes FIRST — it's the primary anchor
    profile_section = f"""## BUSINESS PROFILE (PRIMARY ANCHOR)

{business_profile}""" if business_profile else ""

    user_message = f"""{profile_section}

## VOICE SAMPLES

{voice_samples}

## BUSINESS CONTEXT (POSITIONING REFERENCE ONLY — NOT A CONTENT SOURCE)

Use this ONLY to understand how Evan talks about his business in service of clients. Do NOT use this as source material for the post.

{business_context if business_context else "(No business context brief available. Draft based on voice samples and content idea only.)"}

## CONTENT IDEA TO DRAFT

Content type to write: **{content_type}**

```json
{idea_text}
```

Write the full draft now. Return only valid JSON."""

    max_retries = 3
    for attempt in range(max_retries):
        try:
            response = client.messages.create(
                model=CLAUDE_MODEL,
                max_tokens=4096,
                system=DRAFTING_SYSTEM_PROMPT,
                messages=[{"role": "user", "content": user_message}],
            )
            text = response.content[0].text.strip()
            # Strip code fences
            text = re.sub(r"^```(?:json)?\s*\n?", "", text)
            text = re.sub(r"\n?```\s*$", "", text)
            return json.loads(text)

        except json.JSONDecodeError as e:
            print(f"    Warning: Could not parse JSON (attempt {attempt + 1}): {e}")
            if attempt == max_retries - 1:
                return None

        except anthropic.RateLimitError:
            wait = 2 ** (attempt + 2)
            print(f"    Rate limited, waiting {wait}s...")
            time.sleep(wait)

        except anthropic.APIError as e:
            print(f"    API error: {e}")
            if attempt == max_retries - 1:
                return None
            time.sleep(2 ** (attempt + 1))

    return None


# ──────────────────────────────────────────────────────────────────────
# Main
# ──────────────────────────────────────────────────────────────────────

def main():
    load_dotenv(dotenv_path=SCRIPT_DIR / ".env", override=True)

    parser = argparse.ArgumentParser(
        description="Draft LinkedIn posts and newsletters from extracted content ideas."
    )
    parser.add_argument("--ideas-file", required=True,
                        help="Path to extracted ideas JSON (from transcript_to_notion.py)")
    parser.add_argument("--content-type", choices=["linkedin_post", "newsletter"], default="linkedin_post",
                        help="Type of content to draft (default: linkedin_post)")
    parser.add_argument("--limit", type=int, default=0,
                        help="Only draft first N ideas (0 = all)")
    parser.add_argument("--confidence", choices=["high", "medium", "low"], default=None,
                        help="Only draft ideas at or above this confidence level")
    parser.add_argument("--category", choices=["problem", "process", "proof"], default=None,
                        help="Only draft ideas in this MP3 category")
    parser.add_argument("--dry-run", action="store_true",
                        help="Show which ideas would be drafted without calling the API")
    parser.add_argument("--output-dir", default="./output/drafts",
                        help="Where to save drafts (default: ./output/drafts)")
    args = parser.parse_args()

    anthropic_key = os.environ.get("ANTHROPIC_API_KEY")
    if not anthropic_key:
        print("Error: ANTHROPIC_API_KEY not set.", file=sys.stderr)
        sys.exit(1)

    # Load all inputs
    print("Loading inputs...")
    ideas = load_ideas(Path(args.ideas_file))
    print(f"  {len(ideas)} ideas from {args.ideas_file}")

    # Filter
    confidence_rank = {"high": 3, "medium": 2, "low": 1}
    if args.confidence:
        min_rank = confidence_rank[args.confidence]
        ideas = [i for i in ideas if confidence_rank.get(i.get("confidence", "low"), 0) >= min_rank]
        print(f"  Filtered to {len(ideas)} ideas at {args.confidence}+ confidence")

    if args.category:
        ideas = [i for i in ideas if i.get("mp3_category") == args.category]
        print(f"  Filtered to {len(ideas)} ideas in '{args.category}' category")

    if args.limit > 0:
        ideas = ideas[:args.limit]
        print(f"  Limited to {len(ideas)} ideas")

    if not ideas:
        print("No ideas to draft.")
        return

    business_profile = load_business_profile()
    if business_profile:
        print(f"  Business profile: {len(business_profile):,} chars")

    voice_samples = load_voice_samples(args.content_type)
    print(f"  Voice samples: {len(voice_samples):,} chars")

    business_context = load_business_context()
    if business_context:
        print(f"  Business context: {len(business_context):,} chars")

    if args.dry_run:
        print(f"\nDRY RUN — would draft {len(ideas)} {args.content_type}s:")
        for i, idea in enumerate(ideas, 1):
            conf = idea.get("confidence", "?")
            cat = idea.get("mp3_category", "?")
            print(f"  {i}. [{conf}/{cat}] {idea.get('title', 'Untitled')[:80]}")
        return

    # Draft
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    client = anthropic.Anthropic(api_key=anthropic_key)
    results = []
    success = 0
    failed = 0

    print(f"\nDrafting {len(ideas)} {args.content_type}s...")
    for i, idea in enumerate(ideas, 1):
        title = idea.get("title", "Untitled")[:60]
        print(f"\n  [{i}/{len(ideas)}] {title}...")

        draft = draft_idea(client, idea, voice_samples, business_context, business_profile, args.content_type)
        if draft:
            draft["_source_idea"] = idea
            results.append(draft)
            success += 1
            wc = draft.get("word_count", "?")
            print(f"    -> Drafted ({wc} words)")
        else:
            failed += 1
            print(f"    -> FAILED")

        if i < len(ideas):
            time.sleep(2)

    # Save all drafts as JSON
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    json_path = output_dir / f"drafts_{args.content_type}_{timestamp}.json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)

    # Also save individual markdown files for easy reading
    for j, draft in enumerate(results, 1):
        title_slug = re.sub(r"[^\w\s-]", "", draft.get("title", "draft")).lower()
        title_slug = re.sub(r"[\s_]+", "_", title_slug)[:60]
        md_path = output_dir / f"{timestamp}_{j:02d}_{title_slug}.md"

        content = f"# {draft.get('title', 'Untitled')}\n\n"
        content += f"*Type: {draft.get('content_type', args.content_type)}*\n"
        content += f"*Word count: {draft.get('word_count', '?')}*\n\n"
        content += "---\n\n"
        content += draft.get("draft", "")
        content += "\n\n---\n\n"
        content += f"**Editing notes:** {draft.get('editing_notes', 'None')}\n"

        md_path.write_text(content, encoding="utf-8")

    print(f"\n{'='*60}")
    print(f" DRAFTING COMPLETE")
    print(f"{'='*60}")
    print(f"  Drafted:  {success}")
    print(f"  Failed:   {failed}")
    print(f"  JSON:     {json_path}")
    print(f"  Markdown: {output_dir}/")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
