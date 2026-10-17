import os
import sqlite3

import pytest

from gamayun import data, pipeline, store
from gamayun.builder import g2_vec
from gamayun.evaluation import metrics_for_query
from gamayun.onto import Onto


def test_adf_text_only():
    raw = ("{'type': 'doc', 'version': 1, 'content': [{'type': 'paragraph', 'content': "
           "[{'type': 'text', 'text': 'Scanner fails'}, {'type': 'hardBreak'}]}, "
           "{'type': 'mediaSingle', 'attrs': {'width': 200}, 'content': []}, "
           "{'type': 'paragraph', 'content': [{'type': 'text', 'text': 'on branch'}]}]}")
    assert data.plain_description(raw) == "Scanner fails on branch"
    assert data.plain_description("plain text") == "plain text"


def test_terms_split_identifiers():
    t = data.terms_of("NPE in QualityGateDao when the gate_status is null")
    assert {"qualitygatedao", "quality", "gate", "dao", "gate_status", "status", "npe"} <= t
    assert "the" not in t and "when" not in t


def test_g2_matches_the_worked_example():
    g, pos = g2_vec([202], [381], [464], 9592)       # concepts/GAMAYUN.md §5
    assert round(float(g[0]), 1) == 807.3 and bool(pos[0])


def test_metrics_like_exp3():
    m = metrics_for_query(["A", "X", "B"], {"A", "B", "C"})
    assert round(m["AP"], 3) == 0.556 and m["RR"] == 1.0 and m["hit@10"] == 1.0


# singular (canonical), plural (older simargl ingest), mixed (sonar.db / flink.db)
LAYOUTS = {"singular": ("TASK", '"COMMIT"'), "plural": ("TASKS", "COMMITS"), "mixed": ("TASK", "COMMITS")}


@pytest.fixture(params=list(LAYOUTS))
def db(tmp_path, request):
    """Synthetic tracker: 'scanner' tasks change scanner/, 'gate' tasks change web/."""
    task_t, commit_t = LAYOUTS[request.param]
    p = tmp_path / "t.db"
    con = sqlite3.connect(p)
    con.execute(f"CREATE TABLE {task_t} (ID INTEGER PRIMARY KEY, NAME TEXT, TITLE TEXT, DESCRIPTION TEXT, COMMENTS TEXT)")
    con.execute(f"CREATE TABLE {commit_t} (ID INTEGER PRIMARY KEY, SHA TEXT, AUTHOR_NAME TEXT, AUTHOR_EMAIL TEXT, "
                "CMT_DATE TEXT, MESSAGE BLOB, PATH BLOB, DIFF BLOB, TASK_NAME TEXT)")
    rows = []
    for i in range(600):
        kind = ("scanner", "gate", "misc", "login")[i % 4]   # each word in 25% < max_df
        name = f"T-{i}"
        title = {"scanner": "Scanner report upload fails", "gate": "Quality gate badge wrong",
                 "misc": "Update documentation wording", "login": "Login session expires early"}[kind]
        files = {"scanner": ["scanner/src/ScannerReport.java", "scanner/src/Upload.java"],
                 "gate": ["web/src/QualityGate.tsx", "web/src/Badge.tsx"],
                 "misc": ["docs/readme.md"], "login": ["auth/src/Session.java"]}[kind]
        con.execute(f"INSERT INTO {task_t} VALUES (?,?,?,?,?)", (i + 1, name, title, "", ""))
        for f in files:
            rows.append((f"sha{i}", "u", "", f"2020-01-01 00:00:{i % 60:02d}", title, f, "", name))
    con.executemany(f"INSERT INTO {commit_t} (SHA, AUTHOR_NAME, AUTHOR_EMAIL, CMT_DATE, MESSAGE, PATH, DIFF, TASK_NAME) "
                    "VALUES (?,?,?,?,?,?,?,?)", rows)
    con.commit()
    con.close()
    return str(p)


