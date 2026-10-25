import os, json, csv, io, sqlite3, datetime as dt, urllib.request, urllib.error
from flask import Flask, request, jsonify, g, send_from_directory
from scoring import key_letters, key_warnings
import tracker
DB = os.environ.get("GATE_DB", os.path.join(os.path.dirname(__file__), "data", "gate.db"))
os.makedirs(os.path.dirname(DB), exist_ok=True)
app = Flask(__name__, static_folder="static")
SCHEMA = """
CREATE TABLE IF NOT EXISTS subjects(id INTEGER PRIMARY KEY, name TEXT UNIQUE, section TEXT);
CREATE TABLE IF NOT EXISTS questions(id INTEGER PRIMARY KEY, subject TEXT, topic TEXT, year INTEGER, qno TEXT,
 qtype TEXT CHECK(qtype IN('MCQ','MSQ','NAT')), marks INTEGER DEFAULT 1, text TEXT, options TEXT DEFAULT '[]',
 answer TEXT, tolerance REAL DEFAULT 0, difficulty TEXT, explanation TEXT, source TEXT, is_demo INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS attempts(id INTEGER PRIMARY KEY, qid INTEGER, ts TEXT, selected TEXT, correct INTEGER,
 attempted INTEGER, marks REAL, time_spent INTEGER, error_type TEXT, notes TEXT, session TEXT);
CREATE TABLE IF NOT EXISTS revisions(qid INTEGER PRIMARY KEY, stage INTEGER DEFAULT 0, due TEXT);
CREATE TABLE IF NOT EXISTS sessions(id INTEGER PRIMARY KEY, mode TEXT, title TEXT, qids TEXT, answers TEXT DEFAULT '{}', flags TEXT DEFAULT '{}',
 times TEXT DEFAULT '{}', idx INTEGER DEFAULT 0, duration INTEGER DEFAULT 0, elapsed INTEGER DEFAULT 0, status TEXT DEFAULT 'active', created TEXT, finished TEXT, result TEXT);
CREATE TABLE IF NOT EXISTS settings(k TEXT PRIMARY KEY, v TEXT);
CREATE TABLE IF NOT EXISTS study_notes(id INTEGER PRIMARY KEY, title TEXT NOT NULL, subject TEXT DEFAULT '', topic TEXT DEFAULT '', kind TEXT NOT NULL DEFAULT 'concept', body TEXT NOT NULL DEFAULT '', tags TEXT DEFAULT '', qid INTEGER, pinned INTEGER NOT NULL DEFAULT 0, created TEXT NOT NULL, updated TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS idx_study_notes_updated ON study_notes(updated DESC);
CREATE TABLE IF NOT EXISTS question_flags(qid INTEGER PRIMARY KEY, bookmarked INTEGER NOT NULL DEFAULT 0, difficult INTEGER NOT NULL DEFAULT 0, guessed INTEGER NOT NULL DEFAULT 0, personal_note TEXT DEFAULT '', updated TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS syllabus_topics(id INTEGER PRIMARY KEY, subject TEXT NOT NULL, topic TEXT NOT NULL, subtopic TEXT NOT NULL DEFAULT '', created TEXT NOT NULL, UNIQUE(subject,topic,subtopic));
CREATE INDEX IF NOT EXISTS idx_syllabus_topics_subject ON syllabus_topics(subject,topic);
"""
SEED_SUBJECTS = [("Discrete Mathematics","Engineering Mathematics"),("Linear Algebra","Engineering Mathematics"),
 ("Calculus","Engineering Mathematics"),("Probability and Statistics","Engineering Mathematics"),
 ("Verbal Aptitude","General Aptitude"),("Quantitative Aptitude","General Aptitude"),
 ("Logical and Analytical Reasoning","General Aptitude"),("Spatial Aptitude","General Aptitude"),
 ("Programming and Data Structures","CSE Core"),("Algorithms","CSE Core"),("Operating Systems","CSE Core"),
 ("Database Management Systems","CSE Core"),("Computer Networks","CSE Core"),("Computer Organization and Architecture","CSE Core"),
 ("Theory of Computation","CSE Core"),("Compiler Design","CSE Core"),("Digital Logic","CSE Core"),("Engineering Mathematics","Engineering Mathematics")]
SEED_SYLLABUS_TOPICS = [
 # GATE 2027 CS syllabus — official IIT Madras PDF. Entries retain the official syllabus terminology.
 ("Discrete Mathematics","Discrete Mathematics","Propositional and first order logic"),
 ("Discrete Mathematics","Discrete Mathematics","Sets, relations, functions, partial orders and lattices"),
 ("Discrete Mathematics","Discrete Mathematics","Monoids, Groups"),
 ("Discrete Mathematics","Discrete Mathematics","Graphs: connectivity, matching, colouring"),
 ("Discrete Mathematics","Discrete Mathematics","Combinatorics: counting, recurrence relations, generating functions"),
 ("Linear Algebra","Linear Algebra","Matrices, determinants, system of linear equations, eigenvalues and eigenvectors, LU decomposition"),
 ("Calculus","Calculus","Limits, continuity and differentiability, Maxima and minima, Mean value theorem, Integration"),
 ("Probability and Statistics","Probability and Statistics","Random variables, Uniform, normal, exponential, Poisson and binomial distributions"),
 ("Probability and Statistics","Probability and Statistics","Mean, median, mode and standard deviation"),
 ("Probability and Statistics","Probability and Statistics","Conditional probability and Bayes theorem"),
 ("Verbal Aptitude","Verbal Aptitude","Basic English grammar: tenses, articles, adjectives, prepositions, conjunctions, verb-noun agreement, and other parts of speech"),
 ("Verbal Aptitude","Verbal Aptitude","Basic vocabulary: words, idioms, and phrases in context"),
 ("Verbal Aptitude","Verbal Aptitude","Reading and comprehension, Narrative sequencing"),
 ("Quantitative Aptitude","Quantitative Aptitude","Data interpretation: data graphs (bar graphs, pie charts, and other graphs representing data), 2-and 3-dimensional plots, maps, and tables"),
 ("Quantitative Aptitude","Quantitative Aptitude","Numerical computation and estimation: ratios, percentages, powers, exponents and logarithms, permutations and combinations, and series"),
 ("Quantitative Aptitude","Quantitative Aptitude","Mensuration and geometry, Elementary statistics and probability"),
 ("Logical and Analytical Reasoning","Logical and Analytical Reasoning","Logic: deduction and induction, Analogy, Numerical relations and reasoning"),
 ("Spatial Aptitude","Spatial Aptitude","Transformation of shapes: translation, rotation, scaling, mirroring, assembling, and grouping"),
 ("Spatial Aptitude","Spatial Aptitude","Paper folding, cutting, and patterns in 2 and 3 dimensions"),
 ("Digital Logic","Boolean algebra and minimization","Algebraic technique, Karnaugh map, tabular method"),
 ("Digital Logic","Circuits","Design of combinational and sequential circuits"),
 ("Digital Logic","Number representation and arithmetic","Fixed and floating point"),
 ("Computer Organization and Architecture","Instruction set","Instruction set and addressing modes"),
 ("Computer Organization and Architecture","Arithmetic and logic unit","Design of arithmetic and logic unit (ALU)"),
 ("Computer Organization and Architecture","Control unit","Design of control unit – hardwired and microprogrammed"),
 ("Computer Organization and Architecture","Memory interfacing and hierarchy","Performance, cache memory mapping"),
 ("Computer Organization and Architecture","I/O interface","Interrupt and DMA"),
 ("Computer Organization and Architecture","Instruction pipelining","Pipeline hazards"),
 ("Programming and Data Structures","Programming","Programming in C, Recursion"),
 ("Programming and Data Structures","Data structures","Arrays, stacks, queues, linked lists, trees, binary search trees, binary heaps, graphs"),
 ("Algorithms","Core algorithms","Searching, sorting, hashing"),
 ("Algorithms","Complexity","Asymptotic worst case time and space complexity"),
 ("Algorithms","Algorithm design techniques","Greedy, dynamic programming and divide-and-conquer"),
 ("Algorithms","Graph algorithms","Graph traversals, minimum spanning trees, shortest paths"),
 ("Theory of Computation","Automata and regular languages","Regular expressions and finite automata"),
 ("Theory of Computation","Context-free languages","Context-free grammars and push-down automata"),
 ("Theory of Computation","Language properties","Regular and context-free languages, pumping lemma"),
 ("Theory of Computation","Computability","Turing machines and undecidability"),
 ("Compiler Design","Front end","Lexical analysis, parsing, syntax-directed translation"),
 ("Compiler Design","Runtime environments","Runtime environments"),
 ("Compiler Design","Intermediate code generation","Intermediate code generation"),
 ("Compiler Design","Optimisation and data flow","Local optimisation, constant propagation, liveness analysis, common sub expression elimination"),
 ("Operating Systems","Processes and communication","System calls, processes, threads, inter-process communication"),
 ("Operating Systems","Concurrency and synchronization","Concurrency and synchronization, Deadlock"),
 ("Operating Systems","Scheduling","CPU and I/O scheduling"),
 ("Operating Systems","Memory management","Memory management and virtual memory"),
 ("Operating Systems","File systems","File systems"),
 ("Database Management Systems","Data models","ER-model, relational model"),
 ("Database Management Systems","Relational query languages","Relational algebra, tuple calculus, SQL"),
 ("Database Management Systems","Integrity and normalisation","Integrity constraints, normal forms"),
 ("Database Management Systems","Storage and indexing","File organization, indexing (e.g., B and B+ trees)"),
 ("Database Management Systems","Transactions","Transactions and concurrency control"),
 ("Computer Networks","Layering and switching","Principles of layering; basics of switching (circuit, packet and virtual circuit) and performance metrics"),
 ("Computer Networks","Data link layer","Error detection, Medium Access Control, Ethernet"),
 ("Computer Networks","Routing","Distance vector and link state routing"),
 ("Computer Networks","IPv4","Fragmentation, CIDR Notation, Network Address Translation"),
 ("Computer Networks","Transport layer","TCP flow control and congestion control, socket API"),
 ("Computer Networks","Application layer","DNS and HTTP"),
]
DEMO = [dict(subject="Linear Algebra",topic="Determinants",qtype="MCQ",marks=1,text="[DEMO] det of [[2,0],[0,3]]?",options=["5","6","0","1"],answer="B",explanation="Product of diagonal = 6."),
 dict(subject="Discrete Mathematics",topic="Counting",qtype="MSQ",marks=2,text="[DEMO] Which are even? ",options=["2","3","4","5"],answer="A,C",explanation="2 and 4."),
 dict(subject="Calculus",topic="Limits",qtype="NAT",marks=1,text="[DEMO] lim x->0 sin(x)/x = ?",options=[],answer="1",tolerance=0.01,explanation="Standard limit.")]
