"""Small strict table reader that retains cells, links, and full driver names."""

from html.parser import HTMLParser


class TableReader(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.tables = []
        self.headings = []
        self.table = None
        self.row = None
        self.cell = None
        self.capture_heading = False
        self.heading = []
        self.ignored = 0

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        if tag in {"script", "style", "svg"}:
            self.ignored += 1
        if tag in {"h1", "h2", "h3", "title"} and not self.ignored:
            self.capture_heading = True
            self.heading = []
        if tag == "table":
            if self.table is not None:
                raise ValueError("nested tables are unsupported")
            self.table = []
        if tag == "tr" and self.table is not None:
            self.row = []
        if tag in {"td", "th"} and self.row is not None:
            self.cell = {"header": tag == "th", "parts": [], "links": []}
            if attributes.get("colspan", "1") != "1" or attributes.get("rowspan", "1") != "1":
                raise ValueError("spanning result cells are unsupported")
        if tag == "a" and self.cell is not None:
            self.cell["links"].append(attributes.get("href", ""))
        if tag == "br" and self.cell is not None:
            self.cell["parts"].append("\n")

    def handle_endtag(self, tag):
        if tag in {"script", "style", "svg"}:
            self.ignored = max(0, self.ignored - 1)
        if tag in {"h1", "h2", "h3", "title"} and self.capture_heading:
            self.headings.append(" ".join(self.heading))
            self.capture_heading = False
        if tag in {"td", "th"} and self.cell is not None:
            self.cell["text"] = " ".join(self.cell.pop("parts")).strip()
            self.row.append(self.cell)
            self.cell = None
        if tag == "tr" and self.row is not None:
            self.table.append(self.row)
            self.row = None
        if tag == "table" and self.table is not None:
            self.tables.append(self.table)
            self.table = None

    def handle_data(self, value):
        if self.ignored or not value.strip():
            return
        if self.capture_heading:
            self.heading.append(value.strip())
        if self.cell is not None:
            self.cell["parts"].append(value.strip())


def read_tables(content: bytes) -> TableReader:
    parser = TableReader()
    parser.feed(content.decode("utf-8-sig"))
    if parser.table is not None or parser.cell is not None:
        raise ValueError("truncated result table")
    return parser
