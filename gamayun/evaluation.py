"""Tune on dev, test once (concepts/GAMAYUN.md §11).

Dev tasks are taken from the training part with the same modn rule and a
separate ontology is built without them; parameters chosen there are applied
once to the test tasks with the full-train ontology."""
import itertools
from collections import defaultdict

from .data import module_of

K_VALUES = [1, 3, 5, 10]

GRIDS = {
    "module": {"lam": [0.1, 0.25, 0.5, 1.0, 2.0], "not_in": [0, 1]},
    "file": {"lam": [0.05, 0.1, 0.25, 0.5, 1.0], "beta": [0, 0.5, 1, 2], "beta2": [0, 0.5, 1, 2],
             "mu": [0, 0.5, 1], "gamma": [0, 0.5, 1, 2]},
}


def metrics_for_query(retrieved, relevant, k_values=K_VALUES):
    """Same as simrgl exp3/utils.py calculate_metrics_for_query."""
    m = {}
    if not relevant:
        m["AP"] = m["RR"] = 0.0
        for k in k_values:
            m[f"P@{k}"] = m[f"R@{k}"] = 0.0
        return m
    hits, prec, first = 0, [], 0
    for rank, p in enumerate(retrieved, 1):
        if p in relevant:
            hits += 1
            prec.append(hits / rank)
            first = first or rank
    m["AP"] = sum(prec) / len(relevant) if prec else 0.0
    m["RR"] = 1.0 / first if first else 0.0
    for k in k_values:
        h = sum(1 for p in retrieved[:k] if p in relevant)
        m[f"P@{k}"] = h / k
        m[f"R@{k}"] = h / len(relevant)
    m["hit@10"] = 1.0 if first else 0.0
    return m


class Case:
    def __init__(self, O, task):
        self.q = O.query(task["text"])
        self.files = set(task["files"])
        self.mods = {module_of(f) for f in task["files"]}


def score(O, cases, level, prm):
    """prm None = prior baseline (most frequent targets)."""
    agg = defaultdict(float)
    for c in cases:
        if level == "module":
            got = c.q.rank_modules(prm) if prm else O.mods_by_prior[:10]
            rel = c.mods
        else:
            got = c.q.rank_files(prm) if prm else O.files_by_prior[:10]
            rel = c.files
        for k, v in metrics_for_query(got, rel).items():
            agg[k] += v / len(cases)
    return dict(agg)


def tune(O, cases, level, log=print):
    grid = GRIDS[level]
    best = None
    for vals in itertools.product(*grid.values()):
        prm = dict(zip(grid, vals))
        ap = score(O, cases, level, prm)["AP"]
        if best is None or ap > best[0]:
            best = (ap, prm)
    log(f"tuned {level}: dev MAP {best[0]:.4f} {best[1]}")
    return best[1], best[0]
