"""Refresh the figure manifests, plates and requirement register for this edition.

Run from the repository root:
    ./env/Scripts/python.exe "docs/fyp 25-11-2026/source/refresh_manifests.py"
"""

from __future__ import annotations

import json
from pathlib import Path

SRC = Path(__file__).resolve().parent

CAPTIONS = {
    "packages": "Backend packages: the API enqueues, the graph resolves an adapter",
    "components": "Runtime components: one queue separates the request from the work",
    "deployment": "Local deployment: one host, two processes and a loopback fixture",
    "deployment-queued": "Queued deployment: PostgreSQL carries records and the queue",
    "domain-classes": "Candidate, listing and match: the result holds neither input",
    "drafting-classes": "Draft and reports: three checks answer three questions",
    "application-classes": "Adapter contracts: a capability is granted, not inherited",
    "identity-classes": "Account records: every private row names its owner",
    "object-example": "A synthetic packet: three identifiers answer three questions",
    "account-erd": "Account tables: dotted links are lookups, not foreign keys",
    "workflow-erd": "Workflow tables: the question plan is stored JSON",
    "er-overview": "Logical entities: a case begins at a packet, not a listing",
    "storage": "Storage layout: private files sit apart from shared retrieval data",
    "composite": "Worker internals: a claimed item enters by one port, the packet leaves by the other",
    "profile": "Local stereotypes: labels for the document, not runtime grants",
    "context": "System context: two application targets, only one may submit",
    "use-cases": "Use cases: candidates decide, administrators recover",
    "function-scope": "Function scope: implemented work beside the submission limits",
    "application-state": "Application states: outcomes require a human actor",
    "run-state": "Run states: an administrator resumes a stalled run",
    "refresh-sequence": "Refresh: acceptance is 202, completion is later",
    "refresh-activity": "Refresh and indexing: a finished parent is not ready vectors",
    "upload-sequence": "Intake: a refusal names its cause, and a failed parse leaves no profile",
    "approval-sequence": "Approval: the decision commits before the 202 returns",
    "tailoring-activity": "Tailoring: claims are checked before the draft is delivered",
    "tailoring-sequence": "Tailoring call: the chain walks inside one logical call",
    "nav": "Console routes: four workspaces inside one signed-in shell",
    "communication": "Communication: numbers separate the reply from later evidence",
    "interaction-overview": "Interaction overview: two targets, two endings",
    "timing": "Lease timing: ordinal events, not measured seconds",
    "data-flow": "Discovery data flow: what moves, and who owns the result",
}

NEW_STRUCTURE = {
    "deployment-queued": {
        "type": "UML deployment diagram",
        "caption": CAPTIONS["deployment-queued"],
        "alt": (
            "A browser reaches the static console build, which calls the API process over "
            "HTTPS. The API and the supervised worker share PostgreSQL; the worker alone "
            "writes the Chroma directory and the data volume, and only the worker opens a "
            "browser context."
        ),
        "evidence": [
            "src/config/settings.py",
            "src/runs/queue.py",
            "src/rag/chroma_store.py",
            "src/storage/paths.py",
            "scripts/run_worker.py",
        ],
    },
    "identity-classes": {
        "type": "UML class diagram",
        "caption": CAPTIONS["identity-classes"],
        "alt": (
            "User owns access tokens and a model credential, and owns a candidate profile "
            "with its optional equal-opportunity record. Audit events name an actor."
        ),
        "evidence": [
            "src/db/users.py",
            "src/auth/tokens.py",
            "src/db/byok.py",
            "src/db/profiles.py",
            "src/security/audit.py",
            "src/api/scope.py",
        ],
    },
    "er-overview": {
        "type": "Logical entity-relationship diagram",
        "caption": CAPTIONS["er-overview"],
        "alt": (
            "An account owns a profile. The profile produces matches and drafts; a listing is "
            "assessed in a match. A draft feeds a review packet addressed to a listing, the "
            "packet becomes an application case, and the case is executed as a work run."
        ),
        "evidence": [
            "src/db/users.py",
            "src/db/profiles.py",
            "src/db/matches.py",
            "src/db/tailored.py",
            "src/db/approval.py",
            "src/db/applications.py",
            "src/runs/queue.py",
        ],
    },
}

NEW_BEHAVIOR = {
    "run-state": {
        "type": "UML state machine diagram",
        "caption": CAPTIONS["run-state"],
        "alt": (
            "A run starts queued and becomes running. From running it reaches completed, "
            "partial, failed, retry wait, paused or recoverable, and completed and cancelled "
            "are final. An administrator may return a paused, retry wait, recoverable, failed "
            "or partial run to the queue; no worker adopts a stalled run by itself."
        ),
        "evidence": [
            "src/runs/state.py",
            "src/runs/queue.py",
            "src/runs/worker.py",
            "tests/test_durable_queue.py",
            "tests/test_worker_recovery.py",
        ],
    },
    "upload-sequence": {
        "type": "UML sequence diagram",
        "caption": CAPTIONS["upload-sequence"],
        "alt": (
            "The console posts a file. The route validates extension, size and archive "
            "structure. A file refused there is never written. An accepted file is stored, "
            "then parsed; a parse failure removes the stored file and returns a refusal with "
            "its reason, while a readable one returns its fields with warnings."
        ),
        "evidence": [
            "src/api/routes/resumes.py",
            "src/resume/parser.py",
            "src/storage/paths.py",
            "tests/test_resumes_api.py",
        ],
    },
    "tailoring-sequence": {
        "type": "UML sequence diagram",
        "caption": CAPTIONS["tailoring-sequence"],
        "alt": (
            "The tailoring route grounds facts in the listing, sends a masked prompt to the "
            "fallback provider, validates the returned claims, renders the document and "
            "returns the draft with its reports."
        ),
        "evidence": [
            "src/api/routes/tailoring.py",
            "src/llm/fallback.py",
            "src/resume/tailor.py",
            "src/resume/pipeline.py",
            "src/resume/edit.py",
            "tests/test_tailoring_api.py",
        ],
    },
}

