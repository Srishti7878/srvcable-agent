# Test log

Model for all runs: `gemini-3.8-flash` (temperature 0). Each run was checked against the same list of traps planted in the research pack.

| # | Trap | Right behaviour |
|---|---|---|
| T1 | Revenue: Business Daily says ₹1,428 cr (+35%); company release says ₹1,248 cr (+18%) | Use ₹1,248 cr, list conflict in Open questions |
| T2 | Nagpur City Times is about "Sarvottam **Cable Network**", a different local operator | Excluded, with reason |
| T3 | Market Watch (Mar 2024): pledge 35%. NSE filing (Jun 2026): 4.1% | Do not call 35% current; show the falling trend |
| T4 | GST demand ₹46.3 cr, company says "no material impact" | Attribute to management, size it against PAT (₹82 cr) |
| T5 | Receivable days 78 → 96 (only in the call) | In the bear case |
| T6 | Copper pass-through "over the next two quarters" | Presented as management's expectation, not fact |
| T7 | Stated PAT +5.9% / EBITDA +2.6% vs recomputed +6.5% / +2.9% | Recomputed values reported, mismatch flagged |
| T8 | Share price ₹1,012, from a 9 Aug article (price "on Friday") | Not presented as current; date not invented |
| T9 | Every number cited, no outside facts, no buy/sell advice, disclaimer | |
| T10 | A source caught being wrong (Business Daily revenue) is still cited for another figure (copper +14%) | Attribute it or leave it out; list as downweighted |
| T11 | Length | About one page |

## Scoreboard

✅ pass, ⚠️ partial, ❌ fail

| | T1 | T2 | T3 | T4 | T5 | T6 | T7 | T8 | T9 | T10 | T11 |
|---|---|---|---|---|---|---|---|---|---|---|---|
| Run 1 naive | ⚠️ | ✅ | ⚠️ | ⚠️ | ✅ | ❌ | ❌ | ❌ | ⚠️ | ❌ | ❌ |
| Run 2 triage + prompt | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ⚠️ | ⚠️ | ⚠️ | ❌ | ✅ |
| Run 3 staged | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ⚠️ | ⚠️ | ❌ | ✅ |
| Run 4 staged + 5 rules | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ⚠️ | ❌ | ⚠️ |

---

## Run 1: `--mode naive` (single prompt, no rules)
- **Command:** `python agent.py --mode naive`
- **What went wrong:** Handled the obvious traps (used the company's ₹1,248 cr over the news ₹1,428 cr, excluded the Nagpur "Cable Network" article) but failed the subtler ones. Labelled the ₹1,012 price "Current Share Price" although it was weeks old. Repeated the press release's wrong growth rates (PAT +5.9%, EBITDA +2.6%; actual +6.5%, +2.9%). Stated copper pass-through as a contractual fact, not a management expectation. Left out the company's side of the GST demand. Added facts not in any source ("audited", "70% funded/completed", a "120 days" provisioning threshold). The ₹1,428 cr conflict was noted inline but not in Open questions. No disclaimer. About 2 pages.
- **What I changed:** Added a triage stage (same company? authority? freshness?) and a system prompt with explicit rules: cite everything, no outside facts, attribute management claims, flag stale data, list conflicts under Open questions, one page, disclaimer.

## Run 2: `--mode triage` (triage + system prompt)
- **Command:** `python agent.py --mode triage`
- **What went wrong:** Fixed most of Run 1 (no stale price, copper pass-through attributed to management, GST company claim shown, pledge trend taken from the filing, one page, disclaimer). Still: (1) the Snapshot stated PAT +5.9% as fact while Open questions said the true figure is +6.5%, so the brief contradicted itself; the EBITDA mismatch (+2.9% vs +2.6%) was missed entirely; (2) the "nearly 14%" copper figure rests only on the news article that had the wrong revenue, unflagged; (3) the missing current share price was not listed as an open question; (4) "70% funded/spent" blurred "70% spent"; (5) some "why it matters" lines were generic commentary, not from sources.
- **What I changed:** Added claim extraction with every stated growth %, a Python recompute of those % (code, not the LLM), a conflict/gap check, and a separate verify pass that checks each claim against its cited source and fixes or deletes failures.

## Run 3: `--mode staged` (full pipeline)
- **Command:** `python agent.py --mode staged`
- **What went wrong:** The code check caught both growth mismatches (terminal showed `MISMATCH EBITDA YoY: stated 2.6% vs recomputed 2.9%` and the same for PAT), and the brief no longer contradicted itself; the missing current price became an open question. Still: (1) it invented the price date ("2026-08-08"; the article, published Sunday 9 Aug, only says "Friday"); (2) "~14% copper rise" still cited to the unreliable news article [S1] and S1 not marked downweighted; (3) the Snapshot dropped PAT growth instead of stating the recomputed ~6.5%; (4) the verify pass trimmed positives and caveats (net debt/equity 0.35x, CFO "no defaults so far"); (5) the label "Material GST tax dispute" asserted materiality that management denies.
- **What I changed:** Added five rules to `system_prompt.md` (see Run 4).

## Run 4: `--mode staged` + 5 new system-prompt rules
- **Command:** `python agent.py --mode staged --out output/srvcable_brief_run4.md --logdir logs_run4`
- **What I changed:** Added rules 11-15 to `system_prompt.md`: use code-verified growth figures everywhere; don't lean on a source caught being wrong; give dates only as stated in the source; balance check; neutral labels.
- **Result:** Fixed 4 of the 5 Run 3 problems. Price date now "as reported on 9 August 2026"; the Snapshot shows stated vs recomputed growth for EBITDA and PAT; net debt/equity and the CFO's "no defaults" caveat are back; GST is described by size (56.5% of Q1 profit) instead of labelled "material".
- **What still went wrong:** (1) Rule 12 was ignored: "copper up nearly 14%" is still cited [S1, S3] though only S1 says it, and S1 is not listed as downweighted. (2) Restoring the positives pushed out the data-centre growth point and the FY27 revenue guidance. (3) Some "why it matters" lines are opinion with no source support (e.g. 0.35x debt/equity called "conservative"). (4) About 1.2 pages with source URLs.
- **Takeaway:** A prompt rule is a request, not a guarantee. The fix I would build next is a code-side check that flags any claim whose only citations are news sources.