def test_build_search_and_eval(db, tmp_path, monkeypatch):
    monkeypatch.setenv("GAMAYUN_HOME", str(tmp_path / "home"))
    pipeline.build_project(db, "demo", log=lambda *a: None)
    O = Onto(store.project_dir("demo"))
    assert ("scanner" in O.char["module"]) and ("scanner" in O.char["module"]["scanner"])
    res = O.query("scanner upload is broken").search(pipeline.load_params("demo"), 3)
    assert res["modules"][0]["target"] == "scanner"
    assert res["files"][0]["target"].startswith("scanner/")
    assert res["files"][0]["evidence"], "a result must be explained by triples"
    r = pipeline.evaluate_project("demo", log=lambda *a: None)
    assert r["test"]["module/naive_bayes"]["AP"] > r["test"]["module/prior"]["AP"]
    assert os.path.isfile(store.project_dir("demo") / "params.json")


def test_bad_project_name(tmp_path, monkeypatch):
    monkeypatch.setenv("GAMAYUN_HOME", str(tmp_path))
    with pytest.raises(ValueError):
        store.project_dir("../evil")


def test_missing_tables_say_so(tmp_path):
    p = tmp_path / "empty.db"
    sqlite3.connect(p).close()
    with pytest.raises(ValueError, match="TASK / TASKS"):
        data.load(str(p))


# ── --files: a folder of documents and code, no task database ────────────────

@pytest.fixture
def folder(tmp_path):
    root = tmp_path / "proj"
    for i in range(6):
        (root / "budget").mkdir(parents=True, exist_ok=True)
        (root / "budget" / f"budget_calc{i}.py").write_text(
            f"class BudgetService{i}:\n"
            f"    def close_period(self, final_period):\n"
            f"        # budget of the final period is frozen\n"
            f"        return final_period.budget_total\n\n"
            f"    def plan_budget(self, budget_total):\n"
            f"        return budget_total * 2\n", encoding="utf-8")
        (root / "fuel").mkdir(exist_ok=True)
        (root / "fuel" / f"FuelPrice{i}.java").write_text(
            f"public class FuelPrice{i} {{\n"
            f"    public double litresPerTank(double litres) {{\n"
            f"        // petrol price per litre for the tank\n"
            f"        return litres * petrolPrice;\n    }}\n}}\n", encoding="utf-8")
        (root / "docs").mkdir(exist_ok=True)
        (root / "docs" / f"guide{i}.md").write_text(
            f"# Fuel accounting {i}\n\nPetrol prices change every week. The tank holds litres.\n\n"
            f"## Бюджет\n\nБюджет — це план витрат. Фінальний період закриває бюджети.\n\n"
            f"A tanker is a vehicle. Fuels such as petrol and diesel are tracked.\n"
            f"The Total Cost of Ownership (TCO) matters.\n", encoding="utf-8")
    (root / "docs" / "aviation.md").write_text(
        "# Aviation fuel\n\nKerosene powers jet engines in aviation.\n\n"
        "Aviation kerosene is stored apart.\n\nJet kerosene for aviation is taxed.\n", encoding="utf-8")
    return str(root)


