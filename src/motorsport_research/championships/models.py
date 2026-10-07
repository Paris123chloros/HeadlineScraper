"""Published sporting records, with explicit scope and no derived championship scoring."""

from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Annotated, Literal

from pydantic import Field, StringConstraints, field_validator, model_validator

from motorsport_research.storage.models import Championship, InputModel, Nonempty

Key = Annotated[str, StringConstraints(pattern=r"^[a-z0-9][a-z0-9_-]{0,99}$")]
SessionKind = Literal[
    "practice", "qualifying", "hyperpole", "sprint", "race", "rally", "stage", "warmup"
]
ClassificationState = Literal["published", "provisional", "final", "amended"]


class RaceContext(InputModel):
    kind: Literal["classification"] = "classification"
    adapter: Literal["f1-html", "wec-csv", "wec-class-bundle", "wrc-json", "dtm-json", "fia-f1-pdf"]
    championship: Championship
    season: int = Field(ge=1950, le=2100)
    meeting_key: Key
    meeting_name: Nonempty
    session: SessionKind
    session_number: int = Field(default=1, ge=1, le=100)
    category_scope: Nonempty | None = None
    expected_entries: int = Field(ge=1, le=500)
    event_date: date | None = None
    context_quote: Nonempty

    @model_validator(mode="after")
    def scope(self):
        expected = {
            "f1-html": "F1",
            "fia-f1-pdf": "F1",
            "wec-csv": "WEC",
            "wec-class-bundle": "WEC",
            "wrc-json": "WRC",
            "dtm-json": "DTM",
        }
        if expected[self.adapter] != self.championship:
            raise ValueError("adapter does not match the championship")
        allowed = {
            "F1": {"practice", "qualifying", "sprint", "race"},
            "WEC": {"practice", "qualifying", "hyperpole", "race"},
            "WRC": {"stage", "rally"},
            "DTM": {"practice", "qualifying", "race", "warmup"},
        }
        if self.session not in allowed[self.championship]:
            raise ValueError("session type does not belong to the championship")
        if (
            self.championship == "DTM"
            and self.session == "race"
            and self.session_number not in {1, 2}
        ):
            raise ValueError("DTM race identity must distinguish race one and race two")
        return self

    @property
    def meeting_identity(self) -> str:
        return f"{self.championship.lower()}:{self.season}:{self.meeting_key}"

    @property
    def session_identity(self) -> str:
        return f"{self.meeting_identity}:{self.session}:{self.session_number}"

    @property
    def record_key(self) -> str:
        return f"{self.session_identity}:{self.category_scope or 'overall'}"


class PublishedResult(InputModel):
    entry_number: Nonempty
    position_raw: Nonempty
    overall_position: int | None = Field(default=None, ge=1)
    class_position: int | None = Field(default=None, ge=1)
    category: Nonempty | None = None
    drivers: list[Nonempty] = Field(default_factory=list, max_length=5)
    co_driver: Nonempty | None = None
    driver_code: Nonempty | None = None
    team: Nonempty | None = None
    manufacturer: Nonempty | None = None
    manufacturer_basis: Literal["publisher_field", "vehicle_prefix", "unknown"] = "unknown"
    vehicle: Nonempty | None = None
    laps: int | None = Field(default=None, ge=0)
    time_raw: Nonempty | None = None
    gap_raw: Nonempty | None = None
    status_raw: Nonempty | None = None
    status: Literal[
        "unknown", "classified", "not_classified", "retired", "disqualified", "did_not_start"
    ] = "unknown"
    restart_status: Literal["unknown", "restarted", "not_restarted"] = "unknown"
    points_raw: Nonempty | None = None
    timing: dict[Nonempty, str | None] = Field(default_factory=dict)
    published_fields: dict[Nonempty, str | None]
    quote: Nonempty
    start_offset: int = Field(ge=0)

    @field_validator("points_raw")
    @classmethod
    def published_points(cls, value):
        if value is not None:
            try:
                if not Decimal(value).is_finite():
                    raise ValueError("points must be finite")
            except InvalidOperation as error:
                raise ValueError("points must preserve a published decimal number") from error
        return value


