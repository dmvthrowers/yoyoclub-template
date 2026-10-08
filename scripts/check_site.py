#!/usr/bin/env python3
"""Check the built site in _site/ for problems. Run after build.py:

    python3 build.py && python3 scripts/check_site.py

Checks every page for: broken internal links and images, images without alt text or
size, invalid JSON-LD, missing title/description, the skip link, main#main-content,
that the header, menu, and footer are identical on every page, and that no text still
shows a {placeholder} (a misspelled word like {toys} in site.jsonc or a preset).
Security: every page has the Content Security Policy and referrer tags, with no
'unsafe-inline', no inline styles, scripts or event handlers, and no http:// links.
With --real (your copy's deploy workflow), it also fails while the template's sample content
(example.org addresses, the Springfield sample club) is still on the site.
Exits non-zero if anything fails. No installs needed.
"""
import json
import re
import sys
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlparse, unquote

ROOT = Path(__file__).resolve().parent.parent
args = sys.argv[1:]
# --real: this is someone's live site, so the template's sample content must be gone.
# Your copy's deploy workflow passes it; the template's own showcase doesn't.
REAL = "--real" in args
args = [a for a in args if a != "--real"]
# Text that only appears in the template's sample settings. Reserved example domains never belong
# on a real site.
SAMPLE_MARKERS = ("example.org", "example.com", "Springfield Throwers", "Jordan Example")
# Optional: check_site.py [SITE_DIR [BASE_PATH]] (used for the showcase's example sites)
SITE = (ROOT / args[0]).resolve() if args else ROOT / "_site"
base_file = ROOT / ".build-base-path"
BASE = args[1] if len(args) > 1 else (base_file.read_text().strip() if base_file.exists() else "/")
errors = []
PLACEHOLDER = re.compile(r"\{[A-Za-z_]+\}")


class Page(HTMLParser):
    def __init__(self):
        super().__init__()
        self.refs, self.imgs, self.svgs, self.ids, self.ld = [], [], [], set(), []
        self._ld = False
        self.title = False
        self.meta = {}
        self.csp = None
        self.security = []
        self.placeholders = []
        self.stray_refs = []
        self._skip = 0

    def handle_starttag(self, tag, attrs):
        # HTMLParser lower-cases tag and attribute names and handles any quoting style.
        a = dict(attrs)
        if a.get("id"):
            self.ids.add(a["id"])
        for k in ("href", "src"):
            if a.get(k) and tag != "iframe":
                self.refs.append(a[k])
        if tag == "img":
            self.imgs.append(a)
        if tag == "svg":
            self.svgs.append(a)
        if tag == "title":
            self.title = True
        if tag in ("script", "style"):
            self._skip += 1
        for k in ("alt", "title", "content", "aria-label"):
            self.placeholders += PLACEHOLDER.findall(a.get(k) or "")
        if tag == "meta" and a.get("name"):
            self.meta[a["name"].lower()] = a.get("content", "")
        if tag == "meta" and (a.get("http-equiv") or "").lower() == "content-security-policy":
            self.csp = a.get("content") or ""
        is_ld = tag == "script" and (a.get("type") or "").lower() == "application/ld+json"
        if is_ld:
            self._ld = True
            self.ld.append("")
        if tag == "style":
            self.security.append("inline <style> block (use style.css)")
        if tag == "script" and "src" not in a and not is_ld:
            self.security.append("inline <script> (use a .js file)")
        for k, v in a.items():
            if k == "style":
                self.security.append(f"inline style on <{tag}> (use a class in style.css)")
            elif k.startswith("on"):
                self.security.append(f"inline event handler {k}= on <{tag}>")
            elif k in ("href", "src", "action") and v:
                low = v.strip().lower()
                if low.startswith("http:"):
                    self.security.append(f"insecure http:// link: {v}")
                elif low.startswith("javascript:"):
                    self.security.append(f"javascript: URL on <{tag}>")

    def handle_endtag(self, tag):
        if tag == "script":
            self._ld = False
        if tag in ("script", "style"):
            self._skip = max(0, self._skip - 1)

    def handle_data(self, d):
        if self._ld:
            self.ld[-1] += d
            self.placeholders += PLACEHOLDER.findall(d)
        elif not self._skip:
            self.placeholders += PLACEHOLDER.findall(d)
            self.stray_refs += re.findall(r"\[ref:[^\]]*\]", d)


