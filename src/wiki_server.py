#!/usr/bin/env python3
"""
Wikipedia-style wiki browser for local .wiki files.
Parses MediaWiki markup and serves as a Flask web app.
"""

import re
import os
from pathlib import Path
from collections import defaultdict
from flask import Flask, render_template, request, redirect, url_for, abort

app = Flask(__name__)

WIKI_DIR = Path.home() / "wiki"
INDEX_DIR = Path.home() / "wiki-index"

# ─── Wiki Parser ───────────────────────────────────────────────

class WikiParser:
    """Convert MediaWiki markup to HTML."""

    def __init__(self, wiki_dir: Path):
        self.wiki_dir = wiki_dir
        self._all_pages = None

    @property
    def all_pages(self):
        if self._all_pages is None:
            self._all_pages = self._scan_pages()
        return self._all_pages

    def _scan_pages(self):
        pages = []
        for f in sorted(self.wiki_dir.glob("*.wiki")):
            title = f.stem.replace("_", " ")
            content = f.read_text()
            pages.append({"title": title, "file": f, "content": content})
        return pages

    def page_exists(self, title: str) -> bool:
        fpath = self.wiki_dir / f"{title.replace(' ', '_')}.wiki"
        return fpath.exists()

    def get_page(self, title: str) -> dict | None:
        fpath = self.wiki_dir / f"{title.replace(' ', '_')}.wiki"
        if not fpath.exists():
            return None
        return {"title": title, "file": fpath, "content": fpath.read_text()}

    def parse(self, wikitext: str, current_title: str = "") -> str:
        """Convert wiki markup to HTML."""
        if not wikitext:
            return ""

        # Pre-process: extract and replace templates before line processing
        wikitext = self._handle_redirect(wikitext)
        wikitext = self._handle_templates(wikitext)

        lines = wikitext.split("\n")
        html = []
        i = 0
        in_table = False
        table_rows = []

        while i < len(lines):
            line = lines[i]

            # Skip empty lines between blocks
            if not line.strip():
                if in_table:
                    html.append(self._render_table(table_rows))
                    in_table = False
                    table_rows = []
                html.append("")
                i += 1
                continue

            # Table
            if line.strip().startswith("{|"):
                in_table = True
                table_rows = []
                i += 1
                continue

            if in_table:
                if line.strip().startswith("|}"):
                    html.append(self._render_table(table_rows))
                    in_table = False
                    table_rows = []
                else:
                    table_rows.append(line)
                i += 1
                continue

            # Headings
            heading_match = re.match(r'^(={2,6})\s*(.+?)\s*\1\s*$', line)
            if heading_match:
                level = len(heading_match.group(1))
                text = self._parse_inline(heading_match.group(2), current_title)
                h_level = min(level, 6)
                html.append(f'<h{h_level} id="{self._anchor_id(heading_match.group(2))}">{text}</h{h_level}>')
                i += 1
                continue

            # Horizontal rule
            if line.strip() == "----" or line.strip() == "---":
                html.append("<hr>")
                i += 1
                continue

            # Unordered list
            if re.match(r'^\*+\s', line):
                list_lines = []
                while i < len(lines) and re.match(r'^\*+\s', lines[i]):
                    list_lines.append(lines[i])
                    i += 1
                html.append(self._render_list(list_lines, "ul"))
                continue

            # Ordered list
            if re.match(r'^#+\s', line):
                list_lines = []
                while i < len(lines) and re.match(r'^#+\s', lines[i]):
                    list_lines.append(lines[i])
                    i += 1
                html.append(self._render_list(list_lines, "ol"))
                continue

            # Definition list (; term : definition)
            if re.match(r'^;', line):
                html.append(self._render_definition(line))
                i += 1
                continue

            # Paragraph
            para_lines = []
            while i < len(lines) and lines[i].strip() and not lines[i].strip().startswith(("{|", "|}", "=", "*", "#", ";", "----", "---")):
                para_lines.append(lines[i])
                i += 1
            if para_lines:
                text = " ".join(para_lines)
                html.append(f"<p>{self._parse_inline(text, current_title)}</p>")

        if in_table:
            html.append(self._render_table(table_rows))

        return "\n".join(html)

    def _handle_redirect(self, wikitext: str) -> str:
        """Handle #REDIRECT [[Target]]."""
        m = re.match(r'#REDIRECT\s*\[\[([^\]]+)\]\]', wikitext.strip())
        if m:
            target = m.group(1).split("|")[0].strip()
            return f'<div class="redirect">Redirect to: [[{target}]]</div>'
        return wikitext

    def _handle_templates(self, wikitext: str) -> str:
        """Handle common templates."""
        # Short description
        wikitext = re.sub(
            r'\{\{Short description\|(.+?)\}\}',
            r'<div class="shortdesc">\1</div>',
            wikitext
        )

        # Main article
        wikitext = re.sub(
            r'\{\{Main\|(.+?)\}\}',
            lambda m: '<div class="main-article">Main article: ' +
                      ', '.join(f'<a href="/wiki/{self._url_title(p.strip())}">{p.strip()}</a>'
                                for p in m.group(1).split("|")) +
                      '</div>',
            wikitext
        )

        # Portal
        wikitext = re.sub(
            r'\{\{Portal\|(.+?)\}\}',
            '<div class="portal">📖 Portal: \\1</div>',
            wikitext
        )

        # Reflist
        wikitext = wikitext.replace("{{Reflist|30em}}", '<div class="reflist">References</div>')
        wikitext = wikitext.replace("{{Reflist}}", '<div class="reflist">References</div>')

        # Infobox: multi-line handling
        wikitext = re.sub(
            r'\{\{Infobox\s+(\w+)(.*?)\}\}',
            lambda m: self._render_infobox(m.group(1), m.group(2)),
            wikitext,
            flags=re.DOTALL
        )

        return wikitext

    def _render_infobox(self, box_type: str, content: str) -> str:
        """Render a simplified infobox."""
        rows = []
        for line in content.strip().split("\n"):
            line = line.strip()
            if not line or line.startswith("|"):
                # parameter line: | key = value
                m = re.match(r'\|\s*(\w[\w\s_]*?)\s*=\s*(.+)', line)
                if m:
                    key = m.group(1).strip()
                    val = m.group(2).strip()
                    if val:
                        rows.append(f'<tr><th>{key}</th><td>{val}</td></tr>')
            elif line.startswith("image"):
                m = re.match(r'image\s*=\s*(.+)', line)
                if m:
                    rows.append(f'<tr><td colspan="2" class="infobox-image">📷 {m.group(1).strip()}</td></tr>')
            elif line.startswith("caption"):
                m = re.match(r'caption\s*=\s*(.+)', line)
                if m:
                    rows.append(f'<tr><td colspan="2" class="infobox-caption">{m.group(1).strip()}</td></tr>')

        if not rows:
            return ""
        return f'<table class="infobox"><tbody>{"".join(rows)}</tbody></table>'

    def _render_table(self, rows: list) -> str:
        """Render a wiki table."""
        html_rows = []
        for row in rows:
            row = row.strip()
            if row.startswith("|-") or row.startswith("|}"):
                continue
            if row.startswith("!"):
                # Header row
                cells = re.split(r'\s*!!\s*', row[1:].strip())
                html_rows.append("<tr>" + "".join(f'<th>{self._parse_inline(c.strip())}</th>' for c in cells) + "</tr>")
            elif row.startswith("|"):
                # Data row
                cells = re.split(r'\s*\|\|\s*', row[1:].strip())
                html_rows.append("<tr>" + "".join(f'<td>{self._parse_inline(c.strip())}</td>' for c in cells) + "</tr>")

        return f'<table class="wikitable"><tbody>{"".join(html_rows)}</tbody></table>'

    def _render_list(self, lines: list, list_type: str) -> str:
        """Render nested bullet or numbered lists."""
        def _process(items, indent=0):
            html = ""
            i = 0
            while i < len(items):
                line = items[i]
                prefix_char = "*" if list_type == "ul" else "#"
                depth = len(re.match(rf'^\{prefix_char}+', line).group())
                if depth == indent + 1:
                    content = re.sub(rf'^\{prefix_char}+\s*', '', line)
                    html += f"<li>{self._parse_inline(content)}"
                    # Check for sublist
                    sub = []
                    j = i + 1
                    while j < len(items):
                        sub_depth = len(re.match(rf'^\{prefix_char}+', items[j]).group())
                        if sub_depth <= indent + 1:
                            break
                        sub.append(items[j])
                        j += 1
                    if sub:
                        html += _process(sub, indent + 1)
                    html += "</li>"
                    i = j
                else:
                    i += 1
            return html

        inner = _process(lines, 0)
        return f"<{list_type}>{inner}</{list_type}>"

    def _render_definition(self, line: str) -> str:
        """Render ; term : definition."""
        m = re.match(r';(.+?):(.+)', line)
        if m:
            term = self._parse_inline(m.group(1).strip())
            defn = self._parse_inline(m.group(2).strip())
            return f"<dl><dt>{term}</dt><dd>{defn}</dd></dl>"
        return f"<p>{self._parse_inline(line)}</p>"

    def _parse_inline(self, text: str, current_title: str = "") -> str:
        """Parse inline wiki markup."""
        if not text:
            return ""

        # External links [URL text]
        text = re.sub(
            r'\[(https?://[^\s\]]+)\s+([^\]]*)\]',
            r'<a href="\1" class="external">\2</a>',
            text
        )

        # Wiki links [[page]] and [[page|text]] - nested handling
        def replace_link(m):
            inner = m.group(1)
            if "|" in inner:
                parts = inner.split("|", 1)
                target = parts[0].strip()
                display = parts[1].strip()
            else:
                target = inner.strip()
                display = target

            # Handle #anchor within link
            anchor = ""
            if "#" in target:
                target, anchor = target.split("#", 1)
                target = target.strip()

            if self.page_exists(target):
                cls = ""
            else:
                cls = ' class="new"'

            anchor_attr = f"#{self._anchor_id(anchor)}" if anchor else ""
            return f'<a href="/wiki/{self._url_title(target)}{anchor_attr}"{cls}>{display}</a>'

        text = re.sub(r'\[\[([^\]]+)\]\]', replace_link, text)

        # Math: <math>...</math>
        text = re.sub(
            r'<math>(.*?)</math>',
            r'<span class="math">\\(\1\\)</span>',
            text
        )

        # Bold and italic
        text = re.sub(r"'''''(.+?)'''''", r"<b><i>\1</i></b>", text)
        text = re.sub(r"'''(.+?)'''", r"<b>\1</b>", text)
        text = re.sub(r"''(.+?)''", r"<i>\1</i>", text)

        # Nowiki
        text = re.sub(r'<nowiki>(.*?)</nowiki>', r'\1', text)

        return text

    def _url_title(self, title: str) -> str:
        """Convert title to URL-safe string."""
        return title.replace(" ", "_")

    def _anchor_id(self, text: str) -> str:
        """Convert text to anchor ID."""
        result = text.strip().lower()
        for ch in "'()–,—/-.":
            result = result.replace(ch, "")
        result = re.sub(r'[^\w]+', '-', result)
        result = re.sub(r'-+', '-', result)
        return result.strip("-")

    def search(self, query: str, limit: int = 50) -> list:
        """Full-text search across all wiki pages. Returns list of {title, snippet}."""
        query_lower = query.lower()
        results = []

        for page in self.all_pages:
            title = page["title"]
            content = page["content"]
            title_match = query_lower in title.lower()

            if title_match:
                # Title match: show first paragraph
                snippet = self._extract_snippet(content, query_lower)
                results.append({"title": title, "snippet": snippet, "score": 2})
                continue

            # Content match
            if query_lower in content.lower():
                snippet = self._extract_snippet(content, query_lower)
                results.append({"title": title, "snippet": snippet, "score": 1})

        # Sort: title matches first, then alphabetically
        results.sort(key=lambda r: (-r["score"], r["title"].lower()))
        return results[:limit]

    def _extract_snippet(self, content: str, query: str, context: int = 120) -> str:
        """Extract relevant snippet from content."""
        # Strip templates for snippet
        clean = re.sub(r'\{\{.*?\}\}', '', content, flags=re.DOTALL)
        clean = re.sub(r'<math>.*?</math>', '', clean)
        clean = re.sub(r'\[\[Category:.*?\]\]', '', clean)
        clean = re.sub(r'={2,}.*?={2,}', '', clean)

        # Find query position
        pos = clean.lower().find(query)
        if pos == -1:
            return clean[:context * 2].strip()

        start = max(0, pos - context)
        end = min(len(clean), pos + context)

        snippet = clean[start:end].strip()
        if start > 0:
            snippet = "…" + snippet
        if end < len(clean):
            snippet += "…"

        # Highlight
        snippet = re.sub(
            f'({re.escape(query)})',
            r'<mark>\1</mark>',
            snippet,
            flags=re.IGNORECASE
        )

        return snippet

    def get_categories(self) -> dict:
        """Extract categories from all pages. Returns {category: [titles]}."""
        cats = defaultdict(list)
        for page in self.all_pages:
            for m in re.finditer(r'\[\[Category:(.+?)(?:\|.*?)?\]\]', page["content"]):
                cat = m.group(1).strip()
                cats[cat].append(page["title"])
        return dict(sorted(cats.items()))


