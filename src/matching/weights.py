"""Match-weight defaults and validation (WS-03, extended WS-20).

The hybrid score blends seven components. Weights are validated once at
settings load (``MATCH_WEIGHTS`` env) and again at every engine call, so an
invalid override can never silently skew ranking.

WS-20 adds the ``lexical`` component (BM25 over the full posting) and — the
important part — **removes** ``redistribute_without``. A component whose value
is unavailable keeps its weight in the denominator; its weight is never moved
onto the components that happen to be present. See ``src/matching/scores.py``
for the full policy.
"""

from __future__ import annotations

DEFAULT_WEIGHTS: dict[str, float] = {
    "semantic": 0.15,
    "lexical": 0.10,
    "skill": 0.25,
    "experience": 0.20,
    "seniority": 0.10,
    "location": 0.10,
    "preference": 0.10,
}

# Sum tolerance: weights are authored as fractions summing to ~1.
SUM_TOLERANCE = 0.01


def validate_weights(weights: dict[str, float]) -> dict[str, float]:
    """Validate a weight mapping; returns a normalized copy.

    Raises:
        ValueError: On unknown components, non-positive weights, or a total
            that does not sum to ~1.0.
    """
    unknown = set(weights) - set(DEFAULT_WEIGHTS)
    if unknown:
        raise ValueError(
            f"Unknown match weight components: {sorted(unknown)}; "
            f"expected exactly {sorted(DEFAULT_WEIGHTS)}"
        )
    missing = set(DEFAULT_WEIGHTS) - set(weights)
    if missing:
        raise ValueError(f"Missing match weight components: {sorted(missing)}")
    for component, value in weights.items():
        if not isinstance(value, (int, float)) or isinstance(value, bool) or value <= 0:
            raise ValueError(f"Match weight {component!r} must be a positive number, got {value!r}")
    total = sum(weights.values())
    if abs(total - 1.0) > SUM_TOLERANCE:
        raise ValueError(
            f"Match weights must sum to ~1.0 (tolerance {SUM_TOLERANCE}); got {total:.4f}"
        )
    return {component: float(value) for component, value in weights.items()}


def resolve_weights(weights: dict[str, float] | None) -> dict[str, float]:
    """Explicit weights win; otherwise the documented defaults (copy)."""
    if weights is not None:
        return validate_weights(weights)
    return dict(DEFAULT_WEIGHTS)
