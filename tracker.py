"""Milestone 4: countdown, study timer, subject progress, revision tasks, daily planner, dashboard, reports.

Design rules (see DATABASE_NOTES.md):
- Timer state is stored as timestamps in SQLite, so a server/app restart loses nothing: a running timer keeps counting
  by wall clock; a paused timer keeps its accumulated seconds. A timer running > STALE_HOURS is flagged `stale`
  so the user can correct it instead of silently logging a forgotten timer.
- NULL in progress fields means UNKNOWN / not recorded. 0 means a recorded zero. Nothing is inferred as "complete".
- Time attribution: a session counts on the day it started (sessions crossing midnight are not split).
- The planner is rule-based and always labelled so; no AI provider is wired in (Milestone 6).
"""
import json, re, datetime as dt
from flask import request, jsonify

STALE_HOURS = 12
KINDS = ("study", "solving", "mock")
TASK_STATUS = ("pending", "done", "skipped", "carried")
DAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
PROGRESS_FIELDS = ("lectures_total", "lectures_done", "pyq_total", "pyq_attempted", "pyq_correct", "pyq_incorrect",
                   "topics_total", "topics_done", "tests_attempted")
DEFAULT_EXAM = dict(date="2027-02-06", tz="Asia/Kolkata", status="provisional",
                    note="GATE 2027 is listed by IIT Madras for 6, 7, 13, 14, 20 and 21 Feb 2027 (all dates liable to change). "
                         "Your own paper date/session is not verified - set it from your admit card.")

TRACKER_SCHEMA = """
CREATE TABLE IF NOT EXISTS study_sessions(id INTEGER PRIMARY KEY, subject TEXT NOT NULL, topic TEXT DEFAULT '',
 kind TEXT NOT NULL DEFAULT 'study' CHECK(kind IN('study','solving','mock')), source TEXT NOT NULL DEFAULT 'timer' CHECK(source IN('timer','manual')),
 status TEXT NOT NULL DEFAULT 'running' CHECK(status IN('running','paused','stopped')), day TEXT NOT NULL, started TEXT, ended TEXT,
 accum INTEGER NOT NULL DEFAULT 0, resumed_at TEXT, task_id INTEGER, note TEXT, deleted INTEGER NOT NULL DEFAULT 0);
CREATE UNIQUE INDEX IF NOT EXISTS one_active_timer ON study_sessions(status) WHERE status IN('running','paused');
CREATE TABLE IF NOT EXISTS study_edits(id INTEGER PRIMARY KEY, session_id INTEGER, ts TEXT, action TEXT, before TEXT, after TEXT);
CREATE TABLE IF NOT EXISTS progress_items(id INTEGER PRIMARY KEY, subject TEXT NOT NULL, topic TEXT NOT NULL DEFAULT '',
 lectures_total INTEGER, lectures_done INTEGER, pyq_total INTEGER, pyq_attempted INTEGER, pyq_correct INTEGER, pyq_incorrect INTEGER,
 topics_total INTEGER, topics_done INTEGER, tests_attempted INTEGER, updated TEXT, UNIQUE(subject, topic));
CREATE TABLE IF NOT EXISTS topic_revisions(id INTEGER PRIMARY KEY, subject TEXT NOT NULL, topic TEXT DEFAULT '', due TEXT NOT NULL, done_ts TEXT, note TEXT, created TEXT);
CREATE TABLE IF NOT EXISTS plan_tasks(id INTEGER PRIMARY KEY, day TEXT NOT NULL, start_time TEXT, subject TEXT, topic TEXT DEFAULT '', title TEXT,
 planned_min INTEGER NOT NULL, status TEXT NOT NULL DEFAULT 'pending' CHECK(status IN('pending','done','skipped','carried')),
 origin TEXT NOT NULL DEFAULT 'manual', carried_from INTEGER, carried_to INTEGER, created TEXT, updated TEXT);
"""
TRACKER_TABLES = ("study_sessions", "study_edits", "progress_items", "topic_revisions", "plan_tasks")

CLOCK = None  # tests may set a callable returning a datetime


def _now():
    return CLOCK() if CLOCK else dt.datetime.now()


def iso(d): return d.isoformat(timespec="seconds")


def _today(): return _now().date()


def err(msg, code=400): return jsonify(error=msg), code


class Bad(Exception):
    pass


def ival(v, name, lo, hi, none_ok=False):
    if v is None or v == "":
        if none_ok: return None
        raise Bad(f"{name} is required")
    if isinstance(v, bool) or not isinstance(v, int):
        if isinstance(v, float) and v == int(v): v = int(v)
        elif isinstance(v, str) and re.fullmatch(r"-?\d+", v.strip()): v = int(v)
        else: raise Bad(f"{name} must be a whole number")
    if not lo <= v <= hi: raise Bad(f"{name} must be between {lo} and {hi}")
    return v


def pdate(s, name="date"):
    try: return dt.date.fromisoformat(str(s))
    except Exception: raise Bad(f"{name} must be YYYY-MM-DD")


def ptime(s, name="start"):
    if s in (None, ""): return None
    if not re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", str(s)): raise Bad(f"{name} must be HH:MM (24h)")
    return str(s)


