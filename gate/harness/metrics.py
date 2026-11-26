"""H1 metrics and decision rules (PROTOCOL.md sections 7 and 8; AMENDMENTS.md 26 Nov).

Two versions of every metric for every detector (AMENDMENTS.md, dual reporting):
  "phi"       LLM parse failures scored as PHI (s = 1.0); this is the primary version
  "excluded"  scenarios with a parse failure for that (policy, detector) removed from numerator and denominator
Rates are used for thresholds; for the standard denominators (50/43, 26/16) they reproduce the counts
stated in the protocol exactly.
"""

from __future__ import annotations

import math
from collections import Counter, defaultdict

from .common import LLM_DETECTORS, NON_AUTHOR, PARSE_FAIL_FLAG
from .engine import Result


def wilson(k: int, n: int, z: float = 1.959964) -> list[float] | None:
    if n == 0:
        return None
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return [round(max(0.0, c - h), 4), round(min(1.0, c + h), 4)]


def _rate(k: int, n: int) -> dict:
    return {"k": k, "n": n, "rate": round(k / n, 4) if n else None, "ci95": wilson(k, n)}


def group_metrics(rs: list[Result]) -> dict:
    phi = [r for r in rs if r.phi_flow]
    nonphi = [r for r in rs if not r.phi_flow]
    feas = [r for r in rs if r.feasible]
    comp_feas = [r for r in feas if r.completed]
    d = [r for r in rs if r.stratum == "D"]

    def fa(xs): return sum(r.fa_hop is not None for r in xs)
    def den(xs): return sum(not r.completed for r in xs)
    def ovr(xs): return sum(r.or_hop is not None for r in xs)

    hop_loc = {"FA": Counter(r.fa_hop for r in rs if r.fa_hop),
               "FD": Counter(r.denied_at for r in feas if not r.completed),
               "OR": Counter(r.or_hop for r in rs if r.or_hop)}
    dep = defaultdict(lambda: [0, 0])
    for r in rs:
        for h in r.hops:
            dep[r.stratum][1] += 1
            dep[r.stratum][0] += h.inferred_relevant
    return {
        "FA": {"full": _rate(fa(phi), len(phi)),
               "standard": _rate(fa([r for r in phi if not r.hard]), len([r for r in phi if not r.hard]))},
        "FD_neg": {"full": _rate(den(nonphi), len(nonphi)),
                   "standard": _rate(den([r for r in nonphi if not r.trap]), len([r for r in nonphi if not r.trap]))},
        "FD_all": _rate(den(feas), len(feas)),
        "OR": {"full": _rate(ovr(comp_feas), len(comp_feas)),
               "standard": _rate(ovr([r for r in comp_feas if not (r.trap or r.hard)]),
                                 len([r for r in comp_feas if not (r.trap or r.hard)]))},
        "D_downstream": {"n": len(d),
                         "FA": sum(r.fa_hop == 3 for r in d),
                         "FD": sum(r.denied_at == 3 and r.feasible for r in d),
                         "OR": sum(r.or_hop == 3 for r in d)},
        "error_location": {k: dict(sorted(v.items())) for k, v in hop_loc.items()},
        "inferred_dependence_by_stratum": {k: _rate(*v) for k, v in sorted(dep.items())},
        "correct_denials": sorted(r.scenario for r in rs if not r.feasible and not r.completed),
        "fa_scenarios": sorted(r.scenario for r in rs if r.fa_hop),
        "fd_scenarios": sorted(r.scenario for r in feas if not r.completed),
        "or_scenarios": sorted(r.scenario for r in rs if r.or_hop),
        "parse_failure_scenarios": sorted(r.scenario for r in rs if r.parse_failure),
    }


def all_metrics(results: list[Result]) -> dict:
    groups = defaultdict(list)
    for r in results:
        groups[(r.policy, r.detector)].append(r)
    out = {"phi": {}, "excluded": {}}
    for (p, d), rs in sorted(groups.items()):
        out["phi"][f"{p}|{d}"] = group_metrics(rs)
        out["excluded"][f"{p}|{d}"] = group_metrics([r for r in rs if not r.parse_failure])
    return out


