"""Load an ontology (triples.txt) and search it with naive Bayes.

score(target) = log P(target) + lam * sum over the query's terms of log lift(term, target)

lift comes from the [src] of 'characterizes' triples; a term without a
significant triple has lift 1 and adds nothing. 'not_in' adds log(0.5 / expected).
Files back off to the evidence of their dir (beta) and module (beta2); 'names'
adds mu * log(1 + n); co-change adds gamma * normalised G² from the 10 best files.
See concepts/GAMAYUN.md §10. The same code ranks for the CLI, the web UI and
the evaluation, so what is measured is what users get.
"""
import math
import os
import re
from collections import defaultdict

import numpy as np

from .data import dir_of, module_of, terms_of

TOP_K = 10
LINE = re.compile(r"^(.+?) :: (\S+) :: (.+?)  \[src: (.*)\]$")     # subjects may hold spaces (patterns)
NUM = re.compile(r"(\w+)=(-?\d[\d.]*(?:[eE][+-]?\d+)?)(?=;|$)")

DEFAULT_PARAMS = {
    "module": {"lam": 0.5, "not_in": 1},
    "file": {"lam": 0.5, "beta": 0.5, "beta2": 0.5, "mu": 0.5, "gamma": 0.5},
}


class Onto:
    def __init__(self, path):
        """path: triples.txt or the folder holding it."""
        if os.path.isdir(path):
            path = os.path.join(path, "triples.txt")
        self.path = path
        self.char = {k: defaultdict(dict) for k in ("module", "dir", "file", "sym")}
        self.names = defaultdict(dict)
        self.not_in = defaultdict(dict)
        self.cochange = defaultdict(dict)
        self.count = {"module": {}, "file": {}}
        self.lines = []
        self.by_entity = defaultdict(list)      # entity -> line numbers (subject or object)
        self.N = 0
        self.folder = False                     # built from a folder (units), not from tasks
        self.variant = {}                       # word form -> the form the ontology uses
        with open(path, encoding="utf-8") as fh:
            for ln in fh:
                m = LINE.match(ln.rstrip("\n"))
                if not m:
                    continue
                s, p, o, src = m.groups()
                idx = len(self.lines)
                self.lines.append((s, p, o, src))
                self.by_entity[s].append(idx)
                self.by_entity[o].append(idx)
                num = {k: float(v) for k, v in NUM.findall(src)}
                key = s.split(":", 1)[-1]                  # term:x / ident:x -> x
                if p == "characterizes":
                    kind, target = o.split(":", 1)
                    self.char.setdefault(kind, defaultdict(dict))[key][target] = (num["g2"], num["lift"], idx)
                elif p == "names":
                    self.names[key][o[5:]] = (num["n"], idx)
                elif p == "variant_of":
                    self.variant[key] = o.split(":", 1)[1]
                elif p == "not_in":
                    self.not_in[key][o[7:]] = (num["expected"], idx)
                elif p == "co_changes_with":
                    a, b = s[5:], o[5:]
                    self.cochange[a][b] = self.cochange[b][a] = (num["g2"], idx)
                elif p in ("task_count", "unit_count"):
                    kind, name = s.split(":", 1)
                    self.count[kind][name] = int(o)
                elif p in ("train_tasks", "units"):
                    self.N = int(o)
                    self.folder = p == "units"
        self.files_by_prior = sorted(self.count["file"], key=lambda f: (-self.count["file"][f], f))
        self.mods_by_prior = sorted(self.count["module"], key=lambda x: (-self.count["module"][x], x))
        self.files_in_dir, self.files_in_mod = defaultdict(list), defaultdict(list)
        for f in self.files_by_prior:
            self.files_in_dir[dir_of(f)].append(f)
            self.files_in_mod[module_of(f)].append(f)

    def line(self, idx):
        s, p, o, src = self.lines[idx]
        return f"{s} :: {p} :: {o}  [src: {src}]"

    def entity(self, name, limit=500):
        """All triples where `name` is subject or object, strongest first."""
        rows = [self.lines[i] for i in self.by_entity.get(name, [])]
        def strength(r):
            num = dict(NUM.findall(r[3]))
            return -float(num.get("g2", num.get("n", 0)) or 0)
        rows.sort(key=strength)
        return [{"s": s, "p": p, "o": o, "src": src} for s, p, o, src in rows[:limit]]

    def query(self, text):
        return Query(self, text)

    def files_in_text(self, text):
        """Files of this ontology named in free text (an LLM answer, a list):
        a full path, or a bare file name that only one known file has. In order
        of first mention."""
        known = self.count["file"]
        by_name = defaultdict(list)
        for f in known:
            by_name[f.rsplit("/", 1)[-1]].append(f)
        out = []
        for tok in re.findall(r"[\w./\\-]+\.[A-Za-z0-9]+", (text or "").replace("\\", "/")):
            tok = tok.strip("./")
            hit = tok if tok in known else None
            if hit is None:
                tail = [f for f in known if f.endswith("/" + tok)] if "/" in tok else by_name.get(tok, [])
                hit = tail[0] if len(tail) == 1 else None
            if hit and hit not in out:
                out.append(hit)
        return out

    def companions(self, chosen, k=TOP_K):
        """Files that changed together with the chosen ones and are not among them.
        Ranked by how many chosen files each changed with, then by summed G²:
        a file that went along with every chosen file is the likeliest one missed.
        -> [{"target", "with": [chosen files], "g2", "triples": [lines]}]"""
        chosen = [f for f in chosen if f in self.count["file"]]
        found = defaultdict(lambda: {"with": [], "g2": 0.0, "triples": []})
        for f in chosen:
            for c, (g2, idx) in self.cochange.get(f, {}).items():
                if c in chosen:
                    continue
                e = found[c]
                e["with"].append(f)
                e["g2"] += g2
                e["triples"].append(self.line(idx))
        order = sorted(found, key=lambda c: (-len(found[c]["with"]), -found[c]["g2"], c))[:k]
        return [{"target": c, "with": found[c]["with"], "g2": round(found[c]["g2"], 1),
                 "triples": found[c]["triples"]} for c in order]

    @property
    def unit(self):
        return "units" if self.folder else "tasks"


