"""Explicit, attributed sources; configured coverage is not observed connectivity."""

import hashlib
import json
from pathlib import Path
from typing import Annotated, Literal

import yaml
from pydantic import AnyHttpUrl, Field, StringConstraints, field_validator, model_validator

from motorsport_research.storage.models import (
    Championship,
    InputModel,
    Nonempty,
    SourceInput,
    canonical_url,
    safe_url,
)


class CatalogueError(ValueError):
    pass


class SourceDefinition(InputModel):
    key: Annotated[str, StringConstraints(pattern=r"^[a-z0-9][a-z0-9_-]{0,79}$")]
    name: Nonempty
    homepage: AnyHttpUrl
    url: AnyHttpUrl
    kind: Literal["official", "independent", "unknown"]
    role: Literal["championship", "governing_body", "team", "newsroom"]
    publisher: Nonempty
    issuing_body: Nonempty | None = None
    upstream_key: Nonempty | None = None
    championships: list[Championship] = Field(default_factory=list)
    topics: list[Nonempty] = Field(default_factory=list)
    language: Literal["en"] = "en"
    method: Literal["rss", "http", "browser"]
    enabled: bool = True
    availability: Literal["unverified", "usable", "access_denied", "needs_browser", "unsupported"]
    notes: Nonempty
    refresh_seconds: int = Field(default=1800, ge=60, le=604800)
    host_interval_seconds: float = Field(default=2, ge=0.1, le=60)
    timeout_seconds: float = Field(default=10, gt=0, le=30)
    total_seconds: float = Field(default=45, gt=0, le=60)
    max_bytes: int = Field(default=2 * 1024 * 1024, ge=1024, le=10 * 1024 * 1024)
    max_attempts: int = Field(default=2, ge=1, le=3)
    max_redirects: int = Field(default=4, ge=0, le=8)
    allowed_hosts: list[Nonempty] = Field(default_factory=list)

    _urls = field_validator("url", "homepage")(safe_url)

    @field_validator("allowed_hosts")
    @classmethod
    def hostnames(cls, hosts):
        for host in hosts:
            if host != host.lower() or any(c in host for c in "/:@* "):
                raise ValueError("redirect hosts must be exact lowercase hostnames")
        return hosts

    @model_validator(mode="after")
    def routing(self):
        if self.allowed_hosts and self.url.host not in self.allowed_hosts:
            raise ValueError("allowed_hosts must include the source endpoint host")
        return self

    @property
    def hosts(self) -> set[str]:
        return set(self.allowed_hosts) or {self.url.host}

    @property
    def digest(self) -> str:
        value = json.dumps(self.model_dump(mode="json"), sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(value.encode()).hexdigest()

    def attribution(self, upstream_source_id: str | None = None) -> SourceInput:
        return SourceInput(
            key=self.key,
            name=self.name,
            url=self.homepage,
            kind=self.kind,
            upstream_source_id=upstream_source_id,
        )


class Catalogue(InputModel):
    schema_version: Literal[1] = 1
    sources: list[SourceDefinition] = Field(max_length=2000)

    @model_validator(mode="after")
    def identities(self):
        by_key = {source.key: source for source in self.sources}
        if len(by_key) != len(self.sources):
            raise ValueError("source keys must be unique")
        for source in self.sources:
            seen = {source.key}
            upstream = source.upstream_key
            while upstream is not None:
                if upstream not in by_key:
                    raise ValueError("upstream source must exist in the catalogue")
                if upstream in seen:
                    raise ValueError("upstream source links must not contain cycles")
                seen.add(upstream)
                upstream = by_key[upstream].upstream_key
        return self

    def select(self, keys: list[str] | None = None) -> list[SourceDefinition]:
        if not keys:
            return [source for source in self.sources if source.enabled]
        missing = set(keys) - {source.key for source in self.sources}
        if missing:
            raise CatalogueError("Unknown source keys: " + ", ".join(sorted(missing)))
        return [source for source in self.sources if source.key in keys]


class UniqueKeyLoader(yaml.SafeLoader):
    """Reject ambiguous YAML rather than silently discarding a setting."""


def _mapping(loader, node, deep=False):
    mapping = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if key in mapping:
            raise CatalogueError("Duplicate YAML setting")
        mapping[key] = loader.construct_object(value_node, deep=deep)
    return mapping


UniqueKeyLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _mapping)


def load_catalogue(path: Path) -> Catalogue:
    from pydantic import ValidationError

    if path.stat().st_size > 256 * 1024:
        raise CatalogueError("Catalogue exceeds 256 KiB")
    try:
        return Catalogue.model_validate(
            yaml.load(path.read_text(encoding="utf-8"), UniqueKeyLoader)
        )
    except (yaml.YAMLError, ValidationError, TypeError, RecursionError) as error:
        raise CatalogueError("Invalid source catalogue; check its schema and YAML") from error


def endpoint(source: SourceDefinition) -> str:
    return canonical_url(source.url)
