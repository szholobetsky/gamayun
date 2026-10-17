"""Health of a code base over time: the Novelty x Structurality square (SIMARGL concept,
concepts/SIMARGL_concept.md in the simrgl repository), computed from the task history.

Every task that changed 2..MAX_FILES files is a set of file pairs that changed together.
A pair is
  novel        if those two files had changed together in fewer than `min_before` earlier
               tasks — judged on the history up to that task's date only, never later;
  structural   if both files lie in the same unit: the first `depth` folders of the path
               (depth 2: server/sonar-web, sonar-core/src, ...; depth 1: the top module).
The four zones of the square:
  EVOLUTION    novel and inside a unit      new work where it belongs
  MAINTENANCE  known and inside a unit      routine work
  DISRUPTION   novel and across units       new coupling between parts — architecture erodes
  STAGNATION   known and across units       the same cross-unit pairs again — shotgun surgery
A task counts once: its pairs' shares are averaged over the tasks of a period, so a task of
30 files does not outweigh thirty tasks of two. Novelty = EVOLUTION + DISRUPTION,
Structurality = EVOLUTION + MAINTENANCE, SES = sqrt(N * S), HES = harmonic mean.

Scope: the whole code base, one unit (`unit=`, a path prefix: pairs with at least one file in
it — structural = both inside, i.e. cohesion against coupling), or one file (`file=`).

The task date is its first commit (CMT_DATE); tasks of more than MAX_FILES files (merges, mass
renames) are left out, as in the ontology's co_changes_with.
"""
import math
import sqlite3
from collections import Counter, OrderedDict, defaultdict
from itertools import combinations

from .data import _text, tables

MAX_FILES = 30
ZONES = ("evolution", "maintenance", "disruption", "stagnation")


def load_history(db_path):
    """-> [(date 'YYYY-MM-DD...', task name, frozenset(paths))], oldest first."""
    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    _, commit_t = tables(con)
    first, files = {}, defaultdict(set)
    for name, date, path in con.execute(
            f"SELECT TASK_NAME, CMT_DATE, PATH FROM {commit_t} WHERE TASK_NAME IS NOT NULL AND TASK_NAME <> ''"):
        d, p = _text(date), _text(path).replace("\\", "/").strip()
        if d and (name not in first or d < first[name]):
            first[name] = d
        if p:
            files[name].add(p)
    con.close()
    return sorted(((first[n], n, frozenset(fs)) for n, fs in files.items() if n in first), key=lambda x: (x[0], x[1]))


# source-layout folders end a unit: sonar-core/src/main/java/... and sonar-core/build.gradle
# are one unit, sonar-core — not two (sonar-core/src and sonar-core)
LAYOUT = {"src", "source", "sources", "main", "test", "tests", "it", "lib", "java", "kotlin", "scala",
          "resources", "js", "ts", "app", "pkg", "internal", "include"}


def unit_of(path, depth=2):
    """The first `depth` folders of a path, stopping at a source-layout folder:
    server/sonar-web/src/... -> server/sonar-web; sonar-core/src/main/... -> sonar-core."""
    out = []
    for part in path.split("/")[:-1]:
        if part.lower() in LAYOUT or len(out) == depth:
            break
        out.append(part)
    return "/".join(out) if out else "(root)"


def period_of(date, by="month"):
    y, m = date[:4], date[5:7]
    if by == "year":
        return y
    if by == "quarter":
        return f"{y}-Q{(int(m) - 1) // 3 + 1}"
    return f"{y}-{m}"


def _in_unit(path, unit):
    return path == unit or path.startswith(unit.rstrip("/") + "/")


def _summary(shares, tasks, pairs):
    n = shares["evolution"] + shares["disruption"]
    s = shares["evolution"] + shares["maintenance"]
    zone = ("evolution" if s >= 0.5 else "disruption") if n >= 0.5 else ("maintenance" if s >= 0.5 else "stagnation")
    return {"tasks": tasks, "pairs": pairs, **{z: round(shares[z], 4) for z in ZONES},
            "novelty": round(n, 4), "structurality": round(s, 4), "ses": round(math.sqrt(n * s), 4),
            "hes": round(2 * n * s / (n + s), 4) if n + s else 0.0, "zone": zone}


