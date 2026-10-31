"""Selective, local-only OCR with the Tesseract command-line tool.

Only pages classified as OCR candidates are rendered (locally, with PyMuPDF) and passed
to a locally installed `tesseract` binary. Nothing is sent to any external service.

- OCR text is stored separately and never replaces native text.
- Hindi sources require the `hin` language pack. English OCR is never used as a
  substitute for Hindi (status `language_unavailable` instead).
- Every outcome is explicit: `not_required`, `disabled`, `unavailable`,
  `language_unavailable`, `failed`, `no_text_found`, `minimal_text`, `completed` or
  `low_confidence`.
- Deterministic: Tesseract runs single-threaded (`OMP_THREAD_LIMIT=1`) with a fixed page
  segmentation mode and DPI, so the same page and engine give the same text.
- Only languages approved in `config.yaml` (`ocr.languages`) and installed are used.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pymupdf

OCR_ADAPTER_VERSION = "ocr-pages/1.2.0"
LOW_CONFIDENCE = 70.0  # mean word confidence below this -> `low_confidence`
LOW_WORD_CONFIDENCE = 60.0  # individual words below this are counted as uncertain
MIN_MEANINGFUL_WORDS = 5  # fewer recognised words -> `minimal_text` (e.g. a picture page)
PAGE_SEGMENTATION_MODE = 3  # Tesseract default: fully automatic layout analysis
DEVANAGARI = re.compile(r"[\u0900-\u097F]")
LATIN = re.compile(r"[A-Za-z]")
Runner = Callable[[list[str]], subprocess.CompletedProcess[str]]


def _run(cmd: list[str]) -> subprocess.CompletedProcess[str]:
    env = {**os.environ, "OMP_THREAD_LIMIT": "1"}  # deterministic, single-threaded
    return subprocess.run(cmd, capture_output=True, text=True, timeout=180, check=False, env=env)


@dataclass
class OcrAvailability:
    executable: str | None
    version: str | None
    languages: list[str] = field(default_factory=list)
    error: str | None = None
    tessdata: str | None = None

    @property
    def available(self) -> bool:
        return self.executable is not None and self.version is not None

    def as_dict(self) -> dict[str, Any]:
        return {
            "executable": self.executable,
            "version": self.version,
            "languages": self.languages,
            "english_available": "eng" in self.languages,
            "hindi_available": "hin" in self.languages,
            "tessdata": self.tessdata,
            "error": self.error,
        }


def detect_tesseract(
    which: Callable[[str], str | None] = shutil.which, run: Runner = _run
) -> OcrAvailability:
    executable = which("tesseract")
    if executable is None:
        return OcrAvailability(None, None, error="tesseract executable not found on PATH")
    try:
        version_out = run([executable, "--version"])
        langs_out = run([executable, "--list-langs"])
    except (OSError, subprocess.SubprocessError) as exc:
        return OcrAvailability(executable, None, error=type(exc).__name__)
    if version_out.returncode != 0:
        return OcrAvailability(executable, None, error="tesseract --version failed")
    version = (version_out.stdout or version_out.stderr).splitlines()[0].strip()
    lines = (langs_out.stdout or "").splitlines()
    header = next((line for line in lines if line.startswith("List of")), "")
    tessdata = re.search(r'"([^"]+)"', header)
    languages = [line.strip() for line in lines if line.strip() and not line.startswith("List of")]
    return OcrAvailability(
        executable, version, sorted(languages), tessdata=tessdata.group(1) if tessdata else None
    )


def required_languages(expected_script: str) -> list[str]:
    """Hindi pages need `hin` (plus `eng` for embedded English when available)."""
    return ["hin", "eng"] if expected_script == "devanagari" else ["eng"]


def select_languages(
    expected_script: str, available: list[str], approved: list[str] | None = None
) -> tuple[str | None, str]:
    needed = required_languages(expected_script)
    if approved is not None:
        available = [lang for lang in available if lang in approved]
    primary = needed[0]
    if primary not in available:
        return None, f"required language pack '{primary}' is not installed or not approved"
    usable = [lang for lang in needed if lang in available]
    return "+".join(usable), "ok"


def parse_tsv(tsv: str) -> tuple[str, float | None, int]:
    """Text (line-preserving), mean word confidence and word count from TSV output."""
    lines: dict[tuple[int, int, int], list[str]] = {}
    confidences = []
    for row in tsv.splitlines()[1:]:
        parts = row.split("\t")
        if len(parts) < 12 or parts[0] != "5":
            continue
        word, conf = parts[11], float(parts[10])
        if not word.strip():
            continue
        key = (int(parts[2]), int(parts[3]), int(parts[4]))  # block, paragraph, line
        lines.setdefault(key, []).append(word)
        if conf >= 0:
            confidences.append(conf)
    parts: list[str] = []
    previous: tuple[int, int] | None = None
    for (block, paragraph, _line), words in sorted(lines.items()):
        if previous is not None and (block, paragraph) != previous:
            parts.append("")  # blank line marks a new Tesseract paragraph
        parts.append(" ".join(words))
        previous = (block, paragraph)
    text = "\n".join(parts)
    mean = round(sum(confidences) / len(confidences), 2) if confidences else None
    return text, mean, len(confidences)


def ocr_page(
    page: pymupdf.Page,
    expected_script: str,
    availability: OcrAvailability,
    *,
    enabled: bool,
    dpi: int,
    approved_languages: list[str] | None = None,
    run: Runner = _run,
) -> dict[str, Any]:
    base = {
        "engine": "tesseract (local)",
        "engine_version": availability.version,
        "adapter_version": OCR_ADAPTER_VERSION,
        "required_languages": required_languages(expected_script),
        "config": {
            "dpi": dpi,
            "psm": PAGE_SEGMENTATION_MODE,
            "oem": "default (LSTM)",
            "threads": 1,
            "tessdata": availability.tessdata,
        },
        "dpi": dpi,
        "text": None,
        "mean_confidence": None,
        "word_count": 0,
    }
    if not enabled:
        return {**base, "status": "disabled", "reason": "OCR disabled by configuration"}
    if not availability.available:
        return {**base, "status": "unavailable", "reason": availability.error}
    languages, reason = select_languages(
        expected_script, availability.languages, approved_languages
    )
    if languages is None:
        return {**base, "status": "language_unavailable", "reason": reason}
    with tempfile.TemporaryDirectory(prefix="ct-ocr-") as tmp:
        image = Path(tmp) / "page.png"
        page.get_pixmap(dpi=dpi).save(image)
        try:
            result = run(
                [
                    availability.executable or "tesseract",
                    str(image),
                    "stdout",
                    "-l",
                    languages,
                    "--psm",
                    str(PAGE_SEGMENTATION_MODE),
                    "tsv",
                ]
            )
        except (OSError, subprocess.SubprocessError) as exc:
            return {
                **base,
                "languages": languages,
                "status": "failed",
                "reason": type(exc).__name__,
            }
    if result.returncode != 0:
        return {
            **base,
            "languages": languages,
            "status": "failed",
            "reason": (result.stderr or "non-zero exit").strip()[:200],
        }
    text, confidence, words = parse_tsv(result.stdout)
    uncertain = sum(
        1
        for row in result.stdout.splitlines()[1:]
        if (parts := row.split("\t"))[0] == "5"
        and len(parts) >= 12
        and parts[11].strip()
        and 0 <= float(parts[10]) < LOW_WORD_CONFIDENCE
    )
    if words == 0:
        status = "no_text_found"
    elif words < MIN_MEANINGFUL_WORDS:
        status = "minimal_text"
    elif confidence is not None and confidence >= LOW_CONFIDENCE:
        status = "completed"
    else:
        status = "low_confidence"
    letters = len(DEVANAGARI.findall(text)) + len(LATIN.findall(text))
    return {
        **base,
        "languages": languages,
        "status": status,
        "text": text,
        "mean_confidence": confidence,
        "word_count": words,
        "uncertain_words": uncertain,
        "devanagari_share": round(len(DEVANAGARI.findall(text)) / letters, 3) if letters else None,
    }


def compare_native_and_ocr(native: str, ocr: str | None) -> dict[str, Any] | None:
    """Character-level similarity of native vs OCR text (whitespace-insensitive)."""
    if not ocr:
        return None
    from difflib import SequenceMatcher

    a, b = "".join(native.split()), "".join(ocr.split())
    return {
        "native_chars": len(a),
        "ocr_chars": len(b),
        "similarity": round(SequenceMatcher(None, a, b, autojunk=False).ratio(), 4),
    }
