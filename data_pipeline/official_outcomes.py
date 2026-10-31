"""Build the official learning-outcome catalogue from public CBSE curriculum documents.

Only statements the curriculum itself labels as chapter learning outcomes are captured,
verbatim, with the document URL, its SHA-256 and the PDF page. Nothing is paraphrased.

Currently supported: CBSE Secondary Curriculum 2026-27, Class X Social Science, whose
course content lists `Chapter <n> <title>` followed by `Learning outcome(s) ...` and
bullet points. Other subjects' documents state competencies that are not mapped to
chapters, so they are not turned into chapter outcomes.

    python -m data_pipeline.official_outcomes
"""

from __future__ import annotations

import hashlib
import json
import re
import urllib.request
from pathlib import Path
from typing import Any

import pymupdf

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CATALOGUE = (
    PROJECT_ROOT
    / "data_pipeline/data/overrides/metadata_enrichment/official_learning_outcomes.json"
)
SOURCES = [
    {
        "url": "https://cbseacademic.nic.in/web_material/CurriculumMain27/SecPart1/"
        "SocialScience_SecP1X_2026-27.pdf",
        "source_title": "CBSE Secondary Curriculum Part 1 (2026-27): Social Science, Class X",
        "academic_session": "2026-27",
        "class_level": "10",
        "subject_id": "social_science",
    }
]
USER_AGENT = "Mozilla/5.0 (ConceptTrail source verification)"

# Case-sensitive on purpose: cross-references such as "chapter 4 of Economics: ..." inside
# project notes are not chapter headings.
CHAPTER = re.compile(
    r"^\s*Chapter\s*[-–.]?\s*(?:[IVX]+|\d+)\s*[-–.:]*\s*(?P<title>(?!of\b)\S.*?)\s*$"
)
OUTCOME_HEADER = re.compile(r"^\s*Learning\s+outcomes?\b", re.I)
BULLET = re.compile(r"^\s*[⮚•▪]\s*(?P<text>.*)$")
STOP = re.compile(
    r"^\s*(?:Inter\s*disciplinary|Suggested|Project|Note|Refer|Unit\b|Chapter\b|Geography:|History:"
    r"|Political Science:|Economics:|CLASS\s+X)",
    re.I,
)


def parse_outcomes(pages: list[str]) -> list[dict[str, Any]]:
    """[{chapter_title, outcome, pdf_page_index}] in document order."""
    found: list[dict[str, Any]] = []
    chapter: str | None = None
    collecting = False
    current: dict[str, Any] | None = None
    for page_index, text in enumerate(pages):
        for line in text.splitlines():
            if not line.strip():
                continue
            heading = CHAPTER.match(line)
            if heading:
                chapter, collecting, current = heading["title"].strip(" -–."), False, None
                continue
            if OUTCOME_HEADER.match(line):
                collecting, current = chapter is not None, None
                continue
            if not collecting:
                continue
            bullet = BULLET.match(line)
            if bullet:
                current = {
                    "chapter_title": chapter,
                    "outcome": bullet["text"].strip(),
                    "pdf_page_index": page_index,
                }
                found.append(current)
            elif STOP.match(line):
                collecting, current = False, None
            elif current is not None:
                current["outcome"] = f"{current['outcome']} {line.strip()}"
    for item in found:
        item["outcome"] = " ".join(item["outcome"].split())
    return [item for item in found if item["outcome"]]


def build_catalogue(fetch: Any = None) -> dict[str, Any]:
    outcomes = []
    documents = []
    for source in SOURCES:
        if fetch is None:
            request = urllib.request.Request(source["url"], headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(request, timeout=60) as response:
                body = response.read()
        else:
            body = fetch(source["url"])
        sha = hashlib.sha256(body).hexdigest()
        with pymupdf.open(stream=body, filetype="pdf") as doc:
            pages = [page.get_text() for page in doc]
        parsed = parse_outcomes(pages)
        documents.append({**source, "sha256": sha, "outcomes_parsed": len(parsed)})
        for item in parsed:
            outcomes.append(
                {
                    "academic_session": source["academic_session"],
                    "class_level": source["class_level"],
                    "subject_id": source["subject_id"],
                    "chapter_match": item["chapter_title"],
                    "objective": item["outcome"],
                    "source_url": source["url"],
                    "source_title": source["source_title"],
                    "source_sha256": sha,
                    "source_page": f"PDF page index {item['pdf_page_index']}",
                    "verification": "parsed verbatim from the official PDF; human spot-check"
                    " pending",
                }
            )
    return {"documents": documents, "outcomes": outcomes}


def main() -> int:
    catalogue = build_catalogue()
    CATALOGUE.parent.mkdir(parents=True, exist_ok=True)
    CATALOGUE.write_text(
        json.dumps(catalogue, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    for doc in catalogue["documents"]:
        print(
            f"{doc['source_title']}: {doc['outcomes_parsed']} outcomes, sha256 {doc['sha256'][:12]}"
        )
    print(f"wrote {CATALOGUE.relative_to(PROJECT_ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
