"""Source-reference resolution (D7, contract section 6), milestone M2.

A token `src:<source_id>@<pdf_page_index>[:para<N>]#<sha12>` resolves only against material that
already exists locally:

- the accepted (cleaned) inventory row: title, `publication_or_revision`, academic session and
  the PDF's full SHA-256;
- the existing normalised extraction artifact for that exact PDF (page count, paragraphs);
- the rights overlay: `check_use(source_id, sha256, RESOLUTION_USE)` must permit it.

Nothing is downloaded, extracted, OCR'd or sent anywhere. Paragraph text is hashed
(`passage_sha256`) and never copied into reports. Hindi artifacts are read as normalised; the
separate approved repair overlay is not applied, so passage digests are of the normalised text.
"""

from __future__ import annotations

import csv
import hashlib
import json
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from data_pipeline import authorization
from data_pipeline.kc_graph.contract import PROJECT_ROOT, RESOLUTION_USE
from data_pipeline.kc_graph.findings import Finding, finding
from data_pipeline.kc_graph.rows import SourceToken

INVENTORY = (
    PROJECT_ROOT / "resources/teammate_csv/processed/cleaned/curriculum_inventory.cleaned.csv"
)
ARTIFACT_DIR = PROJECT_ROOT / "data_pipeline/data/processed/textbook_json"
PDF_ROOT = PROJECT_ROOT / "resources/textbook_pdfs"


@dataclass(frozen=True)
class SourceDocument:
    source_id: str
    sha256: str
    title: str
    revision: str
    academic_session: str
    accepted: bool
    rights_permitted: bool
    rights_reason: str
    artifact: str | None  # artifact file name, or None when no artifact exists
    artifact_sha256: str | None  # the PDF digest the artifact itself records
    page_count: int = 0
    # per page: (text_unusable, (passage_sha256, ...))
    pages: tuple[tuple[bool, tuple[str, ...]], ...] = field(default=(), repr=False)
    pdf_status: str | None = None  # None: not checked; "verified", "absent" or "mismatch"


@dataclass(frozen=True)
class Resolution:
    token: str
    source_id: str
    source_sha256: str
    title: str
    revision: str
    academic_session: str
    page: int
    para: int | None
    passage_sha256: str | None

    def manifest(self) -> dict[str, Any]:
        return {k: v for k, v in self.__dict__.items()}


