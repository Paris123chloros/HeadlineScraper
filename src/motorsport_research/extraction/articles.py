"""Bounded HTML article extraction with spans into the archived collection text."""

import hashlib
import re
from dataclasses import dataclass, field
from datetime import datetime
from urllib.parse import urljoin, urlsplit

from pydantic import AnyHttpUrl

from motorsport_research.championships.json_data import decode
from motorsport_research.sources.parsers import PageText
from motorsport_research.storage.models import canonical_url, timestamp

PARSER_VERSION = "article:1"
MAX_BYTES = 10 * 1024 * 1024
BLOCKS = {"p", "li", "blockquote", "h2", "h3", "h4", "pre", "td", "th"}
VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "wbr"}
SKIP = {
    "nav",
    "aside",
    "footer",
    "form",
    "button",
    "script",
    "style",
    "noscript",
    "svg",
    "msnt-survey-promo",
}
FURNITURE = re.compile(
    r"(?:^|[\s_-])(?:cookie\w*|consent|advert\w*|related|recommended|newsletter|"
    r"social|share|sharing|breadcrumb\w*|paywall|subscribe|subscription|relatedContent)(?:$|[\s_-])",
    re.I,
)
BODY_CLASSES = {"article-body", "article-content", "ms-article-content", "field-name-body"}


class ArticleError(ValueError):
    def __init__(self, outcome: str, detail: str):
        self.outcome = outcome
        super().__init__(detail)


@dataclass(eq=False)
class Node:
    tag: str
    attrs: dict
    parent: "Node | None"
    parts: list = field(default_factory=list)

    def ancestors(self):
        node = self
        while node:
            yield node
            node = node.parent


class Tree(PageText):
    def __init__(self):
        super().__init__()
        self.root = Node("root", {}, None)
        self.current = self.root
        self.nodes = [self.root]
        self.fragments = []
        self.source_offset = 0
        self.depth = 0

    def handle_starttag(self, tag, attrs):
        super().handle_starttag(tag, attrs)
        if tag in {"p", "li"} and self.current.tag == tag:
            self.current = self.current.parent
            self.depth -= 1
        node = Node(tag, {name: value or "" for name, value in attrs}, self.current)
        self.current.parts.append(node)
        self.nodes.append(node)
        if len(self.nodes) > 100_000 or self.depth > 128:
            raise ArticleError("parser_failure", "HTML exceeds node/depth limits")
        if tag not in VOID:
            self.current = node
            self.depth += 1

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag not in VOID:
            self.handle_endtag(tag)

    def handle_endtag(self, tag):
        super().handle_endtag(tag)
        for node in self.current.ancestors():
            if node.tag == tag:
                self.current = node.parent or self.root
                self.depth = sum(1 for _ in self.current.ancestors()) - 1
                break

    def handle_data(self, data):
        previous = len(self.parts)
        super().handle_data(data)
        if len(self.parts) != previous:
            quote = self.parts[-1]
            fragment = {
                "quote": quote,
                "start_offset": self.source_offset,
                "end_offset": self.source_offset + len(quote),
            }
            self.current.parts.append(fragment)
            self.fragments.append((self.current, fragment))
            self.source_offset += len(quote) + 1
        elif self.current.tag == "script":
            self.current.parts.append(data)


def hidden(node):
    return any(
        ancestor.tag in SKIP
        or "hidden" in ancestor.attrs
        or ancestor.attrs.get("aria-hidden", "").lower() == "true"
        or re.search(
            r"display\s*:\s*none|visibility\s*:\s*hidden", ancestor.attrs.get("style", ""), re.I
        )
        or FURNITURE.search(ancestor.attrs.get("class", "") + " " + ancestor.attrs.get("id", ""))
        for ancestor in node.ancestors()
    )


def node_text(node):
    parts = []
    for part in node.parts:
        if isinstance(part, Node):
            if not hidden(part):
                parts.append(node_text(part))
        elif isinstance(part, dict):
            parts.append(part["quote"])
    return " ".join(" ".join(parts).split())


def safe_link(value, base_url):
    try:
        return canonical_url(AnyHttpUrl(urljoin(base_url, value)))
    except ValueError:
        return None


def date_metadata(candidates):
    """A calendar day or naive clock time never becomes an invented UTC instant."""
    parsed = []
    for candidate in candidates:
        raw = candidate["value"]
        item = dict(candidate, status="invalid", utc=None)
        try:
            if re.fullmatch(r"\d{4}-\d{2}-\d{2}", raw):
                datetime.fromisoformat(raw)
                item["status"] = "date_only"
            else:
                date = datetime.fromisoformat(raw.replace("Z", "+00:00"))
                if date.tzinfo is None:
                    item["status"] = "timezone_unknown"
                else:
                    item.update(status="exact", utc=timestamp(date), timezone=date.tzname())
        except (ValueError, TypeError, OverflowError):
            pass
        parsed.append(item)
    exact = {item["utc"] for item in parsed if item["utc"]}
    # Multiple different publisher values require review, even if only one is parseable.
    raw_values = {item["value"] for item in parsed}
    conflict = len(exact) > 1 or (
        len(raw_values) > 1 and any(item["status"] != "exact" for item in parsed)
    )
    status = "conflicting" if conflict else parsed[0]["status"] if parsed else "missing"
    value = next(iter(exact)) if len(exact) == 1 and not conflict else None
    return {"status": status, "utc": value, "candidates": parsed}