def db():
    if "db" not in g:
        g.db = sqlite3.connect(DB); g.db.row_factory = sqlite3.Row
    return g.db
@app.teardown_appcontext
def close(e):
    d = g.pop("db", None)
    if d: d.close()
def init():
    c = sqlite3.connect(DB); c.executescript(SCHEMA); c.executescript(tracker.TRACKER_SCHEMA)
    c.executemany("INSERT OR IGNORE INTO subjects(name,section) VALUES(?,?)", SEED_SUBJECTS)
    c.executemany("INSERT OR IGNORE INTO syllabus_topics(subject,topic,subtopic,created) VALUES(?,?,?,?)", [(subject, topic, subtopic, dt.datetime.now().isoformat(timespec="seconds")) for subject,topic,subtopic in SEED_SYLLABUS_TOPICS])
    c.execute("INSERT OR IGNORE INTO settings VALUES('intervals','[1,3,7,14]')")
    c.execute("INSERT OR IGNORE INTO settings VALUES('daily_target','{\"Engineering Mathematics\":10,\"General Aptitude\":10}')")
    c.commit(); c.close()
def score(q, selected):
    """Return (attempted, correct, marks). selected: str ('B', 'A,C', '3.5') or ''."""
    sel = (selected or "").strip()
    if not sel: return 0, 0, 0.0
    if q["qtype"] == "NAT":
        try: ok = abs(float(sel) - float(q["answer"])) <= (q["tolerance"] or 0) + 1e-12
        except ValueError: return 1, 0, 0.0
        return 1, int(ok), float(q["marks"]) if ok else 0.0
    S = key_letters(sel); A = key_letters(q["answer"])  # tolerant of (B), B., Option B; unreadable -> never matches (no guessing)
    ok = S is not None and A is not None and S == A
    if ok: return 1, 1, float(q["marks"])
    if q["qtype"] == "MCQ": return 1, 0, -(1/3 if q["marks"] == 1 else 2/3)
    return 1, 0, 0.0  # MSQ: no negative
def add_questions(rows):
    n = 0
    for r in rows:
        opts = r.get("options") or []
        if isinstance(opts, str):
            try: opts = json.loads(opts)
            except Exception: opts = [o for o in opts.split("|") if o]
        db().execute("INSERT INTO questions(subject,topic,year,qno,qtype,marks,text,options,answer,tolerance,difficulty,explanation,source,is_demo) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
          (r["subject"], r.get("topic"), r.get("year") or None, r.get("qno"), r["qtype"].upper(), int(r.get("marks") or 1), r["text"],
           json.dumps(opts), str(r["answer"]), float(r.get("tolerance") or 0), r.get("difficulty"), r.get("explanation"), r.get("source"), int(r.get("is_demo") or 0)))
        n += 1
    db().commit(); return n
def now(): return dt.datetime.now().isoformat(timespec="seconds")
@app.get("/")
def home(): return send_from_directory("static", "index.html")
@app.get("/api/subjects")
def subjects(): return jsonify([dict(r) for r in db().execute("SELECT * FROM subjects")])
@app.post("/api/subjects")
def add_subject():
    d = request.get_json(silent=True) or {}; name = str(d.get("name", "")).strip(); section = str(d.get("section", "CSE Core")).strip()
    if not name: return jsonify(error="Subject name is required"), 400
    if db().execute("SELECT 1 FROM subjects WHERE name=?", (name,)).fetchone(): return jsonify(error="Subject already exists"), 409
    db().execute("INSERT INTO subjects(name,section) VALUES(?,?)", (name, section or "CSE Core")); db().commit(); return jsonify(ok=True), 201
