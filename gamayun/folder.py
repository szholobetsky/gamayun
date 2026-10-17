"""Ontology from a folder — documents, code or both — without a task tracker
and without an LLM (concepts/GAMAYUN.md §16).

The task database gave gamayun two views of one event (task text x changed
files). A folder has one view, so the 2x2 tables are counted over UNITS:
a paragraph of a document, or the body of one definition in code. Every unit
sits in a chain of targets

    module  ⊃  dir  ⊃  file  ⊃  symbol (class / function / method / document section)

and the same G² test as for tasks says which terms and identifiers are
characteristic of which target. Identifiers (final_period, BudgetService)
are first-class: `ident:` entities with their definition sites and uses.

Predicates (each is a formula + threshold, the numbers go to [src]):
  file/dir part_of ..., sym:X defined_in file:F, sym member_of sym
  term|ident characterizes module|dir|file|sym     G² >= 10.83 over units
  ident defined_in sym|file                         a definition in code
  ident used_in sym|file                            a rare identifier (<= 20 units) used there
  ident has_part term                               camelCase / snake_case parts
  term anchor_of module                             HHI >= 0.5
  term related_to term                              G² co-occurrence in units, top 10 per term
  term narrower_than term                           subsumption P(B|A) >= 0.8
  term names file                                   part of the file name and characterizes it
  term is_a term, term same_as term                 patterns in documents (Hearst, abbreviations)
  term is function_word | domain_core               residual IDF over files + file names (no stop list)
  term is named_entity                              the word is part of file names
  term variant_of term                              word forms merged by recurring ending pairs
  module|file unit_count n, dataset units N         priors for search
"""
import math
import os
import re
import subprocess
from collections import Counter, defaultdict

import numpy as np
from scipy import sparse

from .builder import G2_P001, g2_vec
from .data import _STOP as STOP, dir_of, module_of, split_ident, terms_of

DOC_EXT = {".md", ".markdown", ".txt", ".rst", ".adoc", ".asciidoc", ".org", ".tex", ".html", ".htm"}
CODE_EXT = {".py", ".java", ".kt", ".kts", ".scala", ".groovy", ".gradle", ".js", ".jsx", ".ts", ".tsx",
            ".mjs", ".cjs", ".go", ".rs", ".c", ".h", ".cc", ".cpp", ".hpp", ".cs", ".rb", ".php",
            ".swift", ".sql", ".sh", ".ps1", ".lua", ".r", ".jl", ".dart", ".vue", ".svelte",
            ".properties", ".yaml", ".yml", ".toml", ".ini", ".cfg", ".xml"}
SKIP_DIRS = {".git", ".hg", ".svn", "node_modules", "__pycache__", ".venv", "venv", "env", "build", "dist",
             "target", "out", ".gradle", ".idea", ".vscode", ".pytest_cache", ".mypy_cache", ".tox",
             ".simargl", ".svitovyd", ".gamayun", ".1bcoder", ".vyrii", ".yasna", "site-packages"}
MAX_BYTES = 1_000_000

CODE_STOP = set("""
public private protected static final abstract synchronized native transient volatile void return import
package class interface enum extends implements throws throw new null true false this super self cls def
function const let var async await yield lambda pass none elif else for while break continue switch case
default try catch finally instanceof typeof string int long float double boolean bool char byte short
object list map set dict tuple array override virtual internal sealed readonly struct namespace using
func type interface println printf print assert test tests junit mockito assertthat isequalto when then
param params returns return value values get set args kwargs str len range from with not and
""".split())
UK_STOP = set("""
і й та або але що як це цей ця ці той та те ті для від до на в у з із зі за по при про під над між через
без його її їх їм нам вам ми ви він вона воно вони я ти не ні так також лише тільки вже ще був була було
були бути є має мають можна треба якщо коли де чи бо тому який яка яке які котрий свій своя своє свої
""".split())


# ── reading ──────────────────────────────────────────────────────────────────

def list_files(root):
    """git ls-files when the folder is a git work tree (honours .gitignore), else a walk."""
    try:
        out = subprocess.run(["git", "-C", root, "ls-files", "-z"], capture_output=True, check=True).stdout
        files = [p for p in out.decode("utf-8", "replace").split("\0") if p]
        if files:
            return sorted(p.replace("\\", "/") for p in files
                          if not any(part in SKIP_DIRS for part in p.split("/")[:-1]))
    except (OSError, subprocess.CalledProcessError):
        pass
    files = []
    for d, sub, names in os.walk(root):
        sub[:] = sorted(s for s in sub if s not in SKIP_DIRS and not s.startswith("."))
        for n in names:
            files.append(os.path.relpath(os.path.join(d, n), root).replace("\\", "/"))
    return sorted(files)


