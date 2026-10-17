"""Flask API + static UI (gamayun/ui, no build step).

  GET  /api/projects
  POST /api/search      {project, text, k}
  POST /api/compass     {project, text, k, repo?}   where to start + confidence (repo: the project's own)
  POST /api/companions  {project, text, k}          files changed together with those named in text
  POST /api/health      {project, by, depth, unit?, file?, since?, until?, min_before}  evolution square
  POST /api/map         {project, prefix?, source: ontology|history, compare?, since?, until?, min_tasks, per_node}
                        one layer of the module map (compare: a code project to overlay)
  POST /api/edge        {project, prefix, a, b, source, compare?, since?, until?}  what one link is made of
  GET  /api/entity?project=&name=
  POST /api/build       {db, repo, project} | {files: folder, project}   -> {job}
  POST /api/eval        {project, test}       -> {job}
  GET  /api/jobs/<id>                          -> {status, log, error}
"""
import os
import threading
import traceback
import uuid
from pathlib import Path

from flask import Flask, jsonify, request, send_from_directory

from . import pipeline, store
from .onto import Onto

UI_DIR = Path(__file__).parent / "ui"

_cache = {}           # ontology folder -> (mtime, Onto)
_cache_lock = threading.Lock()
_jobs = {}            # id -> {"status", "log", "error", "kind", "project"}
_start = None         # the folder `gamayun ui` was started in: projects under it are found too


def _onto(project):
    """The ontology of exactly this project. Keyed by its folder, so two projects can never
    share a loaded ontology, and every request names the project it is about."""
    if not project:
        raise ValueError("choose a project first")
    path = store.project_dir(project) / "triples.txt"
    if not path.is_file():
        raise FileNotFoundError(f"project {project!r} is not built")
    mtime = path.stat().st_mtime
    key = str(path.resolve())
    with _cache_lock:
        hit = _cache.get(key)
        if hit and hit[0] == mtime:
            return hit[1]
        O = Onto(path)
        _cache[key] = (mtime, O)
        return O


_hist_cache = {}      # db path -> (mtime, history): reading 10k tasks takes seconds


def _history(db):
    from .health import load_history
    mtime = os.path.getmtime(db)
    with _cache_lock:
        hit = _hist_cache.get(db)
        if hit and hit[0] == mtime:
            return hit[1]
    h = load_history(db)
    with _cache_lock:
        _hist_cache[db] = (mtime, h)
    return h


_titles_cache = {}    # db path -> (mtime, {task name: title})


def _titles(db):
    from .health import load_titles
    mtime = os.path.getmtime(db)
    with _cache_lock:
        hit = _titles_cache.get(db)
        if hit and hit[0] == mtime:
            return hit[1]
    t = load_titles(db)
    with _cache_lock:
        _titles_cache[db] = (mtime, t)
    return t


def _start_job(kind, project, fn):
    jid = uuid.uuid4().hex[:12]
    job = {"status": "running", "log": [], "error": "", "kind": kind, "project": project}
    _jobs[jid] = job

    def run():
        try:
            fn(lambda s="": job["log"].append(str(s)))
            job["status"] = "done"
        except Exception as e:
            job["status"] = "error"
            job["error"] = f"{type(e).__name__}: {e}"
            job["log"].append(traceback.format_exc())

    threading.Thread(target=run, daemon=True).start()
    return jid