@app.get("/api/questions")
def questions():
    sql, p = "SELECT q.*, (SELECT COUNT(*) FROM attempts a WHERE a.qid=q.id) n_att FROM questions q WHERE 1=1", []
    for f in ("subject", "topic", "year", "difficulty", "qtype"):
        if request.args.get(f): sql += f" AND q.{f}=?"; p.append(request.args[f])
    st = request.args.get("status")
    if st == "unattempted": sql += " AND q.id NOT IN (SELECT qid FROM attempts)"
    if st == "wrong": sql += " AND q.id IN (SELECT qid FROM attempts WHERE attempted=1 AND correct=0)"
    if st == "due": sql += " AND q.id IN (SELECT qid FROM revisions WHERE due<=?)"; p.append(now())
    if st in ("bookmarked", "difficult", "guessed"): sql += f" AND q.id IN (SELECT qid FROM question_flags WHERE {st}=1)"
    if request.args.get("q"):
        sql += " AND (q.text LIKE ? OR q.topic LIKE ? OR q.qno LIKE ? OR q.source LIKE ?)"; p += ["%" + request.args["q"] + "%"] * 4
    sql += " ORDER BY RANDOM()" if request.args.get("random") else " ORDER BY q.id"
    if request.args.get("limit"):
        sql += " LIMIT ? OFFSET ?"; p += [int(request.args["limit"]), int(request.args.get("offset") or 0)]
    out = []
    for r in db().execute(sql, p):
        d = dict(r); d["options"] = json.loads(d["options"])
        if request.args.get("hide_answer", "1") == "1": d.pop("answer"); d.pop("explanation")
        out.append(d)
    return jsonify(out)
@app.post("/api/import")
def imp():
    f = request.files.get("file"); raw = f.read().decode("utf-8-sig") if f else request.get_data(as_text=True)
    name = (f.filename if f else request.args.get("fmt", "json")).lower()
    try:
        rows = list(csv.DictReader(io.StringIO(raw))) if name.endswith("csv") else json.loads(raw)
        if not isinstance(rows, list): return jsonify(error="Bad file: expected a list of questions"), 400
        warns = []; unique = []; seen = set(); skipped = 0
        for n, r in enumerate(rows, 1):
            try: warns += [f"row {n}: {x}" for x in key_warnings(r)]
            except Exception: pass
            norm = (str(r.get("subject", "")).strip().casefold(), str(r.get("qtype", "")).strip().upper(), " ".join(str(r.get("text", "")).split()).casefold())
            exists = db().execute("SELECT id FROM questions WHERE lower(trim(subject))=? AND upper(qtype)=? AND lower(trim(text))=? LIMIT 1", norm).fetchone()
            if norm in seen or exists:
                skipped += 1; warns.append(f"row {n}: duplicate question skipped (matching subject/type/text)"); continue
            seen.add(norm); unique.append(r)
        imported = add_questions(unique) if unique else 0
        return jsonify(imported=imported, duplicates_skipped=skipped, warnings=warns[:50], warning_count=len(warns))
    except (KeyError, ValueError, TypeError, AttributeError, sqlite3.IntegrityError) as e: return jsonify(error=f"Bad row/file: {e}"), 400

# Question-bank management API (added in fast-build checkpoint)
def _question_payload(d):
    if not isinstance(d, dict):
        raise ValueError("Question must be a JSON object")
    subject = str(d.get("subject", "")).strip()
    text = str(d.get("text", "")).strip()
    qtype = str(d.get("qtype", "")).upper().strip()
    answer = str(d.get("answer", "")).strip()
    if not subject or not text or not answer:
        raise ValueError("subject, text and answer are required")
    if not db().execute("SELECT 1 FROM subjects WHERE name=?", (subject,)).fetchone():
        raise ValueError("Unknown subject; create/select a subject first")
    if qtype not in ("MCQ", "MSQ", "NAT"):
        raise ValueError("qtype must be MCQ, MSQ or NAT")
    options = d.get("options") or []
    if isinstance(options, str):
        try: options = json.loads(options)
        except Exception: raise ValueError("options must be a JSON array")
    if not isinstance(options, list) or any(not isinstance(x, (str, int, float)) for x in options):
        raise ValueError("options must be an array of strings")
    if qtype in ("MCQ", "MSQ") and len(options) < 2:
        raise ValueError("MCQ/MSQ requires at least two options")
    if qtype in ("MCQ", "MSQ"):
        keys = [x.strip().upper() for x in answer.split(",") if x.strip()]
        allowed = {chr(65 + i) for i in range(len(options))}
        if not keys or any(k not in allowed for k in keys) or len(set(keys)) != len(keys):
            raise ValueError("Answer must use valid option letters (e.g. B or A,C)")
        if qtype == "MCQ" and len(keys) != 1:
            raise ValueError("MCQ must have exactly one correct option")
        answer = ",".join(sorted(keys))
    marks = d.get("marks", 1)
    try: marks = int(marks)
    except (TypeError, ValueError): raise ValueError("marks must be a positive integer")
    if marks < 1 or marks > 20: raise ValueError("marks must be between 1 and 20")
    tolerance = d.get("tolerance", 0)
    try: tolerance = float(tolerance or 0)
    except (TypeError, ValueError): raise ValueError("tolerance must be numeric")
    if tolerance < 0: raise ValueError("tolerance cannot be negative")
    year = d.get("year") or None
    if year is not None:
        try: year = int(year)
        except (TypeError, ValueError): raise ValueError("year must be an integer")
        if year < 1980 or year > dt.date.today().year + 1: raise ValueError("year is outside the supported range")
    return dict(subject=subject, topic=str(d.get("topic") or "").strip() or None,
        year=year, qno=str(d.get("qno") or "").strip() or None, qtype=qtype,
        marks=marks, text=text, options=options, answer=answer, tolerance=tolerance,
        difficulty=str(d.get("difficulty") or "").strip() or None,
        explanation=str(d.get("explanation") or "").strip() or None,
        source=str(d.get("source") or "").strip() or None)

@app.put("/api/subjects/<int:sid>")
def update_subject(sid):
    d = request.get_json(silent=True) or {}
    name = str(d.get("name", "")).strip()
    section = str(d.get("section", "Core CS")).strip() or "Core CS"
    if not name: return jsonify(error="Subject name is required"), 400
    old = db().execute("SELECT * FROM subjects WHERE id=?", (sid,)).fetchone()
    if not old: return jsonify(error="Subject not found"), 404
    if db().execute("SELECT 1 FROM subjects WHERE name=? AND id<>?", (name, sid)).fetchone():
        return jsonify(error="A subject with this name already exists"), 409
    # Avoid collisions in the structured catalog before applying the rename.
    collision = db().execute("SELECT 1 FROM syllabus_topics a JOIN syllabus_topics b ON a.topic=b.topic AND a.subtopic=b.subtopic WHERE a.subject=? AND b.subject=? LIMIT 1", (old["name"], name)).fetchone()
    if collision: return jsonify(error="Rename would duplicate a topic/subtopic in the destination subject. Resolve the catalog conflict first."), 409
    # Keep questions linked by subject name consistent with the renamed subject.
    db().execute("UPDATE questions SET subject=? WHERE subject=?", (name, old["name"]))
    db().execute("UPDATE syllabus_topics SET subject=? WHERE subject=?", (name, old["name"]))
    db().execute("UPDATE subjects SET name=?, section=? WHERE id=?", (name, section, sid))
    db().commit()
    return jsonify(ok=True, id=sid, name=name, section=section)

@app.delete("/api/subjects/<int:sid>")
def delete_subject(sid):
    row = db().execute("SELECT * FROM subjects WHERE id=?", (sid,)).fetchone()
    if not row: return jsonify(error="Subject not found"), 404
    n = db().execute("SELECT COUNT(*) FROM questions WHERE subject=?", (row["name"],)).fetchone()[0]
    if n: return jsonify(error=f"Cannot delete: {n} question(s) use this subject. Move or delete them first."), 409
    topics = db().execute("SELECT COUNT(*) FROM syllabus_topics WHERE subject=?", (row["name"],)).fetchone()[0]
    if topics: return jsonify(error=f"Cannot delete: {topics} syllabus topic/subtopic entr(y/ies) use this subject. Delete or move them first."), 409
    db().execute("DELETE FROM subjects WHERE id=?", (sid,)); db().commit()
    return jsonify(ok=True)

