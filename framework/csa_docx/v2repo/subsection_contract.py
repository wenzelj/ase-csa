"""S623: versioned V2 subsection evidence contracts.

The answer model does not answer a subsection from its heading alone. It needs
an explicit contract that says what the subsection must answer and which
evidence is allowed to answer it. S607-S613 answer contracts and obligations
are answer-format rules (how to write a block); this module adds the V2
retrieval requirements that constrain what evidence a block may rely on.

The contract is deterministic and serialisable: ``build()`` reads only the
subsection key, the question text and the explicitly supplied options. It has
no project-data access, so the same inputs always give the same output and the
output can be embedded in a card, diffed in review, or replayed in tests.

A generic fallback is returned for a subsection whose key has no specialised
contract (``specialised=False``). A specialised contract is returned only when
the caller explicitly opts it in; the framework never widens a subsection's
application scope from a key alone (``widens_scope`` is always False and the
application view never defaults to a wider value than the caller states).

No project facts and no inferred host identities appear in a contract: the
only free-text values are the subsection's own key and question, which the
caller supplies and which the card already shows.
"""
from __future__ import annotations

import hashlib
import json

VERSION = "v2-subsection-contract-v1"
MAX_BYTES = 12000
SPECIALISED_KEYS = ()

VALID_VIEWS = ("owned", "application", "global")
VALID_RELATIONSHIP_KINDS = ("flow", "runs", "service")
VALID_CLASSIFICATIONS = ("required", "optional", "prohibited")
VALID_EVIDENCE_STATUSES = ("VERIFIED", "INFERRED", "CONFLICTING", "UNCONFIRMED", "NOT_FOUND")
VALID_FRESHNESS = ("newest_capture_first", "prefer_recent", "any")

_REQUIRED_CONTENT = (
    "the current state of the system against the subsection's question, stated as a fact the evidence supports",
    "a rating from the card's rating set with a one-sentence rating reason, when the question asks for one",
)
_OPTIONAL_CONTENT = (
    "a one or two sentence note that states one fact the table rows cannot show, when such a fact is in the evidence",
)
_PROHIBITED_CONTENT = (
    "evidence IDs that are not on the card or added by this run",
    "hosts, addresses, zones, roles or counts the cited evidence does not state",
    "another application's facts presented as this application's facts",
    "an inferred host identity not recorded by the host register",
    "NOT_FOUND evidence presented as if it had been found",
)

_FALLBACK_FACTS = (
    "the current state of the part or practice the question names",
    "the hosts or role groups where it holds, stated by role not by a list of host names, when the question is per host",
)
_FALLBACK_OBLIGATIONS = (
    "use only evidence IDs present on the card or added by this run",
    "write a QUESTION: line for each fact the card's evidence does not answer",
    "preserve supported facts and capture evidence from the answer being replaced, or say why a dropped fact no longer applies",
)
_FALLBACK_AREAS = (
    "the evidence-matrix subject area the subsection's frame names, with every spelling of it",
)
_FALLBACK_SOURCE_FIELDS = (
    "evidence_id", "status", "claim", "source_title", "question",
)


def specialisation_for(subsection_key: str) -> dict | None:
    """The specialised contract for ``subsection_key``, or None when none exists.

    ``SPECIALISED_KEYS`` is empty for now: a subsection receives either an
    explicitly supplied contract or the documented fallback. No specialised
    contracts are defined by key in this revision, so the framework never
    infers one from a heading.
    """
    key = (subsection_key or "").strip()
    for candidate in SPECIALISED_KEYS:
        if candidate == key:
            return _SPECIALISED[candidate] if candidate in _SPECIALISED else {}
    return None


# Populated by _register() below; kept as a module global so specialised
# contracts can be added without changing this signature.
_SPECIALISED: dict[str, dict] = {}


