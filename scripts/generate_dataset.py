#!/usr/bin/env python3
"""
Generate data/response-quiz-v2.json and data/openings-v2.json using gnubg's
embedded Python interpreter.

Run with:
    gnubg -t -q -p scripts/generate_dataset.py

Design notes (see docs/phase1-handover-v2.md for the spec):
- gnubg 1.08.003's `hint`/CLI `hint` command was found to ignore the
  configured chequerplay ply setting for move ranking (always evaluates at
  0-ply regardless of `set evaluation chequerplay evaluation plies N`).
  `gnubg.evaluate(board, cubeinfo, evalcontext)` DOES honor an explicit
  eval-context dict passed per call, and its cubeless-equity output was
  cross-checked against the CLI `eval` command's own 2-ply row (matched to
  4 decimal places). So this script uses `hint()` only to enumerate the
  legal move notations for a roll (move generation itself is not affected
  by the ranking bug), and independently scores each resulting position
  with an explicit 2-ply cubeless `evaluate()` call.
- Re-applying a candidate move string through `gnubg.command(move)` in a
  tight loop was found to occasionally fail ("Illegal or unparsable
  move") for a small subset of legal moves, for reasons that look like
  internal CLI state bleed between rapid successive move entries. To
  avoid this entirely, this script re-implements the app's own board
  simulation (parseWhiteMoves/applyWhiteMove/applyGrayMove from
  index.html) in pure Python and only ever asks gnubg to evaluate an
  already-known-good board tuple, never to apply a move via its text
  parser.
"""
import json
import os
import re
import sys

import gnubg

# gnubg's embedded Python does not set __file__, so this must be run with
# the repository root as the current working directory:
#   gnubg -t -q -p scripts/generate_dataset.py
REPO_ROOT = os.getcwd()
INDEX_HTML = os.path.join(REPO_ROOT, "index.html")
DATA_DIR = os.path.join(REPO_ROOT, "data")
RESPONSE_QUIZ_PATH = os.path.join(DATA_DIR, "response-quiz-v2.json")
OPENINGS_PATH = os.path.join(DATA_DIR, "openings-v2.json")

GNUBG_VERSION = "1.08.003"

EC2 = {"cubeful": 0, "plies": 2, "deterministic": 1, "noise": 0.0}
# cube centered, money play, jacoby on (gnubg default) -- validated against
# the CLI `eval` command's own 2-ply cubeless row for the standard opening
# position (matched to 4 decimal places).
CI = gnubg.cubeinfo(1, -1, 0, 0, (0, 0), 0, 0)

OP_KEYS = ["65", "64", "63", "63alt", "62", "61", "54", "53", "52", "51",
           "43", "42", "41", "32", "31", "21"]

# Non-double + double response/opening rolls, 21 total, ordered high-to-low
# to match the ordering already used by index.html's PRESET_PROBLEMS.
RESPONSE_ROLLS = [
    ("66", (6, 6)), ("65", (6, 5)), ("64", (6, 4)), ("63", (6, 3)),
    ("62", (6, 2)), ("61", (6, 1)), ("55", (5, 5)), ("54", (5, 4)),
    ("53", (5, 3)), ("52", (5, 2)), ("51", (5, 1)), ("44", (4, 4)),
    ("43", (4, 3)), ("42", (4, 2)), ("41", (4, 1)), ("33", (3, 3)),
    ("32", (3, 2)), ("31", (3, 1)), ("22", (2, 2)), ("21", (2, 1)),
    ("11", (1, 1)),
]


def load_openings_white():
    """Extract the OPENINGS_WHITE table straight from index.html so this
    script never drifts out of sync with the app's own opening book."""
    with open(INDEX_HTML, encoding="utf-8") as f:
        html = f.read()
    m = re.search(r"const OPENINGS_WHITE=\{(.*?)\};", html, re.S)
    if not m:
        raise RuntimeError("could not find OPENINGS_WHITE in index.html")
    body = m.group(1)
    entries = re.findall(r"'([^']+)':'([^']+)'", body)
    table = dict(entries)
    missing = [k for k in OP_KEYS if k not in table]
    if missing:
        raise RuntimeError(f"OPENINGS_WHITE missing keys: {missing}")
    return table


# ---------------------------------------------------------------------------
# Board simulation -- ports of index.html's parseWhiteMoves / applyWhiteMove /
# applyGrayMove / startBoard. Board = list[24] int, index i = point i+1,
# positive = white(Hero), negative = gray(opponent).
# ---------------------------------------------------------------------------

TOKEN_RE = re.compile(r"^(.*?)(\((\d+)\))?$")
CHAIN_HOP_RE = re.compile(r"(\d+)\/(\d+)\*?")