@app.get("/api/topics/catalog")
def topic_catalog():
    subject = request.args.get("subject", "").strip()
    sql = """SELECT subject, topic, COUNT(*) question_count
             FROM questions WHERE topic IS NOT NULL AND topic<>''"""
    params = []
    if subject:
        sql += " AND subject=?"; params.append(subject)
    sql += " GROUP BY subject, topic ORDER BY subject, topic"
    return jsonify([dict(r) for r in db().execute(sql, params)])

@app.get("/api/questions/<int:qid>")
def q_detail(qid):
    r = db().execute("SELECT * FROM questions WHERE id=?", (qid,)).fetchone()
    if not r: return jsonify(error="Question not found"), 404
    d = dict(r); d["options"] = json.loads(d["options"])
    d["history"] = [dict(x) for x in db().execute(
        "SELECT ts, attempted, correct, error_type FROM attempts WHERE qid=? ORDER BY ts DESC LIMIT 30", (qid,)
    )]
    return jsonify(d)

@app.get("/api/questions/<int:qid>/flags")
def question_flags_get(qid):
    if not db().execute("SELECT 1 FROM questions WHERE id=?", (qid,)).fetchone(): return jsonify(error="Question not found"), 404
    r = db().execute("SELECT * FROM question_flags WHERE qid=?", (qid,)).fetchone()
    return jsonify(dict(r) if r else {"qid":qid,"bookmarked":0,"difficult":0,"guessed":0,"personal_note":""})

@app.put("/api/questions/<int:qid>/flags")
def question_flags_put(qid):
    if not db().execute("SELECT 1 FROM questions WHERE id=?", (qid,)).fetchone(): return jsonify(error="Question not found"), 404
    d = request.get_json(silent=True) or {}; old = db().execute("SELECT * FROM question_flags WHERE qid=?", (qid,)).fetchone()
    vals = {k: d.get(k, old[k] if old else 0) for k in ("bookmarked","difficult","guessed")}; note = str(d.get("personal_note", old["personal_note"] if old else ""))[:4000]
    if any(v not in (0,1,False,True) for v in vals.values()): return jsonify(error="Flags must be true or false"), 400
    db().execute("INSERT OR REPLACE INTO question_flags(qid,bookmarked,difficult,guessed,personal_note,updated) VALUES(?,?,?,?,?,?)", (qid,int(bool(vals["bookmarked"])),int(bool(vals["difficult"])),int(bool(vals["guessed"])),note,now())); db().commit()
    return jsonify(ok=True)

@app.post("/api/questions")
def q_create():
    d = request.get_json(silent=True)
    try: q = _question_payload(d)
    except ValueError as e: return jsonify(error=str(e)), 400
    norm = " ".join(q["text"].casefold().split())
    dup = db().execute("""SELECT id FROM questions WHERE subject=? AND qtype=? AND lower(trim(text))=lower(trim(?))
                          AND COALESCE(topic,'')=COALESCE(?,'') LIMIT 1""",
                       (q["subject"], q["qtype"], q["text"], q["topic"])).fetchone()
    if dup: return jsonify(error="Possible duplicate question", duplicate_id=dup["id"]), 409
    cur = db().execute("""INSERT INTO questions(subject,topic,year,qno,qtype,marks,text,options,answer,tolerance,difficulty,explanation,source,is_demo)
        VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,0)""",
        (q["subject"],q["topic"],q["year"],q["qno"],q["qtype"],q["marks"],q["text"],json.dumps(q["options"], ensure_ascii=False),q["answer"],q["tolerance"],q["difficulty"],q["explanation"],q["source"]))
    db().commit()
    return jsonify(ok=True, id=cur.lastrowid), 201

@app.put("/api/questions/<int:qid>")
def q_update(qid):
    if not db().execute("SELECT id FROM questions WHERE id=?", (qid,)).fetchone():
        return jsonify(error="Question not found"), 404
    try: q = _question_payload(request.get_json(silent=True))
    except ValueError as e: return jsonify(error=str(e)), 400
    dup = db().execute("""SELECT id FROM questions WHERE subject=? AND qtype=? AND lower(trim(text))=lower(trim(?))
                          AND COALESCE(topic,'')=COALESCE(?,'') AND id<>? LIMIT 1""",
                       (q["subject"],q["qtype"],q["text"],q["topic"],qid)).fetchone()
    if dup: return jsonify(error="Possible duplicate question", duplicate_id=dup["id"]), 409
    db().execute("""UPDATE questions SET subject=?,topic=?,year=?,qno=?,qtype=?,marks=?,text=?,options=?,answer=?,tolerance=?,difficulty=?,explanation=?,source=? WHERE id=?""",
        (q["subject"],q["topic"],q["year"],q["qno"],q["qtype"],q["marks"],q["text"],json.dumps(q["options"], ensure_ascii=False),q["answer"],q["tolerance"],q["difficulty"],q["explanation"],q["source"],qid))
    db().commit()
    return jsonify(ok=True, id=qid)

@app.delete("/api/questions/<int:qid>")
def q_delete(qid):
    row = db().execute("SELECT id,is_demo FROM questions WHERE id=?", (qid,)).fetchone()
    if not row: return jsonify(error="Question not found"), 404
    attempts = db().execute("SELECT COUNT(*) FROM attempts WHERE qid=?", (qid,)).fetchone()[0]
    if attempts and request.args.get("delete_history") != "1":
        return jsonify(error=f"This question has {attempts} attempt(s). Add ?delete_history=1 to delete the question and its history explicitly."), 409
    db().execute("DELETE FROM attempts WHERE qid=?", (qid,))
    db().execute("DELETE FROM revisions WHERE qid=?", (qid,))
    db().execute("DELETE FROM question_flags WHERE qid=?", (qid,))
    db().execute("DELETE FROM questions WHERE id=?", (qid,))
    db().commit()
    return jsonify(ok=True, deleted_attempts=attempts)

@app.post("/api/demo")
def demo():
    if db().execute("SELECT 1 FROM questions WHERE is_demo=1").fetchone(): return jsonify(imported=0)
    return jsonify(imported=add_questions([dict(d, is_demo=1, source="DEMO - not official") for d in DEMO]))
def do_submit(d):
    """Body: {session, answers:[{qid, selected, time_spent, error_type, notes}]}. Saves every attempt; never overwrites."""
    res = []; iv = json.loads(db().execute("SELECT v FROM settings WHERE k='intervals'").fetchone()[0])
    for a in d["answers"]:
        q = db().execute("SELECT * FROM questions WHERE id=?", (a["qid"],)).fetchone()
        att, cor, m = score(q, a.get("selected"))
        cur = db().execute("INSERT INTO attempts(qid,ts,selected,correct,attempted,marks,time_spent,error_type,notes,session) VALUES(?,?,?,?,?,?,?,?,?,?)",
            (q["id"], now(), a.get("selected", ""), cor, att, m, a.get("time_spent", 0), a.get("error_type"), a.get("notes"), d.get("session")))
        if att and not cor:  # queue / reset revision
            db().execute("INSERT OR REPLACE INTO revisions VALUES(?,0,?)", (q["id"], (dt.datetime.now() + dt.timedelta(days=iv[0])).isoformat(timespec="seconds")))
        else:
            r = db().execute("SELECT stage FROM revisions WHERE qid=?", (q["id"],)).fetchone()
            if r and cor:
                s = r["stage"] + 1
                if s >= len(iv): db().execute("DELETE FROM revisions WHERE qid=?", (q["id"],))
                else: db().execute("UPDATE revisions SET stage=?, due=? WHERE qid=?", (s, (dt.datetime.now() + dt.timedelta(days=iv[s])).isoformat(timespec="seconds"), q["id"]))
        res.append(dict(attempt_id=cur.lastrowid, qid=q["id"], attempted=att, correct=cor, marks=m, answer=q["answer"], explanation=q["explanation"]))
    db().commit()
    tot = sum(r["marks"] for r in res); mx = sum(db().execute("SELECT marks FROM questions WHERE id=?", (r["qid"],)).fetchone()[0] for r in res)
    return dict(results=res, total=round(tot, 3), max=mx)
