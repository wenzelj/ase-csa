"""Deterministic section -> (change_file, docx) resolution.

Phase 1 of the qwen-mcp-factory-plan.md function factory: nothing calling
into this module ever has to know the workspace's folder-naming convention
or guess a filename. Every section's change file already follows one fixed
pattern (``ChangesCSA_<slug>_Section<N>.md`` inside a
``.../<Final Version folder>/reviews/`` directory) and pairs with the single
``.docx`` that sits one level up from ``reviews/``. ``build_manifest`` scans
for that pattern and fails loudly on anything ambiguous rather than guessing.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from pathlib import Path

# Canonical filename: ChangesCSA_<slug>_Section<N>.md -- NO edit-ID numbers in the
# name (edit IDs live inside the file as S<N>-E<n>). The legacy
# _E<a>_E<b>[_Suffix] form is still matched so old files keep resolving, but new
# files must not use it. Having both forms for one section is a loud error.
_CHANGE_FILE_RE = re.compile(
    r"^ChangesCSA_.*_Section(?P<section>\d+)(?:_E\d+_E\d+(?:_.*)?)?\.md$"
)

class ManifestError(RuntimeError):
    """Raised when the workspace layout is ambiguous enough that guessing
    would be unsafe (duplicate section files, zero or multiple docx
    candidates in a Final Version folder, etc.)."""


@dataclass(slots=True)
class SectionEntry:
    section: str
    change_file: str
    docx: str

    def to_dict(self) -> dict[str, str]:
        return asdict(self)


def _is_archived(path: Path, workspace: Path) -> bool:
    """True if any directory component between ``workspace`` and ``path``
    looks like an archive/backup copy (``archive``, ``z_Archive``, ``old ...``,
    ``...archived...``, case-insensitive) -- these hold stale duplicates of
    the same section files and must never compete with the live ones."""
    try:
        relative_parts = path.relative_to(workspace).parts
    except ValueError:
        relative_parts = path.parts
    for part in relative_parts[:-1]:  # exclude the filename itself
        lowered = part.lower()
        if "archive" in lowered or lowered.startswith("old") or lowered.startswith(" old"):
            return True
    return False


def build_manifest(workspace: Path) -> dict[str, SectionEntry]:
    """Scan ``workspace`` for section change files and resolve each to its
    working docx. Raises :class:`ManifestError` on anything ambiguous."""
    workspace = Path(workspace).resolve()
    candidates: dict[str, list[Path]] = {}

    for path in workspace.rglob("reviews/*.md"):
        if _is_archived(path, workspace):
            continue
        match = _CHANGE_FILE_RE.match(path.name)
        if not match:
            continue
        section = str(int(match.group("section")))
        candidates.setdefault(section, []).append(path)

    entries: dict[str, SectionEntry] = {}
    for section, paths in sorted(candidates.items(), key=lambda kv: int(kv[0])):
        if len(paths) > 1:
            raise ManifestError(
                f"Section {section} has {len(paths)} matching change files "
                f"({', '.join(str(p) for p in paths)}); expected exactly one. "
                "Resolve the duplicate before the manifest can be trusted."
            )
        change_file = paths[0]

        final_version_dir = change_file.parent.parent
        docx_candidates = sorted(
            p for p in final_version_dir.glob("*.docx") if not p.name.startswith("~$")
        )
        if not docx_candidates:
            raise ManifestError(
                f"Section {section}'s working folder {final_version_dir} has no "
                ".docx file. Resolve the ambiguity before the manifest can be trusted."
            )
        # When the folder holds several .docx files (baseline original + the
        # working copy the CSA runs have been writing, plus .bak backups
        # excluded above), prefer the one with the highest revision marker in
        # its name - the working document carries "- v1" (or higher), the
        # untouched original baseline does not. Deterministic, never guesses:
        # ties still fail loudly below.
        def revision_key(p: Path) -> tuple[int, str]:
            import re as _re
            m = _re.search(r"v(\d+)", p.name, _re.IGNORECASE)
            return (int(m.group(1)) if m else -1, p.name)
        docx_candidates.sort(key=revision_key, reverse=True)
        top = revision_key(docx_candidates[0])[0]
        if top != -1 and len(docx_candidates) > 1:
            docx_candidates = [p for p in docx_candidates if revision_key(p)[0] == top]
        if len(docx_candidates) > 1:
            # No revision marker on any of them: ambiguous after all.
            raise ManifestError(
                f"Section {section}'s working folder {final_version_dir} has "
                f"{len(docx_candidates)} .docx files ({', '.join(p.name for p in docx_candidates)}); "
                "expected exactly one. Resolve the ambiguity before the manifest can be trusted."
            )

        entries[section] = SectionEntry(
            section=section,
            change_file=str(change_file),
            docx=str(docx_candidates[0]),
        )

    return entries


def refresh_manifest(workspace: Path) -> dict[str, SectionEntry]:
    """Rebuild the manifest by scanning the workspace.

    The manifest is fully derivable from the live folder layout, so it is
    recomputed on demand and never cached to disk: archiving an old Final
    Version folder and dropping in a new one needs no manual reset, and a
    stale cache can never silently resolve a section to a dead path.
    """
    return build_manifest(workspace)


def get_manifest(workspace: Path, *, force_refresh: bool = False) -> dict[str, SectionEntry]:
    """Return the current manifest, scanned fresh from the workspace layout.

    ``force_refresh`` is accepted for backwards compatibility with older
    callers; every call already reflects the live filesystem, so it has no
    distinct effect.
    """
    return build_manifest(workspace)


def resolve_section(workspace: Path, section: str) -> SectionEntry:
    """Return the :class:`SectionEntry` for ``section``, refreshing the
    manifest once and retrying if it's missing (covers a newly added
    section file), rather than silently returning nothing."""
    section = str(int(section))
    manifest = get_manifest(workspace)
    if section not in manifest:
        manifest = refresh_manifest(workspace)
    if section not in manifest:
        raise ManifestError(
            f"No change file found for section {section} under {workspace}. "
            "Expected a file matching ChangesCSA_..._Section"
            f"{section}.md inside a reviews/ directory."
        )
    return manifest[section]
