"""D17 drafting: refused without a rights record, local-only, mock transport, drafts only."""

from __future__ import annotations

import json
import sys

import httpx
import pytest

from data_pipeline import authorization
from data_pipeline.kc_graph import drafting, synthetic, vocabulary

TOKEN = "src:SRC-C07-MAT-EXMP1-01@5:para2#a1b2c3d4e5f6"
SYNTHETIC_GRANT = [
    {
        "record_id": "SYNTHETIC-TEST-GRANT",
        "authorization_basis": "synthetic test only",
        "uses": dict.fromkeys(authorization.DRAFTING_USES, "permitted"),
        "documents": [{"source_id": synthetic.SYNTHETIC_SOURCE, "sha256": synthetic.SYNTHETIC_SHA}],
    }
]


def client_returning(candidates: list[dict], seen: list) -> drafting.OllamaChat:
    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        body = {"message": {"content": json.dumps({"candidates": candidates})}}
        return httpx.Response(200, json=body)

    return drafting.OllamaChat(transport=httpx.MockTransport(handler))


def run(
    task: str, candidates: list[dict], seen: list, records=SYNTHETIC_GRANT, subject="mathematics"
):
    counter = iter(range(10, 99))
    return drafting.draft(
        task,
        subject,
        {"passages": [{"token": TOKEN, "text": "synthetic passage"}]},
        [TOKEN],
        vocabulary.provisional(),
        synthetic.source_index(),
        client_returning(candidates, seen),
        next_kc_id=lambda s: f"KC-MAT-{next(counter):05d}",
        records=records,
        generated_on="2026-02-01",
    )


GOOD_KC = {
    "stable_key": "mathematics.fractions.common-denominator.compute",
    "name": "Find a common denominator",
    "kc_type": "procedure",
    "scope": "target",
    "learning_objective": "Find a common denominator for two fractions.",
    "source_refs": [TOKEN],
    "declared_class_levels": ["7"],
}


def test_no_existing_record_authorises_drafting() -> None:
    for source_id, sha in (("SRC-C09-MAT-IEMH1-04", "c18321e78f4d" + "0" * 52),):
        for use in authorization.DRAFTING_USES:
            assert not authorization.check_use(source_id, sha, use).permitted
    seen: list = []
    with pytest.raises(drafting.DraftingNotAuthorised, match="refused"):
        run("kc", [GOOD_KC], seen, records=[])
    assert seen == []  # refused before any request


def test_hindi_and_non_local_endpoints_are_refused() -> None:
    seen: list = []
    with pytest.raises(drafting.DraftingNotAuthorised, match="Hindi"):
        run("kc", [GOOD_KC], seen, subject="hindi")
    for url in ("https://api.groq.com", "http://10.0.0.5:11434", "http://example.org"):
        with pytest.raises(drafting.DraftingNotAuthorised, match="local"):
            drafting.OllamaChat(base_url=url)
    assert seen == []


def test_authorised_synthetic_draft_is_needs_review_with_provenance() -> None:
    seen: list = []
    result = run("kc", [GOOD_KC], seen)
    assert len(seen) == 1 and seen[0].url.host == "localhost"
    payload = json.loads(seen[0].content)
    assert payload["think"] is False and payload["options"]["num_ctx"] == 4096
    assert payload["model"] == "qwen3.5:9b" and payload["stream"] is False
    row = result.rows[0]
    assert row["origin"] == "ai_drafted" and row["review_status"] == "needs_review"
    assert row["author_id"] == "" and row["review_record_ids"] == ""
    assert row["origin_ref"] == result.generation["generation_id"]
    assert "synthetic passage" not in json.dumps(result.generation)  # no source text stored


@pytest.mark.parametrize(
    "candidate, code",
    [
        ({**GOOD_KC, "review_status": "approved"}, "AI_FIELD_VIOLATION"),
        ({**GOOD_KC, "reviewer_id": "RV-002"}, "AI_FIELD_VIOLATION"),
        ({**GOOD_KC, "stable_key": "mathematics.new-domain.x"}, "UNKNOWN_DOMAIN"),
        ({**GOOD_KC, "kc_type": "skill"}, "INVALID_KC_TYPE"),
        ({**GOOD_KC, "source_refs": ["src:SRC-C07-MAT-EXMP1-01@9"]}, "INVALID_SOURCE_REF"),
    ],
)
def test_invalid_drafts_are_discarded_never_repaired(candidate: dict, code: str) -> None:
    result = run("kc", [candidate], [])
    assert result.rows == [] and code in result.discarded[0]["codes"]


def test_edge_drafts_never_use_chapter_order() -> None:
    edge = {
        "prerequisite_kc_id": "KC-MAT-00001",
        "dependent_kc_id": "KC-MAT-00002",
        "dependency_basis": "chapter_order",
        "reason": "Comes first.",
        "evidence_refs": [TOKEN],
    }
    result = run("edge", [edge], [])
    assert result.rows == [] and "FORBIDDEN_BASIS" in result.discarded[0]["codes"]
    ok = run(
        "edge",
        [
            {
                **edge,
                "dependency_basis": "uses_concept",
                "reason": "Uses equivalence to rewrite fractions.",
            }
        ],
        [],
    )
    assert ok.rows[0]["review_status"] == "needs_review"


def test_no_external_provider_module_is_imported() -> None:
    assert "groq" not in sys.modules or not hasattr(drafting, "groq")
    source = drafting.__file__
    text = open(source, encoding="utf-8").read()
    assert "groq" not in text.lower().replace("no external provider", "")
