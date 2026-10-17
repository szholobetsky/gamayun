"""Build the ontology: every predicate is a formula over the training tasks
plus a significance threshold (see concepts/GAMAYUN.md §4-8). A triple is
written only when its rule fires; [src: ...] carries the numbers."""
import subprocess
from collections import Counter, defaultdict

import numpy as np
from scipy import sparse

from .data import dir_of, file_name_terms, module_of

G2_P001 = 10.828          # chi-square, 1 dof, p = 0.001

DEFAULTS = {"min_df": 5, "max_df": 0.3, "max_files": 30}


def g2_vec(a, row, col, n):
    """G² (Dunning 1993) of 2x2 tables, vectorised.
    a = both, row = tasks with the term, col = tasks touching the target, n = all.
    -> (G², positive association)."""
    a, row, col = (np.asarray(x, dtype=np.float64) for x in (a, row, col))
    cells = ((a, row * col / n), (row - a, row * (n - col) / n),
             (col - a, (n - row) * col / n), (n - row - col + a, (n - row) * (n - col) / n))
    s = np.zeros_like(a)
    for o, e in cells:
        ok = (o > 0) & (e > 0)
        s[ok] += o[ok] * np.log(o[ok] / e[ok])
    return 2 * s, a * n > row * col


def build(train, repo="", sha="", min_df=5, max_df=0.3, max_files=30, log=print):
    """train: [(task_name, set(terms), set(files))] -> (triple lines, stats)."""
    train = [t for t in train if t[2]]           # no changed files = no evidence
    N = len(train)
    if N < 20:
        raise ValueError(f"too few tasks with changed files: {N}")
    df = Counter(t for _, ts, _ in train for t in ts)
    terms = sorted(t for t, c in df.items() if min_df <= c <= max_df * N)
    files = sorted({f for _, _, fs in train for f in fs})
    dirs = sorted({dir_of(f) for f in files})
    mods = sorted({module_of(f) for f in files})
    ti, fi, di, mi = ({x: i for i, x in enumerate(v)} for v in (terms, files, dirs, mods))
    log(f"tasks {N}  terms {len(terms)}  files {len(files)}  dirs {len(dirs)}  modules {len(mods)}")

    def incidence(rows, ncols):
        r = [i for i, cols in enumerate(rows) for _ in cols]
        c = [j for cols in rows for j in cols]
        return sparse.csr_matrix((np.ones(len(r), dtype=np.float32), (r, c)), shape=(len(rows), ncols))

    T = incidence([{ti[t] for t in ts if t in ti} for _, ts, _ in train], len(terms))
    F = incidence([{fi[f] for f in fs} for _, _, fs in train], len(files))
    D = incidence([{di[dir_of(f)] for f in fs} for _, _, fs in train], len(dirs))
    M = incidence([{mi[module_of(f)] for f in fs} for _, _, fs in train], len(mods))
    row_t = np.asarray(T.sum(0)).ravel()
    col = {"f": np.asarray(F.sum(0)).ravel(), "d": np.asarray(D.sum(0)).ravel(),
           "m": np.asarray(M.sum(0)).ravel()}

    lines, stats = [], Counter()

    def emit(s, p, o, src):
        lines.append(f"{s} :: {p} :: {o}  [src: {src}]")
        stats[p] += 1

    # structure
    emit("dataset", "train_tasks", str(N), "tasks the ontology is built from")
    for m in mods:
        emit(f"module:{m}", "task_count", str(int(col["m"][mi[m]])), "tasks touching it")
    for d in dirs:
        emit(f"dir:{d}", "part_of", f"module:{module_of(d + '/x')}", "path")
    for f in files:
        emit(f"file:{f}", "part_of", f"dir:{dir_of(f)}", "path")
        emit(f"file:{f}", "task_count", str(int(col["f"][fi[f]])), "tasks touching it")

    # characterizes: G² >= 10.83, positive, minimum support
    def characterizes(X, kind, prefix, names, min_a):
        C = (T.T @ X).tocoo()
        keep = C.data >= min_a
        r, c, a = C.row[keep], C.col[keep], C.data[keep]
        g, pos = g2_vec(a, row_t[r], col[kind][c], N)
        ok = pos & (g >= G2_P001)
        for i, j, aa, gg in zip(r[ok], c[ok], a[ok], g[ok]):
            lift = aa * N / (row_t[i] * col[kind][j])
            emit(f"term:{terms[i]}", "characterizes", f"{prefix}:{names[j]}",
                 f"n={int(aa)};df={int(row_t[i])};g2={gg:.1f};lift={lift:.2f}")
        return C

    TM = characterizes(M, "m", "module", mods, 5)
    characterizes(D, "d", "dir", dirs, 3)
    TF = characterizes(F, "f", "file", files, 3)
    log("characterizes done")

    # anchor_of: Herfindahl index of the term's spread over modules >= 0.5
    tm = sparse.csr_matrix((TM.data, (TM.row, TM.col)), shape=TM.shape)
    for i in range(len(terms)):
        rowv = tm.getrow(i)
        tot = rowv.data.sum()
        if row_t[i] < 10 or tot == 0:
            continue
        shares = rowv.data / tot
        hhi = float((shares ** 2).sum())
        if hhi >= 0.5:
            emit(f"term:{terms[i]}", "anchor_of", f"module:{mods[rowv.indices[shares.argmax()]]}",
                 f"hhi={hhi:.2f};share={shares.max():.2f};df={int(row_t[i])}")

    # names: term is part of the file name AND they co-occur in >= 2 tasks
    tf_pairs = {(i, j): a for i, j, a in zip(TF.row, TF.col, TF.data)}
    for f in files:
        j = fi[f]
        for t in sorted(file_name_terms(f)):
            i = ti.get(t)
            if i is not None and tf_pairs.get((i, j), 0) >= 2:
                emit(f"term:{t}", "names", f"file:{f}", f"n={int(tf_pairs[(i, j)])}")

    # not_in: zero co-occurrences although chance predicts some, P0 = (1-r)^df < 0.001
    tm_dense = tm.toarray()
    rate = col["m"] / N
    for i in np.where(row_t >= 30)[0]:
        p0 = (1 - rate) ** row_t[i]
        for j in np.where((tm_dense[i] == 0) & (p0 < 1e-3))[0]:
            emit(f"term:{terms[i]}", "not_in", f"module:{mods[j]}",
                 f"expected={row_t[i] * rate[j]:.1f};observed=0;p0={p0[j]:.1e}")
    log("names, anchors, not_in done")

    # co_changes_with: G² over tasks touching <= max_files files
    small = np.array([len(fs) <= max_files for _, _, fs in train])
    Fs = F[np.where(small)[0]]
    Ns = int(small.sum())
    col_s = np.asarray(Fs.sum(0)).ravel()
    FF = sparse.triu(Fs.T @ Fs, k=1).tocoo()
    keep = FF.data >= 3
    r, c, a = FF.row[keep], FF.col[keep], FF.data[keep]
    g, pos = g2_vec(a, col_s[r], col_s[c], Ns)
    ok = pos & (g >= G2_P001)
    for i, j, aa, gg in zip(r[ok], c[ok], a[ok], g[ok]):
        emit(f"file:{files[i]}", "co_changes_with", f"file:{files[j]}",
             f"n={int(aa)};g2={gg:.1f};lift={aa * Ns / (col_s[i] * col_s[j]):.2f}")

    # narrower_than: subsumption P(A|B) >= 0.8, df(A) > df(B)
    big = np.where(row_t >= 20)[0]
    Tb = T[:, big]
    C = (Tb.T @ Tb).tocoo()
    for x, y, aa in zip(C.row, C.col, C.data):
        if x == y or aa < 5:
            continue
        b_, a_ = big[x], big[y]
        if row_t[a_] > row_t[b_] and aa / row_t[b_] >= 0.8:
            emit(f"term:{terms[b_]}", "narrower_than", f"term:{terms[a_]}",
                 f"p_a_given_b={aa / row_t[b_]:.2f};df_b={int(row_t[b_])};df_a={int(row_t[a_])}")
    log("co_changes_with, narrower_than done")

    if repo and sha:
        try:
            edges, n_java = java_depends(repo, sha)
            for (ma, mb), n in sorted(edges.items()):
                if n >= 3:
                    emit(f"module:{ma}", "depends_on", f"module:{mb}",
                         f"importing_files={n};snapshot={sha[:10]}")
            log(f"depends_on done ({n_java} java files at {sha[:10]})")
        except (OSError, subprocess.CalledProcessError) as e:
            log(f"depends_on skipped: {e}")

    return lines, {"train_tasks": N, "terms": len(terms), "files": len(files),
                   "dirs": len(dirs), "modules": len(mods), "predicates": dict(stats)}