class SourceIndex:
    def __init__(self, documents: Iterable[SourceDocument], *, synthetic: bool = False) -> None:
        self.documents = {d.source_id: d for d in documents}
        self.synthetic = synthetic

    def resolve(
        self, token: SourceToken, *, label: str, record: str, column: str, line: int = 0
    ) -> tuple[Resolution | None, list[Finding]]:
        def bad(code: str, message: str) -> tuple[None, list[Finding]]:
            return None, [
                finding(
                    code,
                    f"{token.raw}: {message}",
                    file=label,
                    line=line,
                    record=record,
                    field=column,
                )
            ]

        doc = self.documents.get(token.source_id)
        if doc is None:
            return bad("SOURCE_UNKNOWN", "not in the accepted inventory")
        if not doc.accepted:
            return bad("SOURCE_NOT_ACCEPTED", "the inventory row is quarantined or rejected")
        if not doc.rights_permitted:
            return bad("SOURCE_RIGHTS_BLOCKED", doc.rights_reason)
        if token.pin != doc.sha256[:12]:
            return bad("SOURCE_PIN_MISMATCH", "pin differs from the inventory SHA-256")
        if doc.artifact is None:
            return bad("SOURCE_ARTIFACT_MISSING", "no normalised extraction artifact exists")
        if doc.artifact_sha256 != doc.sha256:
            return bad("SOURCE_PIN_MISMATCH", "the extraction artifact is of different bytes")
        if doc.pdf_status == "mismatch":
            return bad("SOURCE_PIN_MISMATCH", "the local PDF bytes differ from the inventory")
        if not 0 <= token.page < doc.page_count:
            return bad("PAGE_OUT_OF_RANGE", f"page index must be in [0, {doc.page_count})")
        unusable, passages = doc.pages[token.page]
        passage = None
        if token.para is not None:
            if unusable:
                return bad(
                    "SOURCE_TEXT_UNUSABLE",
                    "page text is unusable; no passage can be located (check the page image)",
                )
            if not 0 <= token.para < len(passages):
                return bad("PARAGRAPH_OUT_OF_RANGE", f"paragraph must be in [0, {len(passages)})")
            passage = passages[token.para]
        return Resolution(
            token.raw,
            doc.source_id,
            doc.sha256,
            doc.title,
            doc.revision,
            doc.academic_session,
            token.page,
            token.para,
            passage,
        ), []

    def document_findings(self, used: Iterable[str]) -> list[Finding]:
        out = []
        for source_id in sorted(set(used)):
            doc = self.documents.get(source_id)
            if doc is not None and doc.pdf_status == "absent":
                out.append(
                    finding(
                        "SOURCE_FILE_ABSENT",
                        f"{source_id}: the local PDF copy is absent; bytes not re-verified",
                        file="sources",
                    )
                )
        return out


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def artifact_pages(data: dict[str, Any]) -> tuple[tuple[bool, tuple[str, ...]], ...]:
    pages = sorted(data.get("pages", []), key=lambda p: p["page_index"])
    return tuple(
        (
            bool(p.get("text_unusable")),
            tuple(
                hashlib.sha256(para.get("text", "").encode("utf-8")).hexdigest()
                for para in p.get("paragraphs", [])
            ),
        )
        for p in pages
    )


def build_index(
    inventory: Path = INVENTORY,
    artifact_dir: Path = ARTIFACT_DIR,
    pdf_root: Path | None = PDF_ROOT,
    records: list[dict[str, Any]] | None = None,
    check: Callable[..., authorization.Decision] = authorization.check_use,
) -> SourceIndex:
    """Index the accepted inventory joined with existing normalised artifacts and rights."""
    artifacts: dict[str, list[tuple[str, dict[str, Any]]]] = {}
    for path in sorted(artifact_dir.glob("*.normalized.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        source_id = data["document"]["source_id"]
        # One artifact per source exists today; if several do, prefer the one whose PDF digest
        # matches the inventory (checked when the row is read).
        artifacts.setdefault(source_id, []).append((path.name, data))
    documents = []
    with inventory.open(encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            source_id, sha = row["source_id"], row["sha256"]
            if not source_id or not sha:
                continue
            decision = check(source_id, sha, RESOLUTION_USE, records)
            options = artifacts.get(source_id, [])
            matching = [o for o in options if o[1]["document"].get("pdf_sha256") == sha]
            name, data = (matching or options or [(None, {})])[0]
            pdf_status = None
            if pdf_root is not None and data:
                relative = data["document"].get("pdf_path", "")
                candidates = [PROJECT_ROOT / relative, pdf_root / Path(relative).name]
                found = next((p for p in candidates if relative and p.is_file()), None)
                if found is None:
                    pdf_status = "absent"
                else:
                    pdf_status = "verified" if _sha256_file(found) == sha else "mismatch"
            pages = artifact_pages(data) if data else ()
            documents.append(
                SourceDocument(
                    source_id=source_id,
                    sha256=sha,
                    title=row.get("resource_title", ""),
                    revision=row.get("publication_or_revision", ""),
                    academic_session=row.get("academic_session", ""),
                    accepted=row.get("validation_status") == "passed",
                    rights_permitted=decision.permitted,
                    rights_reason=decision.reason,
                    artifact=name,
                    artifact_sha256=data["document"]["pdf_sha256"] if data else None,
                    page_count=len(pages),
                    pages=pages,
                    pdf_status=pdf_status,
                )
            )
    return SourceIndex(documents)
