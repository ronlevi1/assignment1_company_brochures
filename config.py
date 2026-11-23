import os
from dataclasses import asdict, dataclass
from pathlib import Path
from urllib.parse import urlsplit

from url_utils import clean_url

SOURCE_CHAR_BUDGET = 12000
ROOT = Path(__file__).resolve().parent


@dataclass(frozen=True)
class Company:
    id: str
    name: str
    url: str


@dataclass(frozen=True)
class Settings:
    companies: tuple
    model: str = "qwen3:8b"
    base_url: str = "http://127.0.0.1:11434/v1"
    budget: int = SOURCE_CHAR_BUDGET
    timeout: float = 180
    output_dir: Path = ROOT / "runs"
    provider_retries: int = 2

    def __post_init__(self):
        if [c.id for c in self.companies] != ["A", "B"] or not all(c.name.strip() for c in self.companies):
            raise ValueError("Provide named companies A and B in order")
        for company in self.companies:
            clean_url(company.url, "")
        if self.budget < 1 or self.timeout <= 0 or not self.model.strip():
            raise ValueError("Model, positive character budget and timeout required")
        if type(self.provider_retries) is not int or not 0 <= self.provider_retries <= 3:
            raise ValueError("PROVIDER_RETRIES must be an integer from 0 to 3")
        route = urlsplit(self.base_url)
        if route.scheme not in ("http", "https") or not route.hostname or route.username or route.password or route.query or route.fragment:
            raise ValueError("Configure a credential-free API base URL")

    def public(self):
        return dict(asdict(self), output_dir=str(self.output_dir), max_retries=0)

    @classmethod
    def load(cls):
        env_file = Path(os.getenv("CONFIG_DIR", ROOT)) / ".env"
        if env_file.is_file():
            from dotenv import load_dotenv
            load_dotenv(env_file, override=False)
        companies = tuple(Company(key, os.getenv(f"COMPANY_{key}_NAME", name),
                                  os.getenv(f"COMPANY_{key}_URL", url))
                          for key, name, url in (("A", "Plausible Analytics", "https://plausible.io/"),
                                                  ("B", "Fathom Analytics", "https://usefathom.com/")))
        return cls(companies, os.getenv("MODEL", cls.model),
                   os.getenv("OPENAI_BASE_URL", cls.base_url),
                   int(os.getenv("SOURCE_CHAR_BUDGET", SOURCE_CHAR_BUDGET)),
                   float(os.getenv("REQUEST_TIMEOUT", str(cls.timeout))),
                   Path(os.getenv("OUTPUT_DIR", ROOT / "runs")),
                   int(os.getenv("PROVIDER_RETRIES", cls.provider_retries)))


def client_for(settings):
    from openai import OpenAI
    local = urlsplit(settings.base_url).hostname in {"localhost", "127.0.0.1", "::1"}
    key = "ollama" if local else os.environ.get("OPENAI_API_KEY")
    if not key:
        raise ValueError("Set OPENAI_API_KEY for the configured endpoint")
    return OpenAI(api_key=key, base_url=settings.base_url, timeout=settings.timeout, max_retries=0)

