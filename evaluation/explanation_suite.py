# ruff: noqa: E501  (prompts and report text are prose)
"""Explanation and citation regression suite (live local model; AI-authored prompts).

    CONTENT_RELEASE_MODE=demo python -m evaluation.explanation_suite

Prompts are AI-authored (`ai_generated_unverified`), not teacher-authored, and are regression
cases only. Each prompt runs through the real pipeline (scoped retrieval -> rights gate ->
local model -> citation validation). Captured answers with their evidence are written to
`.local/evaluation/explanations_<stamp>.jsonl` for later human review (the explanation_case
schema). Deterministic checks only:

- abstention: unanswerable prompts must not return a grounded answer;
- citation validity: every cited label was supplied as evidence (none invented);
- lexical support proxy (`evaluation.citations`), reported as a proxy;
- language: a Hindi prompt gets a Devanagari answer;
- arithmetic consistency: every 'a op b = c' with plain numbers in the answer is correct;
- addresses the prompt (proxy): the answer shares content words with the prompt.

None of this shows an explanation is educationally correct; that needs independent review.
"""

from __future__ import annotations

import json
import re
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

from evaluation import citations
from evaluation.stats import rate

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / ".local/evaluation"
_DEV = re.compile("[ऀ-ॿ]")
_ARITH = re.compile(r"(-?\d+(?:\.\d+)?)\s*([+\-x×*/])\s*(-?\d+(?:\.\d+)?)\s*=\s*(-?\d+(?:\.\d+)?)")

PROMPTS = [
    # (id, prompt, class, subject, answerable)
    ("ex-01", "Why did the Raven lose its piece of food in the fable?", 6, "english", True),
    ("ex-02", "What is latitude and what is its range?", 6, "social_science", True),
    ("ex-03", "How were the Himalayas formed?", 7, "social_science", True),
    (
        "ex-04",
        "How do you write large numbers in the Indian place value system?",
        7,
        "mathematics",
        True,
    ),
    ("ex-05", "What is the difference between a mixture and a compound?", 8, "science", True),
    (
        "ex-06",
        "How do you find the cube root of a number using prime factorisation?",
        8,
        "mathematics",
        True,
    ),
    ("ex-07", "What does an entrepreneur do?", 9, "social_science", True),
    ("ex-08", "What is a combination reaction? Give an example.", 10, "science", True),
    ("ex-09", "What are the zeroes of a polynomial?", 10, "mathematics", True),
    ("ex-10", "Why is contour ploughing useful on hill slopes?", 10, "social_science", True),
    ("ex-11", "कविता 'मातृभूमि' में हिमालय का वर्णन कैसे किया गया है?", 6, "hindi", True),
    ("ex-12", "निबंध में विषय और भाव का क्या संबंध है?", 9, "hindi", True),
    ("ex-13", "Explain how a nuclear reactor produces electricity.", 10, "science", False),
    ("ex-14", "Who won the 2011 Cricket World Cup final?", 8, "social_science", False),
    ("ex-15", "What is the integral of sin x?", 9, "mathematics", False),
    ("ex-16", "मंगल ग्रह के कितने चंद्रमा हैं?", 7, "hindi", False),
]


def arithmetic_errors(text: str) -> list[str]:
    bad = []
    for a, op, b, c in _ARITH.findall(text):
        a, b, c = float(a), float(b), float(c)
        value = {
            "+": a + b,
            "-": a - b,
            "x": a * b,
            "×": a * b,
            "*": a * b,
            "/": a / b if b else None,
        }[op]
        if value is None or abs(value - c) > 1e-6 * max(1, abs(c)):
            bad.append(f"{a} {op} {b} = {c}")
    return bad


