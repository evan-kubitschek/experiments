---
name: proposal-deck
description: >
  Generates a tailored Grow Rogue proposal deck in Gamma from a discovery call transcript.
  Use this skill whenever Evan provides a discovery call transcript (as a file path or
  pasted text) and wants a Gamma proposal deck for that prospect. Trigger on any of:
  "generate a proposal deck", "create a Gamma for [client]", "build a proposal from this
  transcript", "turn this call into a deck", "make a deck from this", "proposal deck",
  "/proposal-deck", or any time a discovery transcript is present and a deck/proposal output
  is requested. Also triggers when the user drops a .md transcript file and asks for a deck
  or proposal. Always use this skill — do not attempt to generate the deck without it.
---

# Grow Rogue Proposal Deck Generator

You are generating a tailored Grow Rogue proposal deck in Gamma for a specific prospect,
based on a discovery call transcript. The deck must feel like it was written after a real
conversation — not a generic template. The prospect should read it and feel like Evan was
listening.

## Step 1 — Parse the transcript

Read the full transcript (file or pasted text). Extract:

- **Client name & company** (e.g., "Brittini Smith, Scality")
- **Contacts** (names, titles if mentioned)
- **Current tech stack** (CRM, MAP, integrations mentioned)
- **Pain points** — the specific problems they described. Use their own language where possible.
  Aim for 3–5 distinct, concrete issues (not vague categories).
- **Current state** — where they are today for each pain point (for the before/after slide)
- **Engagement type** — see Step 2
- **Action items / next steps** mentioned on the call
- **Any specific proof case signals** — industries, platforms, or problems that match the library

## Step 2 — Detect engagement type

Choose ONE of the following based on what the client described:

**RETAINER/BUILD** — use this when the client:
- Needs a zero-to-one build (no marketing automation yet, greenfield HubSpot, etc.)
- Has a major ongoing infrastructure problem requiring sustained work
- Is asking about partnership / ongoing support / fractional MOps
- Investment: $6,000–$9,000/month, 3-month initial then month-to-month
- Deck structure: Cover → What I Heard → What This Is Costing You → **How I'd Fix It (3 phases)** → Proof × 2 → How We Work Together → What to Expect → Investment → Next Steps

**ASSESSMENT** — use this when the client:
- Had a bad migration and wants an audit
- Wants a diagnostic / second opinion before committing to ongoing work
- Specifically mentions wanting someone to "review" or "audit" their instance
- Investment: Good $3,000 / Better $5,500 / Best $7,500
- Deck structure: Cover → What I Heard → What This Is Costing You → **What a Good Assessment Looks Like** → Proof × 2 → How We Work Together → Investment (Good/Better/Best) → Next Steps

If you're uncertain, default to RETAINER/BUILD for first-call prospects and ASSESSMENT for
prospects who already have a live system they want reviewed.

## Step 3 — Select 2 proof cases

Read `references/proof-cases.md` for the full library. Pick the 2 cases whose problems and
tech stack most closely match this prospect. Prioritize match on: platform (HubSpot/Marketo/
Salesforce/Pardot), problem type (attribution, lifecycle, scoring, zero-to-one build, migration),
and company stage (early-stage, enterprise, multi-region). Include a 1-line "similar to your
challenge" note tailored to this specific prospect at the end of each proof case.

## Step 4 — Build the Gamma input text

Use the structure below. Fill in the dynamic sections from your transcript analysis. For the
static sections, read `references/static-slides.md` and use the content verbatim — these
slides are pre-written and should not be paraphrased.

