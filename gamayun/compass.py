"""Compass: where to start for a task, and how sure we are. No LLM.

  1. literal anchors in the task text — a quoted string, a CamelCase name, a dotted.name,
     a Hyphen-Name — are looked up in the code with `git grep -F`; the rarest anchor that
     occurs in 1..MAX_ANCHOR_FILES files wins (a word that is everywhere points nowhere);
  2. without such an anchor: the ontology's file ranking with its evidence;
  3. the files that change together with the first one (co_changes_with).

Confidence is a fixed rule, set before any evaluation, so that it can be checked:
  high    an anchor found in 1..3 files
  medium  an anchor found in 4..MAX_ANCHOR_FILES files, or an ontology answer whose first file
          carries file-level evidence from at least two of the task's words
  low     anything else — then the answer is an area to look in, not a file.
"""
import re
import subprocess

from .data import dir_of, module_of

MAX_ANCHOR_FILES = 30
HIGH_ANCHOR_FILES = 3
_ANCHORS = [
    re.compile(r'"([^"\n]{6,80})"'),                        # "Project is not analyzed yet."
    re.compile(r"\b([a-z]+(?:\.[a-z][A-Za-z0-9]+){2,})\b"),  # sonar.sso.groupsHeader, org.apache.fop
    re.compile(r"\b([A-Z][a-z0-9]+(?:[A-Z][a-z0-9]+)+)\b"),  # FileReportGenerator
    re.compile(r"\b([A-Z][a-z]+(?:-[A-Z][a-z]+)+)\b"),       # Sonar-Version
]
_HOST_END = ("com", "org", "net", "io", "html", "htm")
_SECONDARY = re.compile(r"(/test/|/tests/|__tests__|/it/|/testFixtures/|\.md$|\.snap$|/docs?/)")


def anchors(text):
    """Literal anchors of a task text, in order of appearance, without URLs and host names."""
    out = []
    for rx in _ANCHORS:
        for a in rx.findall(text or ""):
            a = a.strip()
            if not a or a in out or "/" in a or "://" in a:
                continue
            if "." in a and a.rsplit(".", 1)[-1].lower() in _HOST_END and " " not in a:
                continue                                    # jira.sonarsource.com, index.html
            out.append(a)
    return out


def _git_grep(repo, needle, rev=None, line_numbers=False, timeout=60):
    cmd = ["git", "-C", repo, "grep", "-I", "-F", "--no-color"] + (["-n"] if line_numbers else ["-l"]) \
          + ["-e", needle] + ([rev] if rev else [])
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout)
    except (OSError, subprocess.TimeoutExpired):
        return []
    lines = [ln for ln in r.stdout.splitlines() if ln]
    if rev:                                                 # "<rev>:path[:line:text]"
        lines = [ln[len(rev) + 1:] if ln.startswith(rev + ":") else ln for ln in lines]
    return lines


def _first_line(repo, rev, path, needle):
    cmd = ["git", "-C", repo, "grep", "-n", "-I", "-F", "--no-color", "-m", "1", "-e", needle]
    cmd += [rev, "--", path] if rev else ["--", path]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30)
    except (OSError, subprocess.TimeoutExpired):
        return None
    for ln in r.stdout.splitlines():
        rest = ln[len(rev) + 1:] if rev and ln.startswith(rev + ":") else ln
        parts = rest.split(":", 2)
        if len(parts) == 3 and parts[1].isdigit():
            return {"line": int(parts[1]), "text": parts[2].strip()[:160]}
    return None


def compass(O, text, prm, repo=None, rev=None, k=5):
    """prm: the project's ranking parameters ({"module": ..., "file": ...}).
    -> {"confidence", "source", "anchor", "anchor_files", "candidates": [{"file", "why", ...}],
           "companions", "area"}"""
    found = None
    tried = []
    if repo:
        for a in anchors(text):
            hits = _git_grep(repo, a, rev)
            tried.append({"anchor": a, "files": len(hits)})
            if 0 < len(hits) <= MAX_ANCHOR_FILES and (found is None or len(hits) < len(found[1])):
                found = (a, hits)
    cands, source, conf = [], "none", "low"
    if found:
        a, hits = found
        hits = sorted(hits, key=lambda h: (bool(_SECONDARY.search(h)), len(h), h))
        source = "anchor"
        conf = "high" if len(hits) <= HIGH_ANCHOR_FILES else "medium"
        for h in hits[:k]:
            c = {"file": h, "why": f'contains "{a}"'}
            ln = _first_line(repo, rev, h, a) if len(cands) < 3 else None
            if ln:
                c.update(ln)
            cands.append(c)
    else:
        res = O.query(text).search(prm, k)
        files = res["files"]
        if files:
            source = "ontology"
            first_words = {e["term"] for e in files[0]["evidence"] if e["kind"] == "file"}
            conf = "medium" if len(first_words) >= 2 else "low"
            for f in files:
                words = ", ".join(dict.fromkeys(e["term"] for e in f["evidence"]))
                cands.append({"file": f["target"], "why": f"past tasks with words: {words}" if words
                              else "often changed", "score": f.get("score")})
    companions = []
    if cands and cands[0]["file"] in O.count["file"]:
        listed = {c["file"] for c in cands}
        companions = [c["target"] for c in O.companions([cands[0]["file"]], k) if c["target"] not in listed]
    area = None
    if cands:
        area = {"module": module_of(cands[0]["file"]), "dir": dir_of(cands[0]["file"])}
    return {"confidence": conf, "source": source, "anchor": found[0] if found else None,
            "anchor_files": len(found[1]) if found else None, "anchors_tried": tried,
            "candidates": cands, "companions": companions[:k], "area": area}


def render(res):
    """Short text for a person, or for a small model's context."""
    c = res["confidence"]
    if res["source"] == "anchor":
        head = f'compass: {c} - anchor "{res["anchor"]}" found in {res["anchor_files"]} file(s)'
    elif res["source"] == "ontology":
        head = f"compass: {c} - no rare literal anchor in the task; ranked by the task history"
    else:
        return "compass: low - nothing points anywhere; no anchor found and the ontology knows none of the words"
    lines = [head]
    for i, x in enumerate(res["candidates"], 1):
        lines.append(f"  {i}. {x['file']}")
        if "line" in x:
            lines.append(f"       line {x['line']}: {x['text']}")
        else:
            lines.append(f"       {x['why']}")
    if res["companions"]:
        lines.append("changes together with #1: " + ", ".join(f.rsplit("/", 1)[-1] for f in res["companions"]))
    if res["area"]:
        lines.append(f"area: {res['area']['dir']}")
    if c == "low":
        lines.append("direction uncertain: treat the list as an area to look in, not as the answer")
    return "\n".join(lines)
