"""The module map from the ontology alone — no task database needed.

A layer of the map is the children of a prefix (health._node_of). Three readings of it:

history  (a project built from tasks)
  file :: co_changes_with :: file   [n, g2, lift]  significant pairs only
  file :: task_count :: n
  node   sized by its file changes (the sum of its files' task_count — a task changing three of
         its files counts three times), coloured by cohesion: the share of its significant
         co-change pairs that stay inside it
  edge   the significant pairs with one file on each side; `weight` = their number (the width),
         `min_tasks` = the largest n among them: at least that many tasks changed both sides
code     (a project built from a folder of code)
  ident :: defined_in :: file/sym,  ident :: used_in :: file/sym,  file :: unit_count :: n
  node   sized by its units (classes, functions, paragraphs), coloured by cohesion: the share of
         the identifiers it uses that are defined inside it
  edge   identifiers defined on one side and used on the other; `ab` = A uses B, `ba` = B uses A.
         An identifier defined in more than one node is ambiguous and left out; used_in is kept
         by the ontology for rare identifiers only (in <= 20 units), so this is a lower bound
overlay  history and code of the same repository on one layer: a link is
  both     changed together and one uses the other — coupling the code explains
  history  changed together, no identifier between them — hidden (logical) coupling
  code     one uses the other, but they do not change together — a stable dependency
  gone     changed together, but one side is no longer in the code the code ontology was built
           from (history spans years, the code is one snapshot) — not evidence of hidden coupling

There are no dates in the ontology: no time window and nothing "new" here; the task history
(health.unit_map) has both, at the price of reading the database.
"""
from collections import Counter, defaultdict

from .health import _node_of, _in_unit
from .onto import NUM

TOP = 10


def _num(src):
    return {k: float(v) for k, v in NUM.findall(src)}


def _path(entity):
    """file:a/B.java -> a/B.java; sym:a/B.java#B.run -> a/B.java"""
    return entity.split(":", 1)[1].split("#", 1)[0]


def _pairs(O):
    """[(file a, file b, n, g2, lift)], each significant pair once (cached on the ontology)."""
    if getattr(O, "_map_pairs", None) is None:
        out = []
        for a, row in O.cochange.items():
            for b, (g2, idx) in row.items():
                if a < b:
                    num = _num(O.lines[idx][3])
                    out.append((a, b, int(num.get("n", 0)), g2, num.get("lift", 0.0)))
        O._map_pairs = out
    return O._map_pairs


def _uses(O):
    """[(using file, defining file, ident)] across files, each once (cached on the ontology)."""
    if getattr(O, "_map_uses", None) is None:
        defs, uses = defaultdict(set), defaultdict(set)
        for s, p, o, _ in O.lines:
            if p == "defined_in" and s.startswith("ident:"):
                defs[s[6:]].add(_path(o))
            elif p == "used_in" and s.startswith("ident:"):
                uses[s[6:]].add(_path(o))
        out = set()
        for ident, where in defs.items():
            for d in where:
                for u in uses.get(ident, ()):
                    if u != d:
                        out.add((u, d, ident))
        O._map_uses = sorted(out)
    return O._map_uses


def kind(O):
    if O.cochange:
        return "history"
    if O.folder and any(p == "defined_in" for _, p, _, _ in O.lines[:200000]):
        return "code"
    return None


def _collapse(files, prefix):
    while True:
        kids = {_node_of(f, prefix) for f in files} - {None}
        if len(kids) == 1 and next(iter(kids)) not in (prefix, "(root)"):
            prefix = next(iter(kids))
            continue
        return prefix


def _sizes(O, prefix):
    size, deeper = Counter(), defaultdict(set)
    for f, n in O.count["file"].items():
        u = _node_of(f, prefix)
        if not u:
            continue
        size[u] += n
        if u not in (prefix, "(root)"):
            sub = _node_of(f, u)
            if sub != u:
                deeper[u].add(sub)
    return size, deeper


def _layer_history(O, prefix):
    inside, out, agg = Counter(), Counter(), {}
    for a, b, n, g2, lift in _pairs(O):
        ua, ub = _node_of(a, prefix), _node_of(b, prefix)
        if not ua and not ub:
            continue
        if ua == ub:
            inside[ua] += 1
            continue
        for u in (ua, ub):
            if u:
                out[u] += 1
        if ua and ub:
            e = agg.setdefault(tuple(sorted((ua, ub))), {"weight": 0, "min_tasks": 0, "g2": 0.0})
            e["weight"] += 1
            e["min_tasks"] = max(e["min_tasks"], n)
            e["g2"] += g2
    return inside, out, agg


