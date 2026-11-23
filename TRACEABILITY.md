# Requirements and verification map

## Revision verification

| Change | Implementation | Evidence | Status |
|---|---|---|---|
| Host and local Ollama diagnostics | workflow.preflight | runs/preflight/20261123T111722Z-4e25c98c/connectivity.json and sites.json | Both site sockets denied, local model connection refused |
| Hebrew with names and technical vocabulary | validators.hebrew_prose, prompt_builder.SYSTEM | tests/test_recovery.py | Mixed Hebrew/Latin accepted; predominantly foreign text rejected |
| Recovery after invalid writing | ModelService.validated_writing, workflow.replay, evaluation.accepted_text | attempt-specific responses, prompts, contexts, retry log and metadata | Duplicate-request controls and accepted raw output verified with fixtures |
| Documented alternative selection | source_manager.alternative_plan, workflow.select_alternative | alternative selection response, original failed slot, restricted candidates and remaining capacity | One fixture filled a spare slot; full-cap and invalid alternatives fetched no extra pages |
| Brochures, comparison, baseline and claim audit | Existing live entry point, review and export paths | No live run available | Pending all six texts, eight sampled claims and human review |

The supplied Hebrew brief governs this map. The new notebook follows the seven Day 5 entry points; compatibility with the missing instructor notebook is unverified. Status of actual executions is recorded in VERIFICATION.md. Paths below a run refer to one immutable run directory. Tests use fixtures unless explicitly identified as live.

| Requirement | Course starting point and extension | Function or responsibility | Evidence in an actual run | Verification |
|---|---|---|---|---|
| Two same-industry companies, readable sites, names and URLs | Day 5 takes one pair | Settings, preflight, fetch_website_contents | config.json, preflight results | preflight; inspect suitability |
| Deterministic candidates; exact list, domain and redirect policy | scraper returns raw hrefs | fetch_website_links, normalize_url, candidate_urls | data/*_candidates.json, HTTP log | URL and redirect tests |
| JSON selection with type, url, reason; limit three; reject whole response | select_relevant_links only decoded JSON | select_relevant_links, validate_selection | prompts/, responses/, data/*_selection.json | atomic rejection/fetch-count tests |
| One collection per company; homepage first; status, UTC timestamp, 1–4 IDs | course concatenates truncated pages | fetch_page_and_all_relevant_links, collect_selected | data/*_sources.json | collection and replay tests |
| Reuse full text; preserve failures and explain missing evidence | new | source records, context decisions | data/, contexts/, log | empty/failed/deduplicated destination tests |
| 12,000 source characters; fair allocation; metadata and instructions untouched; combined budget | replaces two fixed truncations | build_context | contexts/*.json | long/short/shared budget tests |
| Four distinct Hebrew brochures, 200–300 split words incl. headings, audience structure, company claims and missing-information phrase | general brochure becomes two audiences per company | get_brochure_user_prompt, create_brochure | artifacts/brochures/, metadata | output tests, editorial review |
| Correct IDs, website URLs, exact context; semantic evidence | new | validate_brochure, audit review | metadata and claim_audit.csv | reference and evidence checks |
| One streamed main brochure, return/display/persist exact chunks, partial on interruption | stream_brochure displayed only | aggregate_stream, stream_brochure | responses/, accepted artifact, log | streaming and end-to-end tests |
| Four predefined shared dimensions plus sourced interpretation and gaps | new | comparison_prompt, validate_comparison | protocol.json, artifacts/comparison.md | table tests and review |
| One model and route, no implicit retries; eight calls | consolidates scattered client settings | Settings, ModelService.call | config.json, prompts/, log | mocked workflow call counts |
| Real durations, paths, tokens if reported; HTTP separate; original outputs retained | new | Run.log, ModelService.call | execution_log.jsonl, responses/ | reload and replay tests |
| First two material claims per brochure, exact quotes, four verdicts, explanations/deficiencies | new | prepare_review, verify_review | review forms and reviewed CSV | review validation and manual reading |
| Controlled baseline using same context, model, audience, language, length and grounding; four criteria fixed first | new | protocol, create_brochure, prepare_review | baseline, prompts, contexts, experiment evaluation | controlled-input test and paired review |
| Reproducibility, tests, no secrets, offline replay | new | replay, CLI, export | test results, run directory, ZIP | workflow/replay and archive inspection |
| Demonstration, flowchart, ≤4-page Hebrew report; workflow vs agent, prompt vs context, contributions | new | notebook, report, README | notebook, report/report.pdf | notebook cells, PDF inspection and page count |

## Course sources inspected

- [Week 1 Day 5](https://github.com/ed-donner/llm_engineering/blob/main/week1/day5.ipynb)
- [Week 1 scraper](https://github.com/ed-donner/llm_engineering/blob/main/week1/scraper.py)
- [Course dependencies](https://github.com/ed-donner/llm_engineering/blob/main/pyproject.toml)
- [README](https://github.com/ed-donner/llm_engineering) and [setup](https://github.com/ed-donner/llm_engineering/blob/main/setup/SETUP-new.md)

The course uses requests, BeautifulSoup, dotenv, the OpenAI Chat Completions client and IPython display. Its scraper fetches twice and caps each page at 2,000 characters. Link selection uses JSON mode and asks the model to resolve relative URLs. The brochure prompt calls the scraper and caps the entire prompt at 5,000 characters. Generation displays Markdown. Streaming reads the first choice directly. This extension preserves selection → collection → brochure → display and makes the intermediate data inspectable. The local course checkout had no usable HEAD. The official online files supplied the reference implementation.