@app.post("/api/submit")
def submit(): return jsonify(do_submit(request.json))
@app.get("/api/stats")
def stats():
    c = db(); today = dt.date.today().isoformat()
    t = c.execute("SELECT COUNT(*) n, COALESCE(SUM(correct),0) c, COALESCE(SUM(attempted),0) a, COALESCE(SUM(marks),0) m FROM attempts WHERE ts LIKE ?", (today + "%",)).fetchone()
    by = [dict(r) for r in c.execute("SELECT q.subject, q.topic, COUNT(*) att, SUM(a.correct) cor, ROUND(100.0*SUM(a.correct)/MAX(1,SUM(a.attempted)),1) acc FROM attempts a JOIN questions q ON q.id=a.qid WHERE a.attempted=1 GROUP BY q.subject,q.topic ORDER BY acc")]
    days = {r[0] for r in c.execute("SELECT DISTINCT substr(ts,1,10) FROM attempts")}
    streak, d = 0, dt.date.today()
    if d.isoformat() not in days: d -= dt.timedelta(days=1)
    while d.isoformat() in days: streak += 1; d -= dt.timedelta(days=1)
    nr = c.execute("SELECT COUNT(*) FROM revisions WHERE due<=?", (now(),)).fetchone()[0]
    uniq = c.execute("SELECT COUNT(DISTINCT qid) FROM attempts").fetchone()[0]
    first = c.execute("SELECT COALESCE(AVG(correct)*100,0) FROM attempts WHERE id IN (SELECT MIN(id) FROM attempts WHERE attempted=1 GROUP BY qid)").fetchone()[0]
    last = c.execute("SELECT COALESCE(AVG(correct)*100,0) FROM attempts WHERE id IN (SELECT MAX(id) FROM attempts WHERE attempted=1 GROUP BY qid)").fetchone()[0]
    demo = c.execute("SELECT COUNT(*) FROM questions WHERE is_demo=1").fetchone()[0]
    nq = c.execute("SELECT COUNT(*) FROM questions").fetchone()[0]
    sp = [dict(r) for r in c.execute("SELECT s.name subject,s.section,(SELECT COUNT(*) FROM questions q WHERE q.subject=s.name) total,(SELECT COUNT(DISTINCT a.qid) FROM attempts a JOIN questions q ON q.id=a.qid WHERE q.subject=s.name AND a.attempted=1) done FROM subjects s")]
    return jsonify(demo_questions=demo, total_questions=nq, subject_progress=sp, time_today=c.execute("SELECT COALESCE(SUM(time_spent),0) FROM attempts WHERE ts LIKE ?", (today + "%",)).fetchone()[0], today=dict(t), streak=streak, due_revisions=nr, unique_questions=uniq, first_attempt_acc=round(first, 1), latest_acc=round(last, 1),
                   weak_topics=by[:5], topics=by, targets=json.loads(c.execute("SELECT v FROM settings WHERE k='daily_target'").fetchone()[0]))
@app.get("/api/mocks/full/status")
def full_mock_status():
    """Report whether the local question bank can form the standard GATE CSE mock blueprint."""
    c = db()
    def count(section, marks):
        # Demo placeholders must never make the app claim it has a real GATE mock ready.
        return c.execute("SELECT COUNT(*) FROM questions q JOIN subjects s ON s.name=q.subject WHERE s.section=? AND q.marks=? AND q.is_demo=0", (section, marks)).fetchone()[0]
    required = {"ga_1_mark": ("General Aptitude", 1, 5), "ga_2_mark": ("General Aptitude", 2, 5),
                "math_1_mark": ("Engineering Mathematics", 1, 5), "math_2_mark": ("Engineering Mathematics", 2, 4),
                "core_1_mark": ("CSE Core", 1, 20), "core_2_mark": ("CSE Core", 2, 26)}
    pools = {k: {"available": count(section, marks), "required": need, "section": section, "marks_each": marks}
             for k, (section, marks, need) in required.items()}
    return jsonify(ready=all(v["available"] >= v["required"] for v in pools.values()),
                   total_available=sum(v["available"] for v in pools.values()), pools=pools,
                   blueprint={"questions": 65, "marks": 100, "duration_seconds": 10800,
                              "general_aptitude_questions": 10, "general_aptitude_marks": 15,
                              "engineering_mathematics_questions": 9, "engineering_mathematics_marks": 13,
                              "core_questions": 46, "core_marks": 72})

@app.post("/api/mocks/full")
def create_full_mock():
    """Create a 65-question / 100-mark / 180-minute GATE CSE mock from verified bank items."""
    c = db()
    specs = [("General Aptitude", 1, 5, "GA"), ("General Aptitude", 2, 5, "GA"),
             ("Engineering Mathematics", 1, 5, "MATH"), ("Engineering Mathematics", 2, 4, "MATH"),
             ("CSE Core", 1, 20, "CORE"), ("CSE Core", 2, 26, "CORE")]
    chosen = {"GA": [], "MATH": [], "CORE": []}
    missing = []
    for section, marks, needed, key in specs:
        rows = c.execute("SELECT q.id FROM questions q JOIN subjects s ON s.name=q.subject WHERE s.section=? AND q.marks=? AND q.is_demo=0 ORDER BY RANDOM() LIMIT ?",
                         (section, marks, needed)).fetchall()
        if len(rows) < needed:
            available = c.execute("SELECT COUNT(*) FROM questions q JOIN subjects s ON s.name=q.subject WHERE s.section=? AND q.marks=? AND q.is_demo=0", (section, marks)).fetchone()[0]
            missing.append({"section": section, "marks_each": marks, "required": needed, "available": available})
        chosen[key].extend(r[0] for r in rows)
    if missing:
        return jsonify(error="Not enough questions to build a full GATE mock. Import verified questions with the required sections and marks first.", missing=missing), 400
    # Follow the published GATE 2027 CS pattern: GA 15, Engineering Mathematics 13, CS subject 72.
    ids = chosen["GA"] + chosen["MATH"] + chosen["CORE"]
    cur = c.execute("INSERT INTO sessions(mode,title,qids,duration,created) VALUES(?,?,?,?,?)",
                    ("mock", "GATE CSE Full Mock", json.dumps(ids), 10800, now()))
    c.commit()
    return jsonify(id=cur.lastrowid, questions=len(ids), max_marks=100, duration_seconds=10800,
                   sections=[{"name":"General Aptitude","questions":10,"marks":15},
                             {"name":"Engineering Mathematics","questions":9,"marks":13},
                             {"name":"CSE Core","questions":46,"marks":72}]), 201

