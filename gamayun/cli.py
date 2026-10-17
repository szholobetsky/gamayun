"""gamayun command line.

  gamayun index  --db sonar.db [--repo ./sonarqube] --project sonar   (alias: build)
  gamayun index  --files ./docs --project docs      # documents and/or code, no task database
      the ontology goes to <current folder>/.gamayun/<project> (or --root <folder>), and
      ~/.gamayun/projects.json remembers where, so every other command finds it from anywhere
  gamayun eval   --project sonar            # tune on dev, test once -> params.json, results
  gamayun tune   --project sonar            # dev only -> params.json
  gamayun search "scanner crashes on quality gate" --project sonar [--k 10] [--json]
  gamayun show   term:scanner --project sonar
  gamayun companions --project sonar --from answer.md     # files that change with the ones named
  gamayun compass "FOP logs flood the PDF report" --project sonar --repo ./sonarqube   # where to start
  gamayun health --project sonar [--by month] [--unit server/sonar-web] [--units]     # the evolution square
  gamayun list
  gamayun ui     [--host 127.0.0.1] [--port 8095]
"""
import argparse
import json
import os
import sys


def _print(s=""):
    try:
        print(s)
    except UnicodeEncodeError:
        enc = getattr(sys.stdout, "encoding", None) or "ascii"
        print(s.encode(enc, errors="replace").decode(enc, errors="replace"))


