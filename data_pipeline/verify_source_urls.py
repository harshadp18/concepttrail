"""Research and verify official source URLs for pilot PDFs (network; no AI, nothing uploaded).

Evidence chain for an NCERT chapter PDF:

1. NCERT's public `textbook.php` page script loads chapter `NN` of book code `name` as
   `"../textbook/pdf/" + name + "NN.pdf"`. The rule string itself is checked in the page.
2. The same script lists each book's title against its code
   (`options[i].text="<title>"; options[i].value="textbook.php?<code>=0-<n>"`).
3. The candidate URL `https://ncert.nic.in/textbook/pdf/<code><NN>.pdf` is downloaded and
   hashed in memory (never written to disk). Only an exact match with the
   inventory SHA-256 marks the URL `verified`; anything else stays unresolved with a reason.

A homepage or a guessed path is never recorded as a verified source URL.

    python -m data_pipeline.verify_source_urls
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import re
import ssl
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from pathlib import Path
from typing import Any

import certifi

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SELECTION = PROJECT_ROOT / "data_pipeline/data/logs/extraction_pilot/pilot_selection.json"
OUTPUT = PROJECT_ROOT / "data_pipeline/data/processed/metadata_enrichment/source_url_evidence.json"
VERIFIER_VERSION = "verify-source-urls/1.0.0"
NCERT_INDEX = "https://ncert.nic.in/textbook.php"
NCERT_PDF_BASE = "https://ncert.nic.in/textbook/pdf/"
USER_AGENT = "Mozilla/5.0 (ConceptTrail source verification; contact: project owner)"
MAX_BYTES = 200 * 1024 * 1024
CHAPTER_FILE = re.compile(r"^(?P<code>[a-z]{4}\d)(?P<chapter>\d{2})\.pdf$")
RULE = re.compile(r'omyFrame\.src\s*=\s*"\.\./textbook/pdf/"\s*\+\s*name\s*\+\s*"01\.pdf"')
BOOK_OPTION = re.compile(
    r'options\[(?P<i>\d+)\]\.text="(?P<title>[^"]*)";\s*'
    r'document\.test\.tbook\.options\[(?P=i)\]\.value="textbook\.php\?(?P<code>[a-z0-9]+)=0-(?P<n>\d+)"'
)

Fetch = Callable[[str], tuple[int, bytes | None, str, str | None]]


def _tls_context(host: str) -> ssl.SSLContext:
    """Fully verifying TLS context anchored in the certifi root store.

    Some official sites (ncert.nic.in) send only their leaf certificate. Browsers complete
    the chain from the leaf's Authority Information Access "CA Issuers" URL; this does the
    same. The fetched intermediate is only an untrusted chain hint: OpenSSL still verifies
    the whole chain up to a certifi root and checks the hostname. Verification is never
    disabled.
    """
    if host in _CONTEXTS:
        return _CONTEXTS[host]
    context = ssl.create_default_context(cafile=certifi.where())
    # Intermediates added below must never become trust anchors: the chain has to reach a
    # self-signed root from certifi.
    context.verify_flags &= ~getattr(ssl, "VERIFY_X509_PARTIAL_CHAIN", 0)
    try:
        pem = ssl.get_server_certificate((host, 443), timeout=30)
        for _ in range(MAX_AIA_HOPS):
            issuers = [u for u in _decode_pem(pem).get("caIssuers", ()) if u.startswith("http")]
            if not issuers:
                break
            with urllib.request.urlopen(issuers[0], timeout=30) as response:
                pem = ssl.DER_cert_to_PEM_cert(response.read(64 * 1024))
            context.load_verify_locations(cadata=pem)
    except (OSError, ValueError, ssl.SSLError):
        pass  # fall back to the plain certifi store; verification still applies
    _CONTEXTS[host] = context
    return context


_CONTEXTS: dict[str, ssl.SSLContext] = {}
MAX_AIA_HOPS = 4


def _decode_pem(pem: str) -> dict[str, Any]:
    with tempfile.NamedTemporaryFile("w", suffix=".pem", delete=False) as handle:
        handle.write(pem)
    try:
        return ssl._ssl._test_decode_cert(handle.name)  # noqa: SLF001 (stdlib decoder)
    finally:
        Path(handle.name).unlink(missing_ok=True)


def fetch(url: str) -> tuple[int, bytes | None, str, str | None]:
    """GET -> (HTTP status, body or None, content type, error). Bodies are never written."""
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    context = _tls_context(urllib.parse.urlsplit(url).hostname or "")
    try:
        with urllib.request.urlopen(request, timeout=60, context=context) as response:
            content_type = response.headers.get("Content-Type", "")
            return response.status, response.read(MAX_BYTES), content_type, None
    except urllib.error.HTTPError as exc:
        return exc.code, None, "", f"HTTP {exc.code}"
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        return 0, None, "", f"{type(exc).__name__}: {getattr(exc, 'reason', '')}"[:200]


def ncert_index_evidence(get: Fetch) -> dict[str, Any]:
    status, body, _, error = get(NCERT_INDEX)
    if status != 200 or body is None:
        return {"status": "unreachable", "error": error, "http_status": status, "books": {}}
    page = body.decode("utf-8", errors="replace")
    books: dict[str, dict[str, Any]] = {}
    for match in BOOK_OPTION.finditer(page):
        books.setdefault(
            match["code"],
            {
                "title": match["title"],
                "book_page_url": f"{NCERT_INDEX}?{match['code']}=0-{match['n']}",
                "listed_chapter_range": f"0-{match['n']}",
            },
        )
    return {
        "status": "ok",
        "index_url": NCERT_INDEX,
        "index_sha256": hashlib.sha256(body).hexdigest(),
        "chapter_url_rule_present": bool(RULE.search(page)),
        "chapter_url_rule": '"../textbook/pdf/" + name + "NN.pdf" (NCERT textbook.php script)',
        "books": books,
    }


def verify_document(
    doc: dict[str, Any], index: dict[str, Any], get: Fetch, today: str
) -> dict[str, Any]:
    filename = Path(doc["local_path"]).name
    base = {
        "source_id": doc["source_id"],
        "inventory_id": doc["inventory_id"],
        "local_filename": filename,
        "inventory_sha256": doc["sha256"],
        "verification_date": today,
        "source_organization": None,
        "source_title": None,
        "book_page_url": None,
        "url": None,
        "downloaded_sha256": None,
        "http_status": None,
    }
    match = CHAPTER_FILE.match(filename)
    if index["status"] != "ok":
        return {
            **base,
            "url_value_status": "unknown",
            "reason": "official_index_unreachable",
            "review_status": "needs_research",
            "confidence": None,
        }
    if not match or not index["chapter_url_rule_present"]:
        return {
            **base,
            "url_value_status": "not_found",
            "reason": "no_documented_official_url_rule",
            "review_status": "needs_research",
            "confidence": None,
        }
    book = index["books"].get(match["code"])
    candidate = f"{NCERT_PDF_BASE}{filename}"
    status, body, content_type, error = get(candidate)
    digest = hashlib.sha256(body).hexdigest() if body is not None else None
    result = {
        **base,
        "source_organization": "NCERT (National Council of Educational Research and Training)",
        "source_title": book["title"] if book else None,
        "book_page_url": book["book_page_url"] if book else None,
        "candidate_url": candidate,
        "http_status": status,
        "content_type": content_type,
        "downloaded_sha256": digest,
        "verification_method": "official NCERT textbook.php chapter-URL rule + SHA-256 of"
        " downloaded bytes equals the inventory SHA-256 (bytes not stored)",
    }
    if digest == doc["sha256"]:
        return {
            **result,
            "url": candidate,
            "url_value_status": "verified",
            "confidence": "high",
            "reason": "exact_byte_match",
            "review_status": "verified_automatically",
        }
    if digest is not None:
        return {
            **result,
            "url_value_status": "requires_human_review",
            "confidence": "low",
            "reason": "official_url_serves_different_bytes (edition or reprint may differ)",
            "review_status": "needs_research",
        }
    return {
        **result,
        "url_value_status": "unknown",
        "confidence": None,
        "reason": f"download_failed: {error or status}",
        "review_status": "needs_research",
    }


def run(selection: dict[str, Any], get: Fetch = fetch, today: str | None = None) -> dict[str, Any]:
    today = today or dt.date.today().isoformat()
    index = ncert_index_evidence(get)
    docs = [d for d in selection["selected"] if d.get("status") == "selected"]
    return {
        "verifier_version": VERIFIER_VERSION,
        "verified_on": today,
        "index": {k: v for k, v in index.items() if k != "books"},
        "books_referenced": {
            m["code"]: index["books"].get(m["code"])
            for d in docs
            if (m := CHAPTER_FILE.match(Path(d["local_path"]).name))
        },
        "results": [verify_document(d, index, get, today) for d in docs],
    }


def main() -> int:
    selection = json.loads(SELECTION.read_text(encoding="utf-8"))
    evidence = run(selection)
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(evidence, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    for r in evidence["results"]:
        print(json.dumps({k: r.get(k) for k in ("source_id", "url_value_status", "url", "reason")}))
    print(f"wrote {OUTPUT.relative_to(PROJECT_ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
