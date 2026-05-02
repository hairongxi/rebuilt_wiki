#!/usr/bin/env python3
"""
Multi-discipline Wiki Browser for local .wiki files.
Auto-detects disciplines from cross-reference index files in ~/wiki-index/.
Supports Physics, Electrical Engineering, Western Art History, and more.
"""

import re
import os
from pathlib import Path
from collections import defaultdict
from flask import Flask, render_template, request, redirect, url_for, abort

app = Flask(__name__)

WIKI_DIR = "../wiki"  # Path.home() / 
INDEX_DIR = "../wiki-index"  # Path.home() / 

# ─── Discipline Manager ─────────────────────────────────────────

class DisciplineManager:
    """Auto-detect disciplines from cross-reference index files."""

    DISCIPLINE_META = {
        "": {
            "name": "Fundamentals",
            "icon": "⚛️",
            "description": "Foundational concepts across physics, chemistry, and mathematics."
        },
        "electrical_engineering": {
            "name": "Electrical Engineering",
            "icon": "⚡",
            "description": "Power systems, protection, machines, substations, and grid infrastructure."
        },
        "western_art": {
            "name": "Western Art History",
            "icon": "🎨",
            "description": "From prehistoric cave paintings to contemporary art — artists, movements, works, and techniques."
        },
    }

    def __init__(self, index_dir: Path):
        self.index_dir = index_dir
        self.disciplines = {}  # {id: {"name", "icon", "pages": [...], "index_file": Path}}
        self._all_pages_set = set()
        self._scan()

    def _scan(self):
        """Scan index files and build discipline registry."""
        for f in sorted(self.index_dir.glob("cross-reference-index*.md")):
            stem = f.stem  # e.g. "cross-reference-index-electrical_engineering"
            if stem == "cross-reference-index":
                disc_id = ""
            elif stem.startswith("cross-reference-index-"):
                disc_id = stem[len("cross-reference-index-"):]
            else:
                continue

            meta = self.DISCIPLINE_META.get(disc_id, {})
            name = meta.get("name", disc_id.replace("_", " ").title())
            icon = meta.get("icon", "📄")
            description = meta.get("description", "")

            # Extract page entries from the index file
            pages = self._extract_pages(f)
            self._all_pages_set.update(pages)

            self.disciplines[disc_id] = {
                "id": disc_id,
                "name": name,
                "icon": icon,
                "description": description,
                "pages": sorted(pages),
                "count": len(pages),
                "index_file": f,
            }

        # Ensure we always have an "All" discipline
        if "" not in self.disciplines:
            self.disciplines[""] = {
                "id": "",
                "name": "All Pages",
                "icon": "📚",
                "description": "Browse all wiki pages across all disciplines.",
                "pages": [],
                "count": 0,
                "index_file": None,
            }

    def _extract_pages(self, index_file: Path) -> list:
        """Extract page names from cross-reference index (### headings)."""
        pages = []
        try:
            content = index_file.read_text()
            for m in re.finditer(r'^### (.+)$', content, re.MULTILINE):
                name = m.group(1).strip()
                # Convert displayed name back to filename format
                filename = name.replace(" ", "_")
                pages.append(filename)
        except Exception:
            pass
        return pages

    def get_pages(self, disc_id: str = None) -> list:
        """Get pages for a discipline, or all if disc_id is None."""
        if disc_id is None or disc_id == "":
            return sorted(self._all_pages_set)
        disc = self.disciplines.get(disc_id)
        if disc:
            return disc["pages"]
        return []

    def disc_for_page(self, page_name: str) -> str:
        """Find which discipline a page belongs to (returns first match)."""
        for disc_id, disc in self.disciplines.items():
            if disc_id == "":
                continue
            if page_name in disc["pages"]:
                return disc_id
        return ""

    @property
    def all_disciplines(self):
        return sorted(self.disciplines.values(), key=lambda d: (d["id"] != "", d["name"]))

    @property
    def total_pages(self):
        return len(self._all_pages_set)


# ─── Wiki Parser ───────────────────────────────────────────────

