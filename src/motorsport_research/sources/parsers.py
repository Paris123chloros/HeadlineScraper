"""Bounded collection parsing; full article cleanup and PDF interpretation come later."""

from dataclasses import dataclass, field
from datetime import datetime
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser
from urllib.parse import urljoin
from xml.etree.ElementTree import ParseError

from defusedxml import ElementTree
from defusedxml.common import DefusedXmlException
from pydantic import AnyHttpUrl

from motorsport_research.storage.models import canonical_url, timestamp

PARSER_VERSION = "collection:2"


class CollectionError(ValueError):
    def __init__(self, outcome: str, detail: str):
        self.outcome = outcome
        super().__init__(detail)


@dataclass
class ParsedDocument:
    title: str
    text: str
    links: list[dict] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


class PageText(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []
        self.title = []
        self.in_title = False
        self.hidden = 0
        self.svg_depth = 0

    def handle_starttag(self, tag, attrs):
        if tag == "svg":
            self.svg_depth += 1
        if tag in {"script", "style", "noscript"}:
            self.hidden += 1
        if tag == "title" and not self.svg_depth:
            self.in_title = True

    def handle_endtag(self, tag):
        if tag == "svg":
            self.svg_depth = max(0, self.svg_depth - 1)
        if tag in {"script", "style", "noscript"}:
            self.hidden = max(0, self.hidden - 1)
        if tag == "title":
            self.in_title = False

    def handle_data(self, data):
        value = data.strip()
        if value and not self.hidden:
            self.parts.append(value)
            if self.in_title:
                self.title.append(value)


def page_text(value: str) -> str:
    parser = PageText()
    parser.feed(value)
    return "\n".join(parser.parts)


def _child(node, name):
    return next((child for child in node if child.tag.rsplit("}", 1)[-1] == name), None)


def _text(node, name):
    child = _child(node, name)
    return "".join(child.itertext()).strip() if child is not None else ""


def _date(value: str, warnings: list[str]) -> tuple[str | None, str | None]:
    if not value:
        return None, None
    try:
        try:
            date = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            date = parsedate_to_datetime(value)
        if date.tzinfo is None:
            raise ValueError("unknown timezone")
        return timestamp(date), date.tzname()
    except (ValueError, TypeError, OverflowError):
        warnings.append("Unusable publication date retained only in the raw feed")
        return None, None


def parse_feed(content: bytes, base_url: str) -> ParsedDocument:
    try:
        root = ElementTree.fromstring(content, forbid_dtd=True)
    except (ParseError, DefusedXmlException, ValueError) as error:
        raise CollectionError("parser_failure", "Malformed or unsafe XML feed") from error
    name = root.tag.rsplit("}", 1)[-1]
    if name == "rss":
        channel = _child(root, "channel")
        if channel is None:
            raise CollectionError("parser_failure", "RSS feed has no channel")
        items = [node for node in channel if node.tag.rsplit("}", 1)[-1] == "item"]
    elif root.tag == "{http://www.w3.org/2005/Atom}feed":
        channel = root
        items = [node for node in root if node.tag == "{http://www.w3.org/2005/Atom}entry"]
    elif name == "RDF":
        channel = _child(root, "channel")
        items = [node for node in root if node.tag.rsplit("}", 1)[-1] == "item"]
        if channel is None:
            raise CollectionError("parser_failure", "RSS 1 feed has no channel")
    else:
        raise CollectionError("unsupported_format", "Response is not RSS or Atom")
    title = _text(channel, "title")
    if not title:
        raise CollectionError("parser_failure", "Feed has no title")
    if len(items) > 1000:
        raise CollectionError("parser_failure", "Feed exceeds 1000 entries")
    result = ParsedDocument(title, title)
    xml_base = "{http://www.w3.org/XML/1998/namespace}base"
    feed_base = urljoin(base_url, root.get(xml_base, ""))
    parts = [title, page_text(_text(channel, "description") or _text(channel, "subtitle"))]
    for position, item in enumerate(items):
        item_base = urljoin(feed_base, item.get(xml_base, ""))
        item_title = _text(item, "title")
        if not item_title:
            raise CollectionError("parser_failure", "Feed entry has no title")
        if name == "feed":
            link_node = next(
                (
                    n
                    for n in item
                    if n.tag.endswith("}link") and n.get("rel", "alternate") == "alternate"
                ),
                None,
            )
            link = link_node.get("href", "") if link_node is not None else ""
            if link_node is not None:
                item_base = urljoin(item_base, link_node.get(xml_base, ""))
            date_value = _text(item, "published") or _text(item, "updated")
        else:
            link = _text(item, "link")
            date_value = _text(item, "pubDate") or _text(item, "date")
        parts.extend(
            [
                item_title,
                page_text(
                    _text(item, "description") or _text(item, "summary") or _text(item, "content")
                ),
            ]
        )
        if not link:
            result.warnings.append("Entry has no article link")
            continue
        try:
            url = canonical_url(AnyHttpUrl(urljoin(item_base, link)))
        except ValueError:
            result.warnings.append("Entry has an invalid article link")
            continue
        date, timezone = _date(date_value, result.warnings)
        result.links.append(
            {
                "position": position,
                "url": url,
                "title": item_title,
                "item_key": _text(item, "guid") or _text(item, "id") or None,
                "published_at": date,
                "source_timezone": timezone,
            }
        )
    result.text = "\n".join(part for part in parts if part).replace("\0", "")
    return result


def parse_document(
    content: bytes, media_type: str, encoding: str, method: str, url: str
) -> ParsedDocument:
    if method == "rss":
        if media_type not in {
            "application/rss+xml",
            "application/atom+xml",
            "application/xml",
            "text/xml",
        }:
            raise CollectionError("unsupported_format", "Expected an XML feed content type")
        return parse_feed(content, url)
    if media_type in {"application/json", "text/csv", "application/csv"}:
        try:
            text = content.decode("utf-8-sig")
            if media_type == "application/json":
                from motorsport_research.championships.json_data import decode

                decode(text)
            if not text.strip() or "\0" in text:
                raise ValueError("empty/invalid text")
        except (UnicodeError, ValueError, RecursionError) as error:
            raise CollectionError("parser_failure", "Malformed structured archive") from error
        return ParsedDocument(
            url,
            text,
            warnings=["Structured data archived; normalize with reviewed official context"],
        )
    if media_type == "application/pdf":
        if not content.startswith(b"%PDF-"):
            raise CollectionError("parser_failure", "Response is not a PDF document")
        return ParsedDocument(
            url.rsplit("/", 1)[-1] or "PDF document",
            "",
            warnings=["PDF archived; normalize with reviewed official context"],
        )
    if media_type not in {"text/html", "application/xhtml+xml", "text/plain"}:
        raise CollectionError("unsupported_format", "HTTP content type is not supported")
    try:
        text = content.decode(encoding)
    except (UnicodeError, LookupError) as error:
        raise CollectionError("parser_failure", "Content encoding is invalid") from error
    if not text.strip() or "\0" in text:
        raise CollectionError("parser_failure", "Empty or invalid text response")
    if media_type == "text/plain":
        return ParsedDocument(url, text)
    parser = PageText()
    parser.feed(text)
    body = "\n".join(parser.parts)
    if not body:
        raise CollectionError("parser_failure", "HTML contains no visible text")
    title = " ".join(parser.title) or url
    if any(
        phrase in title.casefold()
        for phrase in ("access denied", "just a moment", "verify you are human")
    ):
        raise CollectionError("access_denied", "Received an access challenge page")
    return ParsedDocument(title, body)
