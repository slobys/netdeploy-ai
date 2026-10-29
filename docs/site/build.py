"""Build and validate the NetDeploy AI public handbook without dependencies."""
from __future__ import annotations

import argparse
import html
import json
import shutil
from html.parser import HTMLParser
from pathlib import Path
from string import Template
from urllib.parse import unquote, urlsplit
from xml.sax.saxutils import escape as xml_escape

ROOT = Path(__file__).resolve().parent
PROJECT = ROOT.parents[1]
DEFAULT_OUTPUT = PROJECT / ".build" / "docs-site"


class ParsedHTML(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.ids: set[str] = set()
        self.links: list[str] = []
        self.headings: list[tuple[str, str, str]] = []
        self.words: list[str] = []
        self._heading: list[str] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        item = dict(attrs)
        identifier = item.get("id")
        if identifier:
            if identifier in self.ids:
                raise ValueError("Repeated HTML id: " + identifier)
            self.ids.add(identifier)
        for attr in ("href", "src"):
            if item.get(attr):
                self.links.append(item[attr])
        if tag in ("h2", "h3"):
            if not identifier:
                raise ValueError("All h2/h3 headings require stable id attributes")
            self._heading = [tag, identifier, ""]

    def handle_data(self, data: str) -> None:
        self.words.append(data)
        if self._heading is not None:
            self._heading[2] += data

    def handle_endtag(self, tag: str) -> None:
        if self._heading is not None and tag == self._heading[0]:
            self.headings.append(tuple(self._heading))
            self._heading = None


def _document(source: str) -> ParsedHTML:
    document = ParsedHTML()
    document.feed(source)
    document.close()
    return document


def validate(output: Path) -> None:
    documents = {p.name: _document(p.read_text(encoding="utf-8"))
                 for p in output.glob("*.html")}
    for filename, doc in documents.items():
        for ref in doc.links:
            parts = urlsplit(ref)
            if parts.scheme in ("https", "http", "mailto", "tel"):
                continue
            if parts.scheme or parts.netloc:
                raise ValueError("Unsupported URL scheme in " + filename + ": " + ref)
            target = unquote(parts.path) or filename
            if target.startswith("/") or ".." in Path(target).parts or "\\" in target:
                raise ValueError("Non-portable relative link: " + ref)
            if not (output / target).is_file():
                raise ValueError(filename + " has broken link: " + ref)
            if parts.fragment and target in documents and unquote(parts.fragment) not in documents[target].ids:
                raise ValueError(filename + " has missing anchor: " + ref)
    index = json.loads((output / "search-index.json").read_text(encoding="utf-8"))
    for record in index:
        url, _, anchor = record["url"].partition("#")
        if url not in documents or (anchor and anchor not in documents[url].ids):
            raise ValueError("Broken search record " + record["url"])


def build(output: Path = DEFAULT_OUTPUT) -> Path:
    config = json.loads((ROOT / "site.json").read_text(encoding="utf-8"))
    pages = [page for group in config["groups"] for page in group["pages"]]
    keys = [page["id"] for page in pages]
    if len(set(keys)) != len(keys) or not keys or keys[0] != "index":
        raise ValueError("Page ids must be unique and begin with index")
    if any(not key.replace("-", "").isalnum() for key in keys):
        raise ValueError("Invalid page id")
    if DEFAULT_OUTPUT.is_symlink():
        raise ValueError("Refusing to follow a symlink for the public output directory")
    output = output.resolve()
    if output == DEFAULT_OUTPUT.resolve() and output.exists():
        shutil.rmtree(output)
    if output.exists() and any(output.iterdir()):
        raise ValueError("Destination must be empty")
    output.mkdir(parents=True, exist_ok=True)
    template = Template((ROOT / "template.html").read_text(encoding="utf-8"))
    for asset in ("site.css", "site.js"):
        shutil.copyfile(ROOT / asset, output / asset)

    search: list[dict[str, str]] = []
    for i, page in enumerate(pages):
        content = (ROOT / "content" / (page["id"] + ".html")).read_text(encoding="utf-8")
        content = content.replace("{{version}}", html.escape(config["version"]))
        doc = _document(content)
        groups = []
        for group in config["groups"]:
            groups.append('<p class="nav-label">' + html.escape(group["title"]) + "</p>")
            for item in group["pages"]:
                current = ' aria-current="page"' if item["id"] == page["id"] else ""
                groups.append('<a href="' + item["id"] + '.html"' + current + ">" +
                              html.escape(item["title"]) + "</a>")
        toc = "".join('<a class="toc-' + tag + '" href="#' + anchor + '">' +
                      html.escape(title) + "</a>" for tag, anchor, title in doc.headings)
        pager = []
        for j, text in ((i - 1, "上一篇"), (i + 1, "下一篇")):
            if j >= 0 and j < len(pages):
                item = pages[j]
                pager.append('<a href="' + item["id"] + '.html"><small>' + text +
                             "</small>" + html.escape(item["title"]) + "</a>")
            else:
                pager.append("<span></span>")
        title = page["title"] + " · NetDeploy AI"
        result = template.substitute(
            title=html.escape(title), description=html.escape(page["description"], quote=True),
            canonical=config["url"] + ("" if page["id"] == "index" else page["id"] + ".html"),
            page_id=page["id"], page_title=html.escape(page["title"]),
            page_description=html.escape(page["description"]),
            version=html.escape(config["version"]), navigation="".join(groups),
            content=content, toc=toc, pager="".join(pager),
        )
        (output / (page["id"] + ".html")).write_text(result, encoding="utf-8")
        sections = content.split("<h2 ")
        for idx, section in enumerate(sections):
            source = section if idx == 0 else "<h2 " + section
            section_doc = _document(source)
            preview = " ".join(" ".join(section_doc.words).split())
            if not preview:
                continue
            heading = section_doc.headings[0] if section_doc.headings else None
            search.append({"title": page["title"],
                           "section": heading[2] if heading else page["description"],
                           "text": preview[:2800],
                           "url": page["id"] + ".html" + ("#" + heading[1] if heading else "")})

    (output / "search-index.json").write_text(json.dumps(search, ensure_ascii=False), encoding="utf-8")
    (output / ".nojekyll").write_text("", encoding="utf-8")
    (output / "404.html").write_text(
        '<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        '<title>未找到页面 · NetDeploy AI</title><link rel="stylesheet" href="site.css">'
        '</head><body><main class="not-found"><h1>404 · 页面未找到</h1>'
        '<p>请返回文档首页并使用左侧目录或搜索。</p>'
        '<a class="button primary" href="index.html">返回文档首页</a></main></body></html>',
        encoding="utf-8",
    )
    (output / "robots.txt").write_text(
        "User-agent: *\nAllow: /\nSitemap: " + config["url"] + "sitemap.xml\n",
        encoding="utf-8",
    )
    urls = "".join("<url><loc>" + xml_escape(config["url"] + page["id"] + ".html") +
                   "</loc></url>" for page in pages)
    (output / "sitemap.xml").write_text(
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">' +
        urls + "</urlset>", encoding="utf-8",
    )
    expected = {page + ".html" for page in keys} | {
        "site.css", "site.js", "404.html", "robots.txt", "sitemap.xml",
        "search-index.json", ".nojekyll",
    }
    actual = {p.name for p in output.iterdir() if p.is_file()}
    if actual != expected:
        raise ValueError("Unexpected published files: " + str(actual ^ expected))
    validate(output)
    print("Built " + str(len(pages)) + " pages / " + str(len(search)) + " searchable sections at " + str(output))
    return output


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    build(args.output)