def test_folder_build_identifiers_and_search(folder, tmp_path, monkeypatch):
    monkeypatch.setenv("GAMAYUN_HOME", str(tmp_path / "home"))
    stats = pipeline.build_folder_project(folder, "proj", log=lambda *a: None)
    assert stats["code_files"] == 12 and stats["documents"] == 7
    O = Onto(store.project_dir("proj"))
    assert O.folder and O.N == stats["units"]
    triples = open(store.project_dir("proj") / "triples.txt", encoding="utf-8").read()
    # identifiers are entities, linked to where they are defined and used
    assert "ident:final_period :: used_in :: sym:budget/budget_calc0.py#BudgetService0.close_period" in triples
    assert "ident:close_period :: defined_in :: sym:budget/budget_calc0.py#BudgetService0.close_period" in triples
    assert "ident:budgetservice0 :: has_part :: term:budget" in triples or "ident:budget_total :: has_part" in triples
    # document patterns
    assert "term:tco :: same_as :: term:total cost of ownership" in triples
    assert "term:petrol :: is_a :: term:fuels" in triples and "term:diesel :: is_a :: term:fuels" in triples
    # search: identifiers and Ukrainian words find their files
    res = O.query("final_period budget").search(pipeline.load_params("proj"), 3)
    assert res["files"][0]["target"].startswith("budget/")
    res = O.query("бюджет фінальний").search(pipeline.load_params("proj"), 3)
    assert res["files"][0]["target"].startswith("docs/")
    res = O.query("kerosene aviation").search(pipeline.load_params("proj"), 3)
    assert res["symbols"][0]["target"] == "docs/aviation.md#Aviation fuel"
    with pytest.raises(ValueError, match="task database"):
        pipeline.evaluate_project("proj", log=lambda *a: None)


def test_word_forms_without_a_dictionary():
    from collections import Counter
    from gamayun.folder import word_variants
    df = Counter()
    for stem in ["user", "group", "rule", "metric", "project", "gate", "issue", "branch"]:
        df[stem] += 10
        df[stem + "s"] += 5
    for stem in ["онтолог", "модул", "систем", "ключ", "задач", "функц", "категор", "стратег", "технолог", "методолог"]:
        for e in ["ія", "ії", "ію"]:
            df[stem + e] += 5 if e == "ія" else 3          # the most frequent form names the group
    df["port"] += 10
    df["portal"] += 10
    # forms used in the same files (frequent forms are compared by their files)
    files = {w: Counter({w.rstrip("sіяюї") + ".md": 1}) for w in df}
    variant, _ = word_variants(df, files, protected=set())
    assert variant["users"] == "user" and variant["groups"] == "group"
    assert variant["онтології"] == variant["онтологію"] == "онтологія"
    assert "portal" not in variant and "port" not in variant      # {-, al} is not a recurring pair


def test_function_words_from_spread_not_length():
    from collections import Counter
    from gamayun.folder import classify_terms
    n = 200
    doc_len = [100] * n
    doc_df, cf, names = Counter(), Counter(), Counter()
    doc_df["the"], cf["the"] = 200, 1000            # everywhere, like chance
    doc_df["ui"], cf["ui"] = 20, 1000               # two letters, bunched in 20 files
    doc_df["fuel"], cf["fuel"] = 200, 1000          # everywhere — but it names files
    names["fuel"] = 40
    kinds = classify_terms(doc_df, cf, doc_len, names, n)
    assert kinds["the"][0] == "function_word"
    assert "ui" not in kinds                         # short words are judged like any other
    assert kinds["fuel"][0] == "domain_core"


def _cochange_onto(tmp_path):
    files = ["web/Form.tsx", "web/Form.css", "web/__tests__/Form-test.tsx", "web/Other.tsx", "l10n/core.properties"]
    lines = ["corpus :: train_tasks :: 40  [src: -]"]
    lines += [f"file:{f} :: task_count :: 10  [src: tasks=10]" for f in files]
    lines += ["file:web/Form.tsx :: co_changes_with :: file:web/Form.css  [src: g2=40.0;n=6]",
              "file:web/__tests__/Form-test.tsx :: co_changes_with :: file:web/Form.css  [src: g2=30.0;n=5]",
              "file:web/Form.tsx :: co_changes_with :: file:web/__tests__/Form-test.tsx  [src: g2=50.0;n=8]",
              "file:web/Form.tsx :: co_changes_with :: file:l10n/core.properties  [src: g2=90.0;n=7]"]
    p = tmp_path / "triples.txt"
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return Onto(str(p))