class WikiParser:
    """Convert MediaWiki markup to HTML with discipline-aware linking."""

    def __init__(self, wiki_dir: Path, disc_manager: DisciplineManager):
        self.wiki_dir = wiki_dir
        self.disc_manager = disc_manager
        self._all_pages = None
        self._alias_map = {}  # Chinese name -> English filename
        self._load_alias_map()

    def _load_alias_map(self):
        """Load alias mappings from index directory."""
        alias_file = INDEX_DIR / "alias-mapping-western_art.md"
        if alias_file.exists():
            for line in alias_file.read_text().split("\n"):
                line = line.strip()
                if " = " in line and not line.startswith("#") and not line.startswith("//"):
                    en, rest = line.split(" = ", 1)
                    en = en.strip()
                    for cn in rest.split(" | "):
                        cn = cn.strip()
                        if cn:
                            self._alias_map[cn] = en

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
        # Direct match
        fpath = self.wiki_dir / f"{title.replace(' ', '_')}.wiki"
        if fpath.exists():
            return True
        # Try alias
        if title in self._alias_map:
            en = self._alias_map[title]
            fpath = self.wiki_dir / f"{en}.wiki"
            return fpath.exists()
        return False

    def get_page(self, title: str) -> dict | None:
        fpath = self.wiki_dir / f"{title.replace(' ', '_')}.wiki"
        if fpath.exists():
            return {"title": title, "file": fpath, "content": fpath.read_text()}
        # Try alias
        if title in self._alias_map:
            en = self._alias_map[title]
            fpath = self.wiki_dir / f"{en}.wiki"
            if fpath.exists():
                return {"title": title, "file": fpath, "content": fpath.read_text()}
        return None

    def resolve_title(self, title: str) -> str | None:
        """Resolve a title to an existing wiki page, or None."""
        if self.page_exists(title):
            return title
        if title in self._alias_map:
            en = self._alias_map[title]
            if self.page_exists(en):
                return en
        return None

    def parse(self, wikitext: str, current_title: str = "", current_disc: str = "") -> str:
        """Convert wiki markup to HTML."""
        if not wikitext:
            return ""

        wikitext = self._handle_redirect(wikitext)
        wikitext = self._handle_templates(wikitext, current_disc)

        lines = wikitext.split("\n")
        html = []
        i = 0
        in_table = False
        table_rows = []

        while i < len(lines):
            line = lines[i]

            if not line.strip():
                if in_table:
                    html.append(self._render_table(table_rows))
                    in_table = False
                    table_rows = []
                html.append("")
                i += 1
                continue

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

            heading_match = re.match(r'^(={2,6})\s*(.+?)\s*\1\s*$', line)
            if heading_match:
                level = len(heading_match.group(1))
                text = self._parse_inline(heading_match.group(2), current_title, current_disc)
                h_level = min(level, 6)
                html.append(f'<h{h_level} id="{self._anchor_id(heading_match.group(2))}">{text}</h{h_level}>')
                i += 1
                continue

            if line.strip() in ("----", "---"):
                html.append("<hr>")
                i += 1
                continue

            if re.match(r'^\*+\s', line):
                list_lines = []
                while i < len(lines) and re.match(r'^\*+\s', lines[i]):
                    list_lines.append(lines[i])
                    i += 1
                html.append(self._render_list(list_lines, "ul", current_title, current_disc))
                continue

            if re.match(r'^#+\s', line):
                list_lines = []
                while i < len(lines) and re.match(r'^#+\s', lines[i]):
                    list_lines.append(lines[i])
                    i += 1
                html.append(self._render_list(list_lines, "ol", current_title, current_disc))
                continue

            if re.match(r'^;', line):
                html.append(self._render_definition(line, current_title, current_disc))
                i += 1
                continue

            para_lines = []
            while i < len(lines) and lines[i].strip() and not lines[i].strip().startswith(("{|", "|}", "=", "*", "#", ";", "----", "---")):
                para_lines.append(lines[i])
                i += 1
            if para_lines:
                text = " ".join(para_lines)
                html.append(f"<p>{self._parse_inline(text, current_title, current_disc)}</p>")

        if in_table:
            html.append(self._render_table(table_rows))

        return "\n".join(html)

    def _handle_redirect(self, wikitext: str) -> str:
        m = re.match(r'#REDIRECT\s*\[\[([^\]]+)\]\]', wikitext.strip())
        if m:
            target = m.group(1).split("|")[0].strip()
            return f'<div class="redirect">Redirect to: [[{target}]]</div>'
        return wikitext

    def _handle_templates(self, wikitext: str, current_disc: str = "") -> str:
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
        # Portal / Reflist
        wikitext = re.sub(r'\{\{Portal\|(.+?)\}\}', '<div class="portal">📖 Portal: \\1</div>', wikitext)
        wikitext = wikitext.replace("{{Reflist|30em}}", '<div class="reflist">References</div>')
        wikitext = wikitext.replace("{{Reflist}}", '<div class="reflist">References</div>')
        # Infobox
        wikitext = re.sub(
            r'\{\{Infobox\s+(\w+)(.*?)\}\}',
            lambda m: self._render_infobox(m.group(1), m.group(2)),
            wikitext,
            flags=re.DOTALL
        )
        return wikitext

    def _render_infobox(self, box_type: str, content: str) -> str:
        rows = []
        for line in content.strip().split("\n"):
            line = line.strip()
            if not line or line.startswith("|"):
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
        html_rows = []
        for row in rows:
            row = row.strip()
            if row.startswith("|-") or row.startswith("|}"):
                continue
            if row.startswith("!"):
                cells = re.split(r'\s*!!\s*', row[1:].strip())
                html_rows.append("<tr>" + "".join(f'<th>{self._parse_inline(c.strip())}</th>' for c in cells) + "</tr>")
            elif row.startswith("|"):
                cells = re.split(r'\s*\|\|\s*', row[1:].strip())
                html_rows.append("<tr>" + "".join(f'<td>{self._parse_inline(c.strip())}</td>' for c in cells) + "</tr>")
        return f'<table class="wikitable"><tbody>{"".join(html_rows)}</tbody></table>'

    def _render_list(self, lines: list, list_type: str, current_title: str = "", current_disc: str = "") -> str:
        prefix_char = "*" if list_type == "ul" else "#"
        def _process(items, indent=0):
            html_str = ""
            i = 0
            while i < len(items):
                line = items[i]
                depth = len(re.match(rf'^\{prefix_char}+', line).group())
                if depth == indent + 1:
                    content = re.sub(rf'^\{prefix_char}+\s*', '', line)
                    html_str += f"<li>{self._parse_inline(content, current_title, current_disc)}"
                    sub = []
                    j = i + 1
                    while j < len(items):
                        sub_depth = len(re.match(rf'^\{prefix_char}+', items[j]).group())
                        if sub_depth <= indent + 1:
                            break
                        sub.append(items[j])
                        j += 1
                    if sub:
                        html_str += _process(sub, indent + 1)
                    html_str += "</li>"
                    i = j
                else:
                    i += 1
            return html_str
        inner = _process(lines, 0)
        return f"<{list_type}>{inner}</{list_type}>"

    def _render_definition(self, line: str, current_title: str = "", current_disc: str = "") -> str:
        m = re.match(r';(.+?):(.+)', line)
        if m:
            term = self._parse_inline(m.group(1).strip(), current_title, current_disc)
            defn = self._parse_inline(m.group(2).strip(), current_title, current_disc)
            return f"<dl><dt>{term}</dt><dd>{defn}</dd></dl>"
        return f"<p>{self._parse_inline(line, current_title, current_disc)}</p>"

    def _parse_inline(self, text: str, current_title: str = "", current_disc: str = "") -> str:
        if not text:
            return ""

        # External links
        text = re.sub(
            r'\[(https?://[^\s\]]+)\s+([^\]]*)\]',
            r'<a href="\1" class="external">\2</a>',
            text
        )

        # Wiki links [[page]] and [[page|text]]
        def replace_link(m):
            inner = m.group(1)
            if "|" in inner:
                parts = inner.split("|", 1)
                target = parts[0].strip()
                display = parts[1].strip()
            else:
                target = inner.strip()
                display = target

            anchor = ""
            if "#" in target:
                target, anchor = target.split("#", 1)
                target = target.strip()

            # Resolve alias
            resolved = self.resolve_title(target)
            if resolved:
                cls = ""
                url_target = self._url_title(resolved)
                # Find which discipline
                disc = self.disc_manager.disc_for_page(resolved)
            elif target in self._alias_map:
                en = self._alias_map[target]
                if self.page_exists(en):
                    cls = ""
                    url_target = self._url_title(en)
                    disc = self.disc_manager.disc_for_page(en)
                else:
                    cls = ' class="new"'
                    url_target = self._url_title(target)
                    disc = current_disc
            else:
                cls = ' class="new"'
                url_target = self._url_title(target)
                disc = current_disc

            anchor_attr = f"#{self._anchor_id(anchor)}" if anchor else ""
            disc_attr = f"?disc={disc}" if disc else ""
            href = f"/wiki/{url_target}{anchor_attr}{disc_attr}"
            return f'<a href="{href}"{cls}>{display}</a>'

        text = re.sub(r'\[\[([^\]]+)\]\]', replace_link, text)

        # Math
        text = re.sub(r'<math>(.*?)</math>', r'<span class="math">\\(\1\\)</span>', text)

        # Bold and italic
        text = re.sub(r"'''''(.+?)'''''", r"<b><i>\1</i></b>", text)
        text = re.sub(r"'''(.+?)'''", r"<b>\1</b>", text)
        text = re.sub(r"''(.+?)''", r"<i>\1</i>", text)

        # Nowiki
        text = re.sub(r'<nowiki>(.*?)</nowiki>', r'\1', text)

        return text

    def _url_title(self, title: str) -> str:
        return title.replace(" ", "_")

    def _anchor_id(self, text: str) -> str:
        result = text.strip().lower()
        for ch in "'()–,—/-.":
            result = result.replace(ch, "")
        result = re.sub(r'[^\w]+', '-', result)
        result = re.sub(r'-+', '-', result)
        return result.strip("-")

    def search(self, query: str, disc_id: str = None, limit: int = 50) -> list:
        """Full-text search, optionally filtered by discipline."""
        query_lower = query.lower()
        disc_pages = set(self.disc_manager.get_pages(disc_id)) if disc_id else None
        results = []

        for page in self.all_pages:
            # Discipline filter
            if disc_pages is not None and page["title"].replace(" ", "_") not in disc_pages:
                continue

            title = page["title"]
            content = page["content"]
            title_match = query_lower in title.lower()

            if title_match:
                snippet = self._extract_snippet(content, query_lower)
                results.append({"title": title, "snippet": snippet, "score": 2})
                continue

            if query_lower in content.lower():
                snippet = self._extract_snippet(content, query_lower)
                results.append({"title": title, "snippet": snippet, "score": 1})

        results.sort(key=lambda r: (-r["score"], r["title"].lower()))
        return results[:limit]

    def _extract_snippet(self, content: str, query: str, context: int = 120) -> str:
        clean = re.sub(r'\{\{.*?\}\}', '', content, flags=re.DOTALL)
        clean = re.sub(r'<math>.*?</math>', '', clean)
        clean = re.sub(r'\[\[Category:.*?\]\]', '', clean)
        clean = re.sub(r'={2,}.*?={2,}', '', clean)

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

        snippet = re.sub(f'({re.escape(query)})', r'<mark>\1</mark>', snippet, flags=re.IGNORECASE)
        return snippet

    def get_categories(self) -> dict:
        cats = defaultdict(list)
        for page in self.all_pages:
            for m in re.finditer(r'\[\[Category:(.+?)(?:\|.*?)?\]\]', page["content"]):
                cat = m.group(1).strip()
                cats[cat].append(page["title"])
        return dict(sorted(cats.items()))