def _metadata(tree, roots, url, warnings):
    meta = {}
    structured = []
    for node in tree.nodes:
        if node.tag == "meta":
            key = (node.attrs.get("property") or node.attrs.get("name") or "").lower()
            if node.attrs.get("content"):
                meta.setdefault(key, []).append(node.attrs["content"].strip())
        if node.tag == "script" and node.attrs.get("type") == "application/ld+json":
            raw = "".join(part for part in node.parts if isinstance(part, str))
            try:
                if len(raw.encode()) > 256 * 1024:
                    raise ValueError("JSON-LD size limit")
                pending = [decode(raw)]
                visited = 0
                while pending:
                    visited += 1
                    if visited > 5000:
                        raise ValueError("JSON-LD node limit")
                    item = pending.pop()
                    if isinstance(item, list):
                        pending.extend(item)
                    elif isinstance(item, dict):
                        types = item.get("@type", [])
                        types = [types] if isinstance(types, str) else types
                        if isinstance(types, list) and any(
                            isinstance(t, str)
                            and t in {"Article", "NewsArticle", "BlogPosting", "OpinionNewsArticle"}
                            for t in types
                        ):
                            structured.append(item)
                        pending.extend(v for v in item.values() if isinstance(v, (list, dict)))
            except (ValueError, RecursionError):
                warnings.append("Invalid/oversized JSON-LD ignored; visible text retained")
    if len(structured) > 1:
        warnings.append("Multiple structured articles; JSON-LD metadata left unassigned")
    ld = structured[0] if len(structured) == 1 else {}
    titles = []
    body_titles = []
    for node in tree.nodes:
        if node.tag in {"h1", "h2"} and not hidden(node):
            inside = any(root in node.ancestors() for root in roots)
            fia_header = "article-header" in node.attrs.get("class", "").split()
            if inside or node.tag == "h1" or fia_header:
                text = node_text(node)
                if text:
                    titles.append(text)
                    if inside and node.tag == "h1":
                        body_titles.append(text)
    # FIA's title is a sibling of its body, wrapped in article-header.
    fia_titles = [
        node_text(n)
        for n in tree.nodes
        if "article-header" in n.attrs.get("class", "").split() and not hidden(n)
    ]
    title = (
        fia_titles
        or body_titles
        or meta.get("og:title")
        or ([ld["headline"]] if isinstance(ld.get("headline"), str) else [])
        or titles
        or [" ".join(tree.title)]
    )[0]
    if not title.strip():
        raise ArticleError("parser_failure", "Article has no title")
    dates = {}
    for field_name, keys, ld_key in (
        ("published", ("article:published_time", "datepublished"), "datePublished"),
        ("modified", ("article:modified_time", "og:updated_time"), "dateModified"),
    ):
        candidates = [
            {"source": key, "value": value} for key in keys for value in meta.get(key, [])
        ]
        if isinstance(ld.get(ld_key), str):
            candidates.append({"source": "jsonld:" + ld_key, "value": ld[ld_key]})
        for node in tree.nodes:
            if node.attrs.get("itemprop") == ld_key and not hidden(node):
                value = node.attrs.get("datetime") or node.attrs.get("content")
                if value:
                    candidates.append({"source": "itemprop:" + ld_key, "value": value})
        dates[field_name] = date_metadata(candidates)
    authors = [{"source": "meta:author", "name": value} for value in meta.get("author", [])]
    values = ld.get("author", [])
    values = values if isinstance(values, list) else [values]
    for value in values:
        name = value.get("name") if isinstance(value, dict) else value
        if isinstance(name, str) and name.strip():
            authors.append({"source": "jsonld:author", "name": name.strip()})
    for node in tree.nodes:
        if not hidden(node) and (
            node.attrs.get("itemprop") == "author" or node.attrs.get("rel") == "author"
        ):
            name = node_text(node)
            if name:
                authors.append({"source": "visible:author", "name": name})
    references = []
    for node in tree.nodes:
        if node.tag == "link" and "canonical" in node.attrs.get("rel", "").split():
            link = safe_link(node.attrs.get("href", ""), url)
            if link:
                references.append({"source": "rel:canonical", "url": link})
    return {
        "title": " ".join(title.split()),
        "authors": authors,
        "dates": dates,
        "canonical_references": references,
        "genre_metadata": meta.get("article:section", [])
        + ([ld["genre"]] if isinstance(ld.get("genre"), str) else []),
    }