def read_text(path):
    try:
        if os.path.getsize(path) > MAX_BYTES:
            return None
        with open(path, "rb") as fh:
            raw = fh.read()
    except OSError:
        return None
    if b"\0" in raw[:4096]:
        return None
    text = raw.decode("utf-8", "replace")
    lines = text.splitlines()
    if lines and sum(map(len, lines)) / len(lines) > 400:          # minified / generated
        return None
    return text


# ── segmentation ─────────────────────────────────────────────────────────────

_KEYWORDS = {"if", "for", "while", "switch", "catch", "return", "new", "else", "synchronized", "super",
             "this", "elif", "with", "try", "throw", "assert", "await", "typeof", "sizeof", "when"}
_CLASSY = {"class", "interface", "enum", "record", "struct", "trait", "object", "type", "module",
           "table", "view", "impl", "namespace"}
_DEF = [
    re.compile(r"^(\s*)(?:async\s+)?(def|class)\s+([A-Za-z_]\w*)"),                                  # python
    re.compile(r"^(\s*)(?:export\s+)?(?:default\s+)?(?:(?:public|private|protected|internal|static|final|"
               r"abstract|sealed|open|data|async|override|virtual|partial|pub|unsafe|inline)\s+)*"
               r"(class|interface|enum|record|struct|trait|object|fun|fn|func|function|module|impl)\s+"
               r"(?:\([^)]*\)\s*)?([A-Za-z_$][\w$]*)"),
    re.compile(r"(?i)^(\s*)create\s+(?:or\s+replace\s+)?(table|view|procedure|function)\s+(?:if\s+not\s+exists\s+)?"
               r"[`\"\[]?([\w.]+)"),
    re.compile(r"^(\s*)(?:@\w+(?:\([^)]*\))?\s+)*(?:(?:public|private|protected|static|final|abstract|"
               r"synchronized|native|override|virtual|async|default|internal)\s+)+[\w<>\[\],.?\s]*?"
               r"\b()([A-Za-z_]\w*)\s*\([^;]*$"),                                                    # java/c# method
    re.compile(r"^(\s*)(?:export\s+)?(?:const|let|var)\s+()([A-Za-z_$][\w$]*)\s*(?::[^=]+)?=\s*"
               r"(?:async\s*)?(?:\([^)]*\)|[A-Za-z_$][\w$]*)\s*(?::\s*[^=]+)?=>"),                   # js arrow
    re.compile(r"^(\s+)(?:(?:public|private|protected|static|async|readonly|get|set)\s+)*()"
               r"([A-Za-z_$][\w$]*)\s*\([^)]*\)\s*(?::\s*[^{;]+)?\{\s*$"),                            # ts method
]
_HEADING_MD = re.compile(r"^(#{1,6})\s+(.+?)\s*#*\s*$")
_HEADING_ADOC = re.compile(r"^(={1,6})\s+(.+?)\s*$")
_TAG = re.compile(r"<[^>]+>")


def code_definitions(lines):
    """-> [(line_no, indent, kind, name)] — line-based, language-agnostic heuristics."""
    out = []
    for i, ln in enumerate(lines):
        if len(ln) > 300 or not ln.strip() or ln.lstrip().startswith(("//", "#", "*", "/*", "--")):
            continue
        for rx in _DEF:
            m = rx.match(ln)
            if m and m.group(3) and m.group(3) not in _KEYWORDS:
                kind = m.group(2).lower() if m.group(2) else "function"
                out.append((i, len(m.group(1).expandtabs(4)),
                            "class" if kind in _CLASSY else "function", m.group(3)))
                break
    return out