def test_files_in_text_paths_and_unique_names(tmp_path):
    O = _cochange_onto(tmp_path)
    text = "**Relevant files:**\n- `web/Form.tsx`\n- Form-test.tsx (its test)\n- missing/Nope.java"
    assert O.files_in_text(text) == ["web/Form.tsx", "web/__tests__/Form-test.tsx"]


def test_companions_rank_by_how_many_chosen_files_they_go_with(tmp_path):
    O = _cochange_onto(tmp_path)
    res = O.companions(["web/Form.tsx", "web/__tests__/Form-test.tsx"], k=5)
    # Form.css changed with both chosen files, so it beats core.properties despite a lower G2
    assert [r["target"] for r in res] == ["web/Form.css", "l10n/core.properties"]
    assert res[0]["with"] == ["web/Form.tsx", "web/__tests__/Form-test.tsx"] and res[0]["g2"] == 70.0


def test_compass_anchors_skip_urls_and_hosts():
    from gamayun.compass import anchors
    text = ('FOP logs: Loggers.get("org.apache.fop") in FileReportGenerator, header Sonar-Version, '
            'see https://jira.sonarsource.com/browse/X and jira.sonarsource.com')
    a = anchors(text)
    assert "org.apache.fop" in a and "FileReportGenerator" in a and "Sonar-Version" in a
    assert not any("jira" in x for x in a)


def test_compass_without_repo_uses_the_ontology(tmp_path):
    from gamayun.compass import compass, render
    from gamayun.onto import DEFAULT_PARAMS
    O = _cochange_onto(tmp_path)
    res = compass(O, "the Form is broken", DEFAULT_PARAMS, repo=None)
    assert res["source"] in ("ontology", "none") and res["anchor"] is None
    assert render(res).startswith("compass:")


@pytest.fixture
def local_home(tmp_path, monkeypatch):
    """No $GAMAYUN_HOME: projects next to their folders, ~/.gamayun only keeps the registry."""
    monkeypatch.delenv("GAMAYUN_HOME", raising=False)
    monkeypatch.setattr(store.Path, "home", classmethod(lambda cls: tmp_path / "user"))
    return tmp_path


def test_index_keeps_the_ontology_next_to_the_folder_and_registers_it(local_home, folder, monkeypatch):
    from pathlib import Path
    folder = Path(folder)
    elsewhere = local_home / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(folder)                                   # `gamayun index` run in the folder
    pipeline.build_folder_project(str(folder), "proj", log=lambda *a: None)
    assert (folder / ".gamayun" / "proj" / "triples.txt").is_file()
    assert store.registry()["proj"]["root"] == str(folder.resolve())
    monkeypatch.chdir(elsewhere)                                # any other command, from anywhere
    assert store.project_dir("proj") == (folder / ".gamayun" / "proj").resolve()
    assert store.project_root("proj") == folder.resolve()
    assert [p["project"] for p in store.list_projects()] == ["proj"]


def test_ui_start_folder_finds_unregistered_projects(local_home, monkeypatch):
    repo = local_home / "work" / "sonar"
    (repo / ".gamayun" / "s1").mkdir(parents=True)
    (repo / ".gamayun" / "s1" / "triples.txt").write_text("dataset :: train_tasks :: 1  [src: -]\n", encoding="utf-8")
    monkeypatch.chdir(local_home)
    names = [p["project"] for p in store.list_projects(start=str(local_home / "work"))]
    assert names == ["s1"] and "s1" in store.registry()


def test_server_keeps_projects_apart(local_home, monkeypatch):
    from gamayun.server import create_app
    for name, word in (("a", "alpha"), ("b", "beta")):
        root = local_home / name
        d = root / ".gamayun" / name
        d.mkdir(parents=True)
        (d / "triples.txt").write_text(
            "dataset :: train_tasks :: 10  [src: -]\n"
            f"file:{word}.py :: task_count :: 5  [src: tasks=5]\n"
            f"term:{word} :: characterizes :: file:{word}.py  [src: g2=20.0;lift=3.0]\n", encoding="utf-8")
        store.register(name, d, root)
    c = create_app().test_client()
    ea = c.get("/api/entity?project=a&name=term:beta").get_json()["triples"]
    eb = c.get("/api/entity?project=b&name=term:beta").get_json()["triples"]
    assert ea == [] and len(eb) == 1                            # b's word is not in a
    assert c.get("/api/entity?project=&name=term:beta").status_code == 400


