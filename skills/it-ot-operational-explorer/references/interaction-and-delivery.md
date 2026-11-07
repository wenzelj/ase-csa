# User experience and acceptance criteria

## Shell
Top: application title + current evidence status.
Left: journey library, view switcher, filters (site, role, evidence status).
Centre: pan/zoom canvas with directional animations, scene focus and legend.
Right: narrative of current step, selected object inspector, evidence links, known gaps.
Bottom: Play/Pause, previous/next step, speed, restart, progress scrub, transcript.

## Animation grammar
- Dispatch: activate source component, create a small labelled packet/token.
- Transfer: animate token only on currently active scenario edge and show edge label.
- Receive: highlight target and display its processing action.
- Branch: animate only when a documented branch condition is met; otherwise present an explicit hypothetical choice.
- Completion: present operational outcome and key dependencies.
- Failure: overlay unavailable component, trace relationships and classify impacts as confirmed / possible / unknown.
- Animate UI at a comprehensible pace. Show 'Illustrative playback; not real-time telemetry' prominently.

## Acceptance tests
1. Switching scenarios changes the actual animated sequence and narrated stages.
2. Play, pause, next/previous, restart and speed work; scrub updates visual and narrative states.
3. Every active animation corresponds to a real, qualified scenario step.
4. Keyboard controls and reduced-motion fallbacks work.
5. Components and transitions open evidence with precise source attribution.
6. Filtering does not silently erase crucial path steps; show filtered elements or warn.
7. Failure explorer never asserts unproven failover or outage consequences.
8. Static build can load its included JSON locally through the documented serving method.
9. No runtime calls to LLM or production OT systems are required.
10. Export SVG/PNG of current state and printable journey summary where feasible.

## Suggested documentation
README: install/build/serve, extend JSON with sources, known assumptions, data sensitivity precautions, and how to add a journey.
