"""Local evaluation artifacts with strict field scores and explicit pending outcomes."""

import hashlib
import json
import time
from collections import Counter
from pathlib import Path
from typing import Literal

from pydantic import Field

from motorsport_research.championships.json_data import decode
from motorsport_research.extraction.qwen_models import PROMPT_VERSION, SuggestedClaim
from motorsport_research.extraction.qwen_service import QwenService
from motorsport_research.extraction.service import ArticleService
from motorsport_research.storage.models import InputModel, Nonempty
from motorsport_research.storage.repository import now

FIELDS = (
    "quote",
    "assertion_type",
    "asserted_by",
    "championships",
    "topic",
    "entities",
    "dates",
    "numbers",
    "uncertainty",
)


class ExpectedClaim(SuggestedClaim):
    passage_id: str = "p00000"


class EvaluationCase(InputModel):
    key: Nonempty
    manifest: Nonempty
    expected: list[ExpectedClaim] = Field(max_length=100)


class Dataset(InputModel):
    schema_version: Literal[1] = 1
    split: Literal["development", "heldout"]
    cases: list[EvaluationCase] = Field(min_length=1, max_length=100)


def _value(claim, field):
    value = claim[field]
    if isinstance(value, list):
        return sorted(json.dumps(v, sort_keys=True, ensure_ascii=False) for v in value)
    return value


def scores(expected, predicted):
    def key(claim):
        return json.dumps({f: _value(claim, f) for f in FIELDS}, sort_keys=True)

    gold = Counter(key(c) for c in expected)
    actual = Counter(key(c) for c in predicted)
    tp = sum((gold & actual).values())
    fp, fn = sum(actual.values()) - tp, sum(gold.values()) - tp
    paired_gold = {c["quote"]: c for c in expected}
    matched = [c for c in predicted if c["quote"] in paired_gold]
    return {
        "true_positive": tp,
        "false_positive": fp,
        "false_negative": fn,
        "precision": tp / (tp + fp) if tp + fp else None,
        "recall": tp / (tp + fn) if tp + fn else None,
        "field_accuracy_for_matched_quotes": {
            field: {
                "correct": sum(
                    _value(c, field) == _value(paired_gold[c["quote"]], field) for c in matched
                ),
                "total": len(matched),
            }
            for field in FIELDS
            if field != "quote"
        },
    }


def aggregate_scores(case_scores):
    # Matches belong to their own document; identical quotes in different cases
    # must not let swapped labels cancel each other's extraction errors.
    totals = {
        key: sum(score[key] for score in case_scores)
        for key in ("true_positive", "false_positive", "false_negative")
    }
    tp, fp, fn = (totals[key] for key in totals)
    return {
        **totals,
        "precision": tp / (tp + fp) if tp + fp else None,
        "recall": tp / (tp + fn) if tp + fn else None,
        "field_accuracy_for_matched_quotes": {
            field: {
                metric: sum(
                    score["field_accuracy_for_matched_quotes"][field][metric]
                    for score in case_scores
                )
                for metric in ("correct", "total")
            }
            for field in FIELDS
            if field != "quote"
        },
    }


def evaluate(settings, dataset_path: Path, output_path: Path, hardware: str, *, service=None):
    if not hardware.strip() or len(hardware) > 2000:
        raise ValueError("Provide a short hardware description: OS, CPU, GPU/VRAM and RAM")
    if dataset_path.stat().st_size > 256 * 1024:
        raise ValueError("Evaluation dataset exceeds 256 KiB")
    if output_path.exists():
        raise ValueError("Evaluation output already exists; choose a new artifact path")
    raw = dataset_path.read_bytes()
    dataset = Dataset.model_validate(decode(raw))
    if len({case.key for case in dataset.cases}) != len(dataset.cases):
        raise ValueError("Dataset case keys must be unique")
    root = dataset_path.parent.resolve()
    paths = []
    for case in dataset.cases:
        path = (root / case.manifest).resolve()
        if not path.is_relative_to(root):
            raise ValueError("Evaluation manifests must be below the dataset directory")
        paths.append(path)
    svc = service or QwenService(settings)
    started = time.monotonic()
    results = []
    for case, path in zip(dataset.cases, paths, strict=True):
        receipt = ArticleService(settings.data_dir).import_manifest(path)
        expected = [claim.model_dump(mode="json") for claim in case.expected]
        if receipt["outcome"] == "irrelevant":
            task = None
            status = "irrelevant"
            predicted = []
        elif receipt["outcome"] == "relevant":
            task = svc.extract(receipt["article_id"], new_run=True)
            status = task["status"]
            predicted = [claim["metadata"] for claim in task["claims"]]
        else:
            task, predicted, status = None, [], receipt["outcome"]
        results.append(
            {
                "key": case.key,
                "status": status,
                "article_id": receipt["article_id"],
                "task_id": task["id"] if task else None,
                "model_digest": task["model_digest"] if task else None,
                "attempts": task["attempts"] if task else [],
                "expected": expected,
                "predicted": predicted,
                "scores": scores(expected, predicted),
            }
        )
    elapsed = time.monotonic() - started
    completed = sum(row["status"] == "completed" for row in results)
    tokens = sum(a["metrics"].get("eval_count", 0) for r in results for a in r["attempts"])
    eval_ns = sum(a["metrics"].get("eval_duration", 0) for r in results for a in r["attempts"])
    artifact = {
        "schema_version": 1,
        "created_at": now(),
        "split": dataset.split,
        "dataset_sha256": hashlib.sha256(raw).hexdigest(),
        "hardware_self_reported": hardware,
        "model_tag": settings.ollama_model,
        "prompt_version": PROMPT_VERSION,
        "model_digests": sorted({r["model_digest"] for r in results if r["model_digest"]}),
        "all_cases_finished": all(r["status"] in {"completed", "irrelevant"} for r in results),
        "completed_inference_cases": completed,
        "case_count": len(results),
        "elapsed_seconds": elapsed,
        "completed_articles_per_minute": completed * 60 / elapsed if elapsed else None,
        "server_generated_tokens": tokens,
        "server_tokens_per_second": tokens * 1e9 / eval_ns if eval_ns else None,
        "strict_field_scores": aggregate_scores([result["scores"] for result in results]),
        "cases": results,
        "automatic_handling_approved": False,
        "interpretation": "Strict passage/field agreement with manual labels; "
        "not truth verification. "
        "Pending/failed cases are not successful inference. Hardware is self-reported. "
        "Automatic handling requires a separate reviewed held-out evaluation.",
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("x", encoding="utf-8") as file:
        json.dump(artifact, file, indent=2, ensure_ascii=False)
        file.write("\n")
    return {
        "output": str(output_path),
        "all_cases_finished": artifact["all_cases_finished"],
        "completed_inference_cases": completed,
        "case_count": len(results),
        "strict_field_scores": artifact["strict_field_scores"],
        "automatic_handling_approved": False,
    }
