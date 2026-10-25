"""Answer-key parsing shared by app.py and check_answer_keys.py (no side effects on import)."""
import re, json
LETTERS = "ABCDEFGH"

def key_letters(raw):
    """Parse an MCQ/MSQ key or a submitted selection into a set of option letters.
    Accepts: B, b, ' B ', (B), B., B), 'Option B', A,C  A;C  'A C'  'A and C'  AC.
    Returns None when it cannot be read as letters (e.g. '2' or free text) - never guesses."""
    s = re.sub(r"(?i)\b(option|opt|and)\b", " ", str(raw if raw is not None else ""))
    out = set()
    for t in (t for t in re.split(r"[\s,;/&|]+", s) if t):
        t = t.strip("()[].:")
        if not t: continue
        if len(t) == 1 and t.upper() in LETTERS: out.add(t.upper())
        elif 1 < len(t) <= len(LETTERS) and all(ch in LETTERS for ch in t.upper()) and len(set(t.upper())) == len(t): out |= set(t.upper())
        else: return None
    return out or None

def key_warnings(r):
    """Import-time sanity warnings for one question row (dict). Never blocks the import."""
    w = []; qt = str(r.get("qtype", "")).upper(); ans = str(r.get("answer", "")).strip()
    opts = r.get("options") or []
    if isinstance(opts, str):  # same rules as app.add_questions: JSON list first, else a|b|c
        try: opts = json.loads(opts)
        except Exception: opts = [o for o in opts.split("|") if o]
    if qt in ("MCQ", "MSQ"):
        A = key_letters(ans)
        if A is None: w.append(f"answer key {ans!r} is not option letters (use B or A,C) - every answer will score wrong")
        else:
            if ans.upper() != ",".join(sorted(A)) and ans.upper().replace(" ", "") != ",".join(sorted(A)): w.append(f"answer key {ans!r} is non-standard; scored as {','.join(sorted(A))}")
            if qt == "MCQ" and len(A) != 1: w.append(f"MCQ key {ans!r} has {len(A)} letters")
            if opts and max(LETTERS.index(x) for x in A) >= len(opts): w.append(f"key {ans!r} points past the {len(opts)} options")
        if len(opts) != 4: w.append(f"{qt} has {len(opts)} options (GATE has 4); if options contain '|' (matrices, |A|) give options as a JSON list")
    elif qt == "NAT":
        try: float(ans)
        except ValueError: w.append(f"NAT answer {ans!r} is not a number")
    return w