def normalize_move(move_str):
    """Convert a gnubg move string into the app-compatible form: split any
    multi-hop compact chain (e.g. "8/7*/4") into separate two-point hops
    (e.g. "8/7* 7/4"), since the app's parseWhiteMoves regex only captures
    the first "/pair" of a token and would silently drop the rest."""
    out_tokens = []
    for tok in move_str.strip().split():
        m = TOKEN_RE.match(tok)
        base, rep_suffix = m.group(1), (m.group(2) or "")
        points = base.split("/")
        if len(points) <= 2:
            out_tokens.append(tok)
            continue
        for i in range(len(points) - 1):
            left = points[i].rstrip("*")
            right = points[i + 1]
            out_tokens.append(f"{left}/{right}{rep_suffix}")
    return " ".join(out_tokens)


def parse_white_moves(move_str):
    """Python port of index.html's parseWhiteMoves()."""
    result = []
    for part in move_str.strip().split():
        rep_m = re.search(r"\((\d+)\)$", part)
        rep = int(rep_m.group(1)) if rep_m else 1
        base = re.sub(r"\(\d+\)$", "", part)
        m = re.search(r"(\d+)/(\d+)\*?", base)
        if not m:
            continue
        for _ in range(rep):
            result.append((int(m.group(1)), int(m.group(2))))
    return result


def apply_white_move(board, move_str):
    """Python port of index.html's applyWhiteMove(). Returns (board, hits)
    where hits is the number of gray blots cleared -- the app's 24-int
    board has no bar slot, so a hit checker simply vanishes from this
    array; callers that need an accurate gnubg position (which DOES have
    a bar) must add `hits` to gray's bar count themselves."""
    b = list(board)
    hits = 0
    for frm, to in parse_white_moves(move_str):
        fi, ti = frm - 1, to - 1
        if 0 <= fi < 24 and b[fi] > 0:
            b[fi] -= 1
        if 0 <= ti < 24:
            if b[ti] == -1:
                b[ti] = 0
                hits += 1
            b[ti] += 1
    return b, hits


def apply_gray_move(board, move_str):
    """Python port of index.html's applyGrayMove()."""
    b = list(board)
    for part in move_str.strip().split():
        rep_m = re.search(r"\((\d+)\)$", part)
        rep = int(rep_m.group(1)) if rep_m else 1
        base = re.sub(r"\(\d+\)$", "", part)
        m = re.search(r"(\d+)/(\d+)\*?", base)
        if not m:
            continue
        for _ in range(rep):
            fi, ti = 24 - int(m.group(1)), 24 - int(m.group(2))
            if 0 <= fi < 24 and b[fi] < 0:
                b[fi] += 1
            if 0 <= ti < 24:
                if b[ti] == 1:
                    b[ti] = 0
                b[ti] -= 1
    return b


def start_board():
    b = [0] * 24
    b[23] = 2
    b[12] = 5
    b[7] = 3
    b[5] = 5
    b[0] = -2
    b[11] = -5
    b[16] = -3
    b[18] = -5
    return b


def hero_own_view(board, bar=0):
    """25-tuple, Hero's own perspective (index i = Hero's point i+1)."""
    return tuple((board[i] if board[i] > 0 else 0) for i in range(24)) + (bar,)


def gray_own_view(board, bar=0):
    """25-tuple, gray's own perspective (index i = gray's point i+1)."""
    return tuple((-board[23 - i] if board[23 - i] < 0 else 0) for i in range(24)) + (bar,)


def gnubg_tuple(board, mover, gray_bar=0, hero_bar=0):
    """gnubg board() convention: (not-on-roll player's own view, on-roll
    player's own view). `gray_bar`/`hero_bar` account for checkers hit off
    the 24-int board (which has no bar slot of its own)."""
    if mover == "Hero":
        return (gray_own_view(board, gray_bar), hero_own_view(board, hero_bar))
    return (hero_own_view(board, hero_bar), gray_own_view(board, gray_bar))


def checker_counts_ok(board, gray_bar=0, hero_bar=0):
    white = sum(v for v in board if v > 0) + hero_bar
    gray = -sum(v for v in board if v < 0) + gray_bar
    return white == 15 and gray == 15


# ---------------------------------------------------------------------------
# gnubg session setup
# ---------------------------------------------------------------------------

def setup_gnubg():
    gnubg.command("new session")
    gnubg.command("set player 0 name Gray")
    gnubg.command("set player 1 name Hero")
    gnubg.command("set player 0 human")
    gnubg.command("set player 1 human")
    gnubg.command("set cube use off")