def _layer_code(O, prefix):
    """Identifiers defined in exactly one node of the layer (or outside it) and used elsewhere."""
    of = lambda f: _node_of(f, prefix)
    def_node = defaultdict(set)
    for u, d, ident in _uses(O):
        def_node[ident].add(of(d))
    inside, out, agg = Counter(), Counter(), {}
    seen = set()
    for u, d, ident in _uses(O):
        if len(def_node[ident]) != 1:
            continue                                         # the same name defined in two places
        nu, nd = of(u), of(d)
        if not nu and not nd:
            continue
        key3 = (nu, nd, ident)
        if key3 in seen:
            continue
        seen.add(key3)
        if nu == nd:
            inside[nu] += 1
            continue
        if nu:
            out[nu] += 1
        if nu and nd:
            a, b = sorted((nu, nd))
            e = agg.setdefault((a, b), {"weight": 0, "ab": 0, "ba": 0})
            e["weight"] += 1
            e["ab" if nu == a else "ba"] += 1                # ab: a uses b
    return inside, out, agg


def _keep(agg, ok, per_node):
    """Each node keeps its `per_node` strongest links among those passing `ok`."""
    per = defaultdict(list)
    for k, v in agg.items():
        if ok(v):
            for u in k:
                per[u].append((v["weight"], k))
    keep = set()
    for lst in per.values():
        keep.update(k for _, k in sorted(lst, reverse=True)[:per_node])
    return keep


def _nodes(size, deeper, inside, out, prefix):
    nodes = []
    for u, n in sorted(size.items()):
        own = u in (prefix, "(root)")
        tot = inside[u] + out[u]
        nodes.append({"id": u, "label": "(own files)" if own and prefix else (u[len(prefix) + 1:] if prefix else u),
                      "own": own, "tasks": n, "drill": bool(deeper[u]), "zone": None, "outside": 0,
                      "links_in": inside[u], "links_out": out[u],
                      "cohesion": round(inside[u] / tot, 4) if tot else None})
    return nodes


def _crumbs(prefix):
    crumbs, acc = [], []
    for part in prefix.split("/") if prefix else []:
        acc.append(part)
        crumbs.append("/".join(acc))
    return crumbs


def unit_map(O, prefix="", min_tasks=3, per_node=6):
    """One layer from one ontology: history (co-change) or code (identifier use)."""
    src = kind(O)
    if not src:
        raise ValueError("this ontology has neither co_changes_with (tasks) nor defined_in / used_in (code)")
    prefix = _collapse(list(O.count["file"]), (prefix or "").strip("/"))
    size, deeper = _sizes(O, prefix)
    if src == "history":
        inside, out, agg = _layer_history(O, prefix)
        keep = _keep(agg, lambda v: v["min_tasks"] >= min_tasks, per_node)
    else:
        inside, out, agg = _layer_code(O, prefix)
        keep = _keep(agg, lambda v: v["weight"] >= min_tasks, per_node)
    edges = [{"source": a, "target": b, **v, "tasks": v["weight"], "lift": 0.0, "new": False}
             for (a, b), v in agg.items() if (a, b) in keep]
    return {"source": src, "prefix": prefix, "crumbs": _crumbs(prefix),
            "nodes": _nodes(size, deeper, inside, out, prefix), "edges": edges, "window_tasks": O.N,
            "params": {"prefix": prefix, "min_tasks": min_tasks, "per_node": per_node, "since": None, "until": None}}


def overlay(Oh, Oc, prefix="", min_tasks=3, per_node=6):
    """History (Oh) and code (Oc) of one repository on one layer. Each source keeps its own
    strongest links; a link is `both` when the other source has any link between the same two
    nodes at all, else `history` (hidden coupling) or `code` (stable dependency)."""
    if kind(Oh) != "history" or kind(Oc) != "code":
        raise ValueError("overlay needs a project built from tasks and a project built from the code")
    prefix = _collapse(list(Oh.count["file"]), (prefix or "").strip("/"))
    size, deeper = _sizes(Oh, prefix)
    csize, cdeeper = _sizes(Oc, prefix)
    hin, hout, hagg = _layer_history(Oh, prefix)
    cin, cout, cagg = _layer_code(Oc, prefix)
    hkeep = _keep(hagg, lambda v: v["min_tasks"] >= min_tasks, per_node)
    ckeep = _keep(cagg, lambda v: v["weight"] >= min_tasks, per_node)
    edges = []
    for k in sorted(hkeep | ckeep):
        h, c = hagg.get(k), cagg.get(k)
        kd = "both" if h and c else ("history" if h else "code")
        if kd == "history" and not (csize.get(k[0]) and csize.get(k[1])):
            kd = "gone"                                       # one side is not in today's code at all
        edges.append({"source": k[0], "target": k[1], "kind": kd, "new": False, "lift": 0.0,
                      "weight": (h or c)["weight"], "tasks": (h or c)["weight"],
                      "pairs": h["weight"] if h else 0, "min_tasks": h["min_tasks"] if h else 0,
                      "idents": c["weight"] if c else 0, "ab": c["ab"] if c else 0, "ba": c["ba"] if c else 0})
    for u, n in csize.items():                                # nodes only the code knows (never changed)
        if u not in size and any(u in (e["source"], e["target"]) for e in edges):
            size[u] = 0
            deeper[u] = cdeeper[u]
    nodes = _nodes(size, deeper, hin, hout, prefix)
    for n in nodes:
        n["units"] = csize.get(n["id"], 0)
        t = cin[n["id"]] + cout[n["id"]]
        n["code_cohesion"] = round(cin[n["id"]] / t, 4) if t else None
    counts = Counter(e["kind"] for e in edges)
    return {"source": "overlay", "prefix": prefix, "crumbs": _crumbs(prefix), "nodes": nodes, "edges": edges,
            "window_tasks": Oh.N, "counts": dict(counts),
            "params": {"prefix": prefix, "min_tasks": min_tasks, "per_node": per_node, "since": None, "until": None}}


