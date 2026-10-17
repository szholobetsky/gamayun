"""Build and evaluate a project — shared by the CLI and the web UI."""
import os
import time

from . import store
from .builder import build
from .data import load, modn_split, terms_of
from .evaluation import Case, score, tune
from .onto import DEFAULT_PARAMS, Onto


def _train_rows(tasks, task_files):
    return [(n, terms_of(txt), task_files.get(n, set())) for _, n, txt in tasks]


def _write(folder, lines, stats, header):
    folder.mkdir(parents=True, exist_ok=True)
    with open(folder / "triples.txt", "w", encoding="utf-8") as f:
        f.write(f"# {header} — gamayun, built without an LLM; see concepts/GAMAYUN.md\n")
        f.write("\n".join(lines) + "\n")
    store.write_json(folder / "stats.json", stats)


def build_project(db, project, repo="", log=print, root=None):
    """Ontology from ALL tasks of the database — what `search` uses.
    Written to <root>/.gamayun/<project> (root: the current folder by default)."""
    t0 = time.time()
    d = store.new_project_dir(project, root)
    log(f"reading {db}")
    tasks, task_files, sha = load(db)
    lines, stats = build(_train_rows(tasks, task_files), repo=repo, sha=sha, log=log)
    stats["seconds"] = round(time.time() - t0, 1)
    _write(d, lines, stats, f"{os.path.basename(db)}, all {stats['train_tasks']} tasks")
    store.write_json(d / "source.json", {"db": os.path.abspath(db),
                                         "repo": os.path.abspath(repo) if repo else "",
                                         "snapshot": sha, "built": time.strftime("%Y-%m-%d %H:%M")})
    log(f"{len(lines)} triples -> {d / 'triples.txt'} ({stats['seconds']}s)")
    try:                                                    # the health square, dated by this build
        from . import health as H
        hist = H.load_history(db)
        rep = H.health(hist, by="month")
        rep["units"] = H.units(hist, top=30)
        if rep["total"]:
            t = rep["total"]
            log(f"health: {t['zone'].upper()}  novelty {t['novelty']:.2f}  structurality {t['structurality']:.2f}"
                f"  -> {H.snapshot(d, rep)}")
    except Exception as e:                                  # never fail a build over the report
        log(f"health report skipped: {e}")
    return stats


def build_folder_project(folder, project, log=print, root=None):
    """Ontology from a folder of documents and/or code (gamayun/folder.py).
    Written to <root>/.gamayun/<project> (root: the current folder by default)."""
    from .folder import build_folder
    if not os.path.isdir(folder):
        raise ValueError(f"folder not found: {folder}")
    t0 = time.time()
    d = store.new_project_dir(project, root)
    log(f"reading {folder}")
    lines, stats = build_folder(folder, log=log)
    stats["seconds"] = round(time.time() - t0, 1)
    _write(d, lines, stats, f"folder {os.path.abspath(folder)}, {stats['units']} units")
    store.write_json(d / "source.json", {"files": os.path.abspath(folder),
                                         "built": time.strftime("%Y-%m-%d %H:%M")})
    log(f"{len(lines)} triples -> {d / 'triples.txt'} ({stats['seconds']}s)")
    return stats


def evaluate_project(project, log=print, with_test=True):
    """modn split: 200 test tasks; 200 dev tasks from the rest. Parameters are
    tuned on dev (ontology without dev and test), then — if with_test — applied
    once to test (ontology without test). Writes params.json and eval/results.json."""
    d = store.project_dir(project)
    src = store.read_json(d / "source.json")
    if not src:
        raise ValueError(f"project {project!r} is not built yet")
    if not src.get("db"):
        raise ValueError(f"project {project!r} was built from files (--files): evaluation needs a task database "
                         "(tasks x changed files); folder projects search with the default parameters")
    log(f"reading {src['db']}")
    tasks, task_files, _ = load(src["db"])
    train, test = modn_split(tasks)
    train_dev, dev = modn_split(train)

    def held(rows):
        return [{"name": n, "text": txt, "files": sorted(task_files.get(n, ()))}
                for _, n, txt in rows if task_files.get(n)]

    log("building the dev ontology (without dev and test tasks)")
    lines, stats = build(_train_rows(train_dev, task_files), log=log)
    _write(d / "eval" / "dev", lines, stats, "dev ontology")
    O = Onto(d / "eval" / "dev")
    cases = [Case(O, t) for t in held(dev)]
    log(f"tuning on {len(cases)} dev tasks")
    pm, ap_m = tune(O, cases, "module", log)
    pf, ap_f = tune(O, cases, "file", log)
    params = {"module": pm, "file": pf, "dev_map": {"module": round(ap_m, 4), "file": round(ap_f, 4)}}
    store.write_json(d / "params.json", params)
    results = {"params": params, "dev_tasks": len(cases)}
    if with_test:
        log("building the test ontology (without test tasks)")
        lines, stats = build(_train_rows(train, task_files), log=log)
        _write(d / "eval" / "test", lines, stats, "test ontology")
        O = Onto(d / "eval" / "test")
        cases = [Case(O, t) for t in held(test)]
        rows = {}
        for level, prm in (("module", pm), ("file", pf)):
            for name, p in (("prior", None), ("naive_bayes", prm)):
                m = score(O, cases, level, p)
                rows[f"{level}/{name}"] = {k: round(v, 4) for k, v in m.items()}
                log(f"test {level:6s} {name:11s} MAP {m['AP']:.4f}  MRR {m['RR']:.4f}  "
                    f"R@10 {m['R@10']:.3f}  hit@10 {m['hit@10']:.3f}")
        results.update({"test_tasks": len(cases), "test": rows})
    store.write_json(d / "eval" / "results.json", results)
    return results


def load_params(project):
    p = store.read_json(store.project_dir(project) / "params.json")
    if not p:
        return DEFAULT_PARAMS
    return {"module": p["module"], "file": p["file"]}