def segment_code(lines):
    """Each line belongs to its innermost definition; one unit per owner.
    -> symbols [(qualname, kind, line, parent_index)], units [(owner_index or -1, first_line, text)]"""
    defs = code_definitions(lines)
    syms, stack, owner = [], [], [-1] * len(lines)
    ends = []
    for k, (ln, ind, kind, name) in enumerate(defs):
        while stack and defs[stack[-1]][1] >= ind:
            stack.pop()
        parent = stack[-1] if stack else -1
        qual = (syms[parent][0] + "." if parent >= 0 else "") + name
        syms.append((qual, kind, ln + 1, parent))
        stack.append(k)
    # range of a definition: until the next definition at the same or lower indent
    for k, (ln, ind, _, _) in enumerate(defs):
        end = len(lines)
        for ln2, ind2, _, _ in defs[k + 1:]:
            if ind2 <= ind:
                end = ln2
                break
        ends.append(end)
    for k, (ln, _, _, _) in enumerate(defs):          # outer first, inner overwrite
        for i in range(ln, ends[k]):
            owner[i] = k
    groups = defaultdict(list)
    for i, o in enumerate(owner):
        groups[o].append(i)
    units = [(o, idx[0] + 1, "\n".join(lines[i] for i in idx)) for o, idx in sorted(groups.items())]
    return syms, units


def segment_doc(lines, ext):
    """Paragraphs; headings become section symbols nested by level."""
    syms, units, stack = [], [], []                    # stack of (level, sym index)
    para, start = [], 0

    def flush():
        if para and any(p.strip() for p in para):
            units.append((stack[-1][1] if stack else -1, start + 1, "\n".join(para)))

    for i, ln in enumerate(lines):
        h = None
        if ext in (".md", ".markdown", ".txt", ".org"):
            m = _HEADING_MD.match(ln)
            h = (len(m.group(1)), m.group(2)) if m else None
        elif ext in (".adoc", ".asciidoc"):
            m = _HEADING_ADOC.match(ln)
            h = (len(m.group(1)), m.group(2)) if m else None
        elif ext in (".html", ".htm"):
            m = re.match(r"\s*<h([1-6])[^>]*>(.*?)</h\1>", ln, re.I)
            h = (int(m.group(1)), _TAG.sub("", m.group(2))) if m else None
        if h:
            flush()
            para = []
            level, title = h
            title = " ".join(title.replace("`", "").split())[:80]
            while stack and stack[-1][0] >= level:
                stack.pop()
            parent = stack[-1][1] if stack else -1
            syms.append((title, "section", i + 1, parent))
            stack.append((level, len(syms) - 1))
            start = i + 1
            para = [ln]
            continue
        if not ln.strip():
            flush()
            para, start = [], i + 1
        else:
            if not para:
                start = i
            para.append(_TAG.sub(" ", ln) if ext in (".html", ".htm") else ln)
    flush()
    return syms, units


# ── terms ────────────────────────────────────────────────────────────────────

_IDENT = re.compile(r"\b[A-Za-z_$][\w$]*\b")
_UWORD = re.compile(r"[^\W\d_]\w{2,}")


def is_identifier(word):
    return "_" in word.strip("_") or any(c.isupper() for c in word[1:]) and any(c.islower() for c in word)


def unit_terms(text):
    """-> (Counter of terms, set of whole identifiers). No stop list here: which
    words carry no information is decided from the corpus (classify_terms)."""
    c = Counter()
    for w in _UWORD.findall(text):
        low = w.lower()
        if not low.isdigit():
            c[low] += 1
    idents = set()
    for w in _IDENT.findall(text):
        if len(w) >= 4 and is_identifier(w):
            idents.add(w.lower())
            for part in split_ident(w):
                c[part] += 1
    return c, idents


# ── word forms: statistical conflation, no dictionary ────────────────────────