def options_schema() -> dict:
    """The explicit options a caller may pass to ``build``.

    These are the only ways the contract's content can change. None of them
    is inferred from the subsection key.
    """
    return {
        "application_view": "owned | application | global (never inferred; an omitted key never widens scope)",
        "scope_rule": "which hosts, services, providers and endpoints the subsection may state: 'owned_hosts_only', 'owned_and_scoped_peers', 'owned_and_external_endpoints', 'global'",
        "relationship_kinds": "subset of the allowed graph relationship kinds (flow, runs, service)",
        "evidence_classes": "evidence classes the subsection may cite",
        "rating_rule": "the rating the question must state, or 'required' when the question asks for one",
        "freshness": "newest_capture_first | prefer_recent | any",
        "not_found_handling": "write a QUESTION: line stating the fact was not found; never present NOT_FOUND as found",
        "conflict_handling": "state which evidence rows disagree and which one is used; never silently pick one",
        "citation_rule": "cite evidence IDs with basis and scope; never cite a row the card does not show",
        "context_limit": "the bounded evidence context the model may rely on (row cap, candidate cap, digest)",
        "required_facts": "explicit facts the subsection must answer",
        "answer_obligations": "explicit obligations the answer must satisfy",
        "source_fields": "evidence source fields the subsection may cite",
        "specialised": "True when the caller supplies a specialised contract body",
    }


def build(subsection_key: str, question_text: str = "", **options) -> dict:
    """Build one versioned, deterministic subsection contract.

    ``subsection_key`` must be the subsection the caller asked for. Everything
    else is either the question text (free text the caller already knows) or an
    explicit option from ``options_schema()``. Nothing here reads project data
    and nothing here infers scope: a contract cannot widen a subsection's
    application scope implicitly.
    """
    key = (subsection_key or "").strip()
    if not key:
        raise ValueError("subsection_key is required")

    question = " ".join((question_text or "").split())

    view = options.get("application_view") or "owned"
    if view not in VALID_VIEWS:
        raise ValueError(f"application_view must be one of {VALID_VIEWS}")

    scope_rule = options.get("scope_rule") or _scope_rule_for_view(view)
    allowed_kinds = tuple(sorted({k for k in (options.get("relationship_kinds") or VALID_RELATIONSHIP_KINDS)
                                  if k in VALID_RELATIONSHIP_KINDS})) or VALID_RELATIONSHIP_KINDS
    rating_rule = options.get("rating_rule") or "required when the question asks for one"
    freshness = options.get("freshness") or "newest_capture_first"
    if freshness not in VALID_FRESHNESS:
        raise ValueError(f"freshness must be one of {VALID_FRESHNESS}")

    areas = tuple(options.get("evidence_areas") or _FALLBACK_AREAS)
    source_fields = tuple(sorted(set(options.get("source_fields") or _FALLBACK_SOURCE_FIELDS)))
    required_facts = tuple(options.get("required_facts") or _FALLBACK_FACTS)
    obligations = tuple(options.get("answer_obligations") or _FALLBACK_OBLIGATIONS)
    not_found = (options.get("not_found_handling")
                 or "write a QUESTION: line stating the fact was not found; never present NOT_FOUND as found")
    conflict = (options.get("conflict_handling")
                or "state which evidence rows disagree and which one is used; never silently pick one")
    citations = (options.get("citation_rule")
                 or "cite evidence IDs with basis and scope; never cite a row the card does not show")
    context = (options.get("context_limit")
               or "the card's evidence pack: a bounded row set per question, a candidate cap and the digest")

    body = {
        "view": {"application_view": view, "scope_rule": scope_rule},
        "scope": {
            "hosts": "owned hosts of the application, named by role group, not by a list of host names",
            "services": "services the question names; the framework does not add services the question does not ask about",
            "providers": "providers the question names, stated by the evidence that names them",
            "endpoints": "endpoints the question names, stated by the evidence that names them",
        },
        "evidence": {
            "areas": areas,
            "source_fields": source_fields,
            "classes": (options.get("evidence_classes") or list(VALID_EVIDENCE_STATUSES)),
        },
        "answer": {
            "required_facts": required_facts,
            "obligations": obligations,
            "rating_rule": rating_rule,
        },
        "handling": {
            "freshness": freshness,
            "not_found": not_found,
            "conflict": conflict,
            "citations": citations,
            "context_limit": context,
        },
        "graph": {
            "allowed_relationship_kinds": allowed_kinds,
        },
        "content": {
            "required": _REQUIRED_CONTENT,
            "optional": _OPTIONAL_CONTENT,
            "prohibited": _PROHIBITED_CONTENT,
        },
    }

    if options.get("specialised"):
        specialised = dict(options.get("specialised_body") or {})
        for k, v in specialised.items():
            if k not in body:
                continue
            if isinstance(body[k], dict) and isinstance(v, dict):
                for kk, vv in v.items():
                    if kk in body[k]:
                        body[k][kk] = vv
            else:
                body[k] = v

    return {
        "contract_version": VERSION,
        "section": key,
        "question": question,
        "classification": "specialised" if options.get("specialised") else "fallback",
        "widens_scope": False,
        "body": body,
        "fingerprint": _fingerprint(body),
    }