@app.post("/api/sessions")
def sess_new():
    d = request.json; mode = d.get("mode", "practice"); c = db(); p = []
    if mode == "revision":
        sql = "SELECT q.id FROM questions q JOIN revisions r ON r.qid=q.id WHERE r.due<=? ORDER BY r.due"; p = [now()]
    else:
        sql = "SELECT id FROM questions q WHERE 1=1"
        for f in ("subject", "topic", "year", "difficulty", "qtype"):
            if d.get(f): sql += f" AND q.{f}=?"; p.append(d[f])
        if d.get("status") == "unattempted": sql += " AND q.id NOT IN (SELECT qid FROM attempts)"
        if d.get("status") == "wrong": sql += " AND q.id IN (SELECT qid FROM attempts WHERE attempted=1 AND correct=0)"
        sql += " ORDER BY RANDOM()"
    sql += " LIMIT ?"; p.append(int(d.get("limit") or 10))
    ids = [r[0] for r in c.execute(sql, p)]
    if not ids: return jsonify(error="No matching questions"), 400
    dur = int(d.get("duration_min") or 0) * 60 if mode == "timed" else 0
    cur = c.execute("INSERT INTO sessions(mode,title,qids,duration,created) VALUES(?,?,?,?,?)", (mode, d.get("title") or mode.title(), json.dumps(ids), dur, now()))
    c.commit(); return jsonify(id=cur.lastrowid)
def session_elapsed(row):
    saved = int(row["elapsed"] or 0)
    if row["status"] == "active" and int(row["duration"] or 0) > 0:
        try:
            created = dt.datetime.fromisoformat(row["created"])
            saved = max(saved, int((dt.datetime.now() - created).total_seconds()))
        except (TypeError, ValueError):
            pass
    return saved

def sess_view(row, with_q=True):
    d = dict(row); d["elapsed"] = session_elapsed(row); [d.__setitem__(k, json.loads(d[k])) for k in ("qids", "answers", "flags", "times")]
    d.pop("result", None) if not with_q else None
    if with_q:
        qs = []
        for i in d["qids"]:
            q = dict(db().execute("SELECT * FROM questions WHERE id=?", (i,)).fetchone()); q["options"] = json.loads(q["options"]); q.pop("answer"); q.pop("explanation"); qs.append(q)
        d["questions"] = qs
    return d
@app.get("/api/sessions/active")
def sess_active():
    out = []
    for r in db().execute("SELECT * FROM sessions WHERE status='active' ORDER BY id DESC"):
        d = {k: r[k] for k in ("id", "mode", "title", "elapsed", "duration", "created")}
        d["n"] = len(json.loads(r["qids"])); d["answered"] = len([x for x in json.loads(r["answers"]).values() if x]); out.append(d)
    return jsonify(out)
@app.get("/api/sessions/history")
def sess_history():
    out = []
    for r in db().execute("SELECT * FROM sessions WHERE status='submitted' ORDER BY id DESC LIMIT 30"):
        res = json.loads(r["result"] or "{}")
        out.append(dict(id=r["id"], mode=r["mode"], title=r["title"], finished=r["finished"], duration=r["duration"], elapsed=r["elapsed"], n=len(json.loads(r["qids"])), total=res.get("total"), max=res.get("max")))
    return jsonify(out)
@app.get("/api/sessions/<int:sid>")
def sess_get(sid):
    r = db().execute("SELECT * FROM sessions WHERE id=?", (sid,)).fetchone()
    if not r: return jsonify(error="not found"), 404
    v = sess_view(r)
    if r["status"] == "submitted": v["result"] = json.loads(r["result"])
    return jsonify(v)
@app.put("/api/sessions/<int:sid>")
def sess_save(sid):
    d = request.json
    db().execute("UPDATE sessions SET answers=?,flags=?,times=?,idx=?,elapsed=? WHERE id=? AND status='active'",
        (json.dumps(d.get("answers", {})), json.dumps(d.get("flags", {})), json.dumps(d.get("times", {})), d.get("idx", 0), d.get("elapsed", 0), sid)); db().commit(); return jsonify(ok=True)
@app.post("/api/sessions/<int:sid>/submit")
def sess_submit(sid):
    c = db(); r = c.execute("SELECT * FROM sessions WHERE id=?", (sid,)).fetchone()
    if r["status"] == "submitted": return jsonify(json.loads(r["result"]))  # idempotent: no duplicate attempts
    d = request.json or {}
    ans, times = d.get("answers") or json.loads(r["answers"]), d.get("times") or json.loads(r["times"])
    res = do_submit(dict(session=f"S{sid}", answers=[dict(qid=i, selected=ans.get(str(i), ""), time_spent=times.get(str(i), 0)) for i in json.loads(r["qids"])]))
    elapsed = session_elapsed(r)
    c.execute("UPDATE sessions SET status='submitted',finished=?,result=?,answers=?,elapsed=? WHERE id=?", (now(), json.dumps(res), json.dumps(ans), elapsed, sid)); c.commit(); return jsonify(res)
@app.post("/api/sessions/<int:sid>/discard")
def sess_discard(sid):
    db().execute("DELETE FROM sessions WHERE id=? AND status='active'", (sid,)); db().commit(); return jsonify(ok=True)
@app.post("/api/annotate")
def annotate():
    """Body: {items:[{attempt_id, error_type, notes}]} - edits only classification fields, never answers/marks."""
    for i in request.json["items"]:
        db().execute("UPDATE attempts SET error_type=?, notes=? WHERE id=?", (i.get("error_type"), i.get("notes"), i["attempt_id"]))
    db().commit(); return jsonify(ok=True)
@app.get("/api/revision")
def rev_list():
    return jsonify([dict(r) for r in db().execute("SELECT r.qid,r.stage,r.due,q.subject,q.topic,CASE WHEN r.due<? THEN 1 ELSE 0 END overdue FROM revisions r JOIN questions q ON q.id=r.qid ORDER BY r.due", (now(),))])
@app.get("/api/analytics")
def analytics():
    c = db(); q = lambda sql, *p: [dict(r) for r in c.execute(sql, p)]
    topics = q("""SELECT q.subject,q.topic,COUNT(*) attempts,COUNT(DISTINCT a.qid) uniq,ROUND(100.0*SUM(a.correct)/MAX(1,SUM(a.attempted)),1) acc,
        ROUND(AVG(a.time_spent),1) avg_time FROM attempts a JOIN questions q ON q.id=a.qid WHERE a.attempted=1 GROUP BY q.subject,q.topic ORDER BY acc""")
    return jsonify(topics=topics,
      errors=q("SELECT COALESCE(error_type,'unclassified') type,COUNT(*) n FROM attempts WHERE attempted=1 AND correct=0 GROUP BY 1 ORDER BY n DESC"),
      repeated=q("SELECT a.qid,q.topic,COUNT(*) wrong FROM attempts a JOIN questions q ON q.id=a.qid WHERE a.attempted=1 AND a.correct=0 GROUP BY a.qid HAVING wrong>=2 ORDER BY wrong DESC"),
      improved=q("SELECT COUNT(*) n FROM (SELECT qid FROM attempts WHERE attempted=1 GROUP BY qid HAVING MIN(id)<>MAX(id) AND (SELECT correct FROM attempts x WHERE x.qid=attempts.qid AND x.attempted=1 ORDER BY id LIMIT 1)=0 AND (SELECT correct FROM attempts x WHERE x.qid=attempts.qid AND x.attempted=1 ORDER BY id DESC LIMIT 1)=1)")[0]["n"],
      daily=q("SELECT substr(ts,1,10) day,COUNT(*) n,SUM(correct) correct FROM attempts GROUP BY 1 ORDER BY 1 DESC LIMIT 14"),
      today_by_section=q("SELECT s.section,COUNT(*) n FROM attempts a JOIN questions q ON q.id=a.qid JOIN subjects s ON s.name=q.subject WHERE a.ts LIKE ? GROUP BY 1", dt.date.today().isoformat() + "%"))
def csv_resp(rows, name):
    from flask import Response
    o = io.StringIO()
    if rows: w = csv.DictWriter(o, fieldnames=list(rows[0])); w.writeheader(); w.writerows(rows)
    return Response(o.getvalue(), mimetype="text/csv", headers={"Content-Disposition": f"attachment; filename={name}"})