def shared_block(html, start, end):
    i = html.find(start)
    j = html.find(end, i)
    chunk = html[i:j + len(end)] if i >= 0 and j >= 0 else ""
    chunk = chunk.replace(' aria-current="page"', "")
    chunk = re.sub(r'(href|src)="' + re.escape(BASE), r'\1="', chunk) if BASE != "/" else chunk.replace('="/', '="')
    return re.sub(r"\s+", " ", chunk).strip()


if not SITE.exists():
    sys.exit("No _site/ folder. Run: python3 build.py")

pages = sorted(SITE.glob("*.html"))
for page in pages:
    html = page.read_text(encoding="utf-8")
    p = Page()
    p.feed(html)
    err = lambda msg, n=page.name: errors.append(f"{n}: {msg}")
    if p.csp is None:
        err("missing Content-Security-Policy meta tag")
    elif "unsafe-inline" in p.csp.lower() or "unsafe-eval" in p.csp.lower():
        err("CSP allows unsafe-inline/unsafe-eval")
    if not p.meta.get("referrer"):
        err("missing referrer meta tag")
    for problem in p.security:
        err(problem)
    for word in dict.fromkeys(p.placeholders):
        err(f"unfilled placeholder {word} in the page text (check its spelling in site.jsonc or the preset)")
    for ref in dict.fromkeys(p.stray_refs):
        err(f"citation {ref} was not turned into a link (is the guide's page listed in guides.items?)")
    if not p.title:
        err("missing <title>")
    if not p.meta.get("description"):
        err("missing meta description")
    if "main-content" not in p.ids:
        err('missing <main id="main-content">')
    if 'class="skip-link"' not in html:
        err("missing skip link")
    for block in p.ld:
        try:
            json.loads(block)
        except ValueError as e:
            err(f"invalid JSON-LD: {e}")
    for img in p.imgs:
        if "alt" not in img:
            err(f"img without alt: {img.get('src')}")
        if not (img.get("width") and img.get("height")):
            err(f"img without width/height: {img.get('src')}")
    for svg in p.svgs:
        if not (svg.get("width") and svg.get("height")):
            err("inline <svg> without width/height")
    for ref in p.refs:
        if ref.strip() in ("", "mailto:", "tel:") or ref.strip().startswith(("mailto:?", "tel:?")):
            err(f"empty link target: {ref!r}")
            continue
        u = urlparse(ref)
        if u.scheme in ("http", "https", "mailto", "tel", "data", "webcal") or ref.startswith("#"):
            continue
        path = unquote(u.path)
        if path.startswith(BASE):
            path = path[len(BASE):]
        elif path.startswith("/"):
            err(f"absolute link outside the site: {ref}")
            continue
        if not (SITE / (path or "index.html")).exists():
            err(f"broken link: {ref}")

if REAL:
    found = sorted({m for page in pages for m in SAMPLE_MARKERS if m in page.read_text(encoding="utf-8")})
    if found:
        errors.append("the site still shows the template's sample content (" + ", ".join(found) + "). "
                      "Put your own club's details in site.jsonc: name, contact email, meetup place and team.")

reference = (SITE / "about.html").read_text(encoding="utf-8")
for label, start, end in (("header", "<header", "</header>"), ("footer", "<footer", "</footer>")):
    want = shared_block(reference, start, end)
    for page in pages:
        if shared_block(page.read_text(encoding="utf-8"), start, end) != want:
            errors.append(f"{page.name}: {label} differs from about.html")

IMAGES = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg"}
for f in SITE.rglob("*"):
    if not f.is_file():
        continue
    size = f.stat().st_size
    if f.suffix.lower() in IMAGES and size > 500_000:
        errors.append(f"{f.relative_to(SITE)} is {size // 1024} KB (keep images under 500 KB)")
    elif size > 10_000_000:
        errors.append(f"{f.relative_to(SITE)} is {size // 1_000_000} MB (keep documents under 10 MB)")

if errors:
    print(f"{len(errors)} problem(s):")
    for e in errors:
        print("  -", e)
    sys.exit(1)
print(f"OK: {len(pages)} pages checked, no problems found.")