# ─── Global Parser ──────────────────────────────────────────────
parser = WikiParser(WIKI_DIR)

# ─── Flask Routes ───────────────────────────────────────────────

@app.context_processor
def inject_globals():
    return {
        "total_pages": len(parser.all_pages),
        "quick_links": ["Physics", "Quantum mechanics", "Classical mechanics",
                         "Electromagnetism", "Thermodynamics", "Standard Model",
                         "General relativity", "Nuclear physics"],
    }


@app.route("/")
def main_page():
    """Wikipedia-style main page with featured content."""
    featured = ["Physics", "Quantum mechanics", "Classical mechanics",
                "Electromagnetism", "Thermodynamics", "Standard Model"]
    all_titles = sorted([p["title"] for p in parser.all_pages], key=str.lower)

    # Get snippets for featured pages
    snippets = {}
    for title in featured:
        page = parser.get_page(title)
        if page:
            clean = re.sub(r'\{\{.*?\}\}', '', page["content"], flags=re.DOTALL)
            clean = re.sub(r'<math>.*?</math>', '', clean)
            clean = re.sub(r'\[\[Category:.*?\]\]', '', clean)
            clean = re.sub(r"''+", '', clean)
            clean = re.sub(r'={2,}.*?={2,}', '', clean)
            lines = [l.strip() for l in clean.split("\n") if l.strip() and not l.strip().startswith("{{")]
            for line in lines:
                if len(line) > 60:
                    snippets[title] = line[:200] + ("…" if len(line) > 200 else "")
                    break
            if title not in snippets:
                snippets[title] = ""

    return render_template("main_page.html",
                           featured=featured,
                           all_titles=all_titles,
                           snippets=snippets,
                           total_pages=len(parser.all_pages),
                           categories=list(parser.get_categories().items())[:12])


