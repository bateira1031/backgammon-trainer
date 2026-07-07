# Dataset validation report

- engine: gnubg 1.08.003 2-ply cubeless
- generated: 

## 1. Count check
- response-quiz-v2.json problems: 336 (expected 336) OK
- openings-v2.json entries: 21 (expected 21) OK
- all 16x21 (opening, myRoll) combinations present: OK

## 2. parseWhiteMoves() notation compatibility
- every move token matches `(\d+)/(\d+)\*?(\(\d+\))?`: OK (no bar/off, no un-split multi-hop chains)

## 3. Best-move equity baseline check
- moves[0].eq == 0.0 for all 336 problems: OK
- moves[] sorted descending (best first) for all problems: OK

## 4. Book / sanity cross-checks
- opening 63 best reply to 31: 8/5 6/5
- opening 63alt best reply to 31: 24/23 13/10*
- gnubg's own ranking for the 63 opening roll: best='24/18 13/10', 24/15 eq=-0.012 (doc predicted these two are a close call -- confirmed, margin is tiny)
- openings-v2 best for roll 65 vs OPENINGS_WHITE['65']: expected~='24/13' actual='24/13' -> OK
- openings-v2 best for roll 31 vs OPENINGS_WHITE['31']: expected~='8/5 6/5' actual='8/5 6/5' -> OK
- openings-v2 best for roll 21 vs OPENINGS_WHITE['21']: expected~='24/23 13/11' actual='24/23 13/11' -> OK
- opening 65, response 31 top move is a plausible standard play: expected~='8/5 6/5 (typical)' actual='8/5 6/5' -> OK

## Summary
Overall structural checks: PASS