PLATES = {
    "home": {
        "type": "Recorded console capture",
        "caption": "Overview: what the agent did, and what is still zero",
        "alt": (
            "Overview shows one tracked application, one awaiting approval, zero verified "
            "submissions and one hundred recorded actions. A next-actions card asks for a "
            "resume to work from."
        ),
        "evidence": ["frontend/src/screens/overview-screen.tsx"],
        "provenance": (
            "Captured at 1440 by 1000 during the WS-33 console audit on 17 November 2026, "
            "against the stored corpus. The account is an audit account, so the counts "
            "belong to it."
        ),
    },
    "discover": {
        "type": "Recorded console capture",
        "caption": "Discover: a weakened score set is disclosed rather than hidden",
        "alt": (
            "Discover lists 50 matches ranked against 8,558 saved jobs. A notice says "
            "semantic scoring was unavailable for part of the corpus, so these scores are "
            "weaker than a full run. Each row carries a score and an expandable reason."
        ),
        "evidence": [
            "frontend/src/screens/matches-screen.tsx",
            "frontend/src/screens/discover/results-list.tsx",
        ],
        "provenance": (
            "Captured at 1440 by 1000 during the WS-33 console audit on 17 November 2026. "
            "The notice reports the state of that run; it is not a claim about the ranker's "
            "normal output."
        ),
    },
    "tailor": {
        "type": "Recorded console capture",
        "caption": "Tailor: one profile, one job, one draft at a time",
        "alt": (
            "Tailor explains that the agent uses only what the resume already says. A list "
            "of jobs already matched to the profile follows, one row per job with its most "
            "recent score."
        ),
        "evidence": ["frontend/src/screens/tailor-screen.tsx"],
        "provenance": (
            "Captured at 1440 by 1000 during the WS-33 console audit on 17 November 2026. "
            "The date in each row is the match timestamp recorded for that account."
        ),
    },
    "review": {
        "type": "Recorded console capture",
        "caption": "Review: the promise made before a packet is prepared",
        "alt": (
            "Two cards. The first says preparing checks the target domain and builds a "
            "payload without contacting the employer or submitting. The second says the "
            "agent cannot answer unsupported questions, bypass a challenge or submit "
            "without a human decision."
        ),
        "evidence": ["frontend/src/screens/approvals-screen.tsx"],
        "provenance": (
            "A crop of the Review screen's two explanatory cards, supplied with the "
            "22 November 2026 pack and carried forward. It shows interface copy, not a "
            "submitted application."
        ),
    },
}

NEW_REQUIREMENTS = [
    {
        "id": "FR-11.13",
        "group": 11,
        "requirement": (
            "Discover narrows the stored corpus by workplace and location, and shows the "
            "active filters as removable chips."
        ),
        "acceptance": (
            "Applying a filter changes the request, the visible chips and the addressable "
            "URL together. Cancelling or pressing Escape discards the draft without "
            "searching."
        ),
        "status": "Implemented",
        "design": "Discover filters dialog",
        "test": "frontend/src/screens/discover/filters-dialog.test.tsx",
    },
    {
        "id": "FR-11.14",
        "group": 11,
        "requirement": (
            "The profile document library pages through owned originals and tailored copies "
            "instead of loading the whole library."
        ),
        "acceptance": (
            "The library shows five documents per page with the shared pager, renders no "
            "pager while everything fits, and restarts paging when the library changes "
            "underneath it."
        ),
        "status": "Implemented",
        "design": "Profile documents tab",
        "test": "frontend/src/screens/profile-screen.test.tsx",
    },
    {
        "id": "FR-11.15",
        "group": 11,
        "requirement": (
            "Account and Security is the one place a candidate reads identity, changes "
            "credentials and manages a personal model key."
        ),
        "acceptance": (
            "The screen offers the three tabs the backend supports and no Sessions tab, "
            "fills the identity card from the authenticated record, and hosts the model-key "
            "card. The profile shows no credential card on any tab."
        ),
        "status": "Implemented",
        "design": "Account and Security screen",
        "test": "frontend/src/screens/account-screen.test.tsx",
    },
    {
        "id": "FR-11.16",
        "group": 11,
        "requirement": "The ranked list states when it is showing a slice of a larger ranked set.",
        "acceptance": (
            "When the server returns a full page, the screen says the list is a slice and "
            "gives the ranked total. A short page is not described as a slice."
        ),
        "status": "Implemented",
        "design": "Match results list",
        "test": "frontend/src/screens/matches-screen.test.tsx",
    },
]


def load(name: str):
    return json.loads((SRC / name).read_text(encoding="utf-8-sig"))


def save(name: str, data) -> None:
    (SRC / name).write_text(json.dumps(data, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")


def main() -> int:
    structure = load("structure-figures.json")
    behavior = load("behavior-figures.json")
    structure.update(NEW_STRUCTURE)
    behavior.update(NEW_BEHAVIOR)
    for data in (structure, behavior):
        for key, entry in data.items():
            if key in CAPTIONS:
                entry["caption"] = CAPTIONS[key]
    save("structure-figures.json", structure)
    save("behavior-figures.json", behavior)
    save("plates.json", PLATES)

    req = load("requirements.json")
    have = {r["id"] for r in req}
    req.extend(r for r in NEW_REQUIREMENTS if r["id"] not in have)
    save("requirements.json", req)

    print(
        f"requirements {len(req)} | structure {len(structure)} | "
        f"behavior {len(behavior)} | plates {len(PLATES)}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