def test_health_square_follows_the_history():
    from gamayun.health import health, unit_of, period_of, units
    hist = [("2020-01-05", "T1", frozenset({"a/x/One.java", "a/x/Two.java"})),        # novel, inside  -> evolution
            ("2020-02-05", "T2", frozenset({"a/x/One.java", "a/x/Two.java"})),        # known, inside  -> maintenance
            ("2021-03-05", "T3", frozenset({"a/x/One.java", "b/y/Three.java"})),      # novel, across  -> disruption
            ("2021-04-05", "T4", frozenset({"a/x/One.java", "b/y/Three.java"})),      # known, across  -> stagnation
            ("2021-05-05", "T5", frozenset({"a/x/One.java"}))]                        # one file: no pair
    r = health(hist, depth=2, by="year")
    y20, y21 = r["periods"]
    assert (y20["period"], y20["evolution"], y20["maintenance"]) == ("2020", 0.5, 0.5)
    assert (y21["disruption"], y21["stagnation"], y21["tasks"]) == (0.5, 0.5, 2)
    assert r["total"]["novelty"] == 0.5 and r["total"]["structurality"] == 0.5
    # the history is judged up to each task only: a window does not forget what came before
    assert health(hist, by="year", since="2021")["total"]["stagnation"] == 0.5
    one = health(hist, by="year", unit="b/y")["total"]          # b/y is in T3, T4 only: both pairs cross out
    assert one["tasks"] == 2 and one["structurality"] == 0.0
    assert unit_of("sonar-core/src/main/java/A.java") == "sonar-core" and unit_of("build.gradle") == "(root)"
    assert period_of("2021-05-05", "quarter") == "2021-Q2"
    assert {u["unit"] for u in units(hist, min_tasks=1)} == {"a/x", "b/y"}


def test_map_layers_open_one_module_at_a_time():
    from gamayun.health import unit_map, _node_of
    hist = []
    for i in range(6):                                           # srv/web and srv/api change together
        hist.append((f"2020-0{i % 9 + 1}-01", f"A{i}", frozenset({"srv/web/src/main/js/apps/A.js",
                                                                   "srv/api/src/main/java/org/x/B.java"})))
    for i in range(6):                                           # core alone, never with srv
        hist.append((f"2020-0{i % 9 + 1}-02", f"C{i}", frozenset({"core/src/main/java/org/x/C.java"})))
    for i in range(3):                                           # in 2022 web starts to go with core
        hist.append((f"2022-01-0{i + 1}", f"N{i}", frozenset({"srv/web/src/main/js/apps/A.js",
                                                              "core/src/main/java/org/x/C.java"})))
    assert _node_of("srv/web/src/main/js/apps/A.js", "srv/web") == "srv/web/src/main/js/apps"
    assert _node_of("core/x.txt", "srv") is None and _node_of("README.md", "") == "(root)"
    top = unit_map(hist, "", min_tasks=3)
    assert {n["id"] for n in top["nodes"]} == {"srv", "core"} and all(n["drill"] for n in top["nodes"])
    (e0,) = top["edges"]                                         # srv~core: 3 tasks, below chance
    assert e0["tasks"] == 3 and e0["lift"] < 1
    srv = unit_map(hist, "srv", min_tasks=3)
    assert {n["label"] for n in srv["nodes"]} == {"web", "api"} and srv["crumbs"] == ["srv"]
    (e,) = srv["edges"]
    assert {e["source"], e["target"]} == {"srv/web", "srv/api"} and e["tasks"] == 6 and not e["new"]
    web = next(n for n in srv["nodes"] if n["id"] == "srv/web")
    assert web["outside"] == 3                                   # its 2022 tasks also touched core
    # a window marks coupling that did not exist before it
    late = unit_map(hist, "", since="2022", min_tasks=3)
    assert [x["new"] for x in late["edges"]] == [True]
    # a chain of single folders is skipped: core opens at org/x, where it would branch
    assert unit_map(hist, "core")["prefix"].startswith("core/src/main/java/org")


