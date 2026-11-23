# Verification snapshot · 23 November 2026

**Implementation and offline verification package. Live academic deliverables remain incomplete.** The attached instructor document (בינה מלאכותית - מטלה מספר 1 (1).docx) was read in full. Its SHA-256 is 8d7ad113d594d6f52221971423fa12744e8cbed34fa8fbbcf61ba64c25218f23. The original assignment1_brochure_pro.ipynb was not found among accessible files. Compatibility with any additional starter-specific interfaces or tests remains unverified.

## Stage resumption verification

Offline inspection of `20261123T153228Z-22762162` verified both selections and all eight source records. The original run recorded two rejected Plausible customer drafts, one rejected job-candidate draft, and HTTP 503 on the next three candidate-brochure requests. The provider reported high demand. No accepted brochure was present at this stop.

A rehearsal on a temporary copy used six scripted writing responses and zero website fetches. It resumed both Plausible brochures at attempt 5, then exercised the two Fathom brochures, comparison and baseline. Offline replay verified all six fixture exports. The original run files were byte-identical before and after the rehearsal. Live generation remains pending. All 59 automated tests passed. [Stage resumption test results](verification/tests-stage-resume.xml)

## Earlier Gemini recovery verification

The live runs `20261123T135640Z-87451b8c` and `20261123T140237Z-9011911f` each retrieved the Plausible homepage successfully and recorded one failed `A_links` call. The saved request files have identical SHA-256 hashes. Both contain the configured model, system and user messages, and `stream=false`. The legacy error artifacts contain only the SDK class. A precise HTTP code or backend explanation cannot be recovered from them.

Both original runs passed the read-only `links-only --inspect` checks with 42 candidates and 2,236 message characters. An outbound TCP connection to the Gemini host on port 443 was denied in the repair environment. Live isolated validation and the remaining generation and human review are pending. The temporary test fixtures operate independently of these original run directories.

The recovery suite passed all 45 tests on Windows Python 3.12.14 with pytest 8.4.2 and SDK 1.109.1. The configured Windows Store Python 3.13 executable could not be launched in this sandbox. Tests cover all four retryable statuses, a 400, exhausted retries, strict selection rejection, redaction, a partial stream, legacy records, reuse of a validated checkpoint, mixed writing and provider retries, offline replay and packaging. [JUnit results](verification/tests-gemini-recovery.xml)

## Earlier revision

The supplied ZIP matched all 29 working files before editing. The user reports that an independent environment with BeautifulSoup passed the original 23 tests. The local revised suite collected 28 tests. **27 passed and one HTML-parser test was skipped** because this runtime lacks BeautifulSoup. The raw local result is in verification/tests-revision.xml.

The latest Windows preflight is runs/preflight/20261123T111722Z-4e25c98c. DNS succeeded. Both website TCP connections failed with Windows error 10013 (access denied), before HTTP. Loopback port 11434 refused the connection (10061). These observations apply to the restricted project session. Host-wide website accessibility and the installed model inventory remain unconfirmed. An earlier native-runtime attempt encountered a missing CA bundle before the socket check. A repeat using the bundled CA file produced the recorded socket failures with TLS verification enabled.

The local model tag in the example is a configuration choice. Actual model calls, live brochures, comparisons, baseline outputs and audited real claims all remain at zero. No paid endpoint was used. Conditional source selection and a fresh sample after invalid prose passed a ten-call fixture with replay; source IDs and originals were preserved. A human must still assess the first two material claims in each real brochure and complete the paired prompt evaluation.

The updated notebook includes the provider check. Its inspection cells were exercised as Python code. The report includes a third-page revision note. The earlier report and evidence below describe the uploaded version.

## Uploaded version and historical results

| Measure | Result |
|---|---|
| Local homepage preflight | Two attempted GETs, two connection failures, zero HTML responses. Actual timestamps and durations are in runs/preflight/20261123T104859Z-171638d0 |
| Real model calls and accepted company documents | Zero calls, zero brochures, zero comparisons, zero baselines |
| Actual model and route | None. No configured OpenAI API key was available to the project, and a check of the default local Ollama endpoint could not connect. The editable OpenAI-compatible configuration is a future run choice |
| Deterministic final suite | 23 collected, 22 passed, 1 skipped. The HTML-to-text test requires BeautifulSoup. See verification/tests-final.xml |
| Full workflow fixture | Two fictitious domains, a homepage and selected team URL per domain, eight scripted completions, one stream, six validated writing artifacts, successful offline replay. The fixture counts and citations test software behaviour. Its repeated words have no evidentiary or editorial value |
| Notebook | All seven inspect-mode code cells executed sequentially in Python 3.12.14. Their actual stdout is saved in the notebook. A Jupyter kernel and live incremental UI display were unavailable in this environment |
| PDF | Two A4 pages. Both pages were rasterized with Poppler and inspected for Hebrew ordering, legibility, flowchart layout and clipping |
| Human evidence review | Zero of eight actual company claims available. Each of A_customers, A_candidates, B_customers and B_candidates lacks both required claim slots because its live output is absent |
| Paired prompt evaluation | Criteria and controls implemented and checked with fixtures. No empirical comparison, concrete live examples or conclusion about relative prompt quality |

