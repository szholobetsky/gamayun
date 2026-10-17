![gamayun](https://raw.githubusercontent.com/szholobetsky/simrgl/main/images/logo/gamayun.png)

# gamayun

**Task-to-code search over an ontology built without an LLM.**

Given a task description, gamayun ranks the modules and files that are likely to change, and
explains every result with the triples that produced it. The ontology is built from a task
tracker plus git history (the simargl / codeXtract SQLite layout), or from a plain folder of
documents and code. Every triple is a significance test, and the numbers that made it pass
travel with it:

```
term:scanner :: characterizes :: module:sonar-scanner-engine  [src: n=205;df=388;g2=820.7;lift=11.01]
term:scanner :: not_in        :: module:sonar-server          [src: expected=46.7;observed=0;p0=2.4e-22]
file:server/sonar-web/package.json :: co_changes_with :: file:server/sonar-web/yarn.lock  [src: n=67;g2=658.9;lift=94.38]
```

Part of the SIMARGL family, next to **simargl** (embeddings: "what is similar in meaning") and
**svitovyd** (project map: "what is connected in the code"). gamayun answers a third question:
"what changes together with what in this project's history, and how sure are we".

---

## Install

```bash
pip install gamayun       # numpy, scipy, flask, waitress, mokosh; no GPU, no LLM
```

The task database comes from **[mokosh](https://github.com/szholobetsky/mokosh)**, installed with
gamayun: `mokosh init` and `mokosh ingest` in the repository folder read its commits and fetch
their tasks from Jira, GitHub, GitLab or YouTrack into `units.db`.

## Use

```bash
mokosh init && mokosh ingest                                      # the database: commits + tasks
gamayun index  --db sonar.db --repo ./sonarqube --project sonar   # ~40 s, no GPU (alias: build)
gamayun eval   --project sonar      # tune on dev, test once (a few minutes)
gamayun search "Scanner crashes when analysing a branch" --project sonar
gamayun show   term:scanner --project sonar
gamayun list
gamayun ui     --port 8095          # http://127.0.0.1:8095/
```

### Files instead of a task database

```bash
gamayun index  --files ./docs --project docs        # documents, code, or both
gamayun search "фінальний період бюджету" --project docs
gamayun show   ident:final_period --project docs
```

Without tasks the 2×2 tables are counted over units of text: a paragraph of a document, the body
of one class / function / method in code. Targets are module ⊃ dir ⊃ file ⊃ symbol (class or
document section), so search also ranks classes and sections. Identifiers (`final_period`,
`BudgetService`) are `ident:` entities with `defined_in`, `used_in`, `has_part` and
`characterizes`. Documents add Hearst patterns (`petrol is_a fuels`) and abbreviations
(`tco same_as total cost of ownership`). There is no built-in stop list: words spread over files
like chance (residual IDF ≈ 0) are `function_word`; words that also name files are `domain_core`;
word forms merge by recurring ending pairs (`users variant_of user`, `онтології variant_of онтологія`).
`eval` needs tasks, so these projects search with default parameters. Details:
`concepts/GAMAYUN.md` §16 in the simrgl repository.

A database project and a files project of the same codebase are best kept as two projects
(`sonar` and `sonar-code`): mixing the code ontology into task ranking did not help (simrgl
`exp8.1`), but the code ontology answers its own questions — where an identifier is defined and
used, and which identifiers belong together.

### Projects and web UI

A project lives next to what it describes. Run `gamayun index` in the repository folder and the
ontology goes to `<folder>/.gamayun/<project>/` (or `--root <folder>`): `triples.txt`, `params.json`
(tuned ranking parameters; defaults until `eval`), `stats.json`, `source.json`, `eval/`.
`~/.gamayun/projects.json` only remembers where each project is, so `gamayun ui`, `search`,
`compass` started from any folder find it by name. To keep several projects in one place — say,
all the ontologies of a study next to its documents — build each with the same `--root`.

```
cd C:\Projects\Data\sonarqube
gamayun index --db ..\sonar.db --repo . --project sonar     # -> sonarqube\.gamayun\sonar\
cd ~
gamayun ui                                                  # sees sonar, flink, ... and switches between them
```

The web UI works on one project at a time: choose it at the top, and every page asks about that
project's ontology only; switching clears what the previous one left on screen. Projects
registered on the machine are listed, and so are those under the folder the UI was started in.
**Search** shows the **compass** (where to start, and how sure: a rare literal anchor of the task
found in the project's repository, else the ranking) and the ranked modules, files and symbols;
open a result to see the triples behind its score. **Companions** takes a list of files, or an
answer that names them, and shows the files that changed together with them in past tasks.
**Health** draws the evolution square of the task history (below) for the whole code base, one
unit or one file, by month, quarter or year, ranks the units by stagnation and lists the dated
snapshots of earlier builds. **Map** draws the modules and the coupling between them, one layer
at a time: the top modules first, and a click on one opens the map of its own sub-folders
(below). **Entity** lists every triple of a term, identifier, module, dir, file or symbol, with a guide to
what the ontology holds. **Projects** builds projects (from a database or a folder) and evaluates
the database ones. A link like `/?project=sonar&q=...` opens a search directly. The theme picker
in the header has gamayun's own palette (light or dark with the system) and the eight themes of
vyrii and alkonost (`&theme=ocean` in a link); the language picker next to it has the same six
languages as vyrii — English, Ukrainian, German, French, Spanish, Portuguese (`&lang=uk`). Only the
interface is translated: terms, paths, relations and task titles are data and stay as they are.

---

## Health: the evolution square

`gamayun health` reads the task history of a database project and shows how the code base
changes: every task of 2–30 files is a set of file pairs that changed together. A pair is
**novel** if those files had not changed together in any earlier task (judged on the history up to
that task's date only), and **structural** if both lie in the same unit — the first folders of the
path up to a source-layout folder (`server/sonar-web`, `sonar-core`).

|  | across units | inside a unit |
|---|---|---|
| **novel** | DISRUPTION — new coupling, the architecture erodes | EVOLUTION — new work where it belongs |
| **known** | STAGNATION — the same cross-unit pairs again, shotgun surgery | MAINTENANCE — routine work |

```bash
gamayun health --project sonar --by year            # the whole code base, year by year
gamayun health --project sonar --units --since 2020 # every unit ranked by stagnation
gamayun health --project sonar --unit server/sonar-web --by quarter   # one unit: cohesion vs coupling
gamayun health --project sonar --file sonar-core/src/main/resources/org/sonar/l10n/core.properties
```

For one unit, structural means both files inside it, so its square is its cohesion against its
coupling; the units with the most stagnation keep dragging the same outside files along —
refactoring candidates. Every `gamayun index` of a database keeps a dated snapshot of the whole
square in `health/<date>.json`, so builds can be compared month by month. The web UI has the same
on its **Health** page (`/?project=sonar&tab=health`). The metrics — Novelty@K, Structurality@K,
SES, HES — come from the SIMARGL concept (`concepts/SIMARGL_concept.md` in the simrgl repository).

## Map: modules and their coupling

The **Map** page of the web UI (`/?project=sonar&tab=map[&prefix=server&since=2022]`) is read in
layers. The first layer shows the top modules; clicking a module with sub-folders (drawn with a
ring) opens the map of its children only, and the path above the map leads back
(`sonar › server › sonar-web`). Source-layout folders (`src/main/java`) are passed through, and a
chain of single folders is skipped. A module is sized by the tasks that touched it and coloured by
the leading zone of its own square; a link joins two modules changed together by at least
*N* tasks, its width is the number of those tasks, and each module keeps only its strongest
links. With a start date, links that had never appeared before it are drawn as **new** — the
coupling that is growing now. Hover a link to see how strong it is both ways; click it for what it is made of:
P(B|A) and P(A|B), the shared tasks per year, the share of new file pairs (disruption) against the
same pairs again (stagnation), the title words that set the shared tasks apart (G²), the file pairs
and files that carry it and the latest shared tasks (`&edge=A|B` links straight to it). Hover a module to see its neighbours, open its health square from
the side panel; wheel to zoom, drag to pan or move a module. A table under the map lists every
module and link.

### Sources of the map: ontology, code, history

The map reads the **ontology** by default — the project's `triples.txt` only, a few tenths of a
second per layer and no database (the task database of a large project is gigabytes, its ontology
tens of megabytes). For a project built from tasks a link is the significant co-change pairs of
files across two modules (`co_changes_with`; the largest *n* among them is a lower bound on the
shared tasks), and a module is coloured by **cohesion** — the share of its significant pairs that
stay inside it. For a project built from **code** (`--files`) a link is the identifiers defined on
one side and used on the other, both ways (`defined_in` / `used_in`: who uses whom); cohesion is
then the share of a module's identifier uses that stay inside it.

**Compare with** a code project of the same repository overlays the two on one layer:

| link | meaning |
|---|---|
| both | they change together and one uses the other — coupling the code explains |
| hidden | they change together with no identifier between them — logical coupling |
| stable | one uses the other, but they do not change together — a stable dependency |
| gone | they changed together, but one side is no longer in the code (history spans years, the code is one snapshot) |

The ontology has no dates; **task history** as the source reads the database instead and adds the
time window, new links, the zones of the squares, and per link P(B|A), years and task titles.

## Predicates

| Predicate | Rule |
|---|---|
| `term characterizes module/dir/file` | G² (Dunning) of task-has-term × task-changes-target, p < 0.001, positive, minimum support |
| `term anchor_of module` | Herfindahl index of the term's spread over modules ≥ 0.5 |
| `term names file` | term is part of the camelCase file name and they co-occur in ≥ 2 tasks |
| `term not_in module` | zero co-occurrences where chance predicts some: (1−r)^df < 0.001 |
| `file co_changes_with file` | G² over tasks changing ≤ 30 files |
| `term narrower_than term` | subsumption P(A\|B) ≥ 0.8 (mostly catches stack traces — not used in ranking) |
| `module depends_on module` | Java imports at the last commit of the database (`git cat-file`, no checkout) |
| `part_of`, `task_count` | paths and counts |

A files project adds:

| Predicate | Rule |
|---|---|
| `ident defined_in file/sym` | a class / function / method definition, line-based regexes for common languages |
| `ident used_in file/sym` | rare identifiers only (in ≤ 20 units) |
| `ident has_part term` | the words of a camelCase / snake_case identifier |
| `term related_to term` | G² co-occurrence in units, top 10 per term |
| `term is_a term` | Hearst patterns ("X such as Y", "Y and other X"; English and Ukrainian) |
| `abbr same_as phrase` | "Total Cost of Ownership (TCO)" |
| `term variant_of term` | word forms merged by recurring ending pairs and similar spread over files |
| `term function_word` / `domain_core` | residual IDF (Church & Gale) and presence in file names |

## Ranking

Naive Bayes: `log P(target) + λ · Σ log lift(term, target)`, with `not_in` as negative
evidence, dir/module back-off for files (β, β₂), file-name matches (μ) and co-change (γ).
Parameters are tuned on 200 dev tasks taken from the training tasks, and the test tasks never
choose a parameter.

## Results (200 test tasks, exp3 `modn` split)

| MAP | sonar | flink |
|---|---|---|
| modules, most frequent | 0.693 | 0.363 |
| **modules, gamayun** | **0.752** | **0.656** |
| files, most frequent | 0.045 | 0.018 |
| **files, gamayun** | **0.116** | **0.124** |

The method is described step by step, with formulas and worked examples, in `concepts/GAMAYUN.md`
of the simrgl repository. The experiment is in `exp7/` there.

---

## Part of the SIMARGL toolkit

gamayun is one of ten tools that together form an **intellectual development support system**:

| Tool | Role |
|---|---|
| **[simargl](https://github.com/szholobetsky/simargl)** | Task-to-code retrieval — given a task description, finds which files and modules are likely affected, using semantic similarity over git history |
| **[svitovyd](https://github.com/szholobetsky/svitovyd)** | Project map — scans any codebase and produces a structural map of definitions and cross-file dependencies; queried from the CLI, a web UI with a layered map, or an MCP server |
| **[1bcoder](https://github.com/szholobetsky/1bcoder)** | AI coding assistant for small local models — surgical context management, agents, parallel inference, proc scripts |
| **[yasna](https://github.com/szholobetsky/yasna)** | Session memory — indexes conversations from all AI agents so you can find what was discussed, when, and where |
| **[radogast](https://github.com/szholobetsky/radogast)** | Context drift monitor — measures how far an AI agent's conversation has drifted from the original task |
| **[vyrii](https://github.com/szholobetsky/vyrii)** | Local AI web UI — chat, translate, web research, RAG and file management in the browser (Flask; Gradio optional); powered by Ollama or any OpenAI-compatible backend |
| **[syryn](https://github.com/szholobetsky/syryn)** | Bluetooth identity beacon for headless devices — the device's IP is its Bluetooth name; hostname, mDNS and network interfaces on request |
| **[alkonost](https://github.com/szholobetsky/alkonost)** | Browser cockpit for 1bcoder's flows — the `deepagent_*` spec pipeline (plan tree → specs → task board) and the glossary (build, browse, search), tuned for small local models |
| **[gamayun](https://github.com/szholobetsky/gamayun)** | Statistical ontology without an LLM — builds triples of terms, identifiers, files and modules from task history or a folder of documents and code; every triple carries its significance test |
| **[mokosh](https://github.com/szholobetsky/mokosh)** | Dataset gathering — commits of a git repository and the tasks of its tracker (Jira, GitHub, GitLab, YouTrack) in one SQLite database that the other tools read |

- **simargl** finds the code related to a task by vector search over the task history (embeddings).
- **svitovyd** answers: *how is the code structured and what depends on what?*
- **1bcoder** answers: *how do I work with local models efficiently?*
- **yasna** answers: *where did I already discuss this?*
- **radogast** answers: *is the AI agent still on track toward the goal?*
- **vyrii** answers: *how do I access all of this through a browser?*
- **syryn** answers: *what is the address of this headless device?*
- **alkonost** answers: *how do I turn one task description into a reviewed, working plan — and see the project's glossary — without a big model or a big context window?*
- **gamayun** finds the code related to a task through an ontology of significant links between words, files and modules (no LLM).
- **mokosh** prepares the initial dataset from version control and the issue tracker.

Together they cover the full development loop: understand the codebase, find relevant history, work with AI locally, remember what was decided, and verify the context stays on target.

The name comes from Slavic mythology. Gamayun (Гамаюн) is the prophetic bird with a woman's face, the messenger of the gods who knows everything about the world and tells it to those who can listen. A fitting name for a tool that foretells which code a task will touch — and always says why.

---

## About

(c) 2026 Stanislav Zholobetskyi, Oleh Andriichuk  
Institute for Information Recording, National Academy of Sciences of Ukraine, Kyiv  
PhD research: «Intelligent Technology for Software Development and Maintenance Support»