# ─── Global Instances ───────────────────────────────────────────

disc_mgr = DisciplineManager(INDEX_DIR)
parser = WikiParser(WIKI_DIR, disc_mgr)


# ─── Context Processor ──────────────────────────────────────────

@app.context_processor
def inject_globals():
    disc_id = request.args.get("disc", "")
    disc = disc_mgr.disciplines.get(disc_id)
    disc_name = disc["name"] if disc else "All Disciplines"

    # Quick links: top 8 pages by cross-reference count in current discipline
    quick_links = []
    if disc_id and disc:
        quick_links = [p.replace("_", " ") for p in disc["pages"][:8]]
    else:
        # Show a mix from all disciplines
        all_pages = sorted([p["title"] for p in parser.all_pages], key=str.lower)
        quick_links = all_pages[:8]

    return {
        "total_pages": len(parser.all_pages),
        "disc_id": disc_id,
        "disc_name": disc_name,
        "disciplines": disc_mgr.all_disciplines,
        "quick_links": quick_links,
    }


# ─── Helper: disc-aware URL builder ─────────────────────────────

def disc_url(path: str, disc_id: str = "") -> str:
    suffix = f"?disc={disc_id}" if disc_id else ""
    return f"{path}{suffix}"


# ─── Routes ─────────────────────────────────────────────────────