def health(history, depth=2, by="month", unit=None, file=None, min_before=1, since=None, until=None):
    """-> {"params", "periods": [{"period", "tasks", "pairs", zones..., novelty, structurality, ses, hes, zone}],
           "total": {...}, "excluded_large": n, "first", "last"}"""
    seen = Counter()
    per = OrderedDict()
    total, n_total, pairs_total, excluded = Counter(), 0, 0, 0
    for date, _, files in history:
        if len(files) > MAX_FILES:
            excluded += 1
            continue
        if len(files) < 2:
            continue
        pairs = list(combinations(sorted(files), 2))
        mine = pairs
        if unit:
            mine = [(a, b) for a, b in pairs if _in_unit(a, unit) or _in_unit(b, unit)]
        elif file:
            mine = [(a, b) for a, b in pairs if file in (a, b)]
        in_window = (not since or date >= since) and (not until or date[:len(until)] <= until)
        if mine and in_window:
            c = Counter()
            for a, b in mine:
                novel = seen[(a, b)] < min_before
                if unit:
                    inside = _in_unit(a, unit) and _in_unit(b, unit)
                else:
                    inside = unit_of(a, depth) == unit_of(b, depth)
                c[("evolution" if inside else "disruption") if novel else ("maintenance" if inside else "stagnation")] += 1
            shares = {z: c[z] / len(mine) for z in ZONES}
            p = per.setdefault(period_of(date, by), {"n": 0, "pairs": 0, "sum": Counter()})
            p["n"] += 1
            p["pairs"] += len(mine)
            p["sum"].update(shares)
            total.update(shares)
            n_total += 1
            pairs_total += len(mine)
        seen.update(pairs)                                  # the history grows with every task, in scope or not
    periods = [{"period": k, **_summary({z: v["sum"][z] / v["n"] for z in ZONES}, v["n"], v["pairs"])}
               for k, v in per.items()]
    tot = _summary({z: total[z] / n_total for z in ZONES}, n_total, pairs_total) if n_total else None
    return {"params": {"depth": depth, "by": by, "unit": unit, "file": file, "min_before": min_before,
                       "since": since, "until": until, "max_files": MAX_FILES},
            "periods": periods, "total": tot, "excluded_large": excluded,
            "first": history[0][0][:10] if history else None, "last": history[-1][0][:10] if history else None}


def units(history, depth=2, min_before=1, since=None, top=None, min_tasks=5):
    """Every unit (depth folders) with its own square over the window: which parts keep
    changing together with the same outside files (stagnation), which grow new couplings
    (disruption). -> [{"unit", "tasks", ...}] ordered by the share of stagnation."""
    seen = Counter()
    acc = defaultdict(lambda: {"n": 0, "pairs": 0, "sum": Counter()})
    for date, _, files in history:
        if len(files) > MAX_FILES or len(files) < 2:
            continue
        pairs = list(combinations(sorted(files), 2))
        if not since or date >= since:
            per_unit = defaultdict(Counter)
            for a, b in pairs:
                ua, ub = unit_of(a, depth), unit_of(b, depth)
                novel = seen[(a, b)] < min_before
                z = ("evolution" if ua == ub else "disruption") if novel else ("maintenance" if ua == ub else "stagnation")
                for u in {ua, ub}:
                    per_unit[u][z] += 1
            for u, c in per_unit.items():
                k = sum(c.values())
                acc[u]["n"] += 1
                acc[u]["pairs"] += k
                acc[u]["sum"].update({z: c[z] / k for z in ZONES})
        seen.update(pairs)
    out = [{"unit": u, **_summary({z: v["sum"][z] / v["n"] for z in ZONES}, v["n"], v["pairs"])}
           for u, v in acc.items() if v["n"] >= min_tasks]
    out.sort(key=lambda r: (-r["stagnation"], -r["tasks"]))
    return out[:top] if top else out