def word_variants(df, word_files, protected, min_stem=4, stem_share=0.6, max_suffix=4,
                  min_pair_stems=5, min_cos=0.3):
    """users -> user, онтології -> онтологія, without a stemmer for any language.

    1. Every plain word is cut as stem + suffix (stem >= min_stem letters and
       >= stem_share of the word, suffix <= max_suffix, the empty suffix too).
       A stem with >= 2 corpus words is a group: user|{-, s}, онтолог|{ія, ії, ію}.
    2. Two endings are forms of one word only if the PAIR recurs: {-, s} and
       {ія, ії} are shared by hundreds of stems, {ains, ent} (contains / content)
       or {-, ial} (part / partial) by a few. A pair is valid when at least
       min_pair_stems different stems have both (Goldsmith's signatures, cut to pairs).
    3. Frequent forms must also be used in similar places: cosine of their file
       distributions >= min_cos (both df >= 5).
    The most frequent form names the group.
    -> {variant: canonical}, {variant: (ending pair, cos)}"""
    words = [w for w in df if w.isalpha() and w not in protected and len(w) >= min_stem]
    groups = defaultdict(dict)                                  # stem -> {suffix: word}
    for w in words:
        lo = max(min_stem, math.ceil(stem_share * len(w)), len(w) - max_suffix)
        for i in range(lo, len(w) + 1):
            groups[w[:i]][w[i:]] = w
    groups = {st: sf for st, sf in groups.items() if len(sf) >= 2}
    pair_stems = Counter()
    for sf in groups.values():
        ends = sorted(sf)
        for i in range(len(ends)):
            for j in range(i + 1, len(ends)):
                pair_stems[(ends[i], ends[j])] += 1
    # an empty ending (user / users) needs min_pair_stems stems, two endings (heads / header) twice that
    valid = {pr for pr, n in pair_stems.items() if n >= min_pair_stems * (1 if "" in pr else 2)}

    def cos(a, b):
        fa, fb = word_files.get(a, {}), word_files.get(b, {})
        num = sum(v * fb.get(k, 0) for k, v in fa.items())
        den = (sum(v * v for v in fa.values()) * sum(v * v for v in fb.values())) ** 0.5
        return num / den if den else 0.0

    parent, why = {}, {}

    def find(w):
        while parent.get(w, w) != w:
            w = parent[w]
        return w

    for st in sorted(groups, key=lambda x: (-len(x), x)):     # longest stems first
        sf = groups[st]
        head_end = max(sf, key=lambda e: (df[sf[e]], e))
        head = sf[head_end]
        for e, w in sorted(sf.items()):
            if w == head or find(w) == find(head) or tuple(sorted((e, head_end))) not in valid:
                continue
            c = cos(w, head) if df[w] >= 5 and df[head] >= 5 else None
            if c is None or c >= min_cos:
                parent[find(w)] = find(head)
                why[w] = (f"{e or '-'}/{head_end or '-'}", "-" if c is None else round(c, 2))
    roots = defaultdict(list)
    for w in set(parent) | set(parent.values()):
        roots[find(w)].append(w)
    final = {}
    for members in roots.values():
        name = max(members, key=lambda w: (df[w], w))
        for w in members:
            if w != name:
                final[w] = name
    return final, why


# ── which words carry no information ─────────────────────────────────────────

def classify_terms(doc_df, cf, doc_len, in_filenames, n_docs, ridf_max=0.3):
    """function_word / domain_core from counts alone (concepts/GAMAYUN.md §16.3).
    Counted over FILES: a paragraph is too short for a word to bunch up in it.

    RIDF (Church & Gale 1995), length-aware: observed document frequency against
    the one a word would have if its occurrences fell on files by chance, in
    proportion to their length. Function words, code keywords and boilerplate
    (licence headers) fall like chance (RIDF ~ 0); words of a topic bunch up.
    Word length plays no part: two-letter abbreviations are often the most
    important words of a domain.

    Only frequent words are judged (in >= mindf files and cf >= n_docs / 2): a
    word met 5 times in 5 files cannot bunch up, its RIDF ~ 0 means nothing.

      a name        : in file names of >= 5 % of the files it occurs in — 'user' of
                      UserService; not 'public' of PublicApi (2 file names, 9000 files)
      function_word : RIDF < ridf_max and not a name
      domain_core   : a name spread like a function word (RIDF < ridf_max) or in more than
                      30 % of files — the corpus is about it, it names things, but it does
                      not tell one place from another

    Known blind spot: language islands. English in code comments or in a mixed
    folder bunches up because its language does, so 'the' gets a high RIDF there.
    -> {word: (kind, numbers)}"""
    L = np.asarray(doc_len, dtype=float)
    L = L / L.sum()
    mindf = max(5, int(0.02 * n_docs))
    out = {}
    for w, d in doc_df.items():
        if d < mindf or cf[w] < n_docs / 2:
            continue
        expected = float((1 - np.exp(-cf[w] * L)).sum())
        ridf = float(np.log2(expected / d))
        nums = f"ridf={ridf:.2f};files={d};cf={cf[w]};in_filenames={in_filenames.get(w, 0)}"
        if in_filenames.get(w, 0) >= 0.05 * d:
            if ridf < ridf_max or d > 0.3 * n_docs:
                out[w] = ("domain_core", nums)
        elif ridf < ridf_max:
            out[w] = ("function_word", nums)
    return out