def top_k(names, scores, fallback, k=TOP_K):
    idx = np.argsort(-scores, kind="stable")[:k]
    out = [names[i] for i in idx if np.isfinite(scores[i])]
    seen = set(out)
    for x in fallback:
        if len(out) >= k:
            break
        if x not in seen:
            out.append(x)
            seen.add(x)
    return out


class Query:
    """Per-query evidence, computed once and re-weighted by any parameters."""

    def __init__(self, O, text):
        self.O = O
        # a folder ontology decided itself which words are empty: no built-in stop list
        self.terms = sorted({O.variant.get(t, t) for t in terms_of(text, unicode=O.folder, stop=not O.folder)})
        # modules
        mod_ll, mod_ni = defaultdict(float), defaultdict(float)
        self.mod_ev = defaultdict(list)                # module -> [(term, contribution, line)]
        for t in self.terms:
            for m, (_, lift, i) in O.char["module"].get(t, {}).items():
                mod_ll[m] += math.log(lift)
                self.mod_ev[m].append((t, math.log(lift), i))
            for m, (exp, i) in O.not_in.get(t, {}).items():
                mod_ni[m] += math.log(0.5 / exp)
                self.mod_ev[m].append((t, math.log(0.5 / exp), i))
        self.mod_ll, self.mod_ni = mod_ll, mod_ni
        # files
        lf, ld, nm = defaultdict(float), defaultdict(float), defaultdict(float)
        self.file_ev, self.dir_ev, self.names_ev = defaultdict(list), defaultdict(list), defaultdict(list)
        for t in self.terms:
            for f, (_, lift, i) in O.char["file"].get(t, {}).items():
                lf[f] += math.log(lift)
                self.file_ev[f].append((t, math.log(lift), i))
            for d, (_, lift, i) in O.char["dir"].get(t, {}).items():
                ld[d] += math.log(lift)
                self.dir_ev[d].append((t, math.log(lift), i))
            for f, (n, i) in O.names.get(t, {}).items():
                nm[f] += n
                self.names_ev[f].append((t, n, i))
        # candidates: direct evidence, files of the best dirs, names, co-change
        # neighbours of evidenced files, most changed files of the 3 best modules
        cand = set(lf) | set(nm)
        for d in sorted(ld, key=lambda x: (-ld[x], x))[:30]:
            cand.update(O.files_in_dir.get(d, [])[:200])
        for f in list(lf):
            cand.update(O.cochange.get(f, ()))
        for m in sorted(mod_ll, key=lambda x: (-mod_ll[x], x))[:3]:
            cand.update(O.files_in_mod.get(m, [])[:200])
        self.cand = sorted(f for f in cand if f in O.count["file"])
        ix = {f: i for i, f in enumerate(self.cand)}
        cnt = np.array([O.count["file"][f] for f in self.cand], dtype=float)
        self.lp = np.log(cnt / O.N) if len(cnt) else np.zeros(0)
        self.LF = np.array([lf.get(f, 0.0) for f in self.cand])
        self.LD = np.array([ld.get(dir_of(f), 0.0) for f in self.cand])
        mll = {m: mod_ll.get(m, 0.0) + mod_ni.get(m, 0.0) for m in set(map(module_of, self.cand))}
        self.LM = np.array([mll[module_of(f)] for f in self.cand])
        self.NM = np.log1p(np.array([nm.get(f, 0.0) for f in self.cand]))
        rows, cols, vals = [], [], []
        for f in self.cand:
            nb = O.cochange.get(f, {})
            top = max((g for g, _ in nb.values()), default=0)
            for g_name, (g, _) in sorted(nb.items()):
                if g_name in ix:
                    rows.append(ix[f])
                    cols.append(ix[g_name])
                    vals.append(g / top)
        self.cc = (np.array(rows, dtype=int), np.array(cols, dtype=int), np.array(vals))
        # symbols (folder ontologies): classes and document sections
        self.sym_ll, self.sym_ev = defaultdict(float), defaultdict(list)
        for t in self.terms:
            for sym, (_, lift, i) in O.char["sym"].get(t, {}).items():
                self.sym_ll[sym] += math.log(lift)
                self.sym_ev[sym].append((t, math.log(lift), i))

    # ── scoring ──────────────────────────────────────────────────────────────
    def module_scores(self, prm):
        O = self.O
        names = O.mods_by_prior
        lam, ni = prm["lam"], prm.get("not_in", 1)
        sc = np.array([math.log(O.count["module"][m] / O.N)
                       + lam * (self.mod_ll.get(m, 0.0) + (self.mod_ni.get(m, 0.0) if ni else 0.0))
                       for m in names])
        return names, sc

    def _cochange_bonus(self, base, k=10):
        n = len(self.cand)
        if not len(self.cc[0]) or not n:
            return np.zeros(n)
        seeds = np.argsort(-base, kind="stable")[:k]
        w = np.zeros(n)
        w[seeds] = 1.0
        rows, cols, vals = self.cc
        out = np.zeros(n)
        np.add.at(out, cols, w[rows] * vals)
        return out

    def file_scores(self, prm):
        if not len(self.cand):
            return [], np.zeros(0)
        base = self.lp + prm["lam"] * (self.LF + prm["beta"] * self.LD + prm["beta2"] * self.LM) \
            + prm["mu"] * self.NM
        return self.cand, base + prm["gamma"] * self._cochange_bonus(base)

    def rank_modules(self, prm, k=TOP_K):
        names, sc = self.module_scores(prm)
        return top_k(names, sc, self.O.mods_by_prior, k)

    def rank_files(self, prm, k=TOP_K):
        names, sc = self.file_scores(prm)
        return top_k(names, sc, self.O.files_by_prior, k)

    def rank_symbols(self, prm, k=TOP_K):
        """classes / sections: lam * sum log lift, a symbol's file prior breaks ties"""
        lam = prm["lam"]
        def sc(sym):
            f = sym.split("#", 1)[0]
            return lam * self.sym_ll[sym] + 0.01 * math.log(self.O.count["file"].get(f, 1) / max(self.O.N, 1))
        return sorted(self.sym_ll, key=lambda s: (-sc(s), s))[:k], sc

    # ── explanation ──────────────────────────────────────────────────────────
    def explain_module(self, m, prm):
        O = self.O
        lam, ni = prm["lam"], prm.get("not_in", 1)
        prior = math.log(O.count["module"][m] / O.N)
        parts = [{"kind": "not_in" if c < 0 else "characterizes", "term": t,
                  "value": round(lam * c, 3), "triple": O.line(i)}
                 for t, c, i in self.mod_ev.get(m, []) if ni or c >= 0]
        return {"target": m, "prior": round(prior, 3), "task_count": O.count["module"][m],
                "score": round(prior + sum(p["value"] for p in parts), 3),
                "evidence": sorted(parts, key=lambda p: -abs(p["value"]))}

    def explain_file(self, f, prm, score=None):
        O = self.O
        lam = prm["lam"]
        parts = [{"kind": "file", "term": t, "value": round(lam * c, 3), "triple": O.line(i)}
                 for t, c, i in self.file_ev.get(f, [])]
        parts += [{"kind": "dir", "term": t, "value": round(lam * prm["beta"] * c, 3), "triple": O.line(i)}
                  for t, c, i in self.dir_ev.get(dir_of(f), []) if prm["beta"]]
        if prm["beta2"]:
            parts += [{"kind": "module", "term": t, "value": round(lam * prm["beta2"] * c, 3),
                       "triple": O.line(i)} for t, c, i in self.mod_ev.get(module_of(f), [])]
        n_names = sum(n for _, n, _ in self.names_ev.get(f, []))
        if prm["mu"] and n_names:
            parts += [{"kind": "names", "term": t, "value": round(prm["mu"] * math.log1p(n_names) / len(self.names_ev[f]), 3),
                       "triple": O.line(i)} for t, n, i in self.names_ev.get(f, [])]
        prior = math.log(O.count["file"][f] / O.N) if f in O.count["file"] else None
        out = {"target": f, "prior": round(prior, 3) if prior is not None else None,
               "task_count": O.count["file"].get(f, 0),
               "evidence": sorted(parts, key=lambda p: -abs(p["value"]))}
        if score is not None:
            known = (prior or 0) + sum(p["value"] for p in parts)
            out["score"] = round(score, 3)
            if prm["gamma"] and abs(score - known) > 1e-6:
                out["co_change_bonus"] = round(score - known, 3)
        return out

    def search(self, params, k=TOP_K):
        """-> {"terms", "modules": [explained], "files": [explained]}"""
        pm, pf = params["module"], params["file"]
        mods = self.rank_modules(pm, k)
        fnames, fsc = self.file_scores(pf)
        score_of = dict(zip(fnames, fsc))
        files = self.rank_files(pf, k)
        out = {"terms": self.terms,
               "modules": [self.explain_module(m, pm) for m in mods],
               "files": [self.explain_file(f, pf, score_of.get(f)) for f in files]}
        if self.sym_ll:
            syms, sc = self.rank_symbols(pf, k)
            out["symbols"] = [{"target": s, "score": round(sc(s), 3), "evidence": sorted(
                [{"kind": "sym", "term": t, "value": round(pf["lam"] * c, 3), "triple": self.O.line(i)}
                 for t, c, i in self.sym_ev[s]], key=lambda e: -abs(e["value"]))} for s in syms]
        return out