def _assemble(groups, source_text):
    body = ""
    blocks = []
    for fragments in groups:
        clean = " ".join(" ".join(fragment["quote"].split()) for fragment in fragments)
        if not clean.strip():
            continue
        start = len(body) + (2 if body else 0)
        body += ("\n\n" if body else "") + clean
        spans = []
        position = start
        for fragment in fragments:
            if source_text[fragment["start_offset"] : fragment["end_offset"]] != fragment["quote"]:
                raise ArticleError("parser_failure", "Body span differs from archived source text")
            clean_fragment = " ".join(fragment["quote"].split())
            spans.append(
                dict(fragment, body_start=position, body_end=position + len(clean_fragment))
            )
            position += len(clean_fragment) + 1
        blocks.append({"body_start": start, "body_end": len(body), "text": clean, "spans": spans})
    if len(body.encode()) > 1024 * 1024 or sum(len(b["spans"]) for b in blocks) > 20_000:
        raise ArticleError("parser_failure", "Article exceeds body/span limits")
    if len(body.split()) < 20:
        raise ArticleError(
            "parser_failure", "Article body too short or unavailable; not irrelevant"
        )
    return body, blocks


def parse_article(raw, media_type, url, source_text, fallback_title, encoding="utf-8"):
    if len(raw) > MAX_BYTES:
        raise ArticleError("parser_failure", "Article exceeds 10 MiB")
    if media_type not in {"text/html", "application/xhtml+xml", "text/plain"}:
        raise ArticleError("unsupported_format", "Article parser requires HTML or plain text")
    try:
        html = raw.decode(encoding)
    except (UnicodeError, LookupError) as error:
        raise ArticleError(
            "parser_failure", "Article encoding invalid; specify its encoding"
        ) from error
    if "\0" in html:
        raise ArticleError("parser_failure", "Article contains invalid NUL characters")
    warnings = []
    if media_type == "text/plain":
        if html != source_text:
            raise ArticleError("parser_failure", "Plain text differs from archived source text")
        groups = [
            [
                {
                    "quote": m.group().strip(),
                    "start_offset": m.start() + len(m.group()) - len(m.group().lstrip()),
                    "end_offset": m.start() + len(m.group().rstrip()),
                }
            ]
            for m in re.finditer(r"[^\n]+", html)
            if m.group().strip()
        ]
        metadata = {
            "title": fallback_title,
            "authors": [],
            "dates": {"published": date_metadata([]), "modified": date_metadata([])},
            "canonical_references": [],
            "genre_metadata": [],
        }
        adapter = "plain-text"
        links = []
    else:
        tree = Tree()
        tree.feed(html)
        tree.close()
        if "\n".join(tree.parts) != source_text:
            raise ArticleError("parser_failure", "HTML differs from archived collection text")
        title = " ".join(tree.title).casefold()
        if any(
            value in title for value in ("access denied", "just a moment", "verify you are human")
        ):
            raise ArticleError("access_denied", "Article is an access challenge")
        eligible = [node for node in tree.nodes if not hidden(node)]
        host = urlsplit(url).hostname
        if host == "www.fia.com":
            roots = [
                n
                for n in eligible
                if {"content-body", "article-description"} & set(n.attrs.get("class", "").split())
            ]
            adapter = "fia-html"
        else:
            roots = [
                n
                for n in eligible
                if n.attrs.get("itemprop") == "articleBody"
                or BODY_CLASSES & set(n.attrs.get("class", "").split())
                or n.attrs.get("data-f1") == "article-body"
            ]
            adapter = "article-body"
        if not roots:
            roots = [n for n in eligible if n.tag == "article"]
            adapter = "semantic-article"
        if len(roots) > 256:
            raise ArticleError("parser_failure", "Too many article-body candidates")
        roots = [n for n in roots if not any(r in list(n.ancestors())[1:] for r in roots)]
        if not roots or (len(roots) > 1 and host != "www.fia.com"):
            raise ArticleError(
                "parser_failure", "No unambiguous article body; index/shell unsupported"
            )
        metadata = _metadata(tree, roots, url, warnings)
        groups = []
        last = None
        for node, fragment in tree.fragments:
            ancestors = list(node.ancestors())
            root = next((r for r in roots if r in ancestors), None)
            if (
                root is None
                or hidden(node)
                or any(
                    n.tag == "h1"
                    or n.attrs.get("itemprop") in {"author", "datePublished", "dateModified"}
                    or n.attrs.get("rel") == "author"
                    for n in ancestors
                )
            ):
                continue
            block = next((n for n in ancestors if n.tag in BLOCKS), root)
            if block is not last:
                groups.append([])
                last = block
            groups[-1].append(fragment)
        links = []
        for node in eligible:
            if node.tag == "a" and any(root in node.ancestors() for root in roots):
                value = node.attrs.get("href", "")
                if value and not value.startswith(("#", "mailto:", "javascript:", "data:")):
                    link = safe_link(value, url)
                    if link:
                        links.append({"url": link, "text": node_text(node)})
    body, blocks = _assemble(groups, source_text)
    if not metadata["authors"]:
        warnings.append("No published author identified")
    if metadata["dates"]["published"]["status"] != "exact":
        warnings.append("Publication instant unknown or conflicting; raw date values retained")
    normalized = " ".join(body.split())
    return {
        **metadata,
        "adapter": adapter,
        "body": body,
        "blocks": blocks,
        "links": links,
        "warnings": warnings,
        "body_hash": hashlib.sha256(normalized.encode()).hexdigest(),
    }
