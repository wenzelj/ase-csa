# Claude Code skill: IT/OT Operational Explorer

Creates evidence-backed, animated HTML walkthroughs of how IT/OT applications operate and communicate.

## Install on macOS/Linux

Copy the `it-ot-operational-explorer` folder to `~/.claude/skills/` for all projects, or to `<your-project>/.claude/skills/` for a project-specific skill.

Example after unzipping into your Downloads folder:

```bash
mkdir -p ~/.claude/skills
cp -R ~/Downloads/it-ot-operational-explorer ~/.claude/skills/
```

Then in Claude Code ask:

> Use the it-ot-operational-explorer skill to read this application's CSA and build a working animated HTML explorer. Start with one evidence-supported end-to-end operational journey; implement Play, Pause, Step, speed, and evidence inspection. Keep application components at the centre and distinguish verified from inferred behaviour. Do not invent system facts.

This archive contains a **skill and example data**, not a prebuilt web application. Claude Code uses it to build the application for a specific CSA.