def rank_moves(board, mover_after_move_is, dice, opening_key=None, roll_key=None):
    """board: app-format board BEFORE the roll is played.
    mover_after_move_is: 'Hero' -- the player who is about to move (always
    Hero in this dataset; used for gnubg.hint()'s candidate generation).
    Returns a list of (normalized_move_str, equity_from_movers_perspective)
    sorted descending by equity."""
    pid = gnubg.positionid(gnubg_tuple(board, "Hero"))
    gnubg.command(f"set board {pid}")
    gnubg.command("set turn Hero")
    gnubg.command(f"set dice {dice[0]} {dice[1]}")
    candidates = gnubg.hint(2000)["hint"]

    scored = []
    for c in candidates:
        raw_move = c["move"]
        if "bar" in raw_move or "off" in raw_move:
            ctx = f"opening={opening_key} roll={roll_key}" if opening_key else "openings-v2"
            raise RuntimeError(f"bar/off move encountered ({ctx}): {raw_move!r}")
        norm_move = normalize_move(raw_move)
        board_after, hits = apply_white_move(board, norm_move)
        if not checker_counts_ok(board_after, gray_bar=hits):
            ctx = f"opening={opening_key} roll={roll_key}" if opening_key else "openings-v2"
            raise RuntimeError(
                f"checker count mismatch after applying {raw_move!r} -> {norm_move!r} ({ctx})"
            )
        gtuple = gnubg_tuple(board_after, "Gray", gray_bar=hits)
        ev = gnubg.evaluate(gtuple, CI, EC2)
        hero_eq = -ev[5]
        scored.append((norm_move, hero_eq))

    scored.sort(key=lambda x: -x[1])
    return scored


def load_checkpoint(path):
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    return None


def save_json(path, data):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")
    os.replace(tmp, path)


def generate_response_quiz(openings_white):
    existing = load_checkpoint(RESPONSE_QUIZ_PATH)
    done = {}
    if existing:
        for p in existing.get("problems", []):
            done[(p["opening"], p["myRoll"])] = p
        print(f"[resume] {len(done)} problems already present in {RESPONSE_QUIZ_PATH}", flush=True)

    problems = []
    total = len(OP_KEYS) * len(RESPONSE_ROLLS)
    n = 0
    for opening_key in OP_KEYS:
        board_after_opening = apply_gray_move(start_board(), openings_white[opening_key])
        if not checker_counts_ok(board_after_opening):
            raise RuntimeError(f"checker count mismatch after opening {opening_key}")
        for roll_key, dice in RESPONSE_ROLLS:
            n += 1
            key = (opening_key, roll_key)
            if key in done:
                problems.append(done[key])
                continue
            scored = rank_moves(board_after_opening, "Hero", dice,
                                 opening_key=opening_key, roll_key=roll_key)
            best_eq = scored[0][1]
            top4 = scored[:4]
            problem = {
                "opening": opening_key,
                "myRoll": roll_key,
                "moves": [{"m": mv, "eq": round(eq - best_eq, 3)} for mv, eq in top4],
            }
            problems.append(problem)
            print(f"[{n}/{total}] {opening_key} {roll_key} -> {top4[0][0]} "
                  f"({len(scored)} candidates)", flush=True)
            # checkpoint after every problem so a crash can resume cleanly
            save_json(RESPONSE_QUIZ_PATH, {
                "version": 2,
                "generated": "",
                "engine": f"gnubg {GNUBG_VERSION} 2-ply cubeless",
                "openingMoves": {k: openings_white[k] for k in OP_KEYS},
                "problems": problems,
            })

    return problems


def generate_openings_v2():
    existing = load_checkpoint(OPENINGS_PATH)
    done = {}
    if existing:
        for o in existing.get("openings", []):
            done[o["roll"]] = o
        print(f"[resume] {len(done)} openings already present in {OPENINGS_PATH}", flush=True)

    board = start_board()
    openings = []
    for roll_key, dice in RESPONSE_ROLLS:
        if roll_key in done:
            openings.append(done[roll_key])
            continue
        scored = rank_moves(board, "Hero", dice, opening_key=None, roll_key=roll_key)
        best_eq = scored[0][1]
        alternatives = [{"m": mv, "eq": round(eq - best_eq, 3)} for mv, eq in scored[1:4]]
        entry = {
            "roll": roll_key,
            "best": scored[0][0],
            "alternatives": alternatives,
        }
        openings.append(entry)
        print(f"[openings-v2] {roll_key} -> {scored[0][0]}", flush=True)
        save_json(OPENINGS_PATH, {"openings": openings})

    return openings


def main():
    os.makedirs(DATA_DIR, exist_ok=True)
    openings_white = load_openings_white()
    setup_gnubg()

    print("=== generating response-quiz-v2.json ===", flush=True)
    generate_response_quiz(openings_white)

    print("=== generating openings-v2.json ===", flush=True)
    generate_openings_v2()

    print("done.", flush=True)


if __name__ == "__main__":
    main()
