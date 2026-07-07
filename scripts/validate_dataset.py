#!/usr/bin/env python3
"""
Validate data/response-quiz-v2.json and data/openings-v2.json.

Run with: python3 scripts/validate_dataset.py

Checks:
  1. response-quiz-v2.json has exactly 16 openings x 21 rolls = 336 problems,
     openings-v2.json has 21 entries.
  2. Every move string is compatible with index.html's parseWhiteMoves()
     regex: each whitespace-separated token must match ^(\\d+)/(\\d+)\\*?(\\(\\d+\\))?$
     (i.e. no unsplit multi-hop chains, no bar/off).
  3. moves[0].eq == 0.0 for every problem (best move is always the reference).
  4. Cross-checks against a handful of well-known book plays.
"""
import json
import os
import re
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__))) \
    if "__file__" in globals() else os.getcwd()
DATA_DIR = os.path.join(REPO_ROOT, "data")
RESPONSE_QUIZ_PATH = os.path.join(DATA_DIR, "response-quiz-v2.json")
OPENINGS_PATH = os.path.join(DATA_DIR, "openings-v2.json")
INDEX_HTML = os.path.join(REPO_ROOT, "index.html")

OP_KEYS = ["65", "64", "63", "63alt", "62", "61", "54", "53", "52", "51",
           "43", "42", "41", "32", "31", "21"]
ROLL_KEYS = ["66", "65", "64", "63", "62", "61", "55", "54", "53", "52", "51",
             "44", "43", "42", "41", "33", "32", "31", "22", "21", "11"]

TOKEN_OK_RE = re.compile(r"^(\d+)/(\d+)\*?(\(\d+\))?$")

report_lines = []


def log(line=""):
    print(line)
    report_lines.append(line)


def load_openings_white():
    with open(INDEX_HTML, encoding="utf-8") as f:
        html = f.read()
    m = re.search(r"const OPENINGS_WHITE=\{(.*?)\};", html, re.S)
    body = m.group(1)
    return dict(re.findall(r"'([^']+)':'([^']+)'", body))


def check_move_string_compat(move_str):
    """Returns list of problems (empty if fully compatible)."""
    problems = []
    for tok in move_str.strip().split():
        if not TOKEN_OK_RE.match(tok):
            problems.append(tok)
    return problems