def main(argv=None):
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass
    p = argparse.ArgumentParser(prog="gamayun", description="Task-to-code search over an LLM-free ontology")
    sub = p.add_subparsers(dest="cmd", required=True)
    for name in ("build", "index"):          # `index` as in simargl / svitovyd
        b = sub.add_parser(name, help="build the ontology from all tasks of a database, or from a folder")
        src = b.add_mutually_exclusive_group(required=True)
        src.add_argument("--db", help="task database (TASK/TASKS + COMMIT/COMMITS)")
        src.add_argument("--files", metavar="FOLDER", help="folder of documents and/or code (no database)")
        b.add_argument("--repo", default="", help="git clone (adds module depends_on; with --db)")
        b.add_argument("--project", required=True)
        b.add_argument("--root", default="", help="folder to keep the ontology in, as <root>/.gamayun/<project> "
                                                  "(default: the current folder)")
    for name in ("eval", "tune"):
        e = sub.add_parser(name, help="tune on dev" + (", then test once" if name == "eval" else ""))
        e.add_argument("--project", required=True)
    s = sub.add_parser("search", help="rank modules and files for a task text")
    s.add_argument("text")
    s.add_argument("--project", required=True)
    s.add_argument("--k", type=int, default=10)
    s.add_argument("--json", action="store_true")
    sh = sub.add_parser("show", help="all triples of an entity (term:x, ident:x, module:x, dir:x, file:x, sym:x)")
    sh.add_argument("entity")
    sh.add_argument("--project", required=True)
    sh.add_argument("--limit", type=int, default=50)
    cp = sub.add_parser("compass", help="where to start for a task, and how sure: a rare literal anchor "
                                         "found in the code, else the ontology ranking (no LLM)")
    cp.add_argument("text")
    cp.add_argument("--project", required=True)
    cp.add_argument("--repo", default="", help="git clone to look for anchors in (default: the project's --repo)")
    cp.add_argument("--rev", default="", help="look at this revision instead of the working tree")
    cp.add_argument("--k", type=int, default=5)
    cp.add_argument("--json", action="store_true")
    c = sub.add_parser("companions", help="files that changed together with the files named in a text "
                                          "(e.g. an answer listing files to change): the ones it likely missed")
    c.add_argument("files", nargs="*", help="file paths; or use --from")
    c.add_argument("--from", dest="src", metavar="FILE", help="read the text naming the files from this file")
    c.add_argument("--project", required=True)
    c.add_argument("--k", type=int, default=10)
    c.add_argument("--json", action="store_true")
    hl = sub.add_parser("health", help="the Novelty x Structurality square of the task history: "
                                       "evolution / maintenance / disruption / stagnation, by month, quarter or year")
    hl.add_argument("--project", required=True)
    hl.add_argument("--by", choices=["month", "quarter", "year"], default="year")
    hl.add_argument("--depth", type=int, default=2, help="folders that make a unit (default 2: server/sonar-web)")
    scope = hl.add_mutually_exclusive_group()
    scope.add_argument("--unit", help="one part of the code (a path prefix): its cohesion against its coupling")
    scope.add_argument("--file", help="one file")
    hl.add_argument("--units", action="store_true", help="also rank every unit by stagnation")
    hl.add_argument("--since", help="YYYY or YYYY-MM")
    hl.add_argument("--until", help="YYYY or YYYY-MM")
    hl.add_argument("--min-before", type=int, default=1,
                    help="a pair is known after changing together in this many earlier tasks (default 1)")
    hl.add_argument("--top", type=int, default=15)
    hl.add_argument("--json", action="store_true")
    sub.add_parser("list", help="projects: registered ones, those under the current folder, home ones")
    u = sub.add_parser("ui", help="web UI over every project this machine knows (and those under the current folder)")
    u.add_argument("--host", default="127.0.0.1")
    u.add_argument("--port", type=int, default=8095)
    a = p.parse_args(argv)

    from . import pipeline, store
    if a.cmd in ("build", "index"):
        if a.files:
            pipeline.build_folder_project(a.files, a.project, log=_print, root=a.root or None)
        else:
            pipeline.build_project(a.db, a.project, a.repo, log=_print, root=a.root or None)
    elif a.cmd in ("eval", "tune"):
        pipeline.evaluate_project(a.project, log=_print, with_test=a.cmd == "eval")
    elif a.cmd == "search":
        from .onto import Onto
        O = Onto(store.project_dir(a.project))
        res = O.query(a.text).search(pipeline.load_params(a.project), a.k)
        if a.json:
            _print(json.dumps(res, indent=2, ensure_ascii=False))
            return
        _print(f"terms: {' '.join(res['terms'])}\n\nmodules:")
        for i, m in enumerate(res["modules"], 1):
            why = ", ".join(f"{e['term']} {e['value']:+.2f}" for e in m["evidence"][:4])
            _print(f"  {i:2d}. {m['target']:40s} {m['score']:7.2f}  {why}")
        _print("\nfiles:")
        for i, f in enumerate(res["files"], 1):
            why = ", ".join(f"{e['term']}/{e['kind']} {e['value']:+.2f}" for e in f["evidence"][:4])
            _print(f"  {i:2d}. {f['target']}\n        {why}")
    elif a.cmd == "show":
        from .onto import Onto
        O = Onto(store.project_dir(a.project))
        rows = O.entity(a.entity, a.limit)
        if not rows:
            _print(f"no triples for {a.entity}")
        for r in rows:
            _print(f"{r['s']} :: {r['p']} :: {r['o']}  [src: {r['src']}]")
    elif a.cmd == "compass":
        from .compass import compass, render
        from .onto import Onto
        O = Onto(store.project_dir(a.project))
        repo = a.repo or default_repo(a.project)
        res = compass(O, a.text, pipeline.load_params(a.project), repo or None, a.rev or None, a.k)
        _print(json.dumps(res, indent=2, ensure_ascii=False) if a.json else render(res))
    elif a.cmd == "companions":
        from .onto import Onto
        O = Onto(store.project_dir(a.project))
        text = " ".join(a.files)
        if a.src:
            text += "\n" + open(a.src, encoding="utf-8", errors="replace").read()
        chosen = O.files_in_text(text)
        res = O.companions(chosen, a.k)
        if a.json:
            _print(json.dumps({"chosen": chosen, "companions": res}, indent=2, ensure_ascii=False))
            return
        if not chosen:
            _print(f"no files of project {a.project} named in the text")
            return
        _print(f"chosen ({len(chosen)}): " + ", ".join(chosen))
        _print("\nchanged together with them, not chosen:" if res else "\nno co-change partners outside the chosen files")
        for i, r in enumerate(res, 1):
            names = ", ".join(f.rsplit("/", 1)[-1] for f in r["with"])
            _print(f"  {i:2d}. {r['target']}\n        with {len(r['with'])} of {len(chosen)} chosen ({names}); G2 {r['g2']}")
    elif a.cmd == "health":
        from . import health as H
        d = store.project_dir(a.project)
        db = (store.read_json(d / "source.json", {}) or {}).get("db")
        if not db:
            raise SystemExit(f"project {a.project!r} has no task database (a folder project): health needs the task history")
        hist = H.load_history(db)
        rep = H.health(hist, a.depth, a.by, a.unit, a.file, a.min_before, a.since, a.until)
        if a.units:
            rep["units"] = H.units(hist, a.depth, a.min_before, a.since, a.top)
        if not (a.unit or a.file or a.since or a.until):
            rep["snapshot"] = str(H.snapshot(d, rep))           # the whole code base: kept, dated
        if a.json:
            _print(json.dumps(rep, indent=1, ensure_ascii=False))
            return
        scope = f"unit {a.unit}" if a.unit else f"file {a.file}" if a.file else "whole code base"
        _print(f"{a.project}: {scope}, tasks {rep['first']} .. {rep['last']}, unit depth {a.depth}, "
               f"{rep['excluded_large']} tasks of > {H.MAX_FILES} files left out\n")
        if not rep["total"]:
            _print("no task with two or more files in scope")
            return
        _print(H.ascii_square(rep["total"]))
        _print(f"\n{'period':9} {'tasks':>5}  {'novelty':>7} {'struct':>6}  {'evol':>5} {'maint':>5} {'disr':>5} {'stagn':>5}  zone")
        for p in rep["periods"][-36:]:
            _print(f"{p['period']:9} {p['tasks']:5}  {p['novelty']:7.2f} {p['structurality']:6.2f}  "
                   f"{p['evolution']:5.2f} {p['maintenance']:5.2f} {p['disruption']:5.2f} {p['stagnation']:5.2f}  {p['zone']}")
        if a.units:
            _print(f"\nunits by stagnation{' since ' + a.since if a.since else ''} (at least 5 tasks)")
            for u in rep["units"]:
                _print(f"  {u['unit']:44} {u['tasks']:5} tasks  stagn {u['stagnation']:.2f}  disr {u['disruption']:.2f}  "
                       f"evol {u['evolution']:.2f}  maint {u['maintenance']:.2f}")
        if rep.get("snapshot"):
            _print(f"\nkept: {rep['snapshot']}")
    elif a.cmd == "list":
        for pr in store.list_projects(start=os.getcwd()):
            st = pr["stats"]
            size = f"{st['train_tasks']} tasks" if "train_tasks" in st else f"{st.get('units', '?')} units"
            _print(f"{pr['project']:20s} {size}  "
                   f"{sum(st.get('predicates', {}).values())} triples  "
                   f"{'tuned' if pr['tuned'] else 'default params'}  "
                   f"{pr['source'].get('db') or pr['source'].get('files', '')}")
            _print(f"{'':20s} kept in {pr['dir']}" + (" (home, from before .gamayun/ in the project folder)"
                                                      if pr["where"] == "home" else ""))
    elif a.cmd == "ui":
        from .server import serve
        serve(a.host, a.port, start=os.getcwd())


def default_repo(project):
    """The repository a project's anchors are looked for in: the one it was built with,
    else the folder it lives in (<repo>/.gamayun/<project>) when that is a git clone."""
    from . import store
    repo = (store.read_json(store.project_dir(project) / "source.json", {}) or {}).get("repo", "")
    if repo:
        return repo
    root = store.project_root(project)
    return str(root) if root and (root / ".git").exists() else ""


if __name__ == "__main__":
    main()