def test_ontology_map_code_map_and_overlay(tmp_path):
    from gamayun import ontomap as M
    hist = tmp_path / "h.txt"
    hist.write_text("\n".join([
        "train_tasks :: train_tasks :: 50  [src: tasks]",
        "file:srv/web/A.js :: task_count :: 10  [src: tasks touching it]",
        "file:srv/api/B.java :: task_count :: 8  [src: tasks touching it]",
        "file:srv/db/C.java :: task_count :: 6  [src: tasks touching it]",
        "file:srv/old/D.java :: task_count :: 5  [src: tasks touching it]",
        "file:srv/web/A.js :: co_changes_with :: file:srv/api/B.java  [src: n=5;g2=20.0;lift=3.0]",
        "file:srv/old/D.java :: co_changes_with :: file:srv/db/C.java  [src: n=4;g2=15.0;lift=4.0]",
        "file:srv/api/B.java :: co_changes_with :: file:srv/db/C.java  [src: n=3;g2=9.0;lift=2.0]",
    ]) + "\n", encoding="utf-8")
    code = tmp_path / "c.txt"
    code.write_text("\n".join([
        "units :: units :: 40  [src: units]",
        "file:srv/web/A.js :: unit_count :: 4  [src: units in it]",
        "file:srv/api/B.java :: unit_count :: 6  [src: units in it]",
        "file:srv/db/C.java :: unit_count :: 3  [src: units in it]",
        "ident:dao :: defined_in :: sym:srv/db/C.java#Dao  [src: line=1]",
        "ident:dao :: used_in :: file:srv/api/B.java  [src: n=1;df=2]",
        "ident:dao2 :: defined_in :: sym:srv/db/C.java#Dao2  [src: line=9]",
        "ident:dao2 :: used_in :: file:srv/api/B.java  [src: n=1;df=2]",
        "ident:dao3 :: defined_in :: sym:srv/db/C.java#Dao3  [src: line=19]",
        "ident:dao3 :: used_in :: sym:srv/api/B.java#Api.run  [src: n=1;df=2]",
    ]) + "\n", encoding="utf-8")
    H, C = Onto(str(hist)), Onto(str(code))
    assert (M.kind(H), M.kind(C)) == ("history", "code")
    h = M.unit_map(H, "srv", min_tasks=3)
    assert h["source"] == "history" and {n["label"] for n in h["nodes"]} == {"web", "api", "db", "old"}
    e = {(x["source"], x["target"]): x for x in h["edges"]}
    assert e[("srv/api", "srv/web")]["min_tasks"] == 5 and e[("srv/api", "srv/web")]["weight"] == 1
    c = M.unit_map(C, "srv", min_tasks=1)
    (ce,) = c["edges"]
    assert (ce["source"], ce["target"], ce["ab"], ce["ba"]) == ("srv/api", "srv/db", 3, 0)    # api uses db
    o = M.overlay(H, C, "srv", min_tasks=3)
    kinds = {(x["source"], x["target"]): x["kind"] for x in o["edges"]}
    assert kinds[("srv/api", "srv/db")] == "both"
    assert kinds[("srv/api", "srv/web")] == "history"           # changed together, no identifier between
    assert kinds[("srv/db", "srv/old")] == "gone"                # old is not in the code any more
    d = M.edge_detail(H, "srv", "srv/api", "srv/db", Oc=C)
    assert d["pairs_total"] == 1 and d["a_uses_b"] == 3 and d["b_uses_a"] == 0