def _history_detail(O, prefix, a, b, top):
    of = lambda f: _node_of(f, prefix)
    pairs, fa, fb = [], Counter(), Counter()
    for x, y, n, g2, lift in _pairs(O):
        ux, uy = of(x), of(y)
        if {ux, uy} == {a, b} and ux != uy:
            if ux == b:
                x, y = y, x
            pairs.append({"a": x, "b": y, "tasks": n, "g2": round(g2, 1), "lift": round(lift, 2)})
            fa[x] += 1
            fb[y] += 1
    pairs.sort(key=lambda p: (-p["g2"], -p["tasks"]))
    return {"pairs_total": len(pairs), "min_tasks": max((p["tasks"] for p in pairs), default=0),
            "g2": round(sum(p["g2"] for p in pairs), 1), "pairs": pairs[:top],
            "files_a": [{"file": f, "n": n} for f, n in fa.most_common(top)],
            "files_b": [{"file": f, "n": n} for f, n in fb.most_common(top)]}


def _code_detail(O, prefix, a, b, top):
    of = lambda f: _node_of(f, prefix)
    def_node = defaultdict(set)
    for u, d, ident in _uses(O):
        def_node[ident].add(of(d))
    ab, ba = defaultdict(set), defaultdict(set)          # ident -> using files
    fa, fb = Counter(), Counter()
    for u, d, ident in _uses(O):
        if len(def_node[ident]) != 1:
            continue
        nu, nd = of(u), of(d)
        if (nu, nd) == (a, b):
            ab[ident].add(u)
            fa[u] += 1
            fb[d] += 1
        elif (nu, nd) == (b, a):
            ba[ident].add(u)
            fb[u] += 1
            fa[d] += 1
    rank = lambda m: [{"ident": i, "used_in": len(fs)} for i, fs in sorted(m.items(), key=lambda kv: (-len(kv[1]), kv[0]))[:top * 2]]
    return {"a_uses_b": len(ab), "b_uses_a": len(ba), "idents_ab": rank(ab), "idents_ba": rank(ba),
            "code_files_a": [{"file": f, "n": n} for f, n in fa.most_common(top)],
            "code_files_b": [{"file": f, "n": n} for f, n in fb.most_common(top)]}


def _words(O, prefix, a, b):
    """Terms that characterize a file or folder on each side, ranked by the weaker side."""
    of = lambda f: _node_of(f, prefix)
    side = {a: defaultdict(float), b: defaultdict(float)}
    for knd in ("file", "dir", "sym"):
        for term, targets in O.char.get(knd, {}).items():
            for t, (g2, lift, idx) in targets.items():
                u = of(t.split("#", 1)[0] + ("/x" if knd == "dir" else ""))
                if u in side:
                    side[u][term] = max(side[u][term], g2)
    both = sorted(((min(side[a][w], side[b][w]), w) for w in side[a].keys() & side[b].keys()), reverse=True)
    return [{"word": w, "g2_a": round(side[a][w], 1), "g2_b": round(side[b][w], 1)} for _, w in both[:12]]


def _depends(O, a, b):
    deps = []
    for s, p, o, src in (O.lines[i] for i in O.by_entity.get(f"module:{a}", [])):
        if p == "depends_on" and {s, o} == {f"module:{a}", f"module:{b}"}:
            deps.append({"from": s[7:], "to": o[7:], "importing_files": int(_num(src).get("importing_files", 0))})
    return deps


def edge_detail(O, prefix, a, b, Oc=None, top=TOP):
    """One link from the ontology (and from the code ontology `Oc`, for the overlay)."""
    prefix = (prefix or "").strip("/")
    src = kind(O)
    res = {"source": src if not Oc else "overlay", "a": a, "b": b, "prefix": prefix}
    if src == "history":
        size, _ = _sizes(O, prefix)
        res.update(_history_detail(O, prefix, a, b, top), a_changes=size[a], b_changes=size[b],
                   words=_words(O, prefix, a, b), depends_on=_depends(O, a, b))
    code = Oc if Oc is not None else (O if src == "code" else None)
    if code is not None:
        res.update(_code_detail(code, prefix, a, b, top))
        if src == "code":
            res["words"] = _words(code, prefix, a, b)
    return res
