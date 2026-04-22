# Proof Case Library

Pick the 2 cases that best match the prospect's platform, problem type, and company stage.
At the end of each case in the deck, write a custom "Similar to your challenge:" line that
connects the case to THIS specific prospect's situation.

---

## Apex Roofing
**Descriptor:** Multi-region roofing company · HubSpot + Salesforce · CallRail → Invoca migration
**Best for:** Attribution problems, offline activity measurement (events, calls), multi-region teams, leadership/CFO visibility into ROI, no source-level data flowing to deals

**Their problem:** No attribution from inbound calls to closed revenue. Sales teams across 8 regions uploading leads with no source data. The CFO had zero visibility into which channels were producing ROI — a pure "we need to be there" anecdotal reporting loop with no data to push back on.

**What I built:** Full UTM tracking system with concatenated links, hidden form fields, and cookie persistence. Led the full migration from CallRail to Invoca — phone number porting, IVR configuration, static vs. dynamic tracking decisions. Connected every channel — events, ads, calls — through to CFO-level ROAS reporting. Built source stamping that persisted from first touch through to closed deal.

**Results:** 8 regions standardized under one attribution model · Full ROAS reporting by channel for CFO · End-to-end tracking from first touch to closed deal

---

## Prophecy.io
**Descriptor:** Data integration platform · HubSpot + Salesforce + Qualified
**Best for:** Race conditions between systems, lifecycle stage architecture problems, lead scoring rebuilds, workflow architecture complexity, system sync issues, MQL logic

**Their problem:** Three systems — Qualified, HubSpot, and Salesforce — all writing to the same record fields independently. Lifecycle stages, campaign membership, and MQL status being stamped by overlapping workflows without centralized control. Race conditions meant the order of operations was unpredictable. Similar to a conversion funnel situation: the architecture worked until it didn't.

**What I built:** Consolidated disparate workflows into a centralized processing architecture with strict order-of-operations controls. Rebuilt lead scoring from scratch as a 100-point fit + engagement matrix. Created lifecycle-aware MQL logic so scoring, routing, and stage transitions all flowed through a single controlled path.

**Results:** Race conditions eliminated via centralized workflow architecture · 100-point scoring model built · Lifecycle-aware MQL logic with proper stage management

---

## Instruqt
**Descriptor:** Developer education platform · HubSpot Marketing Hub · Zero-to-one build
**Best for:** Greenfield HubSpot builds, new HubSpot customers, companies moving from no MAP to HubSpot, marketing team enablement, speed-to-launch as a priority

**Their problem:** Growing B2B SaaS company with a sales team that had outpaced their marketing infrastructure. Needed HubSpot Marketing Hub stood up from scratch — contact management, lifecycle architecture, campaign templates, and integrations to talk to their CRM. Their campaign team had no HubSpot experience and needed to be operational quickly.

**What I built:** Full HubSpot Marketing Hub implementation including contact property framework, lifecycle stage architecture, segmentation model, email campaign templates, and campaign attribution reporting. Enabled their marketing team to run and measure campaigns independently within the first 60 days.

**Results:** Marketing Hub live and integrated within 30 days · Campaign team running independently within 60 days · Complete documentation library handed off at engagement close

---

## Trustwell
**Descriptor:** Food safety SaaS · HubSpot audit and migration cleanup
**Best for:** Post-migration audits, messy HubSpot instances, junior-built systems that need a senior review, clients who went live with a partner and now have reliability problems

**Their problem:** Had gone through a HubSpot implementation with a partner who optimized for go-live speed rather than build quality. Workflows had overlapping logic, naming conventions were inconsistent, and the team didn't trust the system enough to build on top of it. Attribution was broken in ways that weren't immediately visible.

**What I built:** Full instance audit with a prioritized working document of every issue found — direct links to affected assets, plain-language explanations, and specific rebuild recommendations. Video walkthroughs for every complex finding. Rebuilt the highest-priority workflows with documented architecture so the team could maintain them independently.

**Results:** Full audit delivered as actionable working doc · Critical workflow issues resolved · Team confidence restored ahead of planned system expansion

---

## Wistia
**Descriptor:** Video marketing platform · Marketo + Salesforce · Enterprise RevOps alignment
**Best for:** Marketo shops, large marketing teams, RevOps alignment between marketing and sales, enterprise-scale operations, clients with sophisticated existing systems who need architecture-level thinking

**Their problem:** Marketing and sales operating with misaligned definitions, inconsistent data, and a Marketo instance that had grown organically without governance. Leadership wanted to understand pipeline contribution from marketing but lacked the architecture to produce reliable attribution.

**What I built:** Rebuilt the scoring and lifecycle architecture in Marketo to align with how the sales team actually qualified leads. Created shared definitions between marketing and sales ops. Built attribution reporting that gave leadership directionally reliable pipeline contribution data.

**Results:** Scoring and lifecycle architecture rebuilt · Marketing/sales alignment on definitions and handoffs · Pipeline attribution reporting trusted by leadership

*"Evan doesn't just execute — he sees around corners. He identified issues we didn't even know we had and built systems that fundamentally changed how our marketing and sales teams work together."* — Jeff Serlin, Wistia
