"""Build a shareable ZIP from project files and one optionally selected live run."""
import argparse
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

from storage import read_json

PROJECT = Path(__file__).resolve().parent
FILES = ["assignment1_brochure_pro.ipynb", "README.md", "VERIFICATION.md", "TRACEABILITY.md",
         ".env.example", ".gitignore", "requirements.txt", "config.py", "workflow.py", "scraper.py",
         "source_manager.py", "url_utils.py", "context_manager.py", "prompt_builder.py", "llm_service.py",
         "storage.py", "evaluation.py", "validators.py", "package_project.py"]


def build_zip(output, run=None, *, for_review=False):
    if for_review and not run:
        raise ValueError("a review draft needs a completed live generation run")
    files = [(PROJECT / name, name) for name in FILES]
    for pattern in ("tests/test_*.py", "report/report.pdf", "report/report.html", "verification/*.xml",
                    "runs/preflight/*/sites.json", "runs/preflight/*/connectivity.json",
                    "runs/preflight/*/execution_log.jsonl"):
        files.extend((p, p.relative_to(PROJECT)) for p in sorted(PROJECT.glob(pattern)))
    if run:
        from workflow import replay
        run = Path(run).resolve()
        if read_json(run / "config.json")["mode"] != "live":
            raise ValueError("select a live generation run")
        replay(run)
        from evaluation import prepare_review, publish_review
        if for_review:
            prepare_review(run)
        else:
            publish_review(run)
        paths = ["config.json", "protocol.json", "execution_log.jsonl", "data/*.json", "contexts/*.json",
                 "prompts/*.json", "responses/*.txt", "responses/*_error.json", "metadata/*.json", "artifacts/*.md",
                 "artifacts/*.csv", "artifacts/brochures/*.md", "review/*.md", "review/*.json", "review/*.csv"]
        for pattern in paths:
            files.extend((p, Path("runs") / run.name / p.relative_to(run)) for p in sorted(run.glob(pattern)))
    output = Path(output)
    if output.suffix.lower() != ".zip":
        raise ValueError("choose a .zip output")
    with ZipFile(output, "x", compression=ZIP_DEFLATED) as archive:
        for file, name in files:
            archive.write(file, Path("assignment1_company_brochures") / name)
    with ZipFile(output) as archive:
        if archive.testzip() is not None:
            raise ValueError("archive integrity check failed")
    return len(files)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    parser.add_argument("--run", type=Path)
    parser.add_argument("--for-review", action="store_true", help="Include live texts and unfinished review forms")
    args = parser.parse_args()
    print("Archived files:", build_zip(args.output, args.run, for_review=args.for_review))

