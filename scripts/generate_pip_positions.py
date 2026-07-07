#!/usr/bin/env python3
"""
Task 5 (optional): sample ~100 realistic positions from gnubg self-play for
pip-counting practice, classified into race/holding/prime/bearin.

Run with: gnubg -t -q -p scripts/generate_pip_positions.py

Design: rather than letting gnubg's own "both players gnubg-controlled"
session auto-play indefinitely (a `new session` with two AI players plays
games back-to-back forever with no natural stopping point in a batch
script), this script drives each turn explicitly from Python: roll random
dice, ask `hint()` for legal moves (fast 0-ply, plenty good enough for
generating realistic-looking positions -- these are just training
material, not the analyzed quiz), apply the top candidate via
`gnubg.command()`, and read the position back with `gnubg.board()`. Each
game is capped at a fixed number of turns so a bad interaction can never
hang the batch.
"""
import json
import os
import random

import gnubg

REPO_ROOT = os.getcwd()
DATA_DIR = os.path.join(REPO_ROOT, "data")
OUT_PATH = os.path.join(DATA_DIR, "pip-positions.json")

TARGET_COUNT = 100
MAX_GAMES = 40
MAX_PLIES_PER_GAME = 130
# Spread sampling toward mid/late game so race and bear-in phases (which
# only emerge once contact is resolved) are represented too, not just the
# early/mid-game contact positions that dominate the first ~30 plies.
SAMPLE_AT_PLIES = [16, 32, 48, 64, 80, 96, 112, 128]


def setup_gnubg():
    gnubg.command("new session")
    gnubg.command("set player 0 name Gray")
    gnubg.command("set player 1 name Hero")
    gnubg.command("set player 0 human")
    gnubg.command("set player 1 human")
    gnubg.command("set cube use off")
    gnubg.command("set evaluation chequerplay evaluation plies 0")


def gnubg_pair_to_app_board(pair, mover):
    """Inverse of generate_dataset.gnubg_tuple(): gnubg board() pair ->
    24-int app board (positive=Hero/white, negative=Gray, index i = point
    i+1, Hero's own absolute numbering)."""
    if mover == "Hero":
        gray_view, hero_view = pair
    else:
        hero_view, gray_view = pair
    board = [0] * 24
    for i in range(24):
        if hero_view[i] > 0:
            board[i] += hero_view[i]
    for i in range(24):
        if gray_view[i] > 0:
            board[23 - i] -= gray_view[i]
    return board


def classify(board):
    white_pts = [i for i in range(24) if board[i] > 0]
    gray_pts = [i for i in range(24) if board[i] < 0]
    if not white_pts or not gray_pts:
        return "bearin"

    # White moves from high index (24) toward low (1); gray moves from low
    # index toward high. Over a game they cross in the middle, so a clean
    # (no-contact) race means white's checkers have all ended up at lower
    # indices than gray's, or -- more rarely -- the reverse.
    no_contact = max(white_pts) < min(gray_pts) or max(gray_pts) < min(white_pts)
    if no_contact:
        return "race"

    def has_prime(sign):
        run = 0
        for i in range(24):
            owned = (board[i] >= 2) if sign > 0 else (board[i] <= -2)
            run = run + 1 if owned else 0
            if run >= 3:
                return True
        return False

    if has_prime(1) or has_prime(-1):
        return "prime"

    gray_anchor_in_white_home = any(board[i] <= -2 for i in range(0, 6))
    white_anchor_in_gray_home = any(board[i] >= 2 for i in range(18, 24))
    if gray_anchor_in_white_home or white_anchor_in_gray_home:
        return "holding"

    white_all_home = all(i < 6 for i in white_pts)
    gray_all_home = all(i >= 18 for i in gray_pts)
    if white_all_home or gray_all_home:
        return "bearin"

    return "holding"


def play_one_game(samples):
    gnubg.command("new session")
    gnubg.command(f"set board 4HPwATDgc/ABMA")
    mover = "Gray"
    collected_this_game = 0
    for ply in range(1, MAX_PLIES_PER_GAME + 1):
        gnubg.command(f"set turn {mover}")
        d1, d2 = random.randint(1, 6), random.randint(1, 6)
        gnubg.command(f"set dice {d1} {d2}")
        result = gnubg.hint(20)
        candidates = result.get("hint", []) if result else []
        applied = False
        for c in candidates[:5]:
            before = gnubg.board()
            gnubg.command(c["move"])
            after = gnubg.board()
            if after != before:
                applied = True
                break
        if not applied:
            # no legal move applied (e.g. dance on the bar, or a parser
            # quirk on every candidate) -- just pass the turn silently,
            # this is only sampling data, not a rules-correct replay
            pass

        pair = gnubg.board()
        game_over = sum(pair[0]) == 0 or sum(pair[1]) == 0
        if ply in SAMPLE_AT_PLIES or game_over:
            # after the move, `mover` is off roll; the pair's "on roll"
            # slot now belongs to the other player
            next_mover = "Hero" if mover == "Gray" else "Gray"
            board = gnubg_pair_to_app_board(pair, next_mover)
            phase = classify(board)
            samples.append({"board": board, "phase": phase})
            collected_this_game += 1

        if game_over:
            break

        mover = "Hero" if mover == "Gray" else "Gray"

    return collected_this_game


def random_race_position():
    """Synthesize a clean no-contact race position: split the board at a
    random cut point so every white checker is strictly ahead of every
    gray checker (some checkers may already be borne off on each side, to
    vary how far along the race is)."""
    cut = random.randint(8, 16)
    white_area = list(range(0, cut))
    gray_area = list(range(cut, 24))
    board = [0] * 24
    n_white = random.randint(8, 15)
    n_gray = random.randint(8, 15)
    for _ in range(n_white):
        board[random.choice(white_area)] += 1
    for _ in range(n_gray):
        board[random.choice(gray_area)] -= 1
    return board


def main():
    os.makedirs(DATA_DIR, exist_ok=True)
    setup_gnubg()
    samples = []

    # gnubg-driven self-play at 0-ply rarely resolves into a clean
    # no-contact race within a reasonable ply budget (contact tends to
    # persist for a very long time with unguided random dice), so `race`
    # would otherwise be entirely absent from the dataset even though
    # it's arguably the single most important phase for pip-count
    # practice. Seed a batch of synthetic race positions up front.
    n_synthetic_race = 15
    for _ in range(n_synthetic_race):
        board = random_race_position()
        samples.append({"board": board, "phase": classify(board)})
    print(f"[synthetic] added {n_synthetic_race} race positions", flush=True)

    games_played = 0
    while len(samples) < TARGET_COUNT and games_played < MAX_GAMES:
        games_played += 1
        n = play_one_game(samples)
        print(f"[game {games_played}] collected {n} samples "
              f"(total {len(samples)})", flush=True)

    samples = samples[:TARGET_COUNT]
    by_phase = {}
    for s in samples:
        by_phase[s["phase"]] = by_phase.get(s["phase"], 0) + 1
    print("phase distribution:", by_phase, flush=True)

    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump(samples, f, ensure_ascii=False, indent=2)
        f.write("\n")
    print(f"wrote {len(samples)} positions to {OUT_PATH}", flush=True)


if __name__ == "__main__":
    main()
