"""Canonical display order and labels for fixtures in paper tables."""

FIXTURE_ORDER = (
    "search_00",
    "search_01",
    "pareto_01",
    "pareto_02",
    "dense_neighbors",
    "max_iterations",
    "cache_hostile",
    "subnormal",
    "legal_worst",
    "legal_osc",
    "real_slowest",
    "real_median",
)

FIXTURE_LABELS = {
    "search_00": r"\emph{search-00}",
    "pareto_01": r"\emph{pareto-01}",
    "pareto_02": r"\emph{pareto-02}",
    "search_01": r"\emph{search-01}",
    "dense_neighbors": r"\emph{dense-nbrs}",
    "max_iterations": r"\emph{max-iters}",
    "cache_hostile": r"\emph{cache-hostile}",
    "subnormal": r"\emph{subnormal}",
    "legal_worst": r"\emph{geom-stress}",
    "legal_osc": r"\emph{shipped-osc}",
    "real_slowest": r"\emph{real-slowest}",
    "real_median": r"\emph{real-median}",
}


def ordered_fixture_names(names):
    """Return known fixture names in the canonical paper-table order."""
    requested = set(names)
    unknown = requested.difference(FIXTURE_ORDER)
    if unknown:
        joined = ", ".join(sorted(unknown))
        raise ValueError(f"fixture display order is undefined for: {joined}")
    return [name for name in FIXTURE_ORDER if name in requested]
