"""Validated storage inputs; unknown dates stay unknown and evidence stays attributed."""

from datetime import UTC, datetime
from typing import Annotated, Literal
from urllib.parse import urlsplit, urlunsplit

from pydantic import (
    AnyHttpUrl,
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    StringConstraints,
    field_validator,
    model_validator,
)

Nonempty = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
Championship = Literal["F1", "WEC", "WRC", "DTM"]
EntityKind = Literal[
    "driver", "crew", "car", "team", "manufacturer", "governing_body", "official", "organization"
]
EvidenceRelation = Literal["reports", "supports", "contradicts", "response", "correction"]
AssertionType = Literal[
    "reported", "allegation", "response", "investigation", "finding", "decision", "correction"
]


def utc(value: datetime | None) -> datetime | None:
    if value is not None:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("timestamps require an explicit timezone or UTC offset")
        return value.astimezone(UTC)
    return None


def timestamp(value: datetime | None) -> str | None:
    return utc(value).isoformat(timespec="microseconds") if value is not None else None


def canonical_url(value: AnyHttpUrl) -> str:
    if value.username or value.password:
        raise ValueError("source URLs must not contain credentials")
    parts = urlsplit(str(value))
    return urlunsplit((parts.scheme, parts.netloc, parts.path, parts.query, ""))


def safe_url(value: AnyHttpUrl) -> AnyHttpUrl:
    canonical_url(value)
    return value


class InputModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid", allow_inf_nan=False, frozen=True, revalidate_instances="always"
    )


class SourceInput(InputModel):
    key: Nonempty
    name: Nonempty
    url: AnyHttpUrl
    kind: Literal["official", "independent", "unknown"] = "unknown"
    upstream_source_id: Nonempty | None = None

    _url = field_validator("url")(safe_url)


class DocumentInput(InputModel):
    url: AnyHttpUrl
    content: bytes = Field(max_length=10 * 1024 * 1024)
    extracted_text: str = Field(max_length=10 * 1024 * 1024)
    title: Nonempty
    author: Nonempty | None = None
    published_at: datetime | None = None
    retrieved_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    source_timezone: Nonempty | None = None
    parser_version: Nonempty
    media_type: Nonempty = "text/plain"
    retrieval_method: Literal["manual", "http", "browser", "fixture"] = "manual"
    http_status: int | None = Field(default=None, ge=100, le=599)

    _url = field_validator("url")(safe_url)
    _dates = field_validator("published_at", "retrieved_at")(utc)

    @model_validator(mode="before")
    @classmethod
    def retain_source_timezone(cls, values):
        if isinstance(values, dict) and values.get("source_timezone") is None:
            published = values.get("published_at")
            if isinstance(published, str):
                try:
                    published = datetime.fromisoformat(published)
                except ValueError:
                    published = None
            if isinstance(published, datetime) and published.tzinfo is not None:
                label = getattr(published.tzinfo, "key", None) or published.tzname()
                values = {**values, "source_timezone": label}
        return values

    @model_validator(mode="after")
    def observation(self):
        if self.retrieval_method in {"manual", "fixture"} and self.http_status is not None:
            raise ValueError("offline imports cannot claim an HTTP response status")
        if "\0" in self.extracted_text:
            raise ValueError("extracted text must not contain NUL characters")
        return self


class EntityInput(InputModel):
    kind: EntityKind
    name: Nonempty
    identity_key: Nonempty | None = None
    aliases: list[Nonempty] = Field(default_factory=list)
    championship: Championship | None = None


class EvidenceInput(InputModel):
    document_version_id: Nonempty
    quote: str = Field(min_length=1)
    start_offset: int | None = Field(default=None, ge=0)
    relation: EvidenceRelation = "reports"

    @field_validator("quote")
    @classmethod
    def substantial_quote(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("evidence must contain non-whitespace text")
        return value


class ClaimInput(EvidenceInput):
    statement: Nonempty
    assertion_type: AssertionType = "reported"
    asserted_by_entity_id: Nonempty | None = None
    entity_ids: list[Nonempty] = Field(default_factory=list)
    supersedes_claim_id: Nonempty | None = None
    extraction_run_id: Nonempty | None = None
    event_at: datetime | None = None
    effective_at: datetime | None = None

    _dates = field_validator("event_at", "effective_at")(utc)


class ExtractionRunInput(InputModel):
    document_version_id: Nonempty
    parser_version: Nonempty
    model_tag: Nonempty | None = None
    model_version: Nonempty | None = None
    prompt_version: Nonempty | None = None
    status: Literal["success", "failed"] = "success"

    @model_validator(mode="after")
    def model_provenance(self):
        if self.model_tag is not None and (
            self.model_version is None or self.prompt_version is None
        ):
            raise ValueError("model extraction requires both model_version and prompt_version")
        return self


class RecordInput(InputModel):
    kind: Literal[
        "season",
        "meeting",
        "session",
        "classification",
        "decision",
        "announcement",
        "controversy_case",
        "event",
        "report_snapshot",
    ]
    key: Nonempty
    title: Nonempty
    payload: dict[str, JsonValue] = Field(default_factory=dict)
    document_version_id: Nonempty | None = None
    issuer_entity_id: Nonempty | None = None
    jurisdiction: Nonempty | None = None
    championships: list[Championship] = Field(default_factory=list)
    entity_ids: list[Nonempty] = Field(default_factory=list)
    claim_ids: list[Nonempty] = Field(default_factory=list)
    related_versions: dict[Nonempty, Nonempty] = Field(default_factory=dict)
    case_status: (
        Literal["alleged", "under_investigation", "findings_issued", "under_appeal", "closed"]
        | None
    ) = None
    outcome: Literal["sanctioned", "cleared", "overturned", "unresolved"] | None = None
    published_at: datetime | None = None
    event_at: datetime | None = None
    effective_at: datetime | None = None
    parser_version: Nonempty

    _dates = field_validator("published_at", "event_at", "effective_at")(utc)

    @model_validator(mode="after")
    def evidence_and_status(self):
        if self.document_version_id is None and not self.claim_ids:
            raise ValueError("records require a source document version or evidence-linked claims")
        if self.kind == "controversy_case":
            if self.case_status is None:
                raise ValueError("controversy cases require an explicit procedural status")
            if self.case_status == "closed" and self.outcome is None:
                raise ValueError("closed cases require an explicit outcome")
        elif self.case_status is not None or self.outcome is not None:
            raise ValueError("case status and outcome apply only to controversy cases")
        return self


class FixtureClaim(InputModel):
    statement: Nonempty
    quote: str = Field(min_length=1)
    start_offset: int | None = Field(default=None, ge=0)
    assertion_type: AssertionType = "reported"


class EvidenceFixture(InputModel):
    source: SourceInput
    document: DocumentInput
    claims: list[FixtureClaim] = Field(default_factory=list)