def run() -> dict:
    from sqlalchemy import func, select
    from sqlalchemy.orm import Session

    from app.core.content_release import demo_enabled
    from app.db.models import EmbeddingChunk
    from app.db.session import create_db_engine
    from app.services import ai_generation
    from app.services.embeddings import OllamaEmbedder
    from app.services.llm import build_llm
    from app.services.rag import RetrievalFilter, retrieve_evidence
    from app.services.rights import check_use

    embedder, llm = OllamaEmbedder("bge-m3"), build_llm()
    model_id = embedder.describe().model_id
    records = []
    with Session(create_db_engine(read_only=True)) as session:
        generation = session.scalar(select(func.min(EmbeddingChunk.index_generation)))
        mode = "demo" if demo_enabled() else "student"
        for pid, prompt, level, subject, answerable in PROMPTS:
            started = time.monotonic()
            evidence = retrieve_evidence(
                session,
                embedder.embed([prompt])[0],
                embedding_model_id=model_id,
                index_generation=generation,
                filters=RetrievalFilter(class_level=level, subject_id=subject),
                mode=mode,
                k=4,
            )
            result = ai_generation.generate_explanation(llm, prompt, evidence, check_use)
            answer = result.output if result.status == "ok" else {}
            text = " ".join([answer.get("explanation", ""), *answer.get("steps", [])])
            record = {
                "case_id": pid,
                "prompt": prompt,
                "class_level": level,
                "subject_id": subject,
                "language": "hi" if _DEV.search(prompt) else "en",
                "answerable_expected": answerable,
                "label_provenance": "ai_generated_unverified",
                "status": result.status,
                "abstained": result.status != "ok",
                "answer": answer,
                "evidence": [
                    {
                        "label": e.label,
                        "source_id": e.source_id,
                        "pdf_page_index": e.pdf_page_index,
                        "score": e.score,
                        "text": e.text,
                    }
                    for e in evidence
                ],
                "citations": [
                    {"source_id": c["source_id"], "pdf_page_index": c["pdf_page_index"]}
                    for c in result.citations
                ],
                "seconds": round(time.monotonic() - started, 1),
                "retrieval_mode": mode,
            }
            record["checks"] = citations.check_record(record)
            record["checks"]["arithmetic_errors"] = arithmetic_errors(text)
            record["checks"]["language_match"] = (not answer) or (
                bool(_DEV.search(text)) == (record["language"] == "hi")
            )
            prompt_words = citations.content_words(prompt)
            record["checks"]["shares_prompt_words"] = (not answer) or bool(
                prompt_words & citations.content_words(text)
            )
            records.append(record)
            print(f"{pid} {result.status} {record['seconds']}s", flush=True)
    answered = [r for r in records if not r["abstained"]]
    unanswerable = [r for r in records if not r["answerable_expected"]]
    return {
        "kind": "SYNTHETIC explanation regression (AI-authored prompts; deterministic checks only; not educational correctness)",
        "model": llm.identity().model_id if hasattr(llm.identity(), "model_id") else None,
        "retrieval_mode": records[0]["retrieval_mode"] if records else None,
        "prompts": len(records),
        "status_counts": {
            s: sum(1 for r in records if r["status"] == s)
            for s in sorted({r["status"] for r in records})
        },
        "unanswerable_abstained": rate(
            sum(r["abstained"] for r in unanswerable), len(unanswerable), 1
        ),
        "answerable_answered": rate(
            sum(not r["abstained"] for r in records if r["answerable_expected"]),
            sum(1 for r in records if r["answerable_expected"]),
            1,
        ),
        "answered_all_citations_valid": rate(
            sum(r["checks"]["all_cited_labels_were_supplied"] for r in answered), len(answered), 1
        ),
        "invented_labels": sum(len(r["checks"]["invented_labels"]) for r in answered),
        "arithmetic_errors": sum(len(r["checks"]["arithmetic_errors"]) for r in answered),
        "language_mismatch": sum(not r["checks"]["language_match"] for r in answered),
        "not_sharing_prompt_words": sum(not r["checks"]["shares_prompt_words"] for r in answered),
        "sentences_below_overlap_floor": sum(
            r["checks"].get("sentences_below_overlap_floor", 0) for r in answered
        ),
        "sentences_total": sum(r["checks"].get("sentences", 0) for r in answered),
        "records": records,
    }


def markdown(r: dict) -> str:
    def f(c):
        return (
            f"{c['count']}/{c['n']}"
            if c.get("status") == "measured"
            else f"{c.get('status')} (n={c.get('n')})"
        )

    lines = [
        "# Explanation and citation regression",
        "",
        f"**{r['kind']}.** Retrieval mode `{r['retrieval_mode']}`; {r['prompts']} prompts.",
        "",
        f"- Status counts: {r['status_counts']}",
        f"- Unanswerable prompts that abstained: {f(r['unanswerable_abstained'])}",
        f"- Answerable prompts that were answered: {f(r['answerable_answered'])}",
        f"- Answers whose cited labels were all supplied evidence: {f(r['answered_all_citations_valid'])}; invented labels: {r['invented_labels']}",
        f"- Arithmetic inconsistencies: {r['arithmetic_errors']}; language mismatches: {r['language_mismatch']}; answers sharing no words with the prompt: {r['not_sharing_prompt_words']}",
        f"- Lexical-support proxy: {r['sentences_below_overlap_floor']} of {r['sentences_total']} answer sentences below the overlap floor (proxy, not support)",
        "",
        "| case | lang | expected | status | cited pages | seconds |",
        "|---|---|---|---|---|---|",
    ]
    for rec in r["records"]:
        cited = (
            ", ".join(f"{c['source_id']} p{c['pdf_page_index']}" for c in rec["citations"]) or "-"
        )
        lines.append(
            f"| {rec['case_id']} | {rec['language']} | {'answerable' if rec['answerable_expected'] else 'unanswerable'} | {rec['status']} | {cited} | {rec['seconds']} |"
        )
    lines += [
        "",
        "Captured answers are for independent human review; nothing here judges whether they are correct.",
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    report = run()
    OUT.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    with (OUT / f"explanations_{stamp}.jsonl").open("w", encoding="utf-8") as fh:
        for rec in report["records"]:
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
    summary = {k: v for k, v in report.items() if k != "records"}
    (OUT / "reports").mkdir(parents=True, exist_ok=True)
    (OUT / "reports" / f"explanation_suite_{stamp}.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False) + "\n"
    )
    (OUT / "reports" / f"explanation_suite_{stamp}.md").write_text(markdown(report))
    print(markdown(report))
    return 0


if __name__ == "__main__":
    sys.exit(main())