@app.get("/api/export/attempts.csv")
def exp_att(): return csv_resp([dict(r) for r in db().execute("SELECT a.*,q.subject,q.topic,q.year,q.qno FROM attempts a JOIN questions q ON q.id=a.qid ORDER BY a.id")], "attempts.csv")
@app.get("/api/export/questions.csv")
def exp_q(): return csv_resp([dict(r) for r in db().execute("SELECT * FROM questions")], "questions.csv")
@app.get("/api/backup")
def backup():
    c = db(); return jsonify({t: [dict(r) for r in c.execute(f"SELECT * FROM {t}")] for t in TABLES})
@app.get("/api/topics")
def topics():
    sql, p = "SELECT DISTINCT topic FROM questions WHERE topic IS NOT NULL AND topic<>''", []
    if request.args.get("subject"): sql += " AND subject=?"; p.append(request.args["subject"])
    return jsonify([r[0] for r in db().execute(sql + " ORDER BY topic", p)])
# Structured syllabus topic/subtopic catalog; question.topic remains free text for exact source fidelity.
@app.get("/api/syllabus/topics")
def syllabus_topics_list():
    sql = "SELECT * FROM syllabus_topics WHERE 1=1"; args=[]
    subject = request.args.get("subject", "").strip(); term=request.args.get("q", "").strip()
    if subject: sql += " AND subject=?"; args.append(subject)
    if term: sql += " AND (topic LIKE ? OR subtopic LIKE ?)"; args.extend(["%"+term+"%"]*2)
    return jsonify([dict(r) for r in db().execute(sql+" ORDER BY subject,topic,subtopic", args)])

@app.post("/api/syllabus/topics")
def syllabus_topic_create():
    d=request.get_json(silent=True) or {}; subject=str(d.get("subject","")).strip(); topic=str(d.get("topic","")).strip(); subtopic=str(d.get("subtopic","")).strip()
    if not subject or not topic: return jsonify(error="Subject and topic are required"),400
    if not db().execute("SELECT 1 FROM subjects WHERE name=?",(subject,)).fetchone(): return jsonify(error="Unknown subject"),400
    try:
        cur=db().execute("INSERT INTO syllabus_topics(subject,topic,subtopic,created) VALUES(?,?,?,?)",(subject,topic,subtopic,now()));db().commit()
    except sqlite3.IntegrityError: return jsonify(error="This topic/subtopic already exists for that subject"),409
    return jsonify(ok=True,id=cur.lastrowid),201

@app.put("/api/syllabus/topics/<int:tid>")
def syllabus_topic_update(tid):
    old=db().execute("SELECT * FROM syllabus_topics WHERE id=?",(tid,)).fetchone()
    if not old:return jsonify(error="Topic not found"),404
    d=request.get_json(silent=True) or {}; subject=str(d.get("subject",old["subject"])).strip();topic=str(d.get("topic",old["topic"])).strip();subtopic=str(d.get("subtopic",old["subtopic"])).strip()
    if not subject or not topic:return jsonify(error="Subject and topic are required"),400
    if not db().execute("SELECT 1 FROM subjects WHERE name=?",(subject,)).fetchone():return jsonify(error="Unknown subject"),400
    try: db().execute("UPDATE syllabus_topics SET subject=?,topic=?,subtopic=? WHERE id=?",(subject,topic,subtopic,tid));db().commit()
    except sqlite3.IntegrityError:return jsonify(error="This topic/subtopic already exists for that subject"),409
    return jsonify(ok=True)

@app.delete("/api/syllabus/topics/<int:tid>")
def syllabus_topic_delete(tid):
    cur=db().execute("DELETE FROM syllabus_topics WHERE id=?",(tid,));db().commit()
    if not cur.rowcount:return jsonify(error="Topic not found"),404
    return jsonify(ok=True)

# Optional OpenAI-compatible study assistant. Credentials are request-only and never saved in SQLite/backups.
@app.get("/api/ai/status")
def ai_status():
    configured = bool(os.environ.get("GATE_AI_API_KEY"))
    return jsonify(configured=configured, default_model=os.environ.get("GATE_AI_MODEL", "gpt-4o-mini"), base_url=os.environ.get("GATE_AI_BASE_URL", "https://api.openai.com/v1"), note="AI requires a compatible API key and internet. Core app features work without it.")

@app.post("/api/ai/ask")
def ai_ask():
    d = request.get_json(silent=True) or {}; prompt = str(d.get("prompt", "")).strip()
    if not prompt: return jsonify(error="Enter a question or task first"), 400
    if len(prompt) > 12000: return jsonify(error="Prompt is too long (maximum 12,000 characters)"), 400
    # Request-only overrides permit configuration without writing secrets to the database.
    key = str(d.get("api_key") or os.environ.get("GATE_AI_API_KEY", "")).strip()
    base = str(d.get("base_url") or os.environ.get("GATE_AI_BASE_URL", "https://api.openai.com/v1")).strip().rstrip("/")
    model = str(d.get("model") or os.environ.get("GATE_AI_MODEL", "gpt-4o-mini")).strip()
    if not key: return jsonify(error="AI is not configured. Enter an OpenAI-compatible API key for this request; it will not be saved."), 400
    if not base.startswith("https://") and not (base.startswith("http://127.0.0.1") or base.startswith("http://localhost")):
        return jsonify(error="AI base URL must use HTTPS (except localhost)"), 400
    payload = {"model": model, "messages": [{"role":"system","content":"You are a careful GATE CSE 2027 study assistant. Explain step by step, state assumptions, distinguish verified facts from uncertainty, and never claim generated questions are official GATE PYQs. If asked for notes, use clear headings and compact revision-friendly formatting."},{"role":"user","content":prompt}], "temperature":0.2}
    req = urllib.request.Request(base + "/chat/completions", data=json.dumps(payload).encode(), headers={"Content-Type":"application/json","Authorization":"Bearer " + key}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=45) as response: data = json.loads(response.read().decode("utf-8"))
        answer = data.get("choices", [{}])[0].get("message", {}).get("content", "")
        if not answer: return jsonify(error="Provider returned an empty answer"), 502
        return jsonify(answer=answer, model=model)
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "replace")[:500]
        return jsonify(error=f"AI provider returned HTTP {e.code}: {detail}"), 502
    except Exception as e:
        return jsonify(error=f"Could not reach AI provider: {str(e)[:250]}"), 502

# Personal study notebook: concepts, formulas, mistakes and revision notes.
@app.get("/api/notes")
def notes_list():
    sql = "SELECT * FROM study_notes WHERE 1=1"; args = []
    for field in ("subject", "topic", "kind"):
        value = request.args.get(field, "").strip()
        if value: sql += f" AND {field}=?"; args.append(value)
    if request.args.get("q"):
        term = "%" + request.args["q"].strip() + "%"
        sql += " AND (title LIKE ? OR body LIKE ? OR tags LIKE ? OR topic LIKE ?)"; args.extend([term] * 4)
    sql += " ORDER BY pinned DESC, updated DESC"
    limit = min(200, max(1, int(request.args.get("limit", 100))))
    rows = [dict(r) for r in db().execute(sql + " LIMIT ?", args + [limit])]
    return jsonify(rows)