def register(app, db):
    def q(sql, *p): return [dict(r) for r in db().execute(sql, p)]

    def get_setting(k, default=None):
        r = db().execute("SELECT v FROM settings WHERE k=?", (k,)).fetchone()
        return json.loads(r[0]) if r else default

    def set_setting(k, v):
        db().execute("INSERT OR REPLACE INTO settings VALUES(?,?)", (k, json.dumps(v))); db().commit()

    def subject_ok(name):
        if not name or not isinstance(name, str) or not name.strip(): raise Bad("subject is required")
        if not db().execute("SELECT 1 FROM subjects WHERE name=?", (name,)).fetchone(): raise Bad(f"unknown subject {name!r} (add it as a subject first)")
        return name

    def active_secs(r, now=None):
        s = r["accum"] or 0
        if r["status"] == "running" and r["resumed_at"]:
            s += max(0, int((( now or _now()) - dt.datetime.fromisoformat(r["resumed_at"])).total_seconds()))
        return s

    def view(r):
        d = dict(r); d["active_seconds"] = active_secs(r)
        d["stale"] = bool(r["status"] == "running" and d["active_seconds"] - (r["accum"] or 0) > STALE_HOURS * 3600)
        return d

    def edit_log(sid, action, before, after):
        db().execute("INSERT INTO study_edits(session_id,ts,action,before,after) VALUES(?,?,?,?,?)", (sid, iso(_now()), action, json.dumps(before), json.dumps(after)))

    def snap(r): return {k: r[k] for k in ("subject", "topic", "kind", "accum", "status", "deleted", "note", "task_id")}

    # ---------------------------------------------------------------- countdown
    def exam_view():
        e = get_setting("exam", None); src = "saved"
        if not e: e, src = dict(DEFAULT_EXAM), "default"
        try:
            from zoneinfo import ZoneInfo
            today = dt.datetime.now(ZoneInfo(e["tz"])).date() if not CLOCK else _today()
            tzok = True
        except Exception:
            today, tzok = _today(), False
        days = (dt.date.fromisoformat(e["date"]) - today).days
        return dict(e, days_remaining=days, passed=days < 0, source=src, tz_valid=tzok,
                    label="Provisional - verify against your admit card" if e["status"] != "confirmed" else "Confirmed by you")

    @app.get("/api/tracker/exam")
    def exam_get(): return jsonify(exam_view())

    @app.post("/api/tracker/exam")
    def exam_set():
        d = request.get_json(silent=True) or {}
        try:
            date = pdate(d.get("date")); tz = str(d.get("tz") or "Asia/Kolkata"); st = d.get("status", "provisional")
            if st not in ("provisional", "confirmed"): raise Bad("status must be provisional or confirmed")
            try:
                from zoneinfo import ZoneInfo; ZoneInfo(tz)
            except Exception: raise Bad(f"unknown timezone {tz!r} (e.g. Asia/Kolkata)")
        except Bad as e: return err(str(e))
        set_setting("exam", dict(date=date.isoformat(), tz=tz, status=st, note=str(d.get("note") or "")[:300]))
        return jsonify(exam_view())

    # ---------------------------------------------------------------- timer
    def current():
        return db().execute("SELECT * FROM study_sessions WHERE status IN('running','paused') AND deleted=0").fetchone()

    @app.get("/api/tracker/timer")
    def timer_get():
        r = current(); return jsonify(timer=view(r) if r else None)

    @app.post("/api/tracker/timer/start")
    def timer_start():
        d = request.get_json(silent=True) or {}
        try:
            subj = subject_ok(d.get("subject")); kind = d.get("kind", "study")
            if kind not in KINDS: raise Bad("kind must be study, solving or mock")
            tid = ival(d.get("task_id"), "task_id", 1, 10**9, True)
            if tid and not db().execute("SELECT 1 FROM plan_tasks WHERE id=?", (tid,)).fetchone(): raise Bad("unknown task")
        except Bad as e: return err(str(e))
        if current(): return err("A timer is already active. Stop it first.", 409)
        n = _now()
        try:
            cur = db().execute("INSERT INTO study_sessions(subject,topic,kind,source,status,day,started,accum,resumed_at,task_id,note) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                               (subj, str(d.get("topic") or "")[:120], kind, "timer", "running", n.date().isoformat(), iso(n), 0, iso(n), tid, d.get("note")))
            db().commit()
        except Exception: return err("A timer is already active. Stop it first.", 409)
        return jsonify(timer=view(db().execute("SELECT * FROM study_sessions WHERE id=?", (cur.lastrowid,)).fetchone()))

    def transition(frm, to, fn):
        r = current()
        if not r: return err("No active timer", 409)
        if r["status"] != frm: return err(f"Timer is {r['status']}, expected {frm}", 409)
        fn(r); db().commit()
        return jsonify(timer=view(db().execute("SELECT * FROM study_sessions WHERE id=?", (r["id"],)).fetchone()))

    @app.post("/api/tracker/timer/pause")
    def timer_pause():
        return transition("running", "paused", lambda r: db().execute("UPDATE study_sessions SET status='paused',accum=?,resumed_at=NULL WHERE id=?", (active_secs(r), r["id"])))

    @app.post("/api/tracker/timer/resume")
    def timer_resume():
        return transition("paused", "running", lambda r: db().execute("UPDATE study_sessions SET status='running',resumed_at=? WHERE id=?", (iso(_now()), r["id"])))

    @app.post("/api/tracker/timer/stop")
    def timer_stop():
        d = request.get_json(silent=True) or {}; r = current()
        if not r: return err("No active timer", 409)
        secs = active_secs(r)
        if d.get("active_minutes") is not None:  # correction (e.g. forgotten timer); logged in history
            try: m = ival(d["active_minutes"], "active_minutes", 0, 24 * 60)
            except Bad as e: return err(str(e))
            edit_log(r["id"], "stop_override", dict(computed_seconds=secs), dict(active_seconds=m * 60)); secs = m * 60
        db().execute("UPDATE study_sessions SET status='stopped',accum=?,resumed_at=NULL,ended=? WHERE id=?", (secs, iso(_now()), r["id"])); db().commit()
        return jsonify(session=view(db().execute("SELECT * FROM study_sessions WHERE id=?", (r["id"],)).fetchone()))

    # ---------------------------------------------------------------- time entries
    def day_minutes(day, exclude=None):
        tot = 0
        for r in db().execute("SELECT * FROM study_sessions WHERE day=? AND deleted=0", (day,)):
            if r["id"] != exclude: tot += active_secs(r)
        return tot / 60

    @app.get("/api/tracker/time")
    def time_list():
        a = request.args.get("from", "0000-01-01"); b = request.args.get("to", "9999-12-31")
        rows = db().execute("SELECT * FROM study_sessions WHERE day>=? AND day<=? AND deleted=? ORDER BY day DESC,id DESC LIMIT ?",
                            (a, b, 1 if request.args.get("deleted") == "1" else 0, min(int(request.args.get("limit") or 100), 500)))
        return jsonify([view(r) for r in rows])

    @app.post("/api/tracker/time/manual")
    def time_manual():
        d = request.get_json(silent=True) or {}
        try:
            subj = subject_ok(d.get("subject")); kind = d.get("kind", "study")
            if kind not in KINDS: raise Bad("kind must be study, solving or mock")
            day = pdate(d.get("day")); mins = ival(d.get("minutes"), "minutes", 1, 24 * 60); st = ptime(d.get("start"))
            if day > _today(): raise Bad("Cannot log time for a future day")
            if day_minutes(day.isoformat()) + mins > 24 * 60: raise Bad("That would exceed 24 hours logged for the day")
            started = ended = None
            if st:
                s = dt.datetime.combine(day, dt.time.fromisoformat(st)); e = s + dt.timedelta(minutes=mins)
                if e.date() != day: raise Bad("Entry must end before midnight")
                if e > _now(): raise Bad("Entry would end in the future")
                for r in db().execute("SELECT * FROM study_sessions WHERE deleted=0 AND started IS NOT NULL AND day=?", (day.isoformat(),)):
                    rs = dt.datetime.fromisoformat(r["started"]); re_ = dt.datetime.fromisoformat(r["ended"]) if r["ended"] else _now()
                    if r["source"] == "timer" and r["status"] != "stopped": re_ = _now()
                    if s < re_ and rs < e: raise Bad(f"Overlaps entry #{r['id']} ({r['subject']}) - would double-count time")
                started, ended = iso(s), iso(e)
            tid = ival(d.get("task_id"), "task_id", 1, 10**9, True)
        except Bad as e: return err(str(e))
        cur = db().execute("INSERT INTO study_sessions(subject,topic,kind,source,status,day,started,ended,accum,task_id,note) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                           (subj, str(d.get("topic") or "")[:120], kind, "manual", "stopped", day.isoformat(), started, ended, mins * 60, tid, d.get("note")))
        edit_log(cur.lastrowid, "create_manual", None, dict(minutes=mins, day=day.isoformat())); db().commit()
        return jsonify(session=view(db().execute("SELECT * FROM study_sessions WHERE id=?", (cur.lastrowid,)).fetchone()))

    @app.put("/api/tracker/time/<int:sid>")
    def time_edit(sid):
        r = db().execute("SELECT * FROM study_sessions WHERE id=?", (sid,)).fetchone()
        if not r: return err("not found", 404)
        if r["status"] != "stopped": return err("Stop the timer before editing it", 409)
        d = request.get_json(silent=True) or {}; before = snap(r); up = {}
        try:
            if "minutes" in d:
                m = ival(d["minutes"], "minutes", 0, 24 * 60)
                if day_minutes(r["day"], exclude=sid) + m > 24 * 60: raise Bad("That would exceed 24 hours logged for the day")
                up["accum"] = m * 60
            if "subject" in d: up["subject"] = subject_ok(d["subject"])
            if "kind" in d:
                if d["kind"] not in KINDS: raise Bad("kind must be study, solving or mock")
                up["kind"] = d["kind"]
            if "topic" in d: up["topic"] = str(d["topic"] or "")[:120]
            if "note" in d: up["note"] = d["note"]
        except Bad as e: return err(str(e))
        if not up: return err("Nothing to change")
        db().execute(f"UPDATE study_sessions SET {','.join(k + '=?' for k in up)} WHERE id=?", [*up.values(), sid])
        edit_log(sid, "edit", before, {k: up[k] for k in up}); db().commit()
        return jsonify(session=view(db().execute("SELECT * FROM study_sessions WHERE id=?", (sid,)).fetchone()))

    @app.delete("/api/tracker/time/<int:sid>")
    def time_delete(sid):
        r = db().execute("SELECT * FROM study_sessions WHERE id=?", (sid,)).fetchone()
        if not r: return err("not found", 404)
        if r["status"] != "stopped": return err("Stop the timer first (or discard via stop with 0 minutes)", 409)
        db().execute("UPDATE study_sessions SET deleted=1 WHERE id=?", (sid,)); edit_log(sid, "delete", snap(r), dict(deleted=1)); db().commit()
        return jsonify(ok=True)  # soft delete: history kept, can be restored

    @app.post("/api/tracker/time/<int:sid>/restore")
    def time_restore(sid):
        r = db().execute("SELECT * FROM study_sessions WHERE id=?", (sid,)).fetchone()
        if not r or not r["deleted"]: return err("not found or not deleted", 404)
        db().execute("UPDATE study_sessions SET deleted=0 WHERE id=?", (sid,)); edit_log(sid, "restore", dict(deleted=1), dict(deleted=0)); db().commit()
        return jsonify(ok=True)

    @app.get("/api/tracker/time/<int:sid>/history")
    def time_history(sid): return jsonify(q("SELECT * FROM study_edits WHERE session_id=? ORDER BY id", sid))

    # ---------------------------------------------------------------- progress
    def clean_progress(cur, new):
        m = {**cur, **new}
        for k in PROGRESS_FIELDS: m[k] = ival(m.get(k), k, 0, 1_000_000, True)
        for done, tot in (("lectures_done", "lectures_total"), ("pyq_attempted", "pyq_total"), ("topics_done", "topics_total")):
            if m[done] is not None and m[tot] is not None and m[done] > m[tot]: raise Bad(f"{done} ({m[done]}) cannot exceed {tot} ({m[tot]})")
        if m["pyq_correct"] is not None and m["pyq_incorrect"] is not None and m["pyq_attempted"] is not None \
                and m["pyq_correct"] + m["pyq_incorrect"] > m["pyq_attempted"]:
            raise Bad("pyq_correct + pyq_incorrect cannot exceed pyq_attempted")
        for k in ("pyq_correct", "pyq_incorrect"):
            if m[k] is not None and m["pyq_attempted"] is not None and m[k] > m["pyq_attempted"]: raise Bad(f"{k} cannot exceed pyq_attempted")
            if m[k] is not None and m["pyq_attempted"] is None: raise Bad(f"set pyq_attempted before {k}")
        return m

    def pending(a, b): return None if a is None or b is None else b - a

    @app.get("/api/tracker/progress")
    def progress_list():
        out = []
        rows = {(r["subject"], r["topic"]): r for r in db().execute("SELECT * FROM progress_items")}
        keys = [(s["name"], "") for s in db().execute("SELECT name FROM subjects ORDER BY id")] + [k for k in rows if k[1] != "" or k[0] not in {s["name"] for s in db().execute("SELECT name FROM subjects")}]
        today = _today().isoformat()
        for sub, top in dict.fromkeys(keys):
            r = dict(rows.get((sub, top)) or {"id": None, "subject": sub, "topic": top, **{k: None for k in PROGRESS_FIELDS}, "updated": None})
            r["lectures_pending"] = pending(r["lectures_done"], r["lectures_total"])
            r["pyq_pending"] = pending(r["pyq_attempted"], r["pyq_total"])
            r["recorded"] = r["id"] is not None
            tcond, tp = ("AND topic=?", (top,)) if top else ("", ())
            rv = db().execute(f"SELECT COUNT(done_ts) done, SUM(done_ts IS NULL AND due=?) due_today, SUM(done_ts IS NULL AND due<?) overdue FROM topic_revisions WHERE subject=? {tcond}", (today, today, sub, *tp)).fetchone()
            r["revisions"] = dict(completed=rv[0] or 0, due_today=rv[1] or 0, overdue=rv[2] or 0)
            acond, ap = ("AND q.topic=?", (top,)) if top else ("", ())
            au = db().execute(f"SELECT COUNT(DISTINCT a.qid) uniq, COUNT(*) n, COALESCE(SUM(a.correct),0) cor FROM attempts a JOIN questions q ON q.id=a.qid WHERE a.attempted=1 AND q.subject=? {acond}", (sub, *ap)).fetchone()
            r["in_app"] = dict(unique_questions=au[0], attempts=au[1], correct=au[2], note="measured from practice in this app; separate from the manual PYQ counts")
            r["mock_sessions_in_app"] = None
            out.append(r)
        return jsonify(out)

    @app.put("/api/tracker/progress")
    def progress_put():
        d = request.get_json(silent=True) or {}
        try:
            sub = subject_ok(d.get("subject")); top = str(d.get("topic") or "").strip()[:120]
            row = db().execute("SELECT * FROM progress_items WHERE subject=? AND topic=?", (sub, top)).fetchone()
            cur = dict(row) if row else {k: None for k in PROGRESS_FIELDS}
            m = clean_progress(cur, {k: d[k] for k in PROGRESS_FIELDS if k in d})
        except Bad as e: return err(str(e))
        vals = [m[k] for k in PROGRESS_FIELDS]
        db().execute(f"INSERT INTO progress_items(subject,topic,{','.join(PROGRESS_FIELDS)},updated) VALUES(?,?,{','.join('?' * len(PROGRESS_FIELDS))},?) "
                     f"ON CONFLICT(subject,topic) DO UPDATE SET {','.join(k + '=excluded.' + k for k in PROGRESS_FIELDS)},updated=excluded.updated", (sub, top, *vals, iso(_now())))
        db().commit(); return jsonify(ok=True)

    @app.delete("/api/tracker/progress/<int:pid>")
    def progress_del(pid): db().execute("DELETE FROM progress_items WHERE id=?", (pid,)); db().commit(); return jsonify(ok=True)

    # ---------------------------------------------------------------- topic revisions
    @app.get("/api/tracker/revisions")
    def trev_list():
        today = _today().isoformat(); st = request.args.get("status")
        w = {"open": "done_ts IS NULL", "done": "done_ts IS NOT NULL", "due": "done_ts IS NULL AND due<=?", "overdue": "done_ts IS NULL AND due<?"}.get(st, "1=1")
        rows = q(f"SELECT * FROM topic_revisions WHERE {w} ORDER BY due,id", *( (today,) if st in ("due", "overdue") else ()))
        for r in rows: r["overdue"] = bool(r["done_ts"] is None and r["due"] < today)
        return jsonify(rows)

    @app.post("/api/tracker/revisions")
    def trev_add():
        d = request.get_json(silent=True) or {}
        try: sub = subject_ok(d.get("subject")); due = pdate(d.get("due"), "due")
        except Bad as e: return err(str(e))
        cur = db().execute("INSERT INTO topic_revisions(subject,topic,due,note,created) VALUES(?,?,?,?,?)", (sub, str(d.get("topic") or "")[:120], due.isoformat(), d.get("note"), iso(_now())))
        db().commit(); return jsonify(id=cur.lastrowid)

    @app.post("/api/tracker/revisions/<int:rid>/done")
    def trev_done(rid):
        r = db().execute("SELECT * FROM topic_revisions WHERE id=?", (rid,)).fetchone()
        if not r: return err("not found", 404)
        if r["done_ts"]: return err("Already completed", 409)
        d = request.get_json(silent=True) or {}; nxt = None
        db().execute("UPDATE topic_revisions SET done_ts=? WHERE id=?", (iso(_now()), rid))
        if d.get("next_in_days") not in (None, ""):
            try: n = ival(d["next_in_days"], "next_in_days", 1, 365)
            except Bad as e: db().rollback(); return err(str(e))
            nxt = db().execute("INSERT INTO topic_revisions(subject,topic,due,note,created) VALUES(?,?,?,?,?)", (r["subject"], r["topic"], (_today() + dt.timedelta(days=n)).isoformat(), r["note"], iso(_now()))).lastrowid
        db().commit(); return jsonify(ok=True, next_id=nxt)

    @app.delete("/api/tracker/revisions/<int:rid>")
    def trev_del(rid): db().execute("DELETE FROM topic_revisions WHERE id=? AND done_ts IS NULL", (rid,)); db().commit(); return jsonify(ok=True)

    # ---------------------------------------------------------------- planner
    def planner_cfg():
        return get_setting("planner_config", None)

    @app.get("/api/tracker/planner/config")
    def cfg_get(): return jsonify(config=planner_cfg(), configured=planner_cfg() is not None)

    @app.post("/api/tracker/planner/config")
    def cfg_set():
        d = request.get_json(silent=True) or {}
        try:
            av = d.get("available_hours") or {}
            if not isinstance(av, dict) or set(av) - set(DAYS) or not av: raise Bad("available_hours must be an object with keys mon..sun")
            out = {}
            for k in DAYS:
                v = av.get(k)
                if v is None or isinstance(v, bool) or not isinstance(v, (int, float)) or not 0 <= v <= 24: raise Bad(f"available_hours.{k} must be 0-24")
                out[k] = round(float(v), 2)
            dg, wg = d.get("daily_goal_hours"), d.get("weekly_goal_hours")
            for nm, v, hi in (("daily_goal_hours", dg, 24), ("weekly_goal_hours", wg, 168)):
                if v is not None and (isinstance(v, bool) or not isinstance(v, (int, float)) or not 0 <= v <= hi): raise Bad(f"{nm} must be 0-{hi} or null")
            if dg is not None and dg > max(out.values()): raise Bad("daily goal exceeds your largest daily availability")
        except Bad as e: return err(str(e))
        set_setting("planner_config", dict(available_hours=out, daily_goal_hours=dg, weekly_goal_hours=wg)); return jsonify(ok=True)

    def task_view(r, tasks=None):
        d = dict(r)
        secs = db().execute("SELECT * FROM study_sessions WHERE task_id=? AND deleted=0", (r["id"],)).fetchall()
        d["actual_min"] = round(sum(active_secs(x) for x in secs) / 60, 1)
        d["remaining_min"] = max(0, r["planned_min"] - d["actual_min"])
        return d

    def overlaps(rows):
        out = {}
        sl = [(r["id"], r["start_time"], r["planned_min"]) for r in rows if r["start_time"] and r["status"] != "carried"]
        mins = lambda t: int(t[:2]) * 60 + int(t[3:])
        for i, a, am in sl:
            for j, b, bm in sl:
                if i != j and mins(a) < mins(b) + bm and mins(b) < mins(a) + am: out.setdefault(i, []).append(j)
        return out

    @app.get("/api/tracker/planner/tasks")
    def tasks_list():
        day = request.args.get("date") or _today().isoformat()
        try: pdate(day)
        except Bad as e: return err(str(e))
        rows = db().execute("SELECT * FROM plan_tasks WHERE day=? ORDER BY COALESCE(start_time,'99:99'),id", (day,)).fetchall()
        ov = overlaps(rows); out = []
        for r in rows:
            t = task_view(r); t["overlaps_with"] = ov.get(r["id"], []); out.append(t)
        eff = lambda t: min(t["planned_min"], t["actual_min"]) if t["status"] == "carried" else t["planned_min"]
        return jsonify(date=day, tasks=out, planned_min=sum(eff(t) for t in out), actual_min=round(sum(t["actual_min"] for t in out), 1))

    def task_fields(d, cur=None):
        cur = cur or {}
        m = {**cur, **{k: d[k] for k in ("day", "start_time", "subject", "topic", "title", "planned_min", "status") if k in d}}
        if "date" in d: m["day"] = d["date"]
        m["day"] = pdate(m.get("day")).isoformat(); m["start_time"] = ptime(m.get("start_time"), "start_time")
        m["subject"] = subject_ok(m.get("subject")); m["planned_min"] = ival(m.get("planned_min"), "planned_min", 5, 720)
        m["topic"] = str(m.get("topic") or "")[:120]; m["title"] = str(m.get("title") or "")[:200]
        if m.get("status", "pending") not in TASK_STATUS: raise Bad("bad status")
        m["status"] = m.get("status") or "pending"
        return m

    @app.post("/api/tracker/planner/tasks")
    def task_add():
        try: m = task_fields(request.get_json(silent=True) or {})
        except Bad as e: return err(str(e))
        if m["status"] == "carried": return err("Use the carry-forward action to carry tasks")
        cur = db().execute("INSERT INTO plan_tasks(day,start_time,subject,topic,title,planned_min,status,origin,created,updated) VALUES(?,?,?,?,?,?,?,?,?,?)",
                           (m["day"], m["start_time"], m["subject"], m["topic"], m["title"], m["planned_min"], m["status"], "manual", iso(_now()), iso(_now())))
        db().commit(); return jsonify(id=cur.lastrowid)

    @app.put("/api/tracker/planner/tasks/<int:tid>")
    def task_edit(tid):
        r = db().execute("SELECT * FROM plan_tasks WHERE id=?", (tid,)).fetchone()
        if not r: return err("not found", 404)
        d = request.get_json(silent=True) or {}
        if r["status"] == "carried": return err("This task was carried forward; edit the new copy", 409)
        try:
            m = task_fields(d, dict(r))
            if m["status"] == "carried": raise Bad("Use the carry-forward action to carry tasks")
        except Bad as e: return err(str(e))
        db().execute("UPDATE plan_tasks SET day=?,start_time=?,subject=?,topic=?,title=?,planned_min=?,status=?,updated=? WHERE id=?",
                     (m["day"], m["start_time"], m["subject"], m["topic"], m["title"], m["planned_min"], m["status"], iso(_now()), tid)); db().commit()
        return jsonify(ok=True)

    @app.delete("/api/tracker/planner/tasks/<int:tid>")
    def task_del(tid):
        # time already logged against the task is kept (task link is cleared), so deleting a task never deletes study time
        db().execute("UPDATE study_sessions SET task_id=NULL WHERE task_id=?", (tid,)); db().execute("DELETE FROM plan_tasks WHERE id=?", (tid,)); db().commit(); return jsonify(ok=True)

    def carry(from_day, to_day):
        carried, skipped = [], []
        for r in db().execute("SELECT * FROM plan_tasks WHERE day=? AND status='pending' AND carried_to IS NULL ORDER BY id", (from_day,)).fetchall():
            t = task_view(r)
            if t["remaining_min"] <= 0:
                skipped.append(dict(id=r["id"], title=r["title"] or r["subject"], reason="planned time is already logged - mark it done or skipped yourself"))
                continue
            rem = max(5, int(round(t["remaining_min"])))
            nid = db().execute("INSERT INTO plan_tasks(day,start_time,subject,topic,title,planned_min,status,origin,carried_from,created,updated) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                               (to_day, None, r["subject"], r["topic"], r["title"], rem, "pending", "carried", r["id"], iso(_now()), iso(_now()))).lastrowid
            db().execute("UPDATE plan_tasks SET status='carried',carried_to=? WHERE id=?", (nid, r["id"]))
            carried.append(dict(from_id=r["id"], new_id=nid, planned_min=rem, logged_min=t["actual_min"]))
        db().commit(); return carried, skipped

    @app.post("/api/tracker/planner/carry")
    def carry_ep():
        d = request.get_json(silent=True) or {}
        try:
            fd = pdate(d.get("from_date"), "from_date"); td = pdate(d.get("to_date") or (fd + dt.timedelta(days=1)), "to_date")
            if td <= fd: raise Bad("to_date must be after from_date")
        except Bad as e: return err(str(e))
        c, s = carry(fd.isoformat(), td.isoformat()); return jsonify(carried=c, skipped=s)  # idempotent: already-carried tasks are not carried twice

    # ---- rule-based next-day plan (never AI) ----
    @app.post("/api/tracker/planner/generate")
    def generate():
        d = request.get_json(silent=True) or {}; cfg = planner_cfg()
        if not cfg: return err("Set your available hours per weekday first (Planner settings).", 400)
        try: tgt = pdate(d.get("date") or (_today() + dt.timedelta(days=1)))
        except Bad as e: return err(str(e))
        avail = int(cfg["available_hours"][DAYS[tgt.weekday()]] * 60)
        goal = int(cfg["daily_goal_hours"] * 60) if cfg.get("daily_goal_hours") else avail
        budget = min(avail, goal) - int(db().execute("SELECT COALESCE(SUM(planned_min),0) FROM plan_tasks WHERE day=? AND status<>'carried'", (tgt.isoformat(),)).fetchone()[0])
        items, notes, today = [], [], _today()
        def add(subject, topic, title, mins, reason, **kw): items.append(dict(subject=subject, topic=topic or "", title=title, planned_min=mins, reason=reason, **kw))
        # 1. unfinished tasks from the last 7 days (would be carried forward)
        for r in db().execute("SELECT * FROM plan_tasks WHERE day>=? AND day<? AND status='pending' AND carried_to IS NULL ORDER BY day,id", ((tgt - dt.timedelta(days=7)).isoformat(), tgt.isoformat())):
            t = task_view(r)
            if t["remaining_min"] > 0: add(r["subject"], r["topic"], r["title"] or "Unfinished task", max(5, int(round(t["remaining_min"]))), f"Unfinished from {r['day']} ({t['actual_min']:g} of {r['planned_min']} min logged)", carry_from=r["id"])
        # 2. revisions due
        for r in db().execute("SELECT * FROM topic_revisions WHERE done_ts IS NULL AND due<=? ORDER BY due,id", (tgt.isoformat(),)):
            add(r["subject"], r["topic"], f"Revise {r['topic'] or r['subject']}", 30, f"Revision {'overdue' if r['due'] < today.isoformat() else 'due'} ({r['due']})", revision_id=r["id"])
        # 3. weak topics from in-app practice (needs >=5 attempts, accuracy <60%)
        for r in db().execute("SELECT q.subject,q.topic,COUNT(*) n,100.0*SUM(a.correct)/COUNT(*) acc FROM attempts a JOIN questions q ON q.id=a.qid WHERE a.attempted=1 AND q.topic IS NOT NULL GROUP BY q.subject,q.topic HAVING n>=5 AND acc<60 ORDER BY acc"):
            add(r["subject"], r["topic"], f"Practice weak topic: {r['topic']}", 40, f"Accuracy {r['acc']:.0f}% over {r['n']} attempts in this app")
        # 4. pending lectures (only where both totals are recorded)
        rem = [(r["lectures_total"] - r["lectures_done"], r) for r in db().execute("SELECT * FROM progress_items WHERE lectures_total IS NOT NULL AND lectures_done IS NOT NULL")]
        for left, r in sorted(((l, r) for l, r in rem if l > 0), key=lambda x: -x[0] / max(1, x[1]["lectures_total"])):
            add(r["subject"], r["topic"], f"Lectures: {r['topic'] or r['subject']}", 60, f"{left} of {r['lectures_total']} lectures pending")
        if not items: notes.append("Nothing to plan from: no unfinished tasks, due revisions, weak topics (needs >=5 in-app attempts) or recorded lecture totals.")
        chosen, left_b = [], budget
        for it in items:
            if len(chosen) >= 12: break
            if left_b < 15: break
            m = min(it["planned_min"], left_b)
            if m < 15 and "carry_from" not in it: continue
            it["planned_min"] = m; left_b -= m; chosen.append(it)
        dropped = len(items) - len(chosen)
        if dropped > 0: notes.append(f"{dropped} candidate(s) did not fit the time budget.")
        if budget <= 0: notes.append("No free time budget for that day (availability/goal already fully planned).")
        return jsonify(generator="rule-based", ai_used=False, label="Rule-based plan - generated by fixed priority rules, NOT by AI. Review and edit before accepting.",
                       date=tgt.isoformat(), available_min=avail, goal_min=goal, budget_min=max(budget, 0), unallocated_min=max(left_b, 0), items=chosen, notes=notes,
                       priority_order=["unfinished tasks", "due/overdue revisions", "weak topics (<60% over >=5 attempts)", "pending lectures"])

    @app.post("/api/tracker/planner/accept")
    def accept():
        d = request.get_json(silent=True) or {}; ids = []
        try:
            day = pdate(d.get("date")); items = d.get("items")
            if not isinstance(items, list) or not items: raise Bad("items required")
            for it in items:
                m = task_fields(dict(it, day=day.isoformat(), status="pending"))
                cf = it.get("carry_from")
                if cf:
                    src = db().execute("SELECT * FROM plan_tasks WHERE id=?", (cf,)).fetchone()
                    if not src or src["status"] != "pending" or src["carried_to"]: raise Bad(f"task {cf} is not available to carry")
                m["_cf"] = cf; m["_rv"] = it.get("revision_id"); ids.append(m)
        except Bad as e: return err(str(e))
        out = []
        for m in ids:
            nid = db().execute("INSERT INTO plan_tasks(day,start_time,subject,topic,title,planned_min,status,origin,carried_from,created,updated) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                               (m["day"], m["start_time"], m["subject"], m["topic"], m["title"], m["planned_min"], "pending", "rule-based planner", m["_cf"], iso(_now()), iso(_now()))).lastrowid
            if m["_cf"]: db().execute("UPDATE plan_tasks SET status='carried',carried_to=? WHERE id=?", (nid, m["_cf"]))
            out.append(nid)
        db().commit(); return jsonify(created=out)

    # ---------------------------------------------------------------- dashboard & reports
    def sessions_between(a, b):
        return [r for r in db().execute("SELECT * FROM study_sessions WHERE deleted=0 AND day>=? AND day<=?", (a, b))]

    def tracking_since():
        r = db().execute("SELECT MIN(day) FROM study_sessions WHERE deleted=0").fetchone()[0]; return r

    def minutes_by(rows, key):
        out = {}
        for r in rows: out[r[key]] = round(out.get(r[key], 0) + active_secs(r) / 60, 1)
        return out

    @app.get("/api/tracker/dashboard")
    def dashboard():
        today = _today(); ts = tracking_since(); wk0 = today - dt.timedelta(days=today.weekday())
        tod = sessions_between(today.isoformat(), today.isoformat()); wk = sessions_between(wk0.isoformat(), today.isoformat())
        cfg = planner_cfg() or {}
        heat, pva = [], []
        rows90 = sessions_between((today - dt.timedelta(days=89)).isoformat(), today.isoformat()); per = minutes_by(rows90, "day")
        for i in range(89, -1, -1):
            d = (today - dt.timedelta(days=i)).isoformat()
            heat.append(dict(date=d, minutes=None if (ts is None or d < ts) else per.get(d, 0)))  # null = unknown (before tracking began)
        for i in range(6, -1, -1):
            d = (today - dt.timedelta(days=i)).isoformat()
            tk = [task_view(r) for r in db().execute("SELECT * FROM plan_tasks WHERE day=?", (d,))]
            planned = sum(min(t["planned_min"], t["actual_min"]) if t["status"] == "carried" else t["planned_min"] for t in tk)
            pva.append(dict(date=d, planned_min=planned if tk else None, actual_min=None if (ts is None or d < ts) else per.get(d, 0), tasks=len(tk), done=sum(t["status"] == "done" for t in tk)))
        streak, d = 0, today
        if (per.get(d.isoformat()) or 0) <= 0: d -= dt.timedelta(days=1)
        while (per.get(d.isoformat()) or 0) > 0: streak += 1; d -= dt.timedelta(days=1)
        prog = [r for r in progress_list().json if r["topic"] == ""]
        lec_known = [r for r in prog if r["lectures_total"] is not None and r["lectures_done"] is not None]
        py_known = [r for r in prog if r["pyq_attempted"] is not None and r["pyq_correct"] is not None]
        corr, att = sum(r["pyq_correct"] for r in py_known), sum(r["pyq_attempted"] for r in py_known)
        iso_today = today.isoformat()
        st = q("SELECT q.subject,q.topic,COUNT(*) n,ROUND(100.0*SUM(a.correct)/COUNT(*),1) acc FROM attempts a JOIN questions q ON q.id=a.qid WHERE a.attempted=1 AND q.topic IS NOT NULL GROUP BY 1,2 HAVING n>=3 ORDER BY acc LIMIT 5")
        mocks = q("SELECT id,title,finished,result FROM sessions WHERE status='submitted' AND mode='timed' ORDER BY id DESC LIMIT 5")
        for m in mocks:
            res = json.loads(m.pop("result") or "{}"); m["total"], m["max"] = res.get("total"), res.get("max")
        app_secs = db().execute("SELECT COALESCE(SUM(elapsed),0) FROM sessions WHERE status='submitted' AND finished>=?", (iso_today,)).fetchone()[0]
        return jsonify(
            today=dict(minutes=round(sum(active_secs(r) for r in tod) / 60, 1), by_kind=minutes_by(tod, "kind"), by_subject=minutes_by(tod, "subject"), goal_hours=cfg.get("daily_goal_hours")),
            week=dict(start=wk0.isoformat(), minutes=round(sum(active_secs(r) for r in wk) / 60, 1), by_kind=minutes_by(wk, "kind"), by_subject=minutes_by(wk, "subject"), goal_hours=cfg.get("weekly_goal_hours")),
            tracking_since=ts, streak_days=streak, heatmap=heat, planned_vs_actual=pva,
            lectures=dict(subjects_with_data=len(lec_known), subjects_total=len(prog), done=sum(r["lectures_done"] for r in lec_known), total=sum(r["lectures_total"] for r in lec_known),
                          note="only subjects where both totals are recorded are counted"),
            pyq_manual=dict(subjects_with_data=len(py_known), attempted=att, correct=corr, accuracy=round(100 * corr / att, 1) if att else None),
            revisions=dict(topic_due_today=db().execute("SELECT COUNT(*) FROM topic_revisions WHERE done_ts IS NULL AND due=?", (iso_today,)).fetchone()[0],
                           topic_overdue=db().execute("SELECT COUNT(*) FROM topic_revisions WHERE done_ts IS NULL AND due<?", (iso_today,)).fetchone()[0],
                           topic_completed=db().execute("SELECT COUNT(*) FROM topic_revisions WHERE done_ts IS NOT NULL").fetchone()[0],
                           question_due=db().execute("SELECT COUNT(*) FROM revisions WHERE due<=?", (iso(_now()),)).fetchone()[0]),
            recent_tests=mocks, weak_topics=st, in_app_practice_seconds_today=app_secs,
            note="in_app_practice_seconds_today is measured from practice/test sessions and is NOT added to study-timer totals (avoids double counting).")

    @app.get("/api/tracker/report")
    def report():
        per = request.args.get("period", "daily")
        try: anchor = pdate(request.args.get("date") or _today().isoformat())
        except Bad as e: return err(str(e))
        if per == "daily": a = b = anchor
        elif per == "weekly": a = anchor - dt.timedelta(days=anchor.weekday()); b = a + dt.timedelta(days=6)
        elif per == "monthly": a = anchor.replace(day=1); b = (a.replace(day=28) + dt.timedelta(days=4)).replace(day=1) - dt.timedelta(days=1)
        else: return err("period must be daily, weekly or monthly")
        A, B = a.isoformat(), b.isoformat(); rows = sessions_between(A, B); ts = tracking_since()
        days = sorted({r["day"] for r in rows}); tk = [task_view(r) for r in db().execute("SELECT * FROM plan_tasks WHERE day>=? AND day<=?", (A, B))]
        at = db().execute("SELECT COUNT(*),COALESCE(SUM(correct),0) FROM attempts WHERE attempted=1 AND ts>=? AND ts<?", (A, (b + dt.timedelta(days=1)).isoformat())).fetchone()
        return jsonify(period=per, start=A, end=B, tracking_since=ts,
                       partly_unknown=bool(ts is None or ts > A), unknown_note="Days before the first logged study entry are unknown, not zero." if (ts is None or ts > A) else None,
                       total_minutes=round(sum(active_secs(r) for r in rows) / 60, 1), days_with_time_logged=len(days), by_kind=minutes_by(rows, "kind"), by_subject=minutes_by(rows, "subject"),
                       tasks=dict(count=len(tk), done=sum(t["status"] == "done" for t in tk), skipped=sum(t["status"] == "skipped" for t in tk), carried=sum(t["status"] == "carried" for t in tk),
                                  planned_min=sum(min(t["planned_min"], t["actual_min"]) if t["status"] == "carried" else t["planned_min"] for t in tk), actual_min=round(sum(t["actual_min"] for t in tk), 1)),
                       in_app_questions=dict(attempted=at[0], correct=at[1]),
                       topic_revisions_completed=db().execute("SELECT COUNT(*) FROM topic_revisions WHERE done_ts>=? AND done_ts<?", (A, (b + dt.timedelta(days=1)).isoformat())).fetchone()[0])
