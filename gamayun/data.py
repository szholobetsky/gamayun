"""Reading a task database, cleaning text, splitting tasks.

The database has the simargl/codeXtract layout: TASK (NAME, TITLE, DESCRIPTION)
and COMMITS (one row per (commit, file): SHA, CMT_DATE, PATH, TASK_NAME).
"""
import ast
import re
import sqlite3
from collections import defaultdict

TEST_SIZE = 200


def _text(v):
    if v is None:
        return ""
    return v.decode("utf-8", "replace") if isinstance(v, bytes) else str(v)


# ── ADF (Atlassian Document Format) ──────────────────────────────────────────

_ADF_TEXT = re.compile(r"""'text':\s*(?:'((?:[^'\\]|\\.)*)'|"((?:[^"\\]|\\.)*)")""")


def plain_description(v):
    """Jira stores rich text as an ADF tree; some exports keep it as the Python
    repr of a dict ({'type': 'doc', 'content': [...]}). Node names
    (mediaSingle, hardBreak, bulletList) and attrs would become fake terms;
    only the 'text' leaves are the description. Depth-first walk with a stack
    (no recursion limit); ast.literal_eval never executes code."""
    s = _text(v)
    if not s.lstrip().startswith("{'type': 'doc'"):
        return s
    try:
        node = ast.literal_eval(s)
    except (ValueError, SyntaxError, MemoryError, RecursionError):
        return " ".join(a or b for a, b in _ADF_TEXT.findall(s))
    out, stack = [], [node]
    while stack:
        n = stack.pop()
        if isinstance(n, dict):
            if isinstance(n.get("text"), str):
                out.append(n["text"])
            stack.extend(reversed(n.get("content") or []))
        elif isinstance(n, list):
            stack.extend(reversed(n))
    return " ".join(out).replace("\xa0", " ")


# ── database ─────────────────────────────────────────────────────────────────

def tables(con):
    """(task table, commit table), quoted. Singular TASK / COMMIT is canonical;
    older simargl ingest databases have TASKS / COMMITS and the codeXtract
    datasets mix them (TASK + COMMITS), so the file decides. COMMIT is an SQL
    keyword, hence the quotes. Same rule as simargl/schema.py."""
    have = {r[0].upper(): r[0] for r in
            con.execute("SELECT name FROM sqlite_master WHERE type IN ('table', 'view')")}
    def pick(*names):
        for n in names:
            if n in have:
                return f'"{have[n]}"'
        raise ValueError(f"no {' / '.join(names)} table in the database")
    return pick("TASK", "TASKS"), pick("COMMIT", "COMMITS")


def load(db_path):
    """-> tasks [(id, name, text)], task_files {name: set(paths)}, last commit sha.
    Commits without TASK_NAME are skipped: they could belong to a held-out task."""
    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    task_t, commit_t = tables(con)
    tasks = [(i, n, f"{_text(t)}\n{plain_description(d)}")
             for i, n, t, d in con.execute(f"SELECT ID, NAME, TITLE, DESCRIPTION FROM {task_t}")]
    files = defaultdict(set)
    for name, path in con.execute(
            f"SELECT TASK_NAME, PATH FROM {commit_t} WHERE TASK_NAME IS NOT NULL AND TASK_NAME <> ''"):
        p = _text(path).replace("\\", "/").strip()
        if p:
            files[name].add(p)
    row = con.execute(f"SELECT SHA FROM {commit_t} ORDER BY CMT_DATE DESC LIMIT 1").fetchone()
    con.close()
    return tasks, files, (row[0] if row else "")


def modn_split(tasks, test_size=TEST_SIZE):
    """simrgl exp3 'modn' split: sort by ID, every k-th task is held out."""
    tasks = sorted(tasks, key=lambda t: t[0])
    step = max(1, len(tasks) // test_size)
    held = set(list(range(0, len(tasks), step))[:test_size])
    return ([t for i, t in enumerate(tasks) if i not in held],
            [t for i, t in enumerate(tasks) if i in held])


def module_of(path):
    """Root folder (simrgl exp3 extract_module_path)."""
    parts = path.split("/")
    return parts[0] if len(parts) > 1 else "root"


def dir_of(path):
    return path.rsplit("/", 1)[0] if "/" in path else "root"


# ── tokens ───────────────────────────────────────────────────────────────────

_STOP = set("""
a about above after again against all also am an and any are as at be because been before
being below between both but by can cannot could did do does doing down during each few for
from further had has have having he her here hers him his how i if in into is it its itself
just me more most my no nor not now of off on once only or other our ours out over own same
she should so some such than that the their them then there these they this those through to
too under until up very was we were what when where which while who whom why will with would
you your yours should shall may might must get got set use used using new now see also one two
like want need make made way well still even much many able per via etc http https www com org
html htm jira atlassian browse issue issues ticket please thanks thank hi hello currently
""".split())

_WORD = re.compile(r"[A-Za-z][A-Za-z0-9_]{2,}")
_UWORD = re.compile(r"[^\W\d_]\w{2,}")          # any script: folder ontologies (Ukrainian docs too)
_CAMEL = re.compile(r"[A-Z]+(?=[A-Z][a-z])|[A-Z]?[a-z]+|[A-Z]+|\d+")


def split_ident(word):
    """QualityGateDao -> [quality, gate, dao]; snake_case too."""
    out = []
    for part in word.split("_"):
        out += [w.lower() for w in _CAMEL.findall(part)]
    return [w for w in out if len(w) >= 3]


def terms_of(text, unicode=False, stop=True):
    """Set of terms: lowercase words without stop words, plus the parts of
    camelCase / snake_case identifiers quoted in the text. unicode=True keeps
    words of any script (task databases stay Latin-only, as evaluated)."""
    out = set()
    for w in (_UWORD if unicode else _WORD).findall(text or ""):
        low = w.lower()
        if (not stop or low not in _STOP) and not low.isdigit():
            out.add(low)
        if any(c.isupper() for c in w[1:]) or "_" in w:
            out.update(p for p in split_ident(w) if not stop or p not in _STOP)
    return out


def file_name_terms(path):
    base = path.rsplit("/", 1)[-1].split(".", 1)[0]
    return {t for t in split_ident(base) if t not in _STOP}