```
# Grow Rogue × [Client Company]
[Engagement type label: e.g., "Marketing Operations Partnership Proposal" or "HubSpot Instance Assessment Proposal"]
Prepared for [Contact Name(s)] · [Month Year]
Evan Kubitschek · evan@growrogue.com
---
# What I Heard
[Subtitle: e.g., "Four interconnected gaps..." or "Five compounding issues..."]

[3–5 pain points, each as a ## subheading with a punchy title and 2–4 sentences.
Use the prospect's own language. Be specific — name the actual system, the actual number,
the actual thing that broke. Generic problems don't build trust.]
---
# What This Is Costing You
[3–4 paragraphs. Each starts with a bold "Every [X]..." or "Every day without [Y]..." framing.
Connect each pain point to a business outcome: revenue at risk, team productivity lost,
decision quality degraded, leadership credibility on the line.]
---
[DYNAMIC SECTION — varies by engagement type:]

IF RETAINER/BUILD:
# How I'd Fix It
[Subtitle about structured approach]

## Phase 1: [Name] ([Timeframe])
[What gets built, what gets assessed. End with:]
**Deliverable:** [Concrete output]

## Phase 2: [Name] ([Timeframe])
...

## Phase 3: [Name] (Ongoing)
...

IF ASSESSMENT:
# What a Good Assessment Looks Like
[2 paragraphs describing the working-doc output, the Loom walkthroughs, the stakeholder deck.
Speak to THIS client's specific situation — reference the fact that they can execute themselves,
or that they have a team rollout coming, or whatever is true for them.]

[Bullet list: what areas the assessment will cover, drawn from their specific pain points]
---
# Proof: [Case 1 Name]
[Company descriptor · Stack · Key context]

**Their problem:** [2–3 sentences. Lead with what was broken.]
**What I built:** [2–3 sentences. Specific systems, specific work.]
**Results:** [2–3 bullet-style outcomes]

*Similar to your challenge: [1 line connecting this case to THIS prospect's specific situation.]*
---
# Proof: [Case 2 Name]
[Same structure as above]
---
[STATIC SECTION — copy verbatim from references/static-slides.md:]
# How We Work Together
...
---
# What to Expect
[Only include for RETAINER/BUILD engagements. Skip for ASSESSMENT.]
[6 before/after pairs built from THIS client's current state vs. the future state Evan described.
Format: **Today:** [specific current state] → **After:** [specific future state]]
---
[STATIC or DYNAMIC investment section:]

IF RETAINER/BUILD:
# Investment
[Use the retainer investment template from references/static-slides.md, adjusting the
monthly price based on scope discussed on the call ($6K, $7.5K, or $9K/month).]

IF ASSESSMENT:
# Investment
[Use the Good/Better/Best template from references/static-slides.md.]
---
[STATIC SECTION — copy verbatim from references/static-slides.md:]
# Why Grow Rogue
...
---
# Next Steps
[4 numbered steps. First 2–3 are drawn from action items mentioned on the call (e.g.,
"Review X before kickoff", "Send priority list", "Connect with [stakeholder]"). Last step
is always "We kick off" with a timeframe based on what was discussed.]

Evan Kubitschek · evan@growrogue.com · growrogue.com
```

## Step 5 — Call the Gamma MCP tool

Use these settings every time — do not change them:

```
tool: mcp__f5835b2e-6c2e-492d-b1da-fe923bf358b8__generate
inputText: [the full deck text you built in Step 4]
textMode: preserve
format: presentation
themeId: btc4csl82oq1ou3
cardOptions: { dimensions: "16x9" }
imageOptions: { source: "noImages" }
sharingOptions: { workspaceAccess: "edit", externalAccess: "view" }
```

## Step 6 — Draft the follow-up email

After the Gamma link is returned, draft a short follow-up email in Evan's voice. The email:
- Subject line: `[Client Company] × Grow Rogue — [Proposal type]`
- Opens with a one-line callback to something specific from the call (not generic "great talking")
- Links to the Gamma deck with a brief 1-sentence frame
- Summarizes the 2–3 most important pain points in 1–2 sentences — enough that the prospect
  can forward it with context
- For ASSESSMENT: calls out the tier recommendation and why (one sentence)
- Closes with a clear single next step (from the transcript's action items)
- No more than 150 words. No fluff. No "I hope this finds you well."

## Output format

Present to Evan in this order:
1. **Gamma deck URL** (prominent, at the top)
2. **Engagement type detected** and brief rationale (1 sentence)
3. **Proof cases selected** and why (1 sentence each)
4. **Follow-up email draft** (ready to copy-paste)