def create_app():
    app = Flask(__name__, static_folder=None)

    @app.errorhandler(ValueError)
    @app.errorhandler(FileNotFoundError)
    def _bad(e):
        return jsonify({"error": str(e)}), 400

    @app.get("/")
    def index():
        return send_from_directory(UI_DIR, "index.html")

    @app.get("/ui/<path:name>")
    def ui(name):
        return send_from_directory(UI_DIR, name)

    @app.get("/api/projects")
    def projects():
        running = {j["project"] for j in _jobs.values() if j["status"] == "running"}
        out = store.list_projects(start=_start)
        for p in out:
            p["busy"] = p["project"] in running
        return jsonify({"projects": out, "home": str(store.home()), "start": str(_start or "")})

    @app.post("/api/search")
    def search():
        b = request.get_json(silent=True) or {}
        project, text = b.get("project", ""), (b.get("text") or "").strip()
        if not text:
            raise ValueError("empty task text")
        k = max(1, min(50, int(b.get("k", 10))))
        res = _onto(project).query(text).search(pipeline.load_params(project), k)
        return jsonify(res)

    @app.post("/api/compass")
    def compass_api():
        from .compass import compass
        b = request.get_json(silent=True) or {}
        project, text = b.get("project", ""), (b.get("text") or "").strip()
        if not text:
            raise ValueError("empty task text")
        k = max(1, min(20, int(b.get("k", 5))))
        from .cli import default_repo
        _onto(project)                                    # validates the project first
        repo = (b.get("repo") or "").strip() or default_repo(project)
        if repo and not os.path.isdir(repo):
            raise ValueError(f"repository folder not found: {repo}")
        res = compass(_onto(project), text, pipeline.load_params(project), repo or None, None, k)
        res["repo"] = repo
        return jsonify(res)

    def _project_history(project):
        _onto(project)                                    # an existing, built project
        d = store.project_dir(project)
        db = (store.read_json(d / "source.json", {}) or {}).get("db")
        if not db or not os.path.isfile(db):
            raise ValueError("this project has no task database (a folder project, or the database moved): "
                             "health and the map need the task history")
        return d, _history(db), db

    def _code_partner(b):
        other = (b.get("compare") or "").strip()
        if not other:
            return None
        if other == b.get("project"):
            raise ValueError("compare with another project: the one built from the code")
        return _onto(other)

    @app.post("/api/map")
    def map_api():
        """One layer of the module map: the children of `prefix` and the coupling between them.
        source "ontology" (default) reads the project's triples only — co-change for a task
        project, identifier use for a code project; with `compare` (a code project) the two
        are overlaid. source "history" reads the task database: time window, new links, zones."""
        b = request.get_json(silent=True) or {}
        project, prefix = b.get("project", ""), (b.get("prefix") or "").strip()
        min_tasks, per_node = max(1, int(b.get("min_tasks", 3))), max(1, min(30, int(b.get("per_node", 6))))
        if b.get("source") == "history":
            from . import health as H
            _, hist, _ = _project_history(project)
            since, until = (b.get("since") or "").strip() or None, (b.get("until") or "").strip() or None
            res = H.unit_map(hist, prefix, since, until, min_tasks, per_node)
            res["source"] = "history"
            return jsonify(res)
        from . import ontomap
        O, C = _onto(project), _code_partner(b)
        if C is not None:
            return jsonify(ontomap.overlay(O, C, prefix, min_tasks, per_node))
        return jsonify(ontomap.unit_map(O, prefix, min_tasks, per_node))

    @app.post("/api/edge")
    def edge_api():
        """One link of the map in detail (same sources as /api/map)."""
        b = request.get_json(silent=True) or {}
        project, prefix = b.get("project", ""), (b.get("prefix") or "").strip()
        x, y = (b.get("a") or "").strip(), (b.get("b") or "").strip()
        if not x or not y:
            raise ValueError("name both ends of the link")
        if b.get("source") == "history":
            from . import health as H
            _, hist, db = _project_history(project)
            since, until = (b.get("since") or "").strip() or None, (b.get("until") or "").strip() or None
            res = H.edge_detail(hist, prefix, x, y, since, until, _titles(db))
            res["source"] = "history"
            return jsonify(res)
        from . import ontomap
        return jsonify(ontomap.edge_detail(_onto(project), prefix, x, y, _code_partner(b)))

    @app.post("/api/health")
    def health_api():
        """The evolution square of the chosen project: totals, periods, units, and the
        snapshots kept by earlier builds."""
        from . import health as H
        b = request.get_json(silent=True) or {}
        d, hist, _ = _project_history(b.get("project", ""))
        by = b.get("by") if b.get("by") in ("month", "quarter", "year") else "year"
        depth = max(1, min(4, int(b.get("depth", 2))))
        unit, file = (b.get("unit") or "").strip() or None, (b.get("file") or "").strip() or None
        since, until = (b.get("since") or "").strip() or None, (b.get("until") or "").strip() or None
        rep = H.health(hist, depth, by, unit, file, max(1, int(b.get("min_before", 1))), since, until)
        rep["units"] = H.units(hist, depth, max(1, int(b.get("min_before", 1))), since, top=60)
        snaps = []
        for p in sorted((d / "health").glob("*.json")) if (d / "health").is_dir() else []:
            s = store.read_json(p, {}) or {}
            if s.get("total"):
                snaps.append({"built": s.get("built"), "last": s.get("last"),
                              **{k: s["total"][k] for k in ("novelty", "structurality", "zone", "tasks")}})
        rep["snapshots"] = snaps
        return jsonify(rep)

    @app.post("/api/companions")
    def companions_api():
        b = request.get_json(silent=True) or {}
        project, text = b.get("project", ""), (b.get("text") or "").strip()
        if not text:
            raise ValueError("paste a list of files or an answer that names them")
        k = max(1, min(30, int(b.get("k", 10))))
        O = _onto(project)
        chosen = O.files_in_text(text)
        return jsonify({"chosen": chosen, "companions": O.companions(chosen, k)})

    @app.get("/api/entity")
    def entity():
        project, name = request.args.get("project", ""), request.args.get("name", "").strip()
        if not name:
            raise ValueError("empty entity name")
        return jsonify({"name": name, "triples": _onto(project).entity(name, 500)})

    @app.post("/api/build")
    def build():
        b = request.get_json(silent=True) or {}
        project, db, repo = b.get("project", ""), (b.get("db") or "").strip(), (b.get("repo") or "").strip()
        folder = (b.get("files") or "").strip()
        root = (b.get("root") or "").strip()
        store.check_name(project)
        # the ontology lives next to what it describes: the folder of documents / code, else the
        # repository, else the folder the UI was started in
        if folder and not db:
            if not os.path.isdir(folder):
                raise ValueError(f"folder not found: {folder}")
            root = root or folder
            jid = _start_job("build", project,
                             lambda log: pipeline.build_folder_project(folder, project, log, root=root))
            return jsonify({"job": jid, "root": root})
        if not os.path.isfile(db):
            raise ValueError(f"database not found: {db}")
        if repo and not os.path.isdir(repo):
            raise ValueError(f"repository folder not found: {repo}")
        root = root or repo or str(_start or os.getcwd())
        if not os.path.isdir(root):
            raise ValueError(f"folder not found: {root}")
        jid = _start_job("build", project, lambda log: pipeline.build_project(db, project, repo, log, root=root))
        return jsonify({"job": jid, "root": root})

    @app.post("/api/eval")
    def evaluate():
        b = request.get_json(silent=True) or {}
        project = b.get("project", "")
        _onto(project)                                    # an existing, built project
        test = bool(b.get("test", True))
        jid = _start_job("eval", project,
                         lambda log: pipeline.evaluate_project(project, log, with_test=test))
        return jsonify({"job": jid})

    @app.get("/api/jobs/<jid>")
    def job(jid):
        j = _jobs.get(jid)
        if not j:
            return jsonify({"error": "no such job"}), 404
        return jsonify(j)

    return app


def serve(host="127.0.0.1", port=8095, start=None):
    global _start
    _start = start
    app = create_app()
    n = len(store.list_projects(start=start))
    print(f"gamayun UI: http://{host}:{port}/   ({n} project(s): registered in {store.home()}"
          + (f", and under {start})" if start else ")"))
    try:
        from waitress import serve as _serve
        _serve(app, host=host, port=port, threads=8)
    except ImportError:
        app.run(host=host, port=port, threaded=True)