def parse_failure_flags(results: list[Result]) -> dict:
    per = defaultdict(set)
    for r in results:
        if r.parse_failure:
            per[r.detector].add(r.scenario)
    return {d: {"scenarios": sorted(per[d]), "count": len(per[d]), "flagged": len(per[d]) > PARSE_FAIL_FLAG}
            for d in LLM_DETECTORS}


def choose_dstar(m: dict, version: str) -> str:
    """Section 8: lowest FA, then FD_neg, then OR, for SRC-FC among non-author detectors.
    Counts in the primary version (equal denominators); rates in the excluded version (denominators differ)."""
    field = "k" if version == "phi" else "rate"

    def key(d):
        g = m[version].get(f"SRC-FC|{d}")
        if g is None:
            return (math.inf,) * 3
        return tuple((g[x]["full"][field] if g[x]["full"][field] is not None else math.inf)
                     for x in ("FA", "FD_neg", "OR"))
    present = [d for d in NON_AUTHOR if f"SRC-FC|{d}" in m[version]]
    return min(present, key=lambda d: (key(d), NON_AUTHOR.index(d)))


def h1_rule(g: dict) -> tuple[str, str]:
    fa, fdn, orr, dd = g["FA"], g["FD_neg"], g["OR"], g["D_downstream"]
    empty = [name for name, x in (("FA", fa["full"]), ("FA standard", fa["standard"]),
                                  ("FD_neg", fdn["full"]), ("FD_neg standard", fdn["standard"]),
                                  ("D", {"n": dd["n"]})) if x["n"] == 0]
    if empty:
        return "GRAY", f"rule cannot be evaluated: no scenarios left in {', '.join(empty)}"
    if (fa["full"]["k"] == 0 and fdn["full"]["rate"] <= 0.05 and fdn["standard"]["rate"] <= 0.05
            and (orr["full"]["rate"] or 0) <= 0.05):
        return "FAIL", "FA = 0, FD_neg <= 5% (with and without traps), OR <= 5%"
    if dd["FA"] == 0 and dd["FD"] + dd["OR"] <= 1:
        return "NARROW", f"stratum D post-declassification hop: FA 0 of {dd['n']}, FD+OR {dd['FD'] + dd['OR']}"
    price = []
    if fa["full"]["k"] >= 2 and fa["standard"]["k"] >= 2:
        price.append("FA >= 2 in full and standard sets")
    if fdn["full"]["rate"] >= 0.10 and fdn["standard"]["rate"] >= 0.10:
        price.append("FD_neg >= 10% with and without traps")
    if (orr["full"]["rate"] or 0) >= 0.10 and (orr["standard"]["rate"] or 0) >= 0.10:
        price.append("OR >= 10% in both views")
    if price:
        return "PASS", "; ".join(price)
    return "GRAY", "no rule matched; default outcome NARROW unless the review memo records a reason"


def h1_decision(results: list[Result]) -> dict:
    m = all_metrics(results)
    flags = parse_failure_flags(results)
    dstar = {"phi": choose_dstar(m, "phi"), "excluded": choose_dstar(m, "excluded")}
    outcome, why = h1_rule(m["phi"][f"SRC-FC|{dstar['phi']}"])
    outcome_excl, why_excl = h1_rule(m["excluded"][f"SRC-FC|{dstar['excluded']}"])
    override = None
    if any(f["flagged"] for f in flags.values()) and dstar["phi"] != dstar["excluded"]:
        override = (f"parse failures flagged and D* differs between versions "
                    f"({dstar['phi']} vs {dstar['excluded']}): outcome set to GRAY (AMENDMENTS.md 26 Nov)")
        outcome = "GRAY"
    return {"outcome": outcome, "reason": why, "override": override, "dstar": dstar,
            "outcome_excluded_version": outcome_excl, "reason_excluded_version": why_excl,
            "parse_failures": flags, "metrics": m}