The defaults are two real companies offering privacy-oriented web analytics. Public web lookup showed product, pricing and audience information plus company background relevant to candidates. The local failures occurred before an HTTP status was received. No alternative company was confirmed because the available evidence indicated a general connection restriction. Browser observations were not inserted into a model context or presented as collected source records. [Plausible homepage](https://plausible.io/) · [Plausible company information](https://plausible.io/about) · [Fathom homepage](https://usefathom.com/) · [Fathom company information](https://usefathom.com/about)

## Test environment and history

1. The Cygwin Python 3.9.16 pytest launcher failed during import because exceptiongroup was unavailable. Standard-library unittest ran the initial suite successfully with one dependency skip. The HTTP preflight used that interpreter's Requests 2.31.0.
2. A native Python 3.12.14 run with the locally available pytest initially encountered two import/collection errors from the mixed urllib3 installation. The actual failures are retained in verification/tests-first.xml.
3. Using the native runtime's bundled Requests dependency with the available pytest restored collection. The intermediate result (19 passed, one skipped) is retained in verification/tests-recovery.xml.
4. Final verification used native Windows Python 3.12.14, pytest 7.3.0 and bundled Requests 2.34.2. External pytest plugin discovery was disabled. This pytest version emitted unittest duration-reporting warnings on Python 3.12. The installation pins in requirements.txt describe the target course-compatible environment. That entire environment could not be installed and exercised here.

## Final acceptance ledger

“Fixture verified” means deterministic execution against local inputs. “Implemented” identifies a code path whose live behaviour still needs evidence. For the implementing functions, artifacts and tests see [the requirements map](TRACEABILITY.md).

| Requirement | Final status |
|---|---|
| Follow Day 5 workflow | Inspected the actual official notebook, scraper, course configuration, README and setup. Recognizable entry points retained |
| Implement the instructor brief | Engineering paths implemented. Live and manual deliverables outstanding as listed below |
| Use two companies in the same industry | Plausible and Fathom proposed and publicly checked. Live use pending |
| Confirm website readability through the course scraper | Blocked. Actual preflight records two failed connections. The BeautifulSoup extraction test was skipped |
| Normalize URLs in Python | Fixture verified, including relative URLs, www, fragments, schemes, hosts, forbidden paths, ports and redirects |
| Save normalized candidates actually passed to the model | Fixture verified, also retains original transport URLs. No candidates were passed to a real model |
| Strict JSON validation | Fixture verified, including malformed input, missing/non-string fields, duplicates, unknown and forbidden entries, size and empty list |
| Rejection causes zero selected-page requests | Fixture verified both at the validation boundary and through homepage collection |
| At most four sources per company | Implemented and tested, with no recursive fetches |
| Correct IDs, timestamps and source status | Fixture verified for success, failure and empty text in saved order |
| Preserve source text locally | Fixture verified on a 15,000-character source. No live collection available |
| Reuse source collections | Fixture verified from request counts and replay |
| Character budget, metadata, reasons | Fixture verified with a 150,000-character homepage and multiple competitors |
| One shared comparison budget | Fixture verified, including deterministic remainder ties |
| Four main Hebrew brochures | Zero live outputs. Four distinct main generation slots exercised with fixtures |
| 200–300 split words excluding final sources | Boundaries 199, 200, 300 and 301 verified. Live word counts pending |
| Source-based factual claims | Prompt instructions and review protocol implemented. Factual support and consistency require reading actual outputs |
| Cited IDs belong to context, source status and company | Fixture verified, including a valid saved source omitted by budgeting and a foreign company |
| Exactly one streamed main brochure | Fixture verified for B_candidates. Live notebook display pending |
| Missing chunks and interrupted stream | Fixture verified, including exact saved partial and final bytes, missing finish event and exceptions |
| Four predetermined comparison dimensions plus paragraph | Format and cited company cells checked with fixtures. No live table or suitability conclusion |
| Empty, failed and oversized sources | Fixture verified |
| Malformed and forbidden selection simulations | Fixture verified |
| Mock streaming tests | Passed |
| Eight factual claims | Zero reviewed. Sampling, four verdicts, exact excerpts, explanations and deficiency reporting implemented |
| Controlled baseline prompt experiment | Same source context, provider settings and audience verified in a fixture. Live experiment and paired review pending |
| Log HTTP and LLM calls separately | Two actual HTTP attempts logged. Successful and failed model logs tested with mocks. No live model log |
| Save exact prompts and contexts | Fixture verified for all eight requests and reconstructed during replay |
| Offline replay and local tests | Fixture verified, including rejection of a modified exported brochure |
| Hebrew report no longer than four pages | Verified two pages with system diagram, decisions, evaluation limitations and contributions |
| README, dependencies and safe environment example | Present. Install, live, test, replay, review and export instructions supplied |
| AI assistance and actual work division | Recorded in README and Hebrew report. Human factual review pending |
| Single ZIP with requested materials | Implementation, notebook, report, tests and preflight evidence packaged. Required live artifacts absent |
| Secrets and experimental integrity | Package uses an explicit file list. No actual .env, virtual environment or keys included. No model responses attributed to an unexecuted live run |

## Review before academic submission

After a connected run, inspect the original responses and compare material claims to the exact supplied text. Confirm audience fit, Hebrew fluency, limits on pricing or employment claims, consistency across brochures and whether the four comparison rows justify their differences. Finalize the eight-claim audit and controlled comparison with concrete examples, update the report, save the executed live notebook, and package that run. A lexical match between an excerpt and a saved source establishes provenance only.