def _node_of(path, prefix):
    """The child of `prefix` a file belongs to: the next folder after the prefix that is not a
    source-layout folder (sonar-core -> sonar-core/src/main/java/org, layout folders kept in
    the id). Files with no such folder belong to the prefix itself; files outside -> None."""
    if prefix and not _in_unit(path, prefix):
        return None
    acc = prefix.split("/") if prefix else []
    for part in path.split("/")[len(acc):-1]:
        acc.append(part)
        if part.lower() not in LAYOUT:
            return "/".join(acc)
    return prefix or "(root)"


def unit_map(history, prefix="", since=None, until=None, min_tasks=3, per_node=6, min_before=1):
    """The map of one layer of the code base: the children of `prefix` ("" = the top modules)
    and the coupling between them, so the map is read top-down — modules, then the submodules
    of one module, and so on.

    node  a child folder, sized by the tasks of the window that touched it, coloured by its own
          square (pairs inside the node = structural, pairs with any other file = across);
          `outside` = its tasks that also touched files outside the prefix; `drill` = it has
          sub-folders to open; the prefix's own files are one node, `own: true`
    edge  two nodes changed together by at least `min_tasks` tasks of the window; each node keeps
          its `per_node` strongest edges (by shared tasks), so the map shows structure, not a
          hairball. lift = n_uv * N / (n_u * n_v) over the layer's N tasks is reported, not
          filtered on: in a layer of two or three children nearly every task touches one of
          them, and lift cannot exceed 1 there however tight the coupling
    new   (with `since`) the two nodes had never changed together before the window
    A chain of single folders (org/sonar/core) is skipped: the layer opens where it branches."""
    prefix = (prefix or "").strip("/")
    in_win = lambda d: (not since or d >= since) and (not until or d[:len(until)] <= until)
    hist = [h for h in history if 1 <= len(h[2]) <= MAX_FILES]
    while True:                                                    # skip single-folder chains
        kids = {_node_of(f, prefix) for _, _, fs in hist for f in fs} - {None}
        if len(kids) == 1 and next(iter(kids)) not in (prefix, "(root)"):
            prefix = next(iter(kids))
            continue
        break
    node_n, out_n, pair_n, before, deeper = Counter(), Counter(), Counter(), set(), defaultdict(set)
    seen, sq = Counter(), defaultdict(lambda: {"n": 0, "pairs": 0, "sum": Counter()})
    n_window = 0
    for date, _, files in hist:
        of = {f: _node_of(f, prefix) for f in files}
        us = sorted({u for u in of.values() if u})
        pairs = list(combinations(us, 2))
        win = in_win(date)
        if win and us:
            n_window += 1
            node_n.update(us)
            pair_n.update(pairs)
            if any(u is None for u in of.values()):
                out_n.update(us)
            for f, u in of.items():
                if u and u != prefix and u != "(root)":
                    sub = _node_of(f, u)
                    if sub != u:
                        deeper[u].add(sub)
        elif not win and (not since or date < since):
            before.update(pairs)
        fpairs = list(combinations(sorted(files), 2))
        if win and us:
            per = defaultdict(Counter)
            for a, b in fpairs:
                ua, ub = of[a], of[b]
                if not ua and not ub:
                    continue
                novel = seen[(a, b)] < min_before
                inside = ua == ub
                z = ("evolution" if inside else "disruption") if novel else ("maintenance" if inside else "stagnation")
                for u in {ua, ub} - {None}:
                    per[u][z] += 1
            for u, c in per.items():
                k = sum(c.values())
                sq[u]["n"] += 1
                sq[u]["pairs"] += k
                sq[u]["sum"].update({z: c[z] / k for z in ZONES})
        seen.update(fpairs)
    cand = []
    for (a, b), n in pair_n.items():
        if n < min_tasks:
            continue
        cand.append((a, b, n, n * n_window / (node_n[a] * node_n[b])))
    keep, per = set(), defaultdict(list)
    for a, b, n, lift in cand:
        per[a].append((n, lift, b))
        per[b].append((n, lift, a))
    for u, lst in per.items():
        for n, lift, v in sorted(lst, reverse=True)[:per_node]:
            keep.add(tuple(sorted((u, v))))
    edges = [{"source": a, "target": b, "tasks": n, "lift": round(lift, 2),
              "new": bool(since) and (a, b) not in before}             # without a window nothing is "new"
             for a, b, n, lift in cand if (a, b) in keep]
    nodes = []
    for u, n in sorted(node_n.items()):
        s = sq.get(u)
        summ = _summary({z: s["sum"][z] / s["n"] for z in ZONES}, s["n"], s["pairs"]) if s and s["n"] else None
        own = u in (prefix, "(root)")
        nodes.append({"id": u, "label": "(own files)" if own and prefix else
                      (u[len(prefix) + 1:] if prefix else u), "own": own, "tasks": n,
                      "outside": out_n[u], "drill": len(deeper[u]) >= 1,
                      **({k: summ[k] for k in (*ZONES, "zone", "novelty", "structurality")} if summ else {"zone": None})})
    crumbs, acc = [], []
    for part in prefix.split("/") if prefix else []:
        acc.append(part)
        crumbs.append("/".join(acc))
    return {"prefix": prefix, "crumbs": crumbs, "nodes": nodes, "edges": edges, "window_tasks": n_window,
            "params": {"prefix": prefix, "since": since, "until": until, "min_tasks": min_tasks,
                       "per_node": per_node, "min_before": min_before}}


