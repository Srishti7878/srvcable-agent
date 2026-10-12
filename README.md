# SRVCABLE research agent (Super Investing, Part B)

Takes an NSE ticker and a folder of scraped documents, and writes a one-page Markdown research brief (Snapshot, Bull, Bear, Open questions, Sources). Every claim is cited to a source ID.

- System prompt: [`system_prompt.md`](system_prompt.md)
- Code: [`agent.py`](agent.py)
- Submitted brief for SRVCABLE: [`output/srvcable_brief_run4.md`](output/srvcable_brief_run4.md)
- Test log (4 runs, what broke and what I changed): [`TEST_LOG.md`](TEST_LOG.md)

## How to run

```bash
pip install -r requirements.txt
export GEMINI_API_KEY=...        # free key from https://aistudio.google.com/apikey
# Windows cmd:        set GEMINI_API_KEY=...
# Windows PowerShell: $env:GEMINI_API_KEY="..."

# full pipeline (the submitted version, Run 4)
python agent.py --ticker SRVCABLE --pack research_pack --today 2026-09-23 --mode staged \
  --out output/srvcable_brief_run4.md --logdir logs_run4

# earlier designs, used for the test log
python agent.py --mode naive      # Run 1: one prompt, no rules
python agent.py --mode triage     # Run 2: triage + system prompt
python agent.py --mode staged     # Run 3: full pipeline (Run 4 = same code + 5 new prompt rules)
```

Output goes to `output/srvcable_brief_<mode>.md` unless `--out` is given. Intermediate stage outputs (triage, claims, arithmetic checks, issues, pre-verification draft) are saved to the log folder (`logs/` by default, `logs_run4/` for the submitted run) so you can see how the agent reached its conclusions.

`--today` is passed in because the assignment fixes "today" at 23 Sep 2026; the agent judges source freshness against it, not against the real clock.

## How it thinks

| Stage | What it does | Why |
|---|---|---|
| 1. Triage | For each document: same company? how authoritative? how fresh? include / downweight / exclude, with a reason | Scraped packs contain wrong-entity and stale pages. Decide this before writing anything |
| 2. Claim extraction | Atomic claims tagged `fact`, `management_claim` or `third_party`, plus every stated growth % | The draft is built from claims, not from loose reading of articles |
| 3. Arithmetic re-check | **Python** recomputes each stated growth rate | LLMs are unreliable at arithmetic. This one is deterministic. It caught that the company's own release states EBITDA +2.6% and PAT +5.9% where its figures give +2.9% and +6.5% |
| 4. Conflict and gap check | Cross-source conflicts, unverified management claims, missing data, stale data | Surfaces what goes in "Open questions" |
| 5. Draft | Writes the brief under `system_prompt.md` rules | Citations and tone rules live in one separate file |
| 6. Verify | A second call checks every claim against its cited source and fixes or removes failures | Draft and check are separate calls, so the writer doesn't mark its own homework |

## Model

`gemini-3.8-flash` through Google AI Studio's free tier, temperature 0, used for all 4 logged runs. The assignment says free tiers are enough, and this model is capable enough for cross-document reasoning while being fast enough for 6 calls per run. (The first default I tried, `gemini-2.5-flash`, was rejected by the API as no longer available to new users, so I switched.)

The code talks to the model through the OpenAI-compatible API, so it also works with Groq, OpenRouter and similar (`PROVIDER=openai-compatible`, plus `LLM_API_KEY`, `LLM_BASE_URL`, `MODEL`), or with Claude (`PROVIDER=anthropic`, `ANTHROPIC_API_KEY`, default `claude-sonnet-5-5`). Free-tier rate limits are handled with automatic retry and back-off. Model names change; if one is rejected, pick a current Flash model from AI Studio and set `MODEL`.

## Known limits

- **Prompt rules are requests, not guarantees.** In Run 4 the agent ignored one rule: it still cites a news article for a figure ("copper up ~14%") that no filing contains, even though that article was wrong on revenue. The next fix I would build is a code check that flags any claim whose only citations are news sources.
- No live data. It cannot fetch the current share price, so it reports it as missing.
- Entity matching and conflict judgement are done by the LLM and can be wrong. The verify pass reduces this but does not remove it.
- Some "why it matters" lines are generic commentary rather than facts from the sources.
- It cannot judge whether the GST appeal will succeed. It only flags the size and who is making the claim.
- The pack is only as good as what the scraper returned (the pack has 7 documents, not 8).

## Hand edits to the submitted brief

None. `output/srvcable_brief_run4.md` is exactly what the agent generated (the stage progress lines and the "Saved to..." line printed in the terminal are not part of the brief).