@app.post("/api/notes")
def notes_create():
    d = request.get_json(silent=True) or {}; title = str(d.get("title", "")).strip(); body = str(d.get("body", "")).strip()
    kind = str(d.get("kind", "concept")).strip().lower()
    if not title or not body: return jsonify(error="Title and note body are required"), 400
    if kind not in ("concept", "formula", "mistake", "revision", "solution"): return jsonify(error="Unsupported note type"), 400
    subject = str(d.get("subject", "")).strip(); topic = str(d.get("topic", "")).strip()
    if subject and not db().execute("SELECT 1 FROM subjects WHERE name=?", (subject,)).fetchone(): return jsonify(error="Unknown subject"), 400
    qid = d.get("qid")
    if qid is not None and not db().execute("SELECT 1 FROM questions WHERE id=?", (qid,)).fetchone(): return jsonify(error="Question not found"), 400
    stamp = now(); cur = db().execute("INSERT INTO study_notes(title,subject,topic,kind,body,tags,qid,pinned,created,updated) VALUES(?,?,?,?,?,?,?,?,?,?)", (title,subject,topic,kind,body,str(d.get("tags", "")).strip(),qid,int(bool(d.get("pinned"))),stamp,stamp)); db().commit()
    return jsonify(ok=True, id=cur.lastrowid), 201

@app.put("/api/notes/<int:nid>")
def notes_update(nid):
    old = db().execute("SELECT * FROM study_notes WHERE id=?", (nid,)).fetchone()
    if not old: return jsonify(error="Note not found"), 404
    d = request.get_json(silent=True) or {}; vals = {k: d.get(k, old[k]) for k in ("title","subject","topic","kind","body","tags","qid","pinned")}
    vals["title"] = str(vals["title"] or "").strip(); vals["body"] = str(vals["body"] or "").strip(); vals["subject"] = str(vals["subject"] or "").strip(); vals["topic"] = str(vals["topic"] or "").strip(); vals["tags"] = str(vals["tags"] or "").strip(); vals["kind"] = str(vals["kind"] or "concept").lower()
    if not vals["title"] or not vals["body"]: return jsonify(error="Title and note body are required"), 400
    if vals["kind"] not in ("concept", "formula", "mistake", "revision", "solution"): return jsonify(error="Unsupported note type"), 400
    if vals["subject"] and not db().execute("SELECT 1 FROM subjects WHERE name=?", (vals["subject"],)).fetchone(): return jsonify(error="Unknown subject"), 400
    if vals["qid"] is not None and not db().execute("SELECT 1 FROM questions WHERE id=?", (vals["qid"],)).fetchone(): return jsonify(error="Question not found"), 400
    db().execute("UPDATE study_notes SET title=?,subject=?,topic=?,kind=?,body=?,tags=?,qid=?,pinned=?,updated=? WHERE id=?", (vals["title"],vals["subject"],vals["topic"],vals["kind"],vals["body"],vals["tags"],vals["qid"],int(bool(vals["pinned"])),now(),nid)); db().commit(); return jsonify(ok=True)

@app.delete("/api/notes/<int:nid>")
def notes_delete(nid):
    cur = db().execute("DELETE FROM study_notes WHERE id=?", (nid,)); db().commit()
    if not cur.rowcount: return jsonify(error="Note not found"), 404
    return jsonify(ok=True)

@app.get("/api/export/notes.json")
def notes_export():
    return jsonify([dict(r) for r in db().execute("SELECT * FROM study_notes ORDER BY updated DESC")])

@app.get("/api/settings")
def settings_get():
    g_ = lambda k: json.loads(db().execute("SELECT v FROM settings WHERE k=?", (k,)).fetchone()[0])
    return jsonify(intervals=g_("intervals"), daily_target=g_("daily_target"), sections=sorted({r[0] for r in db().execute("SELECT section FROM subjects")}))
@app.post("/api/settings")
def settings_set():
    d = request.json or {}; iv, tg = d.get("intervals"), d.get("daily_target")
    if not (isinstance(iv, list) and 1 <= len(iv) <= 12 and all(isinstance(x, int) and not isinstance(x, bool) and 1 <= x <= 365 for x in iv) and iv == sorted(iv)):
        return jsonify(error="Intervals: 1-12 whole days (1-365), ascending, e.g. 1,3,7,14"), 400
    if not (isinstance(tg, dict) and tg and all(isinstance(v, int) and not isinstance(v, bool) and 0 <= v <= 500 for v in tg.values())):
        return jsonify(error="Daily targets must be whole numbers 0-500"), 400
    c = db(); c.execute("INSERT OR REPLACE INTO settings VALUES('intervals',?)", (json.dumps(iv),)); c.execute("INSERT OR REPLACE INTO settings VALUES('daily_target',?)", (json.dumps(tg),)); c.commit()
    return jsonify(ok=True)  # existing revision due dates are not rewritten; new intervals apply to future reviews
TABLES = ("subjects", "questions", "attempts", "revisions", "settings", "sessions", "study_notes", "question_flags", "syllabus_topics") + tracker.TRACKER_TABLES
def validate_backup(d):
    """Return (errors, counts). Checks structure, column names, required fields and attempt->question links."""
    if not isinstance(d, dict): return ["Not a JSON object (is this a GATE backup file?)"], {}
    err, counts = [], {}
    for t in ("questions", "attempts"):
        if t not in d: err.append(f"Missing required table '{t}'")
    for t in TABLES:
        if t not in d: continue
        if not isinstance(d[t], list): err.append(f"'{t}' must be a list"); continue
        cols = {r[1] for r in db().execute(f"PRAGMA table_info({t})")}; counts[t] = len(d[t])
        for n, r in enumerate(d[t]):
            if not isinstance(r, dict) or not r: err.append(f"{t}[{n}] is not a record"); break
            bad = set(r) - cols
            if bad: err.append(f"{t}[{n}] unknown fields: {sorted(bad)}"); break
        if len(err) > 8: break
    if not err:
        for n, r in enumerate(d["questions"]):
            if not all(r.get(k) not in (None, "") for k in ("id", "subject", "qtype", "text", "answer")) or r["qtype"] not in ("MCQ", "MSQ", "NAT"):
                err.append(f"questions[{n}] missing id/subject/qtype/text/answer or bad qtype"); break
        ids = {r["id"] for r in d["questions"]}
        for n, r in enumerate(d["attempts"]):
            if r.get("qid") not in ids: err.append(f"attempts[{n}] refers to unknown question {r.get('qid')}"); break
    return err[:8], counts
@app.post("/api/restore/validate")
def restore_validate():
    err, counts = validate_backup(request.json)
    cur = {t: db().execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in TABLES}
    return jsonify(ok=not err, errors=err, backup=counts, current=cur)
@app.post("/api/restore")
def restore():
    body = request.json or {}
    if body.get("confirm") is not True: return jsonify(error="Restore needs confirm=true"), 400
    d = body.get("data"); err, _ = validate_backup(d)
    if err: return jsonify(error="Invalid backup", errors=err), 400
    c = db(); bdir = os.path.join(os.path.dirname(DB), "backups"); os.makedirs(bdir, exist_ok=True)
    safe = os.path.join(bdir, "pre-restore-" + now().replace(":", "-") + ".json")
    json.dump({t: [dict(r) for r in c.execute(f"SELECT * FROM {t}")] for t in TABLES}, open(safe, "w"))  # safety copy of current data
    try:
        for t in TABLES:
            if t not in d: continue  # tables absent from the backup are left untouched
            c.execute(f"DELETE FROM {t}")
            for r in d[t]: c.execute(f"INSERT INTO {t}({','.join(r)}) VALUES({','.join('?'*len(r))})", list(r.values()))
        c.commit()
    except Exception as e:
        c.rollback(); return jsonify(error=f"Restore failed, nothing changed: {e}"), 500
    return jsonify(ok=True, safety_copy=os.path.basename(safe))
tracker.register(app, db)
init()
if __name__ == "__main__": app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
