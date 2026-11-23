# Advanced Company Brochure Generator

Assignment 1 extends the Week 1 Day 5 project into a source-grounded Hebrew writing workflow. The program accepts two companies, builds one source collection for each, writes for customers and candidates, compares the companies and runs a controlled prompt experiment. The included snapshot contains implementation and verification materials. Live generation and the human evidence review remain pending. See [verification](VERIFICATION.md) and the [requirements map](TRACEABILITY.md).

## Install on Windows

For an existing Python 3.13 installation with the project dependencies, keep the configured `.env` and use the Windows CMD recovery instructions below. The following PowerShell commands are for a fresh Python 3.12 environment.

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item .env.example .env
notepad .env
```

Open Ollama on Windows, then run `ollama list`. Set MODEL to the exact tag of an installed **local** chat model in .env. The example tag is unverified on your machine. The loopback route uses a dummy SDK key. An existing course environment can run the project with the dependencies in requirements.txt.

The installation pins Requests 2.32.5, BeautifulSoup 4.14.2, OpenAI 1.109.1, python-dotenv 1.1.1, IPython 9.6.0, ipykernel 6.30.1, JupyterLab 4.4.9 and pytest 8.4.2. The available verification runtimes differed. [Executed versions and test results](VERIFICATION.md)

| Configuration | Meaning |
|---|---|
| COMPANY_A_NAME, COMPANY_A_URL, COMPANY_B_NAME, COMPANY_B_URL | Two company names and public HTTP(S) homepages in the same industry |
| MODEL, OPENAI_BASE_URL | One Chat Completions model and endpoint throughout the run. Example defaults are qwen3:8b and http://127.0.0.1:11434/v1 |
| OPENAI_API_KEY | Credential for the specified endpoint. Loaded into the client only |
| SOURCE_CHAR_BUDGET | Combined allowance for raw evidence characters per call, default 12000 |
| REQUEST_TIMEOUT | HTTP and model timeout in seconds, default 180 |
| PROVIDER_RETRIES | Extra attempts per sample after HTTP 500, 502, 503 or 504. Default 2, allowed 0–3, with waits of 1, 2 and 4 seconds |
| CONFIG_DIR, OUTPUT_DIR | Directory containing the input .env file, and parent directory for new runs. Defaults are the project directory and its runs subdirectory |

Process environment variables take precedence over the file. The client sends model, messages and stream with SDK retries disabled. Supported Gemini link selections also send a JSON schema in `response_format`. Each physical call has a numbered prompt, context and response or error file. The JSONL log records its start and outcome, and the reason and wait for each provider retry. Error records include the HTTP status, available provider diagnostics and selected response headers. A completed writing response that fails validation can trigger one additional sample with the identical request. An interrupted stream remains partial. An invalid link selection stops collection.

The local provider check lists models without generating text. Actual generation must establish Hebrew quality, length and citation behaviour. If local inference is unavailable, the same code supports an explicitly chosen hosted OpenAI-compatible endpoint. A hosted provider can bill for tokens and receives the prompts and company excerpts. To choose it, configure its base URL, model and API key. There is no automatic provider fallback. [Ollama compatibility documentation](https://docs.ollama.com/api/openai-compatibility)

## Run

```powershell
.\.venv\Scripts\python.exe -m pytest -ra --junitxml=verification/tests-local.xml
.\.venv\Scripts\python.exe workflow.py preflight
.\.venv\Scripts\jupyter-lab.exe assignment1_brochure_pro.ipynb
```

The diagnostic stores one homepage result per company under `runs/preflight`, including the status, text sample and available links. Check for substantive product and team/about pages suitable for both audiences. A navigation-only page, a blocked site or an authentication wall is insufficient. If a site fails in an otherwise connected environment, document the reason and set a different company in the same industry. A general network failure does not distinguish good websites from bad ones.

For the interactive assignment run, select the project kernel, set `MODE = "live"` in the first notebook code cell, and run all cells. The B candidates brochure updates in a single Jupyter display. The other five writing outputs are displayed upon validation. Save the notebook after the run. The default inspect mode shows diagnostic results and deterministic miniatures without a model. VS Code's Python and Jupyter extensions can open the same file.

As an alternative entry point for the same eight calls, use the CLI. Choose **one** live entry point per experiment.

```powershell
.\.venv\Scripts\python.exe workflow.py live
```

Each invocation creates a new run ID. The final line on success gives its directory. A failed run retains the original text available so far and its error records. Do not rename a run directory because its name is part of the provenance checks.

## Inspect and replay

### Resume a stopped run

Run these commands from the project directory in Windows CMD.

```cmd
set "RUN=runs\20261123T153228Z-22762162"
python workflow.py resume "%RUN%" --inspect
python workflow.py resume "%RUN%"
```

Inspection verifies the saved configuration, selections, source records, prompts, contexts and previous writing results offline. The live command takes a run lock and checks them again. It reuses verified collections and accepted exports. New attempts append to the same log and use the next attempt number for that operation. After a length rejection the new prompt includes the measured body count and targets 240–260 words on the same evidence. An explicit resume permits one fresh sample for previously rejected writing or an interrupted candidate stream, subject to bounded transient provider retries. The original stream stays partial. Permanent API errors and unresolved calls require inspection.

In this run Plausible and Fathom each have four saved sources. After the latest six writing stages, the saved comparison qualifies for local revalidation. Resume checks each identifier inside grouped citations against the exact evidence and the table cell's company scope. It logs the decision and exports the matching raw response verbatim. Five writing stages need fresh responses, including the streamed Fathom candidate brochure. After generation succeeds, `python workflow.py replay "%RUN%"` verifies the completed run offline.

### Test the revised Plausible link selection

Run these commands from the project directory in Windows CMD with the existing Gemini 3.5 Flash-Lite configuration.

```cmd
set "SOURCE_RUN=runs\20261123T152045Z-3b9329fa"
python workflow.py reselect-links "%SOURCE_RUN%" --inspect
set "PROVIDER_RETRIES=0"
python workflow.py reselect-links "%SOURCE_RUN%"
set "PROVIDER_RETRIES="
```

The preview shows the revised prompt and schema offline. The next command sends one new `A_links` request using the saved candidates. It prints the validated choices and a new run directory. The source run retains its original fenced response and rejection. Review each URL and reason in the new run's `data/A_selection.json` before continuing with `live --after-links` on that new directory.

New selections on Google's OpenAI-compatible endpoint use a JSON schema with Gemini 3.5 Flash-Lite and 3.1 Flash-Lite. Each selected page needs an exact candidate URL, a type and an audience-specific reason. Zero to three pages are valid. The local validator rejects Markdown fences, malformed JSON, duplicate URLs and forbidden or unlisted pages. Brochure and comparison calls continue to request Markdown. [Gemini 3.5 Flash-Lite capabilities](https://ai.google.dev/gemini-api/docs/models/gemini-3.5-flash-lite) · [OpenAI-compatible structured output](https://ai.google.dev/gemini-api/docs/openai#structured-output)

### Diagnose the earlier Gemini server errors

The two November 23 failures had identical requests to the configured Gemini Chat Completions endpoint. The 383-character system message requested a JSON object. The 1,853-character user message contained 42 candidate URLs. The request used ordinary text completion with `stream=false` and provider generation defaults. The strict local selection validator runs on the completed reply. Google documents this endpoint and message format. [Gemini OpenAI compatibility](https://ai.google.dev/gemini-api/docs/openai)

The recorded failures took 2.05 and 1.54 seconds with a 180-second timeout. In the pinned SDK, `InternalServerError` represents a 5xx response. The historical error files lack the precise status and message. A successful simple request establishes that the route and model worked for that request. It cannot establish what caused either recorded 5xx. [OpenAI SDK 1.109.1 status mapping](https://github.com/openai/openai-python/blob/v1.109.1/src/openai/_client.py#L369-L397)

From Windows CMD in the project directory, inspect the saved inputs and send at most **one** new model request.

```cmd
set "RUN=runs\20261123T140237Z-9011911f"
python workflow.py links-only "%RUN%" --inspect
set "PROVIDER_RETRIES=0"
python workflow.py links-only "%RUN%"
```

Inspection works offline. The diagnostic checks the run identity, protocol, configuration, saved prompt, candidate list and transport URLs. It performs no website fetches. In the supplied run the new attempt uses `prompts/A_links.attempt2.json`, with its own context and response or error record. The original attempt and homepage remain available. A validated response is saved in `data/A_selection.json`. Repeating the command at that checkpoint verifies the saved result and uses zero additional calls.

**After the isolated command prints `A_links validated`**, continue that same run in CMD. Clearing the environment override restores the configured retry limit.

```cmd
set "PROVIDER_RETRIES="
python workflow.py live --after-links "%RUN%"
python workflow.py replay "%RUN%"
```

Continuation reuses A's original homepage, retrieval timestamp, transport URLs and validated selection. It starts fetching A's selected pages, then follows the existing workflow. A later recorded failure can be resumed with the stage-level command above. A stale `.links-recovery.lock` can be removed after confirming that the recovery process has exited.

For a live notebook demonstration, the same continuation is available by setting `MODE = "live"` and `RUN_DIRECTORY = Path("runs/20261123T140237Z-9011911f")` after validating the isolated step. Choose one continuation entry point. If the CLI already completed generation, use notebook replay mode to display the saved results.

### Replay a completed run

Assuming the default output directory, the following picks the most recent generation attempt. Specify the successful run path explicitly if a later attempt failed.

```powershell
$run = (Get-ChildItem .\runs -Directory | Where-Object { Test-Path (Join-Path $_.FullName 'config.json') } | Sort-Object Name -Descending | Select-Object -First 1).FullName
.\.venv\Scripts\python.exe workflow.py replay "$run"
Get-ChildItem "$run\artifacts\brochures"
Get-Content -Encoding utf8 "$run\execution_log.jsonl"
```

Replay recomputes both selections from the saved raw responses, verifies the ordered source records, reconstructs each context and model request, and compares the original UTF-8 output bytes as decoded text with the exported content. It checks counts, citation scope, metadata and table structure. The notebook can display the paired results using `MODE = "replay"` and `RUN_DIRECTORY = Path(...)`. This needs a completed generation run. The packaged fixture tests exercise this path offline in temporary directories.

## Architecture

| Module | Responsibility |
|---|---|
| config, storage | Two companies, single provider configuration, unique run directory, atomic file writes, UTC event log |
| scraper, url_utils | One GET per page apart from explicit redirects. Parse with BeautifulSoup. Collect all home anchors before removing page chrome. Prefer main content. No recursive crawl |
| source_manager | Validate the complete JSON before selected-page requests. Reuse the homepage already retrieved. Assign A1–A4 or B1–B4 in saved order |
| context_manager | Allocate equal shares across unfinished sources and redistribute unused shares. Stable input order breaks remainder ties. Persist a reason and character count per source |
| prompt_builder | Construct text from arguments. Site text and URLs are untrusted data. A shared evidence policy applies to improved and baseline brochures |
| llm_service, workflow | Save full requests and contexts before calling. Accumulate text deltas. Require finish_reason=stop, log interruptions, validate, return and export accepted outputs |
| validators, evaluation | Check word count and citations, prepare audit evidence and the paired review, verify supplied evidence excerpts |
| package_project | Build a ZIP from explicitly selected project and run file types |

The normalized URL identity folds the host to lowercase, removes one leading www, normalizes default ports and trailing slashes, and drops fragments. Only the same hostname and port qualify. Other subdomains are excluded. HTTP and HTTPS remain distinct candidate URLs. The query string is retained because it may identify real content. Empty/homepage, privacy and terms/legal paths, userinfo, ambiguous encoded paths and non-web schemes are excluded. The first matching original destination preserves www and slash routing for the actual GET. Every redirect is checked before issuing another request. Identical final destinations cannot provide duplicate evidence.

Source records preserve the full extracted text. The allocator assigns prefixes only to successful nonempty sources. For a combined budget of 22 and lengths of 150000, 2 and 200, the grants are 10, 2 and 10. Headers, identifiers, URLs, serialized JSON escaping and prompt instructions lie outside the source-text count. Prefixes can omit important material near a page's end.

A failed or empty selected page retains its ID and consumes a slot. A failed/empty source or fewer than 1,200 usable characters triggers an evidence-gap decision. If an unused slot and unused homepage candidates remain, a single additional model selection can fill the gap. The reason, candidate subset, remaining capacity, response and validation are persisted. Rejected alternatives trigger zero additional fetches. When all slots are spent the system reports the gap. This heuristic measures availability and quantity. A reader must still assess topic coverage and cross-brochure consistency.

The Hebrew check requires at least two thirds of alphabetic word segments to contain Hebrew letters after citation removal. This admits company names and professional terminology inside Hebrew prose. The official 200–300 count still uses the unmodified body and Python split().

## Files

```text
assignment1_brochure_pro.ipynb       inspect / live / replay notebook
*.py, tests/                        implementation, export and deterministic tests
report/report.pdf, report.html      Hebrew report and editable text/layout source
verification/*.xml                  saved pytest results including initial integration errors
runs/preflight/<id>/                actual homepage diagnostics
README.md, TRACEABILITY.md, VERIFICATION.md
requirements.txt, .env.example, .gitignore
```

A successful generation run adds the following directory.

```text
runs/<id>/
  config.json, protocol.json, execution_log.jsonl
  data/                 candidates, transport URLs, selection and full source collections
  prompts/, contexts/   one exact request and context per model call
  responses/            original text, including interrupted or invalid output
  metadata/             run ID, word counts or dimensions, cited IDs
  artifacts/brochures/  A_customers, A_candidates, B_customers, B_candidates (.md)
  artifacts/            comparison.md, baseline.md and completed review exports
  review/               evidence.md, claim_audit.csv, paired_evidence.md, experiment.json
```

## Complete the evaluation and package a live result

The calls are two selections, four main brochures (one streamed), the comparison, and the baseline. The comparison dimensions and sampling method are written before any model call. The baseline repeats A customers using the same serialized context, model and stream setting. Differences in sampled prose can still arise from model variability.

1. Read each original brochure and its exact context in `review/evidence.md`. Take the first two material factual propositions in reading order, including uncited ones. Preserve source qualifications. In the CSV copy the original wording, cited ID, saved URL and exact supporting or contradicting excerpt. Use the verdict names in protocol.json. Explain partial support, missing evidence or a correction. For a genuinely absent claim slot, leave the claim blank and fill deficiency. Keep originals unchanged.
2. Inspect the paired outputs and shared context. Fill `review/experiment.json` with exact quotations from both brochures and a specific finding for each of faithfulness, relevance, coverage and clarity. Ties and mixed findings are valid. No independent human review was performed in this development session.
3. Run the review command. It checks row ordering, completeness and quotation membership and exports the results. Read all four brochures for Hebrew, audience fit, factual consistency and coverage. Inspect differences and the final interpretation in the comparison. Check that any absence uses **לא נמצא במקורות שנמסרו למודל**. An identifier check alone cannot verify a proposition.
4. Update the dated verification snapshot, Hebrew report and notebook with the actual live evidence. The editable report HTML can be printed to A4 PDF with browser headers and footers disabled. Recheck the four-page limit. Package the completed run under a new archive name.

```powershell
.\.venv\Scripts\python.exe workflow.py review "$run"
.\.venv\Scripts\python.exe package_project.py ..\assignment1_live.zip --run "$run"
```

To share a completed live run for audit before human verdicts have been entered, use `python package_project.py ..\assignment1_for_review.zip --run "$run" --for-review`. This includes the actual texts, original responses and evidence worksheets. A final reviewed archive uses the command above. Omitting `--run` creates an implementation-only package. The exporter uses exclusive creation and omits virtual environments, .env files and caches.

## Course lineage and contributions

The notebook supplied by the instructor was not found in the accessible files. The notebook in this directory was written for this implementation. The supplied assignment document, the official Day 5 notebook and scraper, and the course dependency and setup files were inspected. The seven original entry points and interface changes are mapped in TRACEABILITY.md. In particular, link extraction now accepts the already fetched page, and prompt construction accepts the saved context. This removes repeated retrieval during writing.

The user supplied the brief and project direction. Codex inspected the resources, implemented and tested the project, prepared the report and packaged the files. No student judgement of factual support or empirical prompt ranking is attributed to the user.

