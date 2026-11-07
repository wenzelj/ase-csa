---
name: it-ot-operational-explorer
description: Build evidence-backed, animated interactive HTML explorations of IT/OT application behaviour, message flows, dependencies, redundancy, and failure scenarios from Current State Assessments. Use when asked to visualise how an assessed application actually works and communicates, not merely produce infrastructure boxes and arrows.
---

# IT/OT Operational Explorer

## Mission
Turn an application-centric Current State Assessment (CSA) and source evidence into a polished, interactive HTML **operational storytelling experience**. Show what triggers a process, where information travels, what each application component does, and which infrastructure services support it. Treat static topology as a secondary mode, never the sole deliverable.

## Read these references
- `references/architecture-and-evidence.md` for the data model and evidence controls.
- `references/interaction-and-delivery.md` for animation, UI and acceptance tests.
- `examples/scenario-example.json` for a **fictional illustrative** scenario structure. Never adopt its facts as verified user-environment evidence.

## Essential experience
Build an application that starts with a short explanation of the assessed application and a **Choose a journey** menu of actual evidence-supported operational processes, e.g. telemetry received, control message dispatched, identity lookup, failover sequence. A journey must contain:
1. Trigger and initial source
2. Ordered stages with participating components and specific behaviour
3. Directed communication transitions (and protocol/ports only if confirmed)
4. Destination and outcome
5. Evidence link and confidence for each stage and transition

When a user presses Play, animate a labelled message/token along each **verified or expressly qualified** connection; briefly emphasise the executing component and update a synchronised narrative panel. Provide pause, step forward/back, replay, playback speed, timeline scrub, and reduced-motion support. Clicking a component opens an evidence-backed inspector. Clicking a path explains what moves across it, its direction, and what is unknown. Do not automatically animate every connection; only animate transitions in the selected scenario.

## Required views
- **Journey mode (default):** an animated story of how the application performs a function.
- **Dependencies:** upstream/downstream systems and supporting services with selectable focus.
- **Site view:** logical grouping by site/network boundary, with cross-site flows.
- **Resilience explorer:** failure impact and documented alternate paths, distinguishing proven vs hypothetical outcomes.
- **Evidence mode:** trace every claimed node, stage, and connection to source files and page/section references.

Views must all use the **same canonical data model** and share selection state. Represent application services differently from hosts: a service RUNS_ON a host, and a host is LOCATED_AT a site. Avoid falsely implying that a business message travels directly between physical host boxes when the evidence only establishes an application-level integration.

## Technologies
Default: React + TypeScript + Vite; `@xyflow/react` custom nodes/edges, SVG path motion for travelling tokens, ELK.js or dagre for automatic arrangement; CSS/Tailwind for panels and styling. Use D3 only for a specialised view where it improves presentation. No need for Three.js unless a genuinely spatial view materially helps comprehension. Motion must be orchestrated by a deterministic state machine or time-indexed scenario timeline, not by the LLM at playback time. Make animation playback deterministic and independent of network access.

Default deliverable is a runnable web project plus a production static build. If requested, provide a single self-contained HTML file when technically practical and explain any dependency limitations. Do not substitute a mock-up for working interactions.

## Evidence and honesty
- Parse CSA and supporting evidence before designing a visualisation. Every factual node, relationship, stage, role, and outcome needs provenance.
- Never fabricate DNS names, IPs, hosts, services, protocols, ports, temporal ordering, failover triggers or business outcomes.
- Distinguish `verified`, `inferred`, `unknown` and `illustrative` for both nodes and relationships.
- An inference must show its rationale, not impersonate evidence.
- Only verified scenarios can be presented as documented operational behaviour. Inferred stories must have a visible `Inferred — validate` notice. Unknown steps must be visibly interrupted with a question/unknown label, not silently connected.
- Failure mode must not claim a service fails merely because a dependency exists; show `possible impact / needs validation` unless evidence proves the behaviour.
- Avoid invented timing: animation seconds are visual pacing, not real network latency, processing time, or RTO/RPO. State this clearly.
- Never automatically discover or connect to live OT assets; work from documents / supplied models only unless the user explicitly authorises a separate safe integration.
- Prefer Australian English and recognised IT/OT terminology. Preserve product-specific terminology from credible source material.

## Layout and accessibility
Aim for a modern technical investigation tool, not a slide diagram. Use restrained spatial depth, site swimlanes, a compact mini-map, highlights for active flows, component glyphs, collapsible clusters, protocol labels where verified, and a right-side evidence inspector. Avoid gratuitous glowing spaghetti lines, wall-of-boxes diagrams and motion that obscures facts. Colour-code roles consistently, add shape/legend redundancy, keyboard actions, captions, accessible contrast and `prefers-reduced-motion` support.

## Workflow
1. Identify assessed application, user audience and source documents.
2. Extract canonical entities and typed, directed relationships with citations.
3. Catalogue candidate operational journeys and their evidence; prioritise one end-to-end journey.
4. Validate the journey graph: all steps reference known IDs, all transitions have justified edges or clearly flagged gaps.
5. Implement the timeline/player, path animation, component inspector, and evidence drawer.
6. Implement dependencies, site and resilience views using the same model.
7. Run automated checks and manually inspect the build in a browser if browser tools are available; verify play/pause/step/replay, zoom, selection, evidence, reduced motion, unknown relationships and failure-mode claims.
8. Deliver source, static build, JSON model, caveats and instructions to extend the evidence.

## Completion requirement
Deliver an operational animation demonstrating an actual documented process, not just animated decorative lines. If evidence is insufficient, implement a functional explorer with an explicitly labelled *illustrative* scenario, then list exact facts needed to make it authoritative. Do not merge fiction into the CSA.