def main():
    ok = True

    with open(RESPONSE_QUIZ_PATH, encoding="utf-8") as f:
        quiz = json.load(f)
    with open(OPENINGS_PATH, encoding="utf-8") as f:
        openings = json.load(f)

    log("# Dataset validation report")
    log()
    log(f"- engine: {quiz.get('engine')}")
    log(f"- generated: {quiz.get('generated')}")
    log()

    # 1. Count check
    log("## 1. Count check")
    n_problems = len(quiz["problems"])
    n_openings = len(openings["openings"])
    expected_problems = len(OP_KEYS) * len(ROLL_KEYS)
    log(f"- response-quiz-v2.json problems: {n_problems} (expected {expected_problems}) "
        f"{'OK' if n_problems == expected_problems else 'FAIL'}")
    log(f"- openings-v2.json entries: {n_openings} (expected {len(ROLL_KEYS)}) "
        f"{'OK' if n_openings == len(ROLL_KEYS) else 'FAIL'}")
    if n_problems != expected_problems or n_openings != len(ROLL_KEYS):
        ok = False

    seen = set()
    for p in quiz["problems"]:
        seen.add((p["opening"], p["myRoll"]))
    missing = [(o, r) for o in OP_KEYS for r in ROLL_KEYS if (o, r) not in seen]
    if missing:
        ok = False
        log(f"- MISSING combinations: {missing}")
    else:
        log("- all 16x21 (opening, myRoll) combinations present: OK")
    log()

    # 2. Notation compatibility check
    log("## 2. parseWhiteMoves() notation compatibility")
    bad = []
    for p in quiz["problems"]:
        for mv in p["moves"]:
            bad_toks = check_move_string_compat(mv["m"])
            if bad_toks:
                bad.append((p["opening"], p["myRoll"], mv["m"], bad_toks))
    for o in openings["openings"]:
        for mv in [{"m": o["best"]}] + o["alternatives"]:
            bad_toks = check_move_string_compat(mv["m"])
            if bad_toks:
                bad.append(("openings-v2", o["roll"], mv["m"], bad_toks))
    if bad:
        ok = False
        log(f"- INCOMPATIBLE move strings found: {len(bad)}")
        for entry in bad[:20]:
            log(f"    {entry}")
    else:
        log("- every move token matches `(\\d+)/(\\d+)\\*?(\\(\\d+\\))?`: OK "
            "(no bar/off, no un-split multi-hop chains)")
    log()

    # 3. moves[0].eq == 0.0 check
    log("## 3. Best-move equity baseline check")
    nonzero_best = [(p["opening"], p["myRoll"], p["moves"][0]["eq"])
                    for p in quiz["problems"] if p["moves"][0]["eq"] != 0.0]
    if nonzero_best:
        ok = False
        log(f"- moves[0].eq != 0.0 for {len(nonzero_best)} problems: {nonzero_best[:10]}")
    else:
        log("- moves[0].eq == 0.0 for all 336 problems: OK")
    non_ascending = []
    for p in quiz["problems"]:
        eqs = [m["eq"] for m in p["moves"]]
        if eqs != sorted(eqs, reverse=True):
            non_ascending.append((p["opening"], p["myRoll"]))
    if non_ascending:
        ok = False
        log(f"- moves not sorted descending by eq for: {non_ascending[:10]}")
    else:
        log("- moves[] sorted descending (best first) for all problems: OK")
    log()

    # 4. Book cross-checks
    log("## 4. Book / sanity cross-checks")
    openings_white = load_openings_white()
    by_roll = {o["roll"]: o for o in openings["openings"]}

    def find_problem(opening, roll):
        for p in quiz["problems"]:
            if p["opening"] == opening and p["myRoll"] == roll:
                return p
        return None

    checks = []

    # openings-v2's own opening choice should match the app's existing
    # OPENINGS_WHITE table for rolls that map directly onto opening keys.
    for roll_key, op_key in [("65", "65"), ("31", "31"), ("21", "21")]:
        expected = openings_white[op_key]
        actual = by_roll[roll_key]["best"]
        match = actual == expected
        checks.append((f"openings-v2 best for roll {roll_key} vs OPENINGS_WHITE['{op_key}']",
                        expected, actual, match))

    # 63 vs 63alt should be close in equity (both are well-known book plays)
    p63 = find_problem("63", "31")
    p63alt = find_problem("63alt", "31")
    log(f"- opening 63 best reply to 31: {p63['moves'][0]['m'] if p63 else 'N/A'}")
    log(f"- opening 63alt best reply to 31: {p63alt['moves'][0]['m'] if p63alt else 'N/A'}")

    o63 = by_roll["63"]
    alt63_eq = next((a["eq"] for a in o63["alternatives"] if a["m"] == "24/15"), None)
    log(f"- gnubg's own ranking for the 63 opening roll: best={o63['best']!r}, "
        f"24/15 eq={alt63_eq} (doc predicted these two are a close call -- "
        f"{'confirmed, margin is tiny' if alt63_eq is not None and alt63_eq > -0.03 else 'see raw data'})")

    o64 = by_roll["64"]
    alt64_eq = next((a["eq"] for a in o64["alternatives"] if a["m"] == openings_white["64"]), None)
    if o64["best"] != openings_white["64"]:
        log(f"- NOTE: gnubg's top pick for roll 64 is {o64['best']!r}, which differs from "
            f"the app's existing OPENINGS_WHITE['64']={openings_white['64']!r} "
            f"(eq={alt64_eq}, a very small margin -- both are known reasonable plays, "
            "flagged for human review, not treated as an error)")

    # 65 -> 31 response should be a well known play (8/5 6/5 is standard barring
    # interference from gray's 13-point stack)
    p65_31 = find_problem("65", "31")
    checks.append(("opening 65, response 31 top move is a plausible standard play",
                    "8/5 6/5 (typical)", p65_31["moves"][0]["m"],
                    p65_31["moves"][0]["m"] in ("8/5 6/5", "13/10 6/5", "24/23 13/10")))

    for label, expected, actual, match in checks:
        log(f"- {label}: expected~={expected!r} actual={actual!r} -> "
            f"{'OK' if match else 'DIFFERS (see notes)'}")
        if not match:
            log("  (not necessarily a bug -- gnubg 2-ply may legitimately differ "
                  "from the app's hand-picked book move; flagged for human review)")
    log()

    log("## Summary")
    log(f"Overall structural checks: {'PASS' if ok else 'FAIL'}")

    return 0 if ok else 1


if __name__ == "__main__":
    code = main()
    out_path = os.path.join(REPO_ROOT, "docs", "dataset-validation.md")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write("\n".join(report_lines) + "\n")
    print(f"\nWrote {out_path}")
    sys.exit(code)