# ── patterns in documents ────────────────────────────────────────────────────

_JOIN = r"(?:and|or|і|й|та|або)"
_NP = rf"[^\W\d_][\w-]{{2,}}(?: (?!{_JOIN}\b)[^\W\d_][\w-]{{2,}})?"     # one or two words, no joiner
_W = r"[^\W\d_][\w-]{2,}"                                                # list items: one word each
_PATTERNS = [
    ("such_as", re.compile(rf"\b({_NP}),? such as ({_W}(?:, {_W})*(?:,? (?:and|or) {_W})?)", re.I), "x_y"),
    ("and_other", re.compile(rf"\b({_W}) and other ({_NP})", re.I), "y_x"),
    ("is_a", re.compile(rf"\b({_NP}) is an? ({_NP})\b", re.I), "y_x"),
    ("uk_ce", re.compile(rf"\b({_NP})\s+[—–-]\s+це\s+({_NP})", re.I), "y_x"),
    ("uk_taki_yak", re.compile(rf"\b({_NP}),? (?:такі як|такий як|така як|наприклад)\s+({_W}(?:, {_W})*"
                               rf"(?:,? (?:і|й|та|або) {_W})?)", re.I), "x_y"),
]
_ABBR = re.compile(r"\b((?:[^\W\d_][\w-]+\s+){1,5}[^\W\d_][\w-]+)\s+\(([A-ZА-ЯІЇЄҐ]{2,8})\)")
_BAD_NP = {"this", "that", "it", "there", "which", "what", "here", "one", "each", "all", "це", "він", "вона",
           "воно", "вони", "там", "тут", "який", "яка", "яке"}


def _np(s):
    s = " ".join(s.lower().split())
    return None if s.split()[0] in _BAD_NP or s in _BAD_NP else s


def doc_patterns(text):
    """-> [(subject, predicate, object, pattern)] from one paragraph."""
    out = []
    flat = " ".join(text.split())
    for name, rx, order in _PATTERNS:
        for m in rx.finditer(flat):
            x, ys = m.group(1), m.group(2)
            if order == "y_x":
                x, ys = ys, x
            parts = re.split(r",\s*|\s+(?:and|or|і|й|та|або)\s+", ys)
            for y in parts:
                a, b = _np(y), _np(x)
                if a and b and a != b:
                    out.append((a, "is_a", b, name))
    for m in _ABBR.finditer(flat):
        words, abbr = m.group(1).split(), m.group(2)
        # walk back from "(TCO)": capitalised words give letters, lowercase joiners
        # inside the expansion are carried along (Total Cost of Ownership)
        letters, k = [], len(words)
        while k > 0 and len(letters) < len(abbr):
            k -= 1
            if words[k][0].isupper() or not letters:
                letters.insert(0, words[k][0].upper())
            elif k == 0 or not words[k - 1][0].isupper():
                break
        if "".join(letters) == abbr and words[k][0].isupper():
            out.append((abbr.lower(), "same_as", " ".join(words[k:]).lower(), "abbreviation"))
    return out


# ── build ────────────────────────────────────────────────────────────────────