def java_depends(repo, sha):
    """Module -> module edges from Java imports at commit `sha`, read with
    git cat-file (no checkout: the working tree is never touched)."""
    ls = subprocess.run(["git", "-C", repo, "ls-tree", "-r", "--name-only", sha],
                        capture_output=True, text=True, check=True).stdout.split("\n")
    java = [p for p in ls if p.endswith(".java")]
    proc = subprocess.Popen(["git", "-C", repo, "cat-file", "--batch"],
                            stdin=subprocess.PIPE, stdout=subprocess.PIPE)
    pkg_mod, imports = defaultdict(Counter), {}
    for p in java:
        proc.stdin.write(f"{sha}:{p}\n".encode())
        proc.stdin.flush()
        header = proc.stdout.readline().split()
        if len(header) < 3:
            continue
        body = proc.stdout.read(int(header[2]) + 1).decode("utf-8", "replace")
        imps = []
        for ln in body.splitlines():
            ln = ln.strip()
            if ln.startswith("package "):
                pkg_mod[ln[8:].rstrip(";").strip()][module_of(p)] += 1
            elif ln.startswith("import ") and not ln.startswith("import static"):
                imps.append(ln[7:].rstrip(";").strip().rsplit(".", 1)[0])
            elif ln.startswith(("public ", "class ", "final ", "abstract ", "interface ", "@")):
                break
        imports[p] = imps
    proc.stdin.close()
    proc.wait()
    owner = {pk: c.most_common(1)[0][0] for pk, c in pkg_mod.items()}
    edges = Counter()
    for p, imps in imports.items():
        for mb in {owner[i] for i in imps if i in owner}:
            if mb != module_of(p):
                edges[(module_of(p), mb)] += 1
    return edges, len(java)
