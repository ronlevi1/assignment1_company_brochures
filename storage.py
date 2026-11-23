"""Small UTF-8 files, one directory per attempt. Paths in logs are run-relative."""
import json
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4


def utc_now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def dump_text(path, text):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    temporary.write_bytes(text.encode("utf-8"))
    temporary.replace(path)


def dump_json(path, value):
    dump_text(path, json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + "\n")


def read_json(path):
    return json.loads(Path(path).read_bytes().decode("utf-8"))


def attempt_key(operation, attempt):
    return operation if attempt == 1 else f"{operation}.attempt{attempt}"


class Run:
    def __init__(self, root):
        self.root = Path(root)
        self.id = self.root.name

    @classmethod
    def new(cls, parent):
        run = cls(Path(parent) / (datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ-") + uuid4().hex[:8]))
        run.root.mkdir(parents=True, exist_ok=False)
        return run

    def log(self, event, **fields):
        entry = dict(run_id=self.id, at=utc_now(), event=event, **fields)
        with (self.root / "execution_log.jsonl").open("a", encoding="utf-8") as file:
            file.write(json.dumps(entry, ensure_ascii=False) + "\n")

