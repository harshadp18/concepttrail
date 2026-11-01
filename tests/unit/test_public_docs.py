"""Publication boundary: published docs have no broken links and never point at private ones."""

from __future__ import annotations

import os
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SKIP_DIRS = {".git", ".venv", "venv", "__pycache__", ".pytest_cache", ".ruff_cache", "node_modules"}
PRIVATE_DOCS = {"docs/DECISIONS.md", "docs/SOURCE_AUDIT.md"}
# The policy document names the private files on purpose.
MAY_NAME_PRIVATE = {"docs/PUBLICATION_AND_REPRODUCIBILITY.md"}
PRIVATE_REF = re.compile(
    r"docs/DECISIONS\.md|docs/SOURCE_AUDIT\.md|docs/reports/|(?<![A-Za-z_])DECISIONS\.md|SOURCE_AUDIT"
)
LINK = re.compile(r"\[[^\]\n]*\]\(([^)\s]+)\)")
SENSITIVE = re.compile(
    r"/Users/[A-Za-z]|[\w.+-]+@[\w-]+\.(?:com|org|net|in)\b|gsk_[A-Za-z0-9]{10,}|sk-[A-Za-z0-9]{20,}",
)


def is_private(rel: str) -> bool:
    if rel in PRIVATE_DOCS or rel.startswith("docs/reports/"):
        return True
    if rel.startswith("data_pipeline/data/") or rel.startswith("resources/"):
        return not rel.endswith(("README.md", ".gitkeep"))
    return False


def public_markdown() -> list[str]:
    found = []
    for base, dirs, files in os.walk(ROOT):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        for name in files:
            if name.endswith(".md"):
                rel = (Path(base) / name).relative_to(ROOT).as_posix()
                if not is_private(rel):
                    found.append(rel)
    return sorted(found)


@pytest.fixture(scope="module")
def pages() -> dict[str, str]:
    return {rel: (ROOT / rel).read_text(encoding="utf-8") for rel in public_markdown()}


def test_published_documents_have_no_broken_or_private_links(pages: dict[str, str]) -> None:
    problems = []
    for rel, text in pages.items():
        for target in LINK.findall(text):
            if re.match(r"[a-z][a-z0-9+.-]*:", target) or target.startswith("#"):
                continue
            path = (ROOT / rel).parent / target.split("#")[0]
            resolved = path.resolve()
            if not resolved.exists():
                problems.append(f"{rel}: broken link {target}")
            elif is_private(resolved.relative_to(ROOT).as_posix()):
                problems.append(f"{rel}: link to private file {target}")
    assert not problems, "\n".join(problems)


def test_published_documents_do_not_point_at_private_documents(pages: dict[str, str]) -> None:
    offenders = {
        rel: sorted(set(PRIVATE_REF.findall(text)))
        for rel, text in pages.items()
        if rel not in MAY_NAME_PRIVATE and PRIVATE_REF.search(text)
    }
    assert not offenders, offenders


def test_published_documents_contain_no_sensitive_strings(pages: dict[str, str]) -> None:
    hits = {rel: SENSITIVE.findall(text) for rel, text in pages.items() if SENSITIVE.search(text)}
    assert not hits, hits


def test_the_public_register_is_complete_and_makes_no_adapter_claim(pages: dict[str, str]) -> None:
    text = pages["docs/PUBLIC_DECISIONS.md"]
    assert re.findall(r"^\| PD-(\d\d) \|", text, re.M) == [f"{n:02d}" for n in range(1, 13)]
    assert "no LLM provider adapter exists yet" in text
    for required in (
        "26-table",
        "8-digit PIN",
        "school email",
        "qwen3.5:9b",
        "openai/gpt-oss-120b",
        "LLM_FALLBACK_ENABLED=false",
        "undecided",
        "explicit approval",
    ):
        assert required in text, required
    assert "attest" not in text.lower()  # no private owner records in the public register
    # the technical reference indexes the docs
    assert "PUBLIC_DECISIONS.md" in pages["docs/TECHNICAL_REFERENCE.md"]


def test_active_provider_text_names_the_current_architecture(pages: dict[str, str]) -> None:
    readme = pages["docs/TECHNICAL_REFERENCE.md"]
    assert "Qwen 3.5 9B" in readme and "Gemini Flash is the proposed primary" not in readme
    for rel in (
        "docs/TECHNICAL_REFERENCE.md",
        "docs/AI_AND_PROVIDER_STRATEGY.md",
        "docs/PROVIDER_READINESS.md",
    ):
        assert "qwen3.5:9b" in pages[rel] and "openai/gpt-oss-120b" in pages[rel], rel
    # The local Ollama adapter exists (app/services/llm.py); no cloud (Groq) adapter does.
    assert re.search(r"no Groq \(cloud\) adapter exists", readme), "TECHNICAL_REFERENCE"
    assert "LLM_FALLBACK_ENABLED=false" in readme
    for rel in ("docs/PROVIDER_READINESS.md",):
        assert re.search(
            r"no (?:Ollama or Groq |provider )?adapter (?:exists|has been (?:implemented|written))"
            r"|none of the modules",
            pages[rel],
            re.I,
        ), rel


def test_gitignore_hides_private_data_but_never_source_code() -> None:
    lines = [
        ln.strip()
        for ln in (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
        if ln.strip() and not ln.startswith("#")
    ]
    for required in (
        ".env",
        "data_pipeline/data/overrides/**",
        "data_pipeline/data/curated/**",
        "data_pipeline/data/processed/**",
        "data_pipeline/data/raw/**",
        "resources/textbook_pdfs/**",
        "resources/teammate_csv/processed/**",
        "docs/reports/",
        "docs/DECISIONS.md",
        "docs/SOURCE_AUDIT.md",
    ):
        assert required in lines, required
    ignored_source = [ln for ln in lines if ln.endswith(".py") and not ln.startswith("*")]
    assert not ignored_source, ignored_source  # an ignored module hides code from Git and Ruff