class Classification(InputModel):
    context: RaceContext
    state: ClassificationState = "published"
    state_basis: Literal["document_text", "document_url", "unspecified"] = "unspecified"
    state_quote: str | None = None
    rows: list[PublishedResult] = Field(min_length=1, max_length=500)

    @model_validator(mode="after")
    def completeness(self):
        if len(self.rows) != self.context.expected_entries:
            raise ValueError("entry count differs from the reviewed official fixture/context")
        if len({row.entry_number for row in self.rows}) != len(self.rows):
            raise ValueError("classification contains duplicate entry numbers")
        if self.state != "published" and (
            self.state_basis == "unspecified" or not self.state_quote
        ):
            raise ValueError("formal classification status requires published evidence")
        if self.context.championship == "WEC" and any(
            not row.category or not row.drivers for row in self.rows
        ):
            raise ValueError("WEC results require class and crew attribution")
        if self.context.championship == "WRC" and any(
            not row.drivers or not row.co_driver or not row.category for row in self.rows
        ):
            raise ValueError("WRC results require driver, co-driver, and category")
        return self


class TextSelection(InputModel):
    quote: Nonempty
    start_offset: int | None = Field(default=None, ge=0)


class NoticeContext(InputModel):
    kind: Literal["decision", "announcement"]
    adapter: Literal["fia-notice"] = "fia-notice"
    key: Key
    title_quote: Nonempty
    title_start_offset: int | None = Field(default=None, ge=0)
    issuer: Nonempty
    jurisdiction: Nonempty
    championships: list[Championship] = Field(default_factory=list)
    notice_type: Literal[
        "regulation_change",
        "safety_update",
        "calendar_change",
        "governance_notice",
        "investigation_announced",
        "disciplinary_decision",
        "general_notice",
    ]
    statement: TextSelection
    procedural_status: (
        Literal[
            "investigation",
            "imposed",
            "appealed",
            "upheld",
            "overturned",
            "dismissed",
            "no_further_action",
        ]
        | None
    ) = None
    sanction: TextSelection | None = None
    procedural_status_evidence: TextSelection | None = None
    effective_date: date | None = None
    effective_date_quote: Nonempty | None = None
    published_date: date | None = None
    published_date_quote: Nonempty | None = None
    related_versions: dict[Nonempty, Nonempty] = Field(default_factory=dict)

    @model_validator(mode="after")
    def procedure(self):
        if self.procedural_status is not None and self.procedural_status_evidence is None:
            raise ValueError("procedural status requires an exact reviewed source passage")
        if self.kind == "decision" and self.procedural_status is None:
            raise ValueError("decisions require a procedural status")
        if self.notice_type == "investigation_announced" and self.procedural_status not in {
            None,
            "investigation",
        }:
            raise ValueError("an investigation announcement cannot assert a finding or sanction")
        if self.notice_type == "investigation_announced" and self.sanction is not None:
            raise ValueError("an investigation announcement cannot impose a sanction")
        if self.effective_date is not None and self.effective_date_quote is None:
            raise ValueError("effective dates require an exact source passage")
        if self.published_date is not None and self.published_date_quote is None:
            raise ValueError("publication dates require an exact source passage")
        return self


class StandingsContext(InputModel):
    kind: Literal["standings"] = "standings"
    adapter: Literal["f1-standings-html"] = "f1-standings-html"
    championship: Literal["F1"] = "F1"
    season: int = Field(ge=1950, le=2100)
    category: Literal["drivers", "teams"]
    expected_entries: int = Field(ge=1, le=500)
    context_quote: Nonempty


OfficialContext = Annotated[
    RaceContext | NoticeContext | StandingsContext, Field(discriminator="kind")
]