@app.route("/")
def main_page():
    """Main page: discipline overview with featured content."""
    disc_id = request.args.get("disc", "")

    if disc_id:
        disc = disc_mgr.disciplines.get(disc_id)
        if not disc:
            abort(404)
        # Discipline-specific view
        all_titles = sorted([p.replace("_", " ") for p in disc["pages"]], key=str.lower)
        featured = all_titles[:6]
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
                               disc_id=disc_id,
                               disc=disc,
                               featured=featured,
                               all_titles=all_titles,
                               snippets=snippets,
                               total_pages=disc["count"],
                               categories=list(parser.get_categories().items())[:12])
    else:
        # Root: show all disciplines
        return render_template("discipline_home.html",
                               disciplines=disc_mgr.all_disciplines,
                               total_pages=disc_mgr.total_pages)


@app.route("/wiki/<path:title>")
def wiki_page(title: str):
    """Display a wiki page."""
    disc_id = request.args.get("disc", "")
    decoded = title.replace("_", " ")
    page = parser.get_page(decoded)

    if not page:
        # Try alias resolution
        resolved = parser.resolve_title(decoded)
        if resolved:
            return redirect(f"/wiki/{parser._url_title(resolved)}?disc={disc_id}")
        return render_template("404.html", title=decoded), 404

    # Auto-detect discipline if not provided
    file_stem = page["file"].stem
    if not disc_id:
        disc_id = disc_mgr.disc_for_page(file_stem)

    html_content = parser.parse(page["content"], current_title=page["title"], current_disc=disc_id)
    return render_template("page.html", title=page["title"], content=html_content, disc_id=disc_id)


