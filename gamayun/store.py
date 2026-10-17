"""Where projects live.

A project lives next to what it describes: `gamayun index` run in a repository writes
<that folder>/.gamayun/<project>/ and leaves only a pointer in ~/.gamayun/projects.json,
so `gamayun ui` or `gamayun search --project <name>` started anywhere can find it.

  triples.txt   ontology built from all tasks (what search uses)
  params.json   ranking parameters tuned on dev (defaults until `gamayun eval`)
  stats.json    sizes of the build
  source.json   the database / repo the project was built from
  eval/         dev and test ontologies + results.json (from `gamayun eval`)

A project name is resolved in this order: <current folder>/.gamayun/<name>, the registry,
then ~/.gamayun/<name> (the first projects were built there). $GAMAYUN_HOME is for the tests:
with it set, everything is kept in that one folder (no local .gamayun, no registry).
"""
import json
import os
import re
from pathlib import Path

_NAME = re.compile(r"^[A-Za-z0-9._-]+$")
LOCAL = ".gamayun"
REGISTRY = "projects.json"
_SKIP = {".git", "node_modules", "venv", ".venv", "__pycache__", "dist", "build", ".idea", ".vscode", "target"}


def home() -> Path:
    return Path(os.environ.get("GAMAYUN_HOME") or Path.home() / ".gamayun")


def central() -> bool:
    """$GAMAYUN_HOME set: one central folder, the pre-registry behaviour."""
    return bool(os.environ.get("GAMAYUN_HOME"))


def read_json(path, default=None):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def write_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def check_name(name: str) -> str:
    if not _NAME.match(name or "") or name.strip(".") == "":
        raise ValueError(f"bad project name: {name!r}")
    return name


def registry() -> dict:
    """{name: {"dir": <project folder>, "root": <folder holding .gamayun>}}"""
    return read_json(home() / REGISTRY, {}) or {}


def register(name: str, folder: Path, root: Path):
    reg = registry()
    reg[name] = {"dir": str(Path(folder).resolve()), "root": str(Path(root).resolve())}
    write_json(home() / REGISTRY, reg)


def unregister(name: str):
    reg = registry()
    if reg.pop(name, None) is not None:
        write_json(home() / REGISTRY, reg)


def new_project_dir(name: str, root=None) -> Path:
    """Where a build writes: <root or the current folder>/.gamayun/<name>, registered."""
    check_name(name)
    if central():
        return home() / name
    root = Path(root or os.getcwd()).resolve()
    d = root / LOCAL / name
    register(name, d, root)
    return d


def project_dir(name: str) -> Path:
    """The folder of an existing project (or where it would be, for an error message)."""
    check_name(name)
    if central():
        return home() / name
    local = Path.cwd() / LOCAL / name
    if (local / "triples.txt").is_file():
        return local
    hit = registry().get(name)
    if hit and Path(hit["dir"]).is_dir():
        return Path(hit["dir"])
    return home() / name


def project_root(name: str):
    """The folder a project describes (holds its .gamayun), None for a home project."""
    d = project_dir(name)
    return d.parent.parent if d.parent.name == LOCAL else None


def _discover(start: Path, max_depth: int = 4):
    """.gamayun/<name>/triples.txt under the folder the UI was started from (like alkonost)."""
    found = []

    def walk(p: Path, depth: int):
        try:
            entries = list(os.scandir(p))
        except OSError:
            return
        for e in entries:
            if not e.is_dir(follow_symlinks=False):
                continue
            if e.name == LOCAL:
                for sub in os.scandir(e.path):
                    if sub.is_dir() and (Path(sub.path) / "triples.txt").is_file():
                        found.append((sub.name, Path(sub.path), p))
                continue
            if depth < max_depth and e.name not in _SKIP and not e.name.startswith("."):
                walk(Path(e.path), depth + 1)

    walk(start, 0)
    return found


def _entry(name, d: Path, where, root=None):
    return {"project": name, "dir": str(d), "root": str(root) if root else "", "where": where,
            "stats": read_json(d / "stats.json", {}),
            "source": read_json(d / "source.json", {}),
            "tuned": (d / "params.json").is_file(),
            "results": read_json(d / "eval" / "results.json")}


def list_projects(start=None):
    """Every project this machine knows: registered ones, those under `start` (registered on
    the way, unless the name is already taken by another folder), and home ones. One entry
    per name: the same name resolves to one ontology everywhere."""
    out, seen = [], set()
    if central():
        root = home()
        if root.is_dir():
            for d in sorted(root.iterdir()):
                if (d / "triples.txt").is_file():
                    out.append(_entry(d.name, d, "home"))
        return out
    reg = registry()
    if start:
        for name, d, root in _discover(Path(start).resolve()):
            if name not in reg:
                register(name, d, root)
                reg = registry()
    for name, info in sorted(reg.items()):
        d = Path(info["dir"])
        if (d / "triples.txt").is_file():
            out.append(_entry(name, d, "local", info.get("root")))
            seen.add(name)
    root = home()
    if root.is_dir():
        for d in sorted(root.iterdir()):
            if d.is_dir() and d.name not in seen and (d / "triples.txt").is_file():
                out.append(_entry(d.name, d, "home"))
    return out
