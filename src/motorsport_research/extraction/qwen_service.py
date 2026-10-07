"""One manual inference at a time; durable pending work and atomic reviewed claims."""

import json
import time
from datetime import UTC, datetime, timedelta

from motorsport_research.config import Settings
from motorsport_research.extraction.qwen_client import InferenceError, QwenClient
from motorsport_research.extraction.qwen_models import PIPELINE_VERSION, PROMPT_VERSION
from motorsport_research.extraction.qwen_validation import chunks, validate_output
from motorsport_research.extraction.service import ArticleService
from motorsport_research.storage.database import StorageError
from motorsport_research.storage.models import (
    ClaimInput,
    EvidenceInput,
    ExtractionRunInput,
    timestamp,
)
from motorsport_research.storage.repository import fingerprint, identifier, now, open_repository

TRANSIENT = {"unavailable", "timeout", "model_missing"}


class QwenService:
    def __init__(self, settings: Settings, *, client=None):
        self.settings = settings
        self.data_dir = settings.data_dir
        self.client = client or QwenClient(settings)

    def _config(self):
        return {
            "ollama_base_url": str(self.settings.ollama_base_url),
            "ollama_model": self.settings.ollama_model,
            "ollama_timeout_seconds": self.settings.ollama_timeout_seconds,
            "qwen_timeout_seconds": self.settings.qwen_timeout_seconds,
            "qwen_max_input_bytes": self.settings.qwen_max_input_bytes,
            "qwen_max_output_tokens": self.settings.qwen_max_output_tokens,
            "qwen_max_attempts": self.settings.qwen_max_attempts,
            "qwen_max_chunks": self.settings.qwen_max_chunks,
            "num_ctx": 8192,
            "temperature": 0,
            "seed": 0,
            "think": False,
        }

    def extract(self, article_id, *, new_run=False):
        article = ArticleService(self.data_dir).detail(article_id)
        if article["relevance"]["status"] != "relevant":
            raise ValueError(
                "Irrelevant articles are retained for review, not automatic extraction"
            )
        groups = chunks(article, self.settings)
        config = self._config()
        request_hash = fingerprint(
            {
                "article_id": article_id,
                "config": config,
                "prompt": PROMPT_VERSION,
                "pipeline": PIPELINE_VERSION,
                "new_run": identifier("run") if new_run else None,
            }
        )
        with open_repository(self.data_dir) as repo:
            existing = repo.connection.execute(
                "SELECT id FROM qwen_tasks WHERE request_hash = ?", (request_hash,)
            ).fetchone()
            task_id = existing["id"] if existing else identifier("qwen_task")
            if not existing:
                repo.connection.execute(
                    "INSERT INTO qwen_tasks VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        task_id,
                        request_hash,
                        article_id,
                        self.settings.ollama_model,
                        None,
                        PROMPT_VERSION,
                        PIPELINE_VERSION,
                        json.dumps(config),
                        "pending",
                        None,
                        None,
                        None,
                        None,
                        now(),
                        now(),
                    ),
                )
                for position, group in enumerate(groups):
                    repo.connection.execute(
                        "INSERT INTO qwen_chunks VALUES (?, ?, ?, ?, NULL)",
                        (
                            task_id,
                            position,
                            json.dumps(group, ensure_ascii=False),
                            fingerprint(group),
                        ),
                    )
        return self.retry(task_id)

    def _lease(self, task_id):
        owner = identifier("inference_owner")
        with open_repository(self.data_dir) as repo:
            instant = now()
            repo.connection.execute(
                "UPDATE qwen_tasks SET status = 'pending', owner = NULL, "
                "lease_until = NULL, detail = 'Expired inference lease; retry required', "
                "updated_at = ? "
                "WHERE status = 'running' AND lease_until <= ?",
                (instant, instant),
            )
            task = dict(repo._require("qwen_tasks", task_id))
            if task["status"] in {"completed", "failed"}:
                return None
            if task["retry_at"] and task["retry_at"] > instant:
                return None
            active = repo.connection.execute(
                "SELECT id FROM qwen_tasks WHERE status = 'running' AND lease_until > ?", (instant,)
            ).fetchone()
            if active:
                raise StorageError(
                    "Another extraction is running; wait for its bounded request/lease"
                )
            repo.connection.execute(
                "UPDATE qwen_tasks SET status = 'running', owner = ?, lease_until = ?, "
                "updated_at = ? WHERE id = ?",
                (owner, self._expires(), instant, task_id),
            )
            return owner

    def _expires(self):
        return timestamp(
            datetime.now(UTC)
            + timedelta(
                seconds=2 * self.settings.qwen_timeout_seconds
                + 4 * self.settings.ollama_timeout_seconds
                + 30
            )
        )

    def _owned(self, repo, task_id, owner):
        task = dict(repo._require("qwen_tasks", task_id))
        if task["owner"] != owner or task["status"] != "running" or task["lease_until"] <= now():
            raise StorageError("Inference lease was lost; no claims committed")
        return task

    def _touch(self, task_id, owner):
        with open_repository(self.data_dir) as repo:
            self._owned(repo, task_id, owner)
            repo.connection.execute(
                "UPDATE qwen_tasks SET lease_until = ?, updated_at = ? WHERE id = ?",
                (self._expires(), now(), task_id),
            )

    def _attempt(
        self,
        task_id,
        owner,
        position,
        digest,
        outcome,
        *,
        raw=b"",
        metrics=None,
        elapsed=0,
        detail=None,
        result=None,
    ):
        with open_repository(self.data_dir) as repo:
            self._owned(repo, task_id, owner)
            response_hash = repo.blobs.put(raw) if raw else None
            repo.connection.execute(
                "INSERT INTO qwen_attempts VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    identifier("qwen_attempt"),
                    task_id,
                    position,
                    digest,
                    outcome,
                    response_hash,
                    json.dumps(metrics or {}),
                    elapsed,
                    detail,
                    now(),
                ),
            )
            if result is not None:
                repo.connection.execute(
                    "UPDATE qwen_chunks SET result_json = ? WHERE task_id = ? AND position = ? "
                    "AND result_json IS NULL",
                    (json.dumps(result, ensure_ascii=False), task_id, position),
                )

    def _finish(self, task_id, owner, status, detail=None):
        with open_repository(self.data_dir) as repo:
            self._owned(repo, task_id, owner)
            retry_at = (
                timestamp(datetime.now(UTC) + timedelta(seconds=30))
                if status == "pending"
                else None
            )
            repo.connection.execute(
                "UPDATE qwen_tasks SET status = ?, owner = NULL, lease_until = NULL, "
                "retry_at = ?, detail = ?, updated_at = ? WHERE id = ?",
                (status, retry_at, detail, now(), task_id),
            )

    def retry(self, task_id):
        with open_repository(self.data_dir, read_only=True) as repo:
            task = dict(repo._require("qwen_tasks", task_id))
        if json.loads(task["config_json"]) != self._config():
            raise ValueError(
                "Retry requires the original endpoint/model/settings; "
                "start a new run to change them"
            )
        article = ArticleService(self.data_dir).detail(task["article_id"])
        owner = self._lease(task_id)
        if owner is None:
            return self.detail(task_id)
        started = time.monotonic()
        try:
            digest = self.client.model_digest()
            with open_repository(self.data_dir) as repo:
                task = self._owned(repo, task_id, owner)
                if task["model_digest"] and task["model_digest"] != digest:
                    raise InferenceError(
                        "model_changed", "Pinned model changed; start an explicit new run"
                    )
                repo.connection.execute(
                    "UPDATE qwen_tasks SET model_digest = ? WHERE id = ?", (digest, task_id)
                )
                work = [
                    dict(row)
                    for row in repo.connection.execute(
                        "SELECT * FROM qwen_chunks WHERE task_id = ? ORDER BY position", (task_id,)
                    )
                ]
            for chunk in work:
                if chunk["result_json"] is not None:
                    continue
                group = json.loads(chunk["input_json"])
                if fingerprint(group) != chunk["input_hash"]:
                    raise StorageError("Stored inference input differs from its hash")
                while True:
                    with open_repository(self.data_dir, read_only=True) as repo:
                        failures = repo.connection.execute(
                            "SELECT count(*) FROM qwen_attempts WHERE task_id = ? "
                            "AND chunk_position = ? "
                            "AND outcome IN ('invalid_response', 'invalid_evidence')",
                            (task_id, chunk["position"]),
                        ).fetchone()[0]
                    if failures >= self.settings.qwen_max_attempts:
                        self._finish(
                            task_id,
                            owner,
                            "failed",
                            "Invalid completion retry budget exhausted; review required",
                        )
                        return self.detail(task_id)
                    self._touch(task_id, owner)
                    request_started = time.monotonic()
                    response = None
                    try:
                        if self.client.model_digest() != digest:
                            raise InferenceError("model_changed", "Model changed before request")
                        response = self.client.chat(group["payload"])
                        if self.client.model_digest() != digest:
                            raise InferenceError("model_changed", "Model changed during request")
                        with open_repository(self.data_dir, read_only=True) as repo:
                            result = validate_output(response.parsed, group, article, repo)
                        self._attempt(
                            task_id,
                            owner,
                            chunk["position"],
                            digest,
                            "validated",
                            raw=response.raw,
                            metrics=response.metrics,
                            elapsed=time.monotonic() - request_started,
                            result=result,
                        )
                        break
                    except InferenceError as error:
                        self._attempt(
                            task_id,
                            owner,
                            chunk["position"],
                            digest,
                            error.outcome,
                            raw=response.raw if response else error.raw,
                            metrics=response.metrics if response else error.metrics,
                            elapsed=time.monotonic() - request_started,
                            detail=str(error),
                        )
                        if error.outcome in TRANSIENT or error.outcome == "model_changed":
                            self._finish(
                                task_id,
                                owner,
                                "pending" if error.outcome in TRANSIENT else "failed",
                                str(error),
                            )
                            return self.detail(task_id)
            # A whole-article run either commits all claims or none of them.
            with open_repository(self.data_dir) as repo:
                self._owned(repo, task_id, owner)
                run_id = repo.record_extraction(
                    ExtractionRunInput(
                        document_version_id=article["origin"]["document_version_id"],
                        parser_version=PIPELINE_VERSION,
                        model_tag=task["model_tag"],
                        model_version=digest,
                        prompt_version=PROMPT_VERSION,
                    )
                )
                for chunk in repo.connection.execute(
                    "SELECT result_json FROM qwen_chunks WHERE task_id = ? ORDER BY position",
                    (task_id,),
                ):
                    if chunk["result_json"] is None:
                        raise StorageError("Cannot commit incomplete article extraction")
                    for result in json.loads(chunk["result_json"]):
                        evidence = result["evidence"]
                        primary = evidence[0]
                        claim_id = repo.record_claim(
                            ClaimInput(
                                document_version_id=article["origin"]["document_version_id"],
                                statement=result["quote"],
                                quote=primary["quote"],
                                start_offset=primary["start_offset"],
                                assertion_type=result["assertion_type"],
                                extraction_run_id=run_id,
                            )
                        )
                        for span in evidence[1:]:
                            repo.add_evidence(
                                claim_id,
                                EvidenceInput(
                                    document_version_id=article["origin"]["document_version_id"],
                                    **span,
                                ),
                            )
                        repo.connection.execute(
                            "INSERT OR IGNORE INTO qwen_claims VALUES (?, ?, ?, ?)",
                            (task_id, claim_id, run_id, json.dumps(result, ensure_ascii=False)),
                        )
                repo.connection.execute(
                    "UPDATE qwen_tasks SET status = 'completed', owner = NULL, "
                    "lease_until = NULL, retry_at = NULL, "
                    "detail = 'Validated source selections; human review required', "
                    "updated_at = ? WHERE id = ?",
                    (now(), task_id),
                )
            return self.detail(task_id)
        except InferenceError as error:
            self._attempt(
                task_id,
                owner,
                None,
                task.get("model_digest"),
                error.outcome,
                raw=error.raw,
                elapsed=time.monotonic() - started,
                detail=str(error),
            )
            self._finish(
                task_id, owner, "pending" if error.outcome in TRANSIENT else "failed", str(error)
            )
            return self.detail(task_id)
        except Exception:
            # Keep operational errors retryable; transaction rollback prevents partial claims.
            self._finish(
                task_id, owner, "pending", "Operational failure; inspect storage and retry"
            )
            raise

    def detail(self, task_id):
        with open_repository(self.data_dir, read_only=True) as repo:
            task = dict(repo._require("qwen_tasks", task_id))
            task["config"] = json.loads(task.pop("config_json"))
            task.pop("owner")
            task["attempts"] = [
                {**dict(row), "metrics": json.loads(row["metrics_json"])}
                for row in repo.connection.execute(
                    "SELECT * FROM qwen_attempts WHERE task_id = ? ORDER BY created_at, rowid",
                    (task_id,),
                )
            ]
            task["claims"] = [
                {
                    "claim_id": row["claim_id"],
                    "extraction_run_id": row["extraction_run_id"],
                    "metadata": json.loads(row["metadata_json"]),
                }
                for row in repo.connection.execute(
                    "SELECT * FROM qwen_claims WHERE task_id = ? ORDER BY rowid", (task_id,)
                )
            ]
            task["chunk_count"] = repo.connection.execute(
                "SELECT count(*) FROM qwen_chunks WHERE task_id = ?", (task_id,)
            ).fetchone()[0]
            task["validated_chunks"] = repo.connection.execute(
                "SELECT count(*) FROM qwen_chunks WHERE task_id = ? AND result_json IS NOT NULL",
                (task_id,),
            ).fetchone()[0]
            task["review_required"] = True
            return task

    def status(self, *, limit=50, offset=0):
        if not 1 <= limit <= 100 or offset < 0:
            raise ValueError("Use limit 1..100 and nonnegative offset")
        with open_repository(self.data_dir, read_only=True) as repo:
            return {
                "counts": {
                    row["status"]: row["n"]
                    for row in repo.connection.execute(
                        "SELECT status, count(*) AS n FROM qwen_tasks GROUP BY status"
                    )
                },
                "tasks": [
                    dict(row)
                    for row in repo.connection.execute(
                        "SELECT id, article_id, model_tag, model_digest, status, retry_at, "
                        "detail, updated_at FROM qwen_tasks "
                        "ORDER BY created_at DESC, rowid DESC LIMIT ? OFFSET ?",
                        (limit, offset),
                    )
                ],
            }
