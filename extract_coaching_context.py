#!/usr/bin/env python3
"""Extract a business context brief from coaching call transcripts.

Reads all coaching transcripts and uses the Anthropic API to distill them
into a positioning reference document — how Evan talks about his business
in relation to how he serves clients.

This brief is used as BACKGROUND CONTEXT for content drafting (positioning,
framing, messaging). It is NOT a source for content ideas — those come
exclusively from client call transcripts via transcript_to_notion.py.

Run once (or periodically when new coaching calls are added).
Output: ./output/business_context_brief.md
"""

import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path

import anthropic
from dotenv import load_dotenv

CLAUDE_MODEL = "claude-sonnet-4-5-20250929"
CHUNK_LIMIT = 90_000  # chars per API call


EXTRACTION_PROMPT = """You are analyzing business coaching call transcripts for Evan Kubitschek, founder of Grow Rogue — a Revenue Operations consultancy.

Your job is to extract a **Business Context Brief** that captures how Evan talks about his business IN RELATION TO HOW HE SERVES CLIENTS. This brief will be used as a positioning reference when drafting LinkedIn posts and newsletters. It is NOT used to generate content ideas — content ideas come exclusively from client call transcripts.

Focus on insights that shape how Evan positions his expertise, frames his value, and describes client problems. Ignore purely internal business strategy (agency pricing models, referral network mechanics, freelancer tips) unless it directly informs how he communicates value to B2B marketing leaders.

Extract and organize the following sections:

## 1. POSITIONING & MESSAGING
- How does Evan describe what he does to clients and prospects?
- What language does he use to frame the problems he solves?
- What differentiators were identified or refined?
- How does he position foundational ops work vs. campaign execution?
- How does he talk about his company (Grow Rogue) vs. his previous brand (Revenue Ronin)?

## 2. IDEAL CLIENT PROFILE
- Who are his best clients? What makes them ideal?
- Who does he NOT want to work with? What are the red flags?
- What verticals, company sizes, or stages work best?
- What does the ideal engagement look like?
- What are the common pain points these clients bring to him?

## 3. CLIENT-FACING VALUE FRAMING
- How does Evan explain the value of foundational ops to marketing leaders?
- What analogies, metaphors, or frameworks does he use to make ops concepts click?
- How does he frame the cost of NOT fixing foundations?
- How does he handle objections or skepticism from prospects?
- How does he differentiate himself from agencies or other consultants?

## 4. CONTENT STRATEGY (CLIENT-FACING)
- What content themes resonate most with his target audience?
- What content approaches were discussed or recommended by coaches?
- How does his content connect to the problems his clients face?
- What messaging angles have worked or been recommended?

## 5. KEY METAPHORS & LANGUAGE
- Phrases Evan uses repeatedly that resonate with clients
- Analogies that make technical concepts accessible to marketing leaders
- Language patterns that are distinctly "Evan"
- Things coaches or peers said Evan should lean into

## 6. EVOLUTION OF THINKING
- How has Evan's positioning evolved over time?
- Major realizations about how to communicate his value
- Shifts in how he describes client problems
- Strategic decisions about what to emphasize or de-emphasize

Be specific. Use direct quotes where possible. This brief should feel like a positioning dossier — how Evan frames his value to B2B marketing leaders. NOT a business strategy document for consultants. If something was discussed across multiple calls, note the evolution of thinking over time."""


def main():
    load_dotenv(dotenv_path=Path(__file__).parent / ".env", override=True)

    anthropic_key = os.environ.get("ANTHROPIC_API_KEY")
    if not anthropic_key:
        print("Error: ANTHROPIC_API_KEY not set.", file=sys.stderr)
        sys.exit(1)

    coaching_dir = Path(__file__).parent / "coaching_transcripts"
    if not coaching_dir.exists():
        print(f"Error: {coaching_dir} does not exist.", file=sys.stderr)
        sys.exit(1)

    output_dir = Path(__file__).parent / "output"
    output_dir.mkdir(exist_ok=True)

    # Read all coaching transcripts chronologically
    files = sorted(coaching_dir.glob("*.txt"))
    if not files:
        print("No coaching transcripts found.")
        sys.exit(1)

    print(f"Found {len(files)} coaching transcripts.")

    all_text = []
    for f in files:
        text = f.read_text(encoding="utf-8")
        all_text.append(f"--- COACHING CALL: {f.stem} ---\n{text}\n")

    combined = "\n".join(all_text)
    print(f"Total text: {len(combined):,} characters ({len(combined)/1000:.0f}K)")

    # Chunk if needed
    chunks = []
    if len(combined) <= CHUNK_LIMIT:
        chunks = [combined]
    else:
        current = ""
        for entry in all_text:
            if len(current) + len(entry) > CHUNK_LIMIT and current:
                chunks.append(current)
                current = entry
            else:
                current += entry
        if current:
            chunks.append(current)

    print(f"Split into {len(chunks)} chunks for processing.")

    client = anthropic.Anthropic(api_key=anthropic_key)

    # Process each chunk to extract partial briefs
    partial_briefs = []
    for i, chunk in enumerate(chunks, 1):
        print(f"\nProcessing chunk {i}/{len(chunks)}...", end="", flush=True)

        user_msg = f"Here are coaching call transcripts to analyze:\n\n{chunk}"

        response = client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=8192,
            system=EXTRACTION_PROMPT,
            messages=[{"role": "user", "content": user_msg}],
        )
        brief = response.content[0].text
        partial_briefs.append(brief)
        print(f" done ({len(brief):,} chars)")
        if i < len(chunks):
            time.sleep(2)

    # If multiple chunks, merge the partial briefs
    if len(partial_briefs) > 1:
        print("\nMerging partial briefs into final document...")
        merge_prompt = """You previously analyzed coaching call transcripts in multiple batches.
Below are the partial briefs from each batch. Merge them into a single, cohesive Business Context Brief.

Deduplicate, resolve contradictions (prefer more recent information), and create a clean final document.
Keep the same section structure. Be thorough — don't lose important details during the merge."""

        merge_content = "\n\n---\n\n".join(
            [f"BATCH {i+1}:\n{b}" for i, b in enumerate(partial_briefs)]
        )

        response = client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=8192,
            system=merge_prompt,
            messages=[{"role": "user", "content": merge_content}],
        )
        final_brief = response.content[0].text
    else:
        final_brief = partial_briefs[0]

    # Add metadata header
    header = f"""# Business Context Brief — Evan Kubitschek / Grow Rogue

*Auto-generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}*
*Source: {len(files)} coaching call transcripts ({files[0].stem} through {files[-1].stem})*
*Model: {CLAUDE_MODEL}*

---

"""
    final_brief = header + final_brief

    # Save
    output_path = output_dir / "business_context_brief.md"
    output_path.write_text(final_brief, encoding="utf-8")
    print(f"\nBusiness context brief saved: {output_path}")
    print(f"Size: {len(final_brief):,} characters")


if __name__ == "__main__":
    main()
