"""Phase 1 configuration for the company brochure assignment."""

import os
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI


load_dotenv(Path(__file__).with_name(".env"))

GEMINI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/openai/"
MODEL = os.getenv("GEMINI_MODEL", "gemini-3.5-flash-lite")
SOURCE_CONTEXT_BUDGET = int(os.getenv("SOURCE_CONTEXT_BUDGET", "12000"))
if SOURCE_CONTEXT_BUDGET <= 0:
    raise ValueError("SOURCE_CONTEXT_BUDGET must be a positive character count.")

COMPANIES = {
    "A": {"name": "Plausible Analytics", "url": "https://plausible.io/"},
    "B": {"name": "Fathom Analytics", "url": "https://usefathom.com/"},
}

COMPARISON_DIMENSIONS = (
    "Products and services", "Target customers", "Pricing or trial availability",
    "Employment and career information",
)


def create_client():
    """Construct the Gemini client locally. Construction sends no API request."""
    key = os.getenv("GOOGLE_API_KEY")
    if not key:
        raise ValueError("Set GOOGLE_API_KEY in the environment or project .env.")
    return OpenAI(api_key=key, base_url=GEMINI_BASE_URL, max_retries=0)