@app.route("/index")
def page_index():
    """Alphabetical index of all pages, optionally filtered by discipline."""
    disc_id = request.args.get("disc", "")
    disc_pages = set(disc_mgr.get_pages(disc_id)) if disc_id else None

    all_pages = sorted(parser.all_pages, key=lambda p: p["title"].lower())
    if disc_pages is not None:
        all_pages = [p for p in all_pages if p["title"].replace(" ", "_") in disc_pages]

    groups = defaultdict(list)
    for p in all_pages:
        first = p["title"][0].upper()
        groups[first].append(p["title"])

    sorted_groups = sorted(groups.items())
    return render_template("index.html", total=len(all_pages), groups=sorted_groups, disc_id=disc_id)


@app.route("/search")
def search():
    """Search wiki pages, optionally filtered by discipline."""
    query = request.args.get("q", "").strip()
    disc_id = request.args.get("disc", "")
    results = []
    if query:
        results = parser.search(query, disc_id=disc_id if disc_id else None)

    return render_template("search.html", query=query, results=results, disc_id=disc_id)


@app.route("/categories")
def categories():
    """Category index."""
    disc_id = request.args.get("disc", "")
    cats = parser.get_categories()
    return render_template("categories.html", cats=cats, disc_id=disc_id)


@app.route("/random")
def random_page():
    """Redirect to a random wiki page."""
    import random
    disc_id = request.args.get("disc", "")
    disc_pages = disc_mgr.get_pages(disc_id) if disc_id else None

    if disc_pages:
        titles = [p.replace("_", " ") for p in disc_pages if parser.page_exists(p.replace("_", " "))]
    else:
        titles = [p["title"] for p in parser.all_pages]

    if not titles:
        return redirect("/")
    title = random.choice(titles)
    return redirect(f"/wiki/{title.replace(' ', '_')}?disc={disc_id}")


# ─── Static files ───────────────────────────────────────────────

@app.route("/static/<path:filename>")
def static_files(filename):
    from flask import send_from_directory
    return send_from_directory("static", filename)


# ─── Main ───────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="Multi-Discipline Wiki Browser")
    ap.add_argument("port", nargs="?", type=int, default=8080,
                    help="Port number to listen on (default: 8080)")
    ap.add_argument("--host", default="127.0.0.1",
                    help="Host to bind to (default: 127.0.0.1)")
    ap.add_argument("--no-debug", action="store_true",
                    help="Disable debug mode")
    args = ap.parse_args()

    print(f"📚 Multi-Discipline Wiki Browser")
    print(f"   Wiki dir: {WIKI_DIR}")
    print(f"   Index dir: {INDEX_DIR}")
    print(f"   Disciplines: {len(disc_mgr.disciplines)}")
    for d in disc_mgr.all_disciplines:
        print(f"     {d['icon']} {d['name']}: {d['count']} pages")
    print(f"   Total pages: {disc_mgr.total_pages}")
    print(f"   Starting server at http://{args.host}:{args.port}")
    app.run(host=args.host, port=args.port, debug=not args.no_debug)