@app.route("/wiki/<path:title>")
def wiki_page(title: str):
    """Display a wiki page."""
    # Convert URL to title (underscores -> spaces)
    decoded = title.replace("_", " ")
    page = parser.get_page(decoded)

    if not page:
        return render_template("404.html", title=decoded), 404

    html_content = parser.parse(page["content"], current_title=page["title"])
    return render_template("page.html", title=page["title"], content=html_content)


@app.route("/index")
def page_index():
    """Alphabetical index of all pages."""
    all_pages = sorted(parser.all_pages, key=lambda p: p["title"].lower())

    # Group by first letter
    groups = defaultdict(list)
    for p in all_pages:
        first = p["title"][0].upper()
        groups[first].append(p["title"])

    sorted_groups = sorted(groups.items())

    return render_template("index.html", total=len(parser.all_pages), groups=sorted_groups)


@app.route("/search")
def search():
    """Search wiki pages."""
    query = request.args.get("q", "").strip()
    results = []
    if query:
        results = parser.search(query)

    return render_template("search.html", query=query, results=results)


@app.route("/categories")
def categories():
    """Category index."""
    cats = parser.get_categories()

    return render_template("categories.html", cats=cats)


@app.route("/random")
def random_page():
    """Redirect to a random wiki page."""
    import random
    titles = [p["title"] for p in parser.all_pages]
    title = random.choice(titles)
    return redirect(f"/wiki/{title.replace(' ', '_')}")


# ─── Static files ────────────────────────────────────────────────

@app.route("/static/<path:filename>")
def static_files(filename):
    from flask import send_from_directory
    return send_from_directory("static", filename)


# ─── Main ────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse
    parser_args = argparse.ArgumentParser(description="Physics Wiki Browser")
    parser_args.add_argument("port", nargs="?", type=int, default=8080,
                             help="Port number to listen on (default: 8080)")
    parser_args.add_argument("--host", default="127.0.0.1",
                             help="Host to bind to (default: 127.0.0.1)")
    parser_args.add_argument("--no-debug", action="store_true",
                             help="Disable debug mode")
    args = parser_args.parse_args()

    print(f"📚 Physics Wiki Browser")
    print(f"   Wiki dir: {WIKI_DIR}")
    print(f"   Pages: {len(parser.all_pages)}")
    print(f"   Categories: {len(parser.get_categories())}")
    print(f"   Starting server at http://{args.host}:{args.port}")
    app.run(host=args.host, port=args.port, debug=not args.no_debug)