def build_folder(root, min_df=2, max_df=0.3, related_top=10, rare_ident=20, log=print):
    root = os.path.abspath(root)
    files = list_files(root)
    U_count, U_file, U_syms, U_code = [], [], [], []     # per unit
    file_syms = {}                                       # file -> [(qual, kind, line, parent)]
    def_sites = defaultdict(list)                        # ident -> [(file, sym index or -1, line)]
    ident_surface = {}
    idents = set()
    patterns = []
    n_doc = n_code = 0
    for f in files:
        ext = os.path.splitext(f)[1].lower()
        if ext not in DOC_EXT and ext not in CODE_EXT:
            continue
        text = read_text(os.path.join(root, f))
        if not text:
            continue
        lines = text.splitlines()
        code = ext in CODE_EXT
        syms, units = segment_code(lines) if code else segment_doc(lines, ext)
        n_code += code
        n_doc += not code
        file_syms[f] = syms
        for k, (qual, kind, line, parent) in enumerate(syms):
            if code:
                name = qual.rsplit(".", 1)[-1]
                def_sites[name.lower()].append((f, k, line))
                ident_surface.setdefault(name.lower(), name)
        for owner, line, utext in units:
            counts, ids = unit_terms(utext)
            for w in _IDENT.findall(utext):
                if w.lower() in ids:
                    ident_surface.setdefault(w.lower(), w)
            if not counts and not ids:
                continue
            idents |= ids
            for i in ids:
                counts[i] += 1
            chain, o = [], owner
            while o >= 0:
                chain.append(o)
                o = syms[o][3]
            U_count.append(counts)
            U_file.append(f)
            U_syms.append([(f, k) for k in chain])
            U_code.append(code)
            if not code:
                patterns += [(s, p, o_, pat, f, line) for s, p, o_, pat in doc_patterns(utext)]
    N = len(U_count)
    if N < 10:
        raise ValueError(f"too little text in {root}: {N} units from {n_doc + n_code} files")
    log(f"{n_doc} documents, {n_code} code files, {N} units")
    idents |= {n for n in def_sites if len(n) >= 4 and n in ident_surface and is_identifier(ident_surface[n])}

    # word forms
    df0 = Counter(t for c in U_count for t in c)
    word_files = defaultdict(Counter)
    for c, f in zip(U_count, U_file):
        for t in c:
            if df0[t] >= 5:
                word_files[t][f] += 1
    variant, why_variant = word_variants(df0, word_files, protected=idents)
    if variant:
        for k, c in enumerate(U_count):
            if any(t in variant for t in c):
                merged = Counter()
                for t, n in c.items():
                    merged[variant.get(t, t)] += n
                U_count[k] = merged
    log(f"word forms: {len(variant)} merged into {len(set(variant.values()))} words")

    # informative or not
    df = Counter(t for c in U_count for t in c)
    cf = Counter()
    for c in U_count:
        cf.update(c)
    in_filenames = Counter()
    for f in set(U_file):
        for t in split_ident(f.rsplit("/", 1)[-1].split(".", 1)[0]):
            in_filenames[variant.get(t, t)] += 1
    if N >= 500:
        file_count = defaultdict(Counter)
        for c, f in zip(U_count, U_file):
            file_count[f].update(c)
        doc_df = Counter(t for c in file_count.values() for t in c)
        kinds = classify_terms(doc_df, cf, [sum(c.values()) for c in file_count.values()], in_filenames,
                               len(file_count))
    else:                                                # too little text for statistics: built-in lists
        kinds = {w: ("function_word", "built-in list (fewer than 500 units)")
                 for w in df if w in STOP | UK_STOP | CODE_STOP and not in_filenames.get(w)}
    function = {w for w, (k, _) in kinds.items() if k == "function_word"}
    core = {w for w, (k, _) in kinds.items() if k == "domain_core"}
    log(f"function words {len(function)}  domain core {len(core)}")
    U_terms = [{t for t in c if t not in function} for c in U_count]
    terms = sorted(t for t, c in df.items()
                   if c >= min_df and t not in function and (c <= max_df * N or t in core or in_filenames.get(t)))
    fl = sorted(set(U_file))
    dirs = sorted({dir_of(f) for f in fl})
    mods = sorted({module_of(f) for f in fl})
    sym_name = {}
    for f, syms in file_syms.items():
        for k, (qual, kind, line, parent) in enumerate(syms):
            sym_name[(f, k)] = f"{f}#{qual}"
    containers = sorted({s for chain in U_syms for s in chain
                         if file_syms[s[0]][s[1]][1] in ("class", "section")})
    ti = {t: i for i, t in enumerate(terms)}
    fi, di, mi, ci = ({x: i for i, x in enumerate(v)} for v in (fl, dirs, mods, containers))
    log(f"terms {len(terms)} ({sum(t in idents for t in terms)} identifiers)  files {len(fl)}  "
        f"dirs {len(dirs)}  modules {len(mods)}  classes/sections {len(containers)}")

    def incidence(rows, ncols):
        r = [i for i, cols in enumerate(rows) for _ in cols]
        c = [j for cols in rows for j in cols]
        return sparse.csr_matrix((np.ones(len(r), dtype=np.float32), (r, c)), shape=(len(rows), ncols))

    T = incidence([{ti[t] for t in ts if t in ti} for ts in U_terms], len(terms))
    X = {"file": (incidence([{fi[f]} for f in U_file], len(fl)), fl, 2),
         "dir": (incidence([{di[dir_of(f)]} for f in U_file], len(dirs)), dirs, 3),
         "module": (incidence([{mi[module_of(f)]} for f in U_file], len(mods)), mods, 5),
         "sym": (incidence([{ci[s] for s in ch if s in ci} for ch in U_syms], len(containers)),
                 [sym_name[c] for c in containers], 2)}
    row_t = np.asarray(T.sum(0)).ravel()
    lines, stats = [], Counter()

    def ent(t):
        return f"{'ident' if t in idents else 'term'}:{t}"

    def emit(s, p, o, src):
        lines.append(f"{s} :: {p} :: {o}  [src: {src}]")
        stats[p] += 1

    # structure and priors
    emit("dataset", "units", str(N), f"{n_doc} documents, {n_code} code files: {root}")
    col_m = np.asarray(X["module"][0].sum(0)).ravel()
    for m in mods:
        emit(f"module:{m}", "unit_count", str(int(col_m[mi[m]])), "units in it")
    for d in dirs:
        emit(f"dir:{d}", "part_of", f"module:{module_of(d + '/x')}", "path")
    col_f = np.asarray(X["file"][0].sum(0)).ravel()
    for f in fl:
        emit(f"file:{f}", "part_of", f"dir:{dir_of(f)}", "path")
        emit(f"file:{f}", "unit_count", str(int(col_f[fi[f]])), "units in it")
    # what the corpus says about its own words
    for w, (k, nums) in sorted(kinds.items()):
        emit(f"term:{w}", "is", k, nums)
    for w in sorted(variant):
        sfx, c = why_variant.get(w, ("?", "?"))
        emit(f"term:{w}", "variant_of", f"term:{variant[w]}", f"endings={sfx};cos={c};df={df0[w]}")
    for t, n in sorted(in_filenames.items()):
        if t in ti:
            emit(ent(t), "is", "named_entity", f"in_filenames={n};df={df[t]}")
    for f, syms in sorted(file_syms.items()):
        if f not in fi:
            continue
        for k, (qual, kind, line, parent) in enumerate(syms):
            emit(f"sym:{sym_name[(f, k)]}", "defined_in", f"file:{f}", f"kind={kind};line={line}")
            if parent >= 0:
                emit(f"sym:{sym_name[(f, k)]}", "member_of", f"sym:{sym_name[(f, parent)]}", "nesting")

    # characterizes
    TM, char_file = None, set()
    for kind, (Xk, names, min_a) in X.items():
        if not len(names):
            continue
        col = np.asarray(Xk.sum(0)).ravel()
        C = (T.T @ Xk).tocoo()
        keep = C.data >= min_a
        r, c, a = C.row[keep], C.col[keep], C.data[keep]
        g, pos = g2_vec(a, row_t[r], col[c], N)
        ok = pos & (g >= G2_P001)
        for i, j, aa, gg in zip(r[ok], c[ok], a[ok], g[ok]):
            emit(ent(terms[i]), "characterizes", f"{kind}:{names[j]}",
                 f"n={int(aa)};df={int(row_t[i])};g2={gg:.1f};lift={aa * N / (row_t[i] * col[j]):.2f}")
            if kind == "file":
                char_file.add((terms[i], names[j]))
        if kind == "module":
            TM = C
    log("characterizes done")

    # identifiers: definitions, rare uses, parts
    for t in sorted(idents):
        surface = ident_surface.get(t, t)
        for f, k, line in def_sites.get(t, []):
            if f in fi:
                emit(f"ident:{t}", "defined_in", f"sym:{sym_name[(f, k)]}", f"as={surface};line={line}")
        if t in ti:
            for part in sorted(set(split_ident(surface)) - {t}):
                if part in ti:
                    emit(f"ident:{t}", "has_part", ent(part), f"as={surface}")
    rare = {ti[t] for t in idents if t in ti and row_t[ti[t]] <= rare_ident}
    uses = Counter()
    for u, ts in enumerate(U_terms):
        target = sym_name[U_syms[u][0]] if U_syms[u] else None
        for t in ts:
            i = ti.get(t)
            if i in rare:
                uses[(t, "sym", target) if target else (t, "file", U_file[u])] += 1
    for (t, kind, target), n in sorted(uses.items()):
        if (kind == "sym" and not any(target == sym_name[(f, k)] for f, k, _ in def_sites.get(t, []))) \
                or kind == "file":
            emit(f"ident:{t}", "used_in", f"{kind}:{target}", f"n={n};df={int(row_t[ti[t]])}")
    log("identifiers done")

    # anchor_of: HHI over modules
    if TM is not None and len(mods) > 1:
        tm = sparse.csr_matrix((TM.data, (TM.row, TM.col)), shape=TM.shape)
        for i in range(len(terms)):
            rowv = tm.getrow(i)
            tot = rowv.data.sum()
            if row_t[i] < 10 or tot == 0:
                continue
            shares = rowv.data / tot
            hhi = float((shares ** 2).sum())
            if hhi >= 0.5:
                emit(ent(terms[i]), "anchor_of", f"module:{mods[rowv.indices[shares.argmax()]]}",
                     f"hhi={hhi:.2f};share={shares.max():.2f};df={int(row_t[i])}")

    # names: part of the file name and characterizes the file
    for f in fl:
        base = f.rsplit("/", 1)[-1].split(".", 1)[0]
        for t in sorted(set(split_ident(base))):
            if (t, f) in char_file:
                emit(ent(t), "names", f"file:{f}", "n=2")

    # related_to: G² co-occurrence within units, top partners per term
    cols = np.where(row_t >= max(3, min_df))[0]
    Tc = T[:, cols].tocsc()
    done = set()
    for start in range(0, len(cols), 2000):
        blk = cols[start:start + 2000]
        C = (T[:, blk].T @ Tc).tocsr()
        for bi, i in enumerate(blk):
            rowv = C.getrow(bi)
            jj, a = cols[rowv.indices], rowv.data
            keep = (jj != i) & (a >= 3)
            jj, a = jj[keep], a[keep]
            if not len(jj):
                continue
            g, pos = g2_vec(a, np.full(len(a), row_t[i]), row_t[jj], N)
            ok = np.where(pos & (g >= G2_P001))[0]
            for k in ok[np.argsort(-g[ok], kind="stable")][:related_top]:
                pair = (min(i, jj[k]), max(i, jj[k]))
                if pair not in done:
                    done.add(pair)
                    j = jj[k]
                    emit(ent(terms[i]), "related_to", ent(terms[j]),
                         f"n={int(a[k])};g2={g[k]:.1f};lift={a[k] * N / (row_t[i] * row_t[j]):.2f}")
    log("related_to done")

    # narrower_than: subsumption
    big = np.where(row_t >= 10)[0]
    if len(big):
        Tb = T[:, big]
        C = (Tb.T @ Tb).tocoo()
        for x, y, aa in zip(C.row, C.col, C.data):
            if x == y or aa < 5:
                continue
            b_, a_ = big[x], big[y]
            if row_t[a_] > row_t[b_] and aa / row_t[b_] >= 0.8:
                emit(ent(terms[b_]), "narrower_than", ent(terms[a_]),
                     f"p_a_given_b={aa / row_t[b_]:.2f};df_b={int(row_t[b_])};df_a={int(row_t[a_])}")

    # patterns: no stop word anywhere, the head (last word) of both sides is a corpus word (df >= 2)
    stop = function | (STOP | UK_STOP if N < 500 else set())
    def good(phrase):
        words = [variant.get(w, w) for w in phrase.split()]
        return all(w not in stop and len(w) >= 3 for w in words) and df.get(words[-1], 0) >= 2
    patterns = [x for x in patterns if x[1] == "same_as" or (good(x[0]) and good(x[2]))]
    seen = Counter((s, p, o) for s, p, o, *_ in patterns)
    first = {}
    for s, p, o, pat, f, line in patterns:
        first.setdefault((s, p, o), (pat, f, line))
    for (s, p, o), n in sorted(seen.items()):
        pat, f, line = first[(s, p, o)]
        emit(f"term:{s}", p, f"term:{o}", f"n={n};pattern={pat};at={f}:{line}")
    log("narrower_than, patterns done")

    return lines, {"units": N, "documents": n_doc, "code_files": n_code, "terms": len(terms),
                   "function_words": len(function), "domain_core": len(core), "word_forms_merged": len(variant),
                   "identifiers": sum(t in idents for t in terms), "files": len(fl), "dirs": len(dirs),
                   "modules": len(mods), "symbols": len(sym_name), "predicates": dict(stats)}