def _scope_rule_for_view(view: str) -> str:
    return {
        "owned": "owned_hosts_only",
        "application": "owned_and_scoped_peers",
        "global": "owned_and_external_endpoints",
    }[view]


def _fingerprint(body: dict) -> str:
    """A stable content hash of the contract body, independent of dict order."""
    canonical = json.dumps(body, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]


def render(contract: dict) -> str:
    """The contract as bounded serial text, for embedding in a card or prompt."""
    lines = [f"SUBSECTION CONTRACT: {contract['contract_version']} ({contract['classification']})"]
    lines.append(f"Section: {contract['section']}")
    if contract["question"]:
        lines.append(f"Question: {contract['question']}")
    body = contract["body"]
    lines += ["", "VIEW: " + " | ".join(f"{k}={v}" for k, v in body["view"].items())]
    lines += [f"SCOPE: {k}: {v}" for k, v in sorted(body["scope"].items())]
    lines += [f"EVIDENCE: {k}: {', '.join(body['evidence'][k])}" for k in ("areas", "source_fields", "classes")]
    lines += [f"ANSWER: {k}: {'; '.join(body['answer'][k]) if isinstance(body['answer'][k], tuple) else body['answer'][k]}"
              for k in ("required_facts", "obligations", "rating_rule")]
    lines += [f"HANDLING: {k}: {body['handling'][k]}" for k in ("freshness", "not_found", "conflict", "citations", "context_limit")]
    lines += [f"GRAPH: allowed relationship kinds: {', '.join(body['graph']['allowed_relationship_kinds'])}"]
    lines += [f"CONTENT: {cls}: {'; '.join(body['content'][cls])}" for cls in ("required", "optional", "prohibited")]
    lines += ["", f"fingerprint: {contract['fingerprint']}  widens_scope: {contract['widens_scope']}"]
    text = "\n".join(lines) + "\n"
    if len(text.encode("utf-8")) > MAX_BYTES:
        raise ValueError(f"subsection contract render exceeds {MAX_BYTES} bytes")
    return text


def metadata(contract: dict) -> dict:
    return {
        "contract_version": contract["contract_version"],
        "section": contract["section"],
        "classification": contract["classification"],
        "application_view": contract["body"]["view"]["application_view"],
        "scope_rule": contract["body"]["view"]["scope_rule"],
        "relationship_kinds": list(contract["body"]["graph"]["allowed_relationship_kinds"]),
        "fingerprint": contract["fingerprint"],
        "widens_scope": contract["widens_scope"],
    }


def check_widening(base: dict, wider: dict) -> bool:
    """True when ``wider`` widens ``base``'s application scope.

    Owned is the narrowest view and global the widest. A contract that moves
    from owned to application, or from application to global, widens scope.
    A same-view contract that only narrows the relationship kinds does not
    widen it.
    """
    order = {"owned": 0, "application": 1, "global": 2}
    try:
        b = order[base["body"]["view"]["application_view"]]
        w = order[wider["body"]["view"]["application_view"]]
    except (KeyError, TypeError):
        return False
    return w > b
