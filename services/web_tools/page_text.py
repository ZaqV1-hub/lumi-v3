"""Texto e metadados de HTML público, sem executar scripts."""
import json
from html.parser import HTMLParser

SKIP = {"head", "script", "style", "noscript", "nav", "footer", "aside", "form", "svg", "canvas", "iframe", "template"}
VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}
BLOCK = {"main", "article", "section", "div", "p", "li", "tr", "h1", "h2", "h3", "h4", "blockquote", "br"}


class PageText(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stack = []
        self.buffers = {"body": [], "main": [], "article": []}
        self.title = ""
        self.metadata = {}
        self.structured = []
        self.ld = None
        self.heading_start = None

    def append(self, value):
        if any(tag in SKIP for tag in self.stack):
            return
        self.buffers["body"].append(value)
        for tag in ("main", "article"):
            if tag in self.stack:
                self.buffers[tag].append(value)

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "meta":
            key = (attrs.get("property") or attrs.get("name") or "").lower()
            if key in ("description", "article:published_time", "article:modified_time", "date", "datepublished", "datemodified"):
                self.metadata[key] = attrs.get("content", "")[:400]
        if tag == "script" and attrs.get("type", "").lower() == "application/ld+json":
            self.ld = ""
        if tag == "h1" and self.heading_start is None:
            self.heading_start = len(self.buffers["body"])
        if tag in BLOCK:
            self.append("\n")
        if tag not in VOID:
            self.stack.append(tag)
        if tag == "time" and attrs.get("datetime"):
            self.append(" " + attrs["datetime"][:80] + " ")
        if tag == "img" and attrs.get("alt"):
            self.append(" " + attrs["alt"][:160] + " ")

    def handle_data(self, value):
        if "title" in self.stack:
            self.title = (self.title + value)[:200]
        if self.ld is not None and "script" in self.stack:
            self.ld = (self.ld + value)[:32000]
        self.append(" " + value + " ")

    def handle_endtag(self, tag):
        if tag == "script" and self.ld is not None:
            try:
                parsed = json.loads(self.ld)
                if isinstance(parsed, (dict, list)) and len(self.structured) < 2:
                    self.structured.append(json.dumps(parsed, ensure_ascii=False)[:2000])
            except ValueError:
                pass
            self.ld = None
        if tag in self.stack:
            index = len(self.stack) - 1 - self.stack[::-1].index(tag)
            del self.stack[index:]
        if tag in BLOCK:
            self.append("\n")

    def result(self, limit=6000):
        def clean(parts):
            return "\n".join(line for raw in "".join(parts).splitlines() if (line := " ".join(raw.split())))
        candidates = [clean(self.buffers[tag]) for tag in ("article", "main")]
        text = next((value for value in candidates if len(value) >= 80), "")
        if not text:
            text = clean(self.buffers["body"][self.heading_start or 0:])
        return {"title": " ".join(self.title.split()), "text": text[:limit],
                "truncated": len(text) > limit, "metadata": self.metadata,
                "structured_data": self.structured}