def load_titles(db_path):
    """-> {task name: title}, for showing tasks by what they were about."""
    from .data import tables as _tables
    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    task_t, _ = _tables(con)
    out = {_text(n): _text(t) for n, t in con.execute(f"SELECT NAME, TITLE FROM {task_t}") if n}
    con.close()
    return out


def edge_detail(history, prefix, a, b, since=None, until=None, titles=None, min_before=1, top=10):
    """What one link of the map is made of: the tasks that changed both nodes `a` and `b`
    of the layer `prefix` (node ids as unit_map gives them).

    strength     shared tasks, lift over the layer's tasks, P(b|a) and P(a|b) — the link is
                 often lopsided: a small module that always drags a big one along
    time         shared tasks per year, first and last
    character    of the cross pairs (a file of a with a file of b) in the shared tasks: novel
                 (those two files never changed together before) = disruption, known = stagnation
    files        the file pairs and the files of each side that carry the link
    words        title words of the shared tasks against the tasks of only one side (G², the
                 same test as the ontology's): what the two change together *for*
    tasks        the latest shared tasks, with titles"""
    from .builder import g2_vec
    from .data import terms_of
    import numpy as np
    prefix = (prefix or "").strip("/")
    in_win = lambda d: (not since or d >= since) and (not until or d[:len(until)] <= until)
    seen = Counter()
    n_layer = n_a = n_b = 0
    shared, only = [], []
    per_year, pair_n, fa_n, fb_n, zone = Counter(), Counter(), Counter(), Counter(), Counter()
    for date, name, files in history:
        if not 1 <= len(files) <= MAX_FILES:
            continue
        fpairs = list(combinations(sorted(files), 2))
        if in_win(date):
            of = {f: _node_of(f, prefix) for f in files}
            nodes = set(of.values()) - {None}
            if nodes:
                n_layer += 1
            ia, ib = a in nodes, b in nodes
            n_a += ia
            n_b += ib
            if ia and ib:
                fa = sorted(f for f in files if of[f] == a)
                fb = sorted(f for f in files if of[f] == b)
                shared.append((date, name, len(files)))
                per_year[date[:4]] += 1
                fa_n.update(fa)
                fb_n.update(fb)
                for x in fa:
                    for y in fb:
                        pair_n[(x, y)] += 1
                        zone["disruption" if seen[tuple(sorted((x, y)))] < min_before else "stagnation"] += 1
            elif ia or ib:
                only.append(name)
        seen.update(fpairs)
    k = len(shared)
    res = {"a": a, "b": b, "prefix": prefix, "tasks": k, "a_tasks": n_a, "b_tasks": n_b, "layer_tasks": n_layer,
           "lift": round(k * n_layer / (n_a * n_b), 2) if n_a and n_b else 0.0,
           "p_b_given_a": round(k / n_a, 4) if n_a else 0.0, "p_a_given_b": round(k / n_b, 4) if n_b else 0.0,
           "avg_files": round(sum(m for _, _, m in shared) / k, 1) if k else 0.0,
           "first": shared[0][0][:10] if shared else None, "last": shared[-1][0][:10] if shared else None,
           "years": [{"year": y, "tasks": n} for y, n in sorted(per_year.items())],
           "cross_pairs": sum(zone.values()),
           "disruption": round(zone["disruption"] / max(1, sum(zone.values())), 4),
           "stagnation": round(zone["stagnation"] / max(1, sum(zone.values())), 4),
           "pairs": [{"a": x, "b": y, "tasks": n} for (x, y), n in pair_n.most_common(top)],
           "files_a": [{"file": f, "tasks": n} for f, n in fa_n.most_common(top)],
           "files_b": [{"file": f, "tasks": n} for f, n in fb_n.most_common(top)],
           "words": [], "recent": []}
    if titles:
        res["recent"] = [{"task": n, "date": d[:10], "files": m, "title": titles.get(n, "")}
                         for d, n, m in reversed(shared[-top:])]
        tw = lambda n: set(terms_of(titles.get(n, "")))
        in_s, in_o = Counter(), Counter()
        for _, n, _ in shared:
            in_s.update(tw(n))
        for n in only:
            in_o.update(tw(n))
        words = [w for w in in_s if in_s[w] >= 2]
        if words and only:
            k11 = np.array([in_s[w] for w in words], float)
            k12 = np.array([in_o[w] for w in words], float)
            g, pos = g2_vec(k11, k11 + k12, np.full_like(k11, k), np.full_like(k11, k + len(only)))
            ranked = sorted((float(g[i]), w) for i, w in enumerate(words) if pos[i] and g[i] > 3.84)
            res["words"] = [{"word": w, "shared": in_s[w], "one_side": in_o[w], "g2": round(gv, 1)}
                            for gv, w in reversed(ranked[-12:])]
    return res


def snapshot(project_dir, report, built=None):
    """Keep the report under <project>/health/<date>.json, dated by the build, so the
    health of the code base can be compared from one build to the next."""
    import json
    import time
    from pathlib import Path
    built = built or time.strftime("%Y-%m-%d %H:%M")
    d = Path(project_dir) / "health"
    d.mkdir(parents=True, exist_ok=True)
    path = d / f"{built[:10]}.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"built": built, **report}, f, indent=1, ensure_ascii=False)
    return path


def ascii_square(t):
    """The square as text, for the CLI."""
    pct = lambda z: f"{100 * t[z]:5.1f}%"
    return "\n".join([
        "                       structurality ->",
        "                 across units           inside a unit",
        f"  novel     DISRUPTION  {pct('disruption')}     EVOLUTION   {pct('evolution')}",
        f"  known     STAGNATION  {pct('stagnation')}     MAINTENANCE {pct('maintenance')}",
        f"  Novelty {t['novelty']:.2f}  Structurality {t['structurality']:.2f}  SES {t['ses']:.2f}  "
        f"HES {t['hes']:.2f}  -> {t['zone'].upper()}   ({t['tasks']} tasks, {t['pairs']} pairs)",
    ])
