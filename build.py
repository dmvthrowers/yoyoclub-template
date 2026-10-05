#!/usr/bin/env python3
"""Build the website from site.jsonc + a preset into _site/.

    python3 build.py                 # build into _site/
    python3 build.py --serve         # build, then preview at http://localhost:8000/
    python3 build.py --base-url https://example.org/   # set the public address

No installs needed: standard-library Python 3.9+ only.

How it fits together:
  site.jsonc        your settings (the only file most people edit)
  presets/*.json    starting text for each kind of club (yo-yo, skill toys, kendama, youth program)
  assets/           stylesheet, script, your images and documents (copied as-is)
  content/*.html    optional extra HTML added to the bottom of a page (e.g. content/about.html)
  build.py          this file: meetup dates, then one small function per page, near the bottom
"""
import argparse
import datetime as dt
import html
import http.server
import json
import os
import re
import shutil
import struct
import sys
import zlib
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "_site"
warnings = []


# ---------------------------------------------------------------- config

def load_jsonc(path):
    """JSON that allows whole-line // comments and trailing commas."""
    # Blank out comment lines (instead of removing them) so error line numbers match the file.
    lines = ["" if l.lstrip().startswith("//") else l for l in path.read_text(encoding="utf-8").splitlines()]
    text = re.sub(r",(\s*[}\]])", r"\1", "\n".join(lines))
    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        sys.exit(f"\n{path.name} has a typo near line {e.lineno}: {e.msg}.\n"
                 "Check for a missing comma or quote on that line or the one above it.\n")


def merge(base, override):
    """Settings in site.jsonc win over the preset. Empty strings/lists don't erase preset values."""
    if isinstance(base, dict) and isinstance(override, dict):
        out = dict(base)
        for k, v in override.items():
            out[k] = merge(base.get(k), v) if k in base else v
        return out
    if override in (None, "", []) and base not in (None, "", []):
        return base
    return override


def load_config(config_path=ROOT / "site.jsonc"):
    site = load_jsonc(config_path)
    name = site.get("preset") or "yoyo-club"
    preset_path = ROOT / "presets" / f"{name}.json"
    if not preset_path.exists():
        choices = ", ".join(sorted(p.stem for p in (ROOT / "presets").glob("*.json")))
        sys.exit(f'\nUnknown preset "{name}" in site.jsonc. Choose one of: {choices}\n')
    preset = json.loads(preset_path.read_text(encoding="utf-8"))
    return merge(preset, site)


# ---------------------------------------------------------------- helpers

esc = html.escape


def ext_link(url, label, cls=""):
    c = f' class="{cls}"' if cls else ""
    return f'<a{c} href="{esc(url)}" rel="noopener noreferrer">{esc(label)}</a>'


def mailto(email, subject=""):
    q = f"?subject={esc(subject)}" if subject else ""
    return f'<a href="mailto:{esc(email)}{q}">{esc(email)}</a>'


def hex_rgb(color):
    c = color.lstrip("#")
    if len(c) == 3:
        c = "".join(ch * 2 for ch in c)
    if not re.fullmatch(r"[0-9a-fA-F]{6}", c):
        sys.exit(f'\nTheme color "{color}" must be a hex color like "#102040".\n')
    return tuple(int(c[i:i + 2], 16) for i in (0, 2, 4))


def luminance(rgb):
    def ch(v):
        v /= 255
        return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4
    r, g, b = (ch(v) for v in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(a, b):
    la, lb = luminance(hex_rgb(a)), luminance(hex_rgb(b))
    return (max(la, lb) + 0.05) / (min(la, lb) + 0.05)


def darken(color, f=0.72):
    return "#%02x%02x%02x" % tuple(int(v * f) for v in hex_rgb(color))


MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
MONTHS_FULL = ["January", "February", "March", "April", "May", "June", "July", "August",
               "September", "October", "November", "December"]
DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
DAYS_FULL = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
ORDINALS = {1: "1st", 2: "2nd", 3: "3rd", 4: "4th", 5: "5th", -1: "last"}


def fmt_date(d, style):
    if style == "intl":
        return f"{DAYS[d.weekday()]} {d.day} {MONTHS[d.month - 1]} {d.year}"
    return f"{DAYS[d.weekday()]}, {MONTHS[d.month - 1]} {d.day}, {d.year}"


def fmt_day(d, style):
    """Short date for the date block: "October 18" or "18 October"."""
    return f"{d.day} {MONTHS_FULL[d.month - 1]}" if style == "intl" else f"{MONTHS_FULL[d.month - 1]} {d.day}"


def parse_time(t, what):
    if not t:
        return None
    m = re.fullmatch(r"(\d{1,2}):(\d{2})", str(t).strip())
    if not m or int(m.group(1)) > 23 or int(m.group(2)) > 59:
        warnings.append(f'{what} "{t}" should be a 24-hour time like "13:00". Ignored.')
        return None
    return dt.time(int(m.group(1)), int(m.group(2)))


def fmt_time(t, style, meridiem=True):
    if style == "intl":
        return f"{t.hour:02d}:{t.minute:02d}"
    h = t.hour % 12 or 12
    s = f"{h}:{t.minute:02d}" if t.minute else str(h)
    return f"{s} {'AM' if t.hour < 12 else 'PM'}" if meridiem else s


def fmt_time_range(start, end, style):
    if not start:
        return ""
    if not end:
        return fmt_time(start, style)
    if style == "intl":
        return f"{fmt_time(start, style)}–{fmt_time(end, style)}"
    if (start.hour < 12) == (end.hour < 12):
        return f"{fmt_time(start, style, meridiem=False)}–{fmt_time(end, style)}"
    return f"{fmt_time(start, style)} – {fmt_time(end, style)}"


def weekday_index(name):
    n = str(name or "").strip().lower()
    for i, full in enumerate(DAYS_FULL):
        if n and full.lower().startswith(n[:3]):
            return i
    sys.exit(f'\nmeetup.schedule.weekday "{name}" should be a day name like "Sunday".\n')


def nth_weekday(year, month, weekday, n):
    """The nth weekday (0=Mon) of a month; n = -1 means the last one. None if it doesn't exist."""
    if n == -1:
        last = (dt.date(year + (month == 12), month % 12 + 1, 1) - dt.timedelta(days=1))
        return last - dt.timedelta(days=(last.weekday() - weekday) % 7)
    first = dt.date(year, month, 1)
    d = first + dt.timedelta(days=(weekday - first.weekday()) % 7 + 7 * (n - 1))
    return d if d.month == month else None


def image_size(path):
    """Width/height of PNG, GIF, JPEG, or WebP files without any libraries."""
    data = path.read_bytes()
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return struct.unpack(">II", data[16:24])
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return struct.unpack("<HH", data[6:10])
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        kind = data[12:16]
        if kind == b"VP8X":
            return (int.from_bytes(data[24:27], "little") + 1, int.from_bytes(data[27:30], "little") + 1)
        if kind == b"VP8 ":
            w, h = struct.unpack("<HH", data[26:30])
            return w & 0x3FFF, h & 0x3FFF
        if kind == b"VP8L":
            b = int.from_bytes(data[21:25], "little")
            return (b & 0x3FFF) + 1, ((b >> 14) & 0x3FFF) + 1
    if data[:2] == b"\xff\xd8":
        i = 2
        while i < len(data) - 9:
            if data[i] != 0xFF:
                i += 1
                continue
            marker = data[i + 1]
            if marker in (0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF):
                h, w = struct.unpack(">HH", data[i + 5:i + 9])
                return w, h
            i += 2 + struct.unpack(">H", data[i + 2:i + 4])[0]
    return None


def png(width, height, pixel):
    """Tiny PNG writer: pixel(x, y) -> (r, g, b)."""
    rows = b"".join(b"\x00" + bytes(c for x in range(width) for c in pixel(x, y)) for y in range(height))
    def chunk(tag, body):
        return struct.pack(">I", len(body)) + tag + body + struct.pack(">I", zlib.crc32(tag + body) & 0xFFFFFFFF)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(rows, 9)) + chunk(b"IEND", b""))


def yoyo_png(size_w, size_h, primary, accent, background):
    """A flat yo-yo on a string (accent rim, primary body, hub) for social previews and app icons."""
    p, a, bg = hex_rgb(primary), hex_rgb(accent), hex_rgb(background)
    wide = size_w > size_h
    cx, cy = (size_w * 0.70, size_h * 0.56) if wide else (size_w / 2, size_h * 0.56)
    r = min(size_w, size_h) * (0.30 if wide else 0.36)
    string_w = max(2, int(r * 0.05))
    stripe = size_h - max(8, size_h // 30)
    def pixel(x, y):
        if wide and y >= stripe:
            return a
        d2 = (x - cx) ** 2 + (y - cy) ** 2
        if d2 <= (r * 0.16) ** 2:
            return a
        if d2 <= (r * 0.78) ** 2:
            return p
        if d2 <= r * r:
            return a
        if abs(x - cx) <= string_w and y < cy:
            return p
        return bg
    return png(size_w, size_h, pixel)


# ---------------------------------------------------------------- page building

class Site:
    def __init__(self, cfg, base_url):
        self.cfg = cfg
        self.club = cfg["club"]
        self.meetup = cfg.get("meetup") or {}
        self.base_url = base_url                                   # "" when unknown
        self.base_path = urlparse(base_url).path or "/" if base_url else "/"
        self.theme = cfg["theme"]
        self.name = self.club["name"]
        self.style = cfg["site"].get("date_format", "us")
        self.tz = None
        tzname = cfg["site"].get("timezone")
        if tzname:
            try:
                from zoneinfo import ZoneInfo
                self.tz = ZoneInfo(tzname)
            except Exception:
                warnings.append(f'Time zone "{tzname}" not found; using the computer\'s clock. '
                                'Use a name like "America/New_York".')
        self.today = dt.datetime.now(self.tz).date()
        self.has_calendar = bool(cfg.get("calendar", {}).get("embed_url"))
        self.pages = [("index", "Home"), ("about", "About"), ("meetups", "Meetups"), ("learn", "Learn"),
                      ("team", "Team"), ("gallery", "Gallery"), ("resources", "Resources"),
                      ("faq", "FAQ"), ("contact", "Contact")]
        self.footer_pages = self.pages + [("conduct", "Code of Conduct"), ("privacy", "Privacy & Safety")]
        self.occurrences = self.meetup_occurrences()

    # --- meetup dates
    def schedule_times(self):
        s = self.meetup.get("schedule") or {}
        return parse_time(s.get("start"), "meetup.schedule.start"), parse_time(s.get("end"), "meetup.schedule.end")

    def meetup_occurrences(self):
        """Upcoming meetup dates from the repeating rule, as (date, skip_note_or_None)."""
        s = self.meetup.get("schedule") or {}
        repeat = (s.get("repeat") or "none").lower()
        if repeat == "none":
            return []
        count = int(self.meetup.get("show") or 6)
        months = set(s.get("months") or range(1, 13))
        skips = {}
        for sk in self.meetup.get("skip", []):
            try:
                skips[dt.date.fromisoformat(sk["date"])] = sk.get("note") or "No meetup this month"
            except (KeyError, ValueError):
                warnings.append(f'meetup.skip date "{sk.get("date")}" should be YYYY-MM-DD. Ignored.')
        wd = weekday_index(s.get("weekday"))
        candidates = []
        if repeat == "monthly":
            week = s.get("week", 1)
            n = -1 if str(week).lower() in ("last", "-1") else int(week)
            if n not in ORDINALS:
                sys.exit('\nmeetup.schedule.week should be 1, 2, 3, 4, 5, or "last".\n')
            y, m = self.today.year, self.today.month
            for _ in range(36):
                d = nth_weekday(y, m, wd, n)
                if d and d >= self.today and m in months:
                    candidates.append(d)
                y, m = (y + 1, 1) if m == 12 else (y, m + 1)
        elif repeat == "weekly":
            every = int(s.get("every") or 1)
            anchor = None
            if every > 1:
                try:
                    anchor = dt.date.fromisoformat(s.get("from", ""))
                except ValueError:
                    sys.exit('\nmeetup.schedule.every is more than 1, so set "from" to the date of '
                             'one real meetup, like "2026-10-06".\n')
            d = self.today + dt.timedelta(days=(wd - self.today.weekday()) % 7)
            for _ in range(160):
                if d.month in months and (not anchor or ((d - anchor).days // 7) % every == 0):
                    candidates.append(d)
                d += dt.timedelta(days=7)
        else:
            sys.exit(f'\nmeetup.schedule.repeat "{repeat}" should be "monthly", "weekly", or "none".\n')
        out, held = [], 0
        for d in candidates:
            out.append((d, skips.get(d)))
            held += d not in skips
            if held >= count:
                break
        return out

    def next_meetup(self):
        return next((d for d, skip in self.occurrences if not skip), None)

    def meetup_summary(self):
        if self.meetup.get("summary"):
            return self.meetup["summary"]
        s = self.meetup.get("schedule") or {}
        repeat = (s.get("repeat") or "none").lower()
        if repeat == "none":
            return ""
        day = DAYS_FULL[weekday_index(s.get("weekday"))]
        if repeat == "monthly":
            week = s.get("week", 1)
            n = -1 if str(week).lower() in ("last", "-1") else int(week)
            when = f"Every {ORDINALS[n]} {day}" if n > 0 else f"The last {day} of every month"
        else:
            every = int(s.get("every") or 1)
            when = f"Every {day}" if every == 1 else ("Every other " + day if every == 2 else f"Every {every} weeks on {day}")
        times = fmt_time_range(*self.schedule_times(), self.style)
        return f"{when}, {times}" if times else when

    def venue_line(self):
        m = self.meetup
        return " · ".join(x for x in (m.get("venue"), m.get("room")) if x)

    # --- shared text
    def fill(self, text):
        c, m = self.cfg, self.meetup
        loan = c.get("loaners") or {}
        values = {"name": self.name, "city": self.club.get("city", ""), "area": self.area(),
                  "ages": c["program"]["ages"], "welcome": c["program"]["welcome"],
                  "meetup": self.meetup_summary() or "Meetup dates are posted on our Meetups page",
                  "venue": m.get("venue", ""), "address": m.get("address", ""),
                  "email": c["contact"]["email"], "cost": c["cost"]["details"] or c["cost"]["summary"],
                  "loaners": loan.get("yes") if m.get("loaners", True) else loan.get("no", ""),
                  "toy": c["terms"]["toy"], "toys": c["terms"]["toys"], "players": c["terms"]["players"]}
        return re.sub(r"\{(\w+)\}", lambda mt: values.get(mt.group(1), mt.group(0)), text)

    def area(self):
        return self.club.get("area") or ", ".join(x for x in (self.club.get("city"), self.club.get("region")) if x)

    def url(self, page):
        if not self.base_url:
            return ""
        return self.base_url if page == "index" else f"{self.base_url}{page}.html"

    def csp(self):
        frame = "https://calendar.google.com" if self.has_calendar else "'none'"
        return ("default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
                f"font-src 'self'; frame-src {frame}; connect-src 'self'; base-uri 'self'; "
                "form-action 'none'; object-src 'none'; upgrade-insecure-requests")

    def nav(self, current, pages, root):
        items = []
        for slug, label in pages:
            cur = ' aria-current="page"' if slug == current else ""
            items.append(f'<li><a href="{root}{slug}.html"{cur}>{esc(label)}</a></li>')
        return "\n        ".join(items)

    def top_bar(self, root):
        d = self.next_meetup()
        if d:
            times = fmt_time_range(*self.schedule_times(), self.style)
            bits = [fmt_date(d, self.style)] + [x for x in (times, self.meetup.get("venue")) if x]
            text = f'<strong>Next meetup</strong> {esc(" · ".join(bits))}'
        else:
            text = esc(self.club.get("slogan") or self.club.get("tagline", ""))
        return (f'<div class="top-bar"><div class="top-bar-inner"><p>{text}</p>'
                f'<a href="{root}meetups.html">Details</a></div></div>')

    def socials(self):
        return [s for s in self.cfg["contact"].get("social", []) if s.get("url")]

    def donate(self):
        d = self.cfg["contact"].get("donate") or {}
        return d if d.get("url") else None

    def footer(self, current, root):
        c = self.cfg
        socials = " &bull; ".join(ext_link(s["url"], s["name"]) for s in self.socials())
        donate = self.donate()
        donate_html = f'<p>{ext_link(donate["url"], donate.get("label") or "Support the club")}</p>' if donate else ""
        source = c["site"].get("source_url")
        source_html = (f'<p class="footer-source"><a href="{esc(source)}" rel="noopener noreferrer">'
                       f'Website source code</a></p>') if source else ""
        credit_html = ('<p class="footer-credit">Site template by Brandon Rogers &amp; '
                       '<a href="https://dmvthrowers.club/" rel="noopener noreferrer">DMV Throwers</a></p>'
                       ) if c["site"].get("credit", True) else ""
        slogan = self.club.get("slogan")
        return f"""<footer class="site-footer">
  <div class="wrap">
    <p class="footer-name">{esc(self.name)}</p>
    {f'<p class="footer-slogan">{esc(slogan)}</p>' if slogan else ''}
    <nav class="footer-nav" aria-label="Footer navigation">
      <ul>
        {self.nav(current, self.footer_pages, root)}
      </ul>
    </nav>
    <p>{mailto(c["contact"]["email"])}</p>
    {f'<p>{socials}</p>' if socials else ''}
    {donate_html}
    {source_html}
    <p class="footer-note">&copy; {self.today.year} {esc(self.name)}{(' &mdash; ' + esc(self.area())) if self.area() else ''}</p>
    {credit_html}
  </div>
</footer>"""

    def layout(self, slug, title, description, body, jsonld=None, robots="index, follow"):
        root = self.base_path if slug == "404" else ""
        page_title = self.name if slug == "index" else f"{title} — {self.name}"
        head_urls = []
        if self.base_url:
            if slug != "404":
                head_urls.append(f'<link rel="canonical" href="{esc(self.url(slug))}">')
                head_urls.append(f'<meta property="og:url" content="{esc(self.url(slug))}">')
            head_urls.append(f'<meta property="og:image" content="{esc(self.base_url)}og-card.png">')
            head_urls.append('<meta property="og:image:width" content="1200">')
            head_urls.append('<meta property="og:image:height" content="630">')
        ld = []
        if self.base_url and slug not in ("index", "404"):
            ld.append({"@context": "https://schema.org", "@type": "BreadcrumbList", "itemListElement": [
                {"@type": "ListItem", "position": 1, "name": "Home", "item": self.url("index")},
                {"@type": "ListItem", "position": 2, "name": title, "item": self.url(slug)}]})
        if isinstance(jsonld, list):
            ld.extend(jsonld)
        elif jsonld:
            ld.append(jsonld)
        ld_html = ""
        if ld:
            payload = json.dumps(ld if len(ld) > 1 else ld[0], indent=2, ensure_ascii=False).replace("</", "<\\/")
            ld_html = f'\n  <script type="application/ld+json">\n{payload}\n  </script>'
        sub = " · ".join(x for x in (self.cfg["terms"]["club_type"], self.area()) if x)
        page = f"""<!DOCTYPE html>
<html lang="{esc(self.cfg['site'].get('language') or 'en')}">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{esc(page_title)}</title>
  <meta name="description" content="{esc(description)}">
  <meta name="robots" content="{robots}">
  <meta name="referrer" content="strict-origin-when-cross-origin">
  <meta name="theme-color" content="{esc(self.theme['primary'])}">
  <meta http-equiv="Content-Security-Policy" content="{self.csp()}">
  {chr(10).join('  ' + h for h in head_urls).strip()}
  <meta property="og:type" content="website">
  <meta property="og:site_name" content="{esc(self.name)}">
  <meta property="og:title" content="{esc(page_title)}">
  <meta property="og:description" content="{esc(description)}">
  <meta name="twitter:card" content="summary_large_image">
  <link rel="icon" href="{root}favicon.svg" type="image/svg+xml">
  <link rel="apple-touch-icon" href="{root}apple-touch-icon.png">
  <link rel="manifest" href="{root}site.webmanifest">
  <link rel="stylesheet" href="{root}theme.css">
  <link rel="stylesheet" href="{root}style.css">{ld_html}
</head>
<body>
<a class="skip-link" href="#main-content">Skip to main content</a>
<header class="site-header">
  {self.top_bar(root)}
  <div class="header-inner">
    <a class="brand" href="{root}index.html">
      <img class="brand-mark" src="{root}emblem.svg" alt="" width="44" height="44">
      <span class="brand-text"><span class="brand-name">{esc(self.name)}</span><span class="brand-sub">{esc(sub)}</span></span>
    </a>
    <button class="nav-toggle" type="button" aria-label="Menu" aria-expanded="false" aria-controls="site-nav">&#9776;</button>
  </div>
  <nav class="site-nav" id="site-nav" aria-label="Main navigation">
    <ul>
      {self.nav(slug, self.pages, root)}
    </ul>
  </nav>
</header>
<main id="main-content">
{body}{self.extra_content(slug)}
</main>
{self.footer(slug, root)}
<script src="{root}site.js" defer></script>
</body>
</html>
"""
        return re.sub(r"\n\s*\n(\s*<meta property=\"og:type\")", r"\n\1", page)

    def extra_content(self, slug):
        """Optional hand-written HTML in content/<page>.html, added at the end of that page."""
        f = ROOT / "content" / f"{slug}.html"
        if not f.exists():
            return ""
        return f'\n<section class="section section-extra">\n  <div class="wrap">\n{f.read_text(encoding="utf-8")}\n  </div>\n</section>'

    def page_head(self, eyebrow, title, lede):
        return f"""<section class="page-head">
  <div class="wrap">
    <p class="eyebrow">{esc(eyebrow)}</p>
    <h1>{esc(title)}</h1>
    <p>{esc(lede)}</p>
  </div>
</section>"""

    def cards(self, items, cls="cards"):
        return f'<div class="{cls}">' + "".join(
            f'\n  <div class="card"><h3>{esc(i["title"])}</h3><p>{esc(self.fill(i["text"]))}</p></div>' for i in items) + "\n</div>"

    def link_cards(self, items):
        cards = []
        for i in items:
            if not i.get("url"):
                continue
            text = f'<p>{esc(self.fill(i["text"]))}</p>' if i.get("text") else ""
            cards.append(f'\n  <div class="card link-card"><h3>{esc(i["title"])}</h3>{text}'
                         f'<p>{ext_link(i["url"], i.get("label") or "Visit", "more")}</p></div>')
        return f'<div class="cards cards-3">{"".join(cards)}\n</div>' if cards else ""

    def link_groups(self, groups):
        out = []
        for g in groups:
            links = "".join(f'<li>{ext_link(l["url"], l["title"])}'
                            + (f' <span class="muted">{esc(l["text"])}</span>' if l.get("text") else "") + "</li>"
                            for l in g.get("links", []) if l.get("url"))
            if links:
                out.append(f'<div class="link-group"><h3>{esc(g["title"])}</h3><ul>{links}</ul></div>')
        return '<div class="link-groups">' + "".join(out) + "</div>" if out else ""

    def chips(self):
        items = self.cfg.get("disciplines", [])
        return ('<ul class="chips" aria-label="What we play">' + "".join(f"<li>{esc(d)}</li>" for d in items) + "</ul>"
                if items else "")

    # --- events (special events from site.jsonc, plus the repeating meetups)
    def special_events(self):
        upcoming, tbd = [], []
        for e in self.cfg.get("events", []):
            if not e.get("date"):
                tbd.append((None, e))
                continue
            try:
                d = dt.date.fromisoformat(e["date"])
                end = dt.date.fromisoformat(e["end_date"]) if e.get("end_date") else d
            except ValueError:
                warnings.append(f'Event "{e.get("title")}" has a bad date (use YYYY-MM-DD). Skipped.')
                continue
            if end >= self.today:
                upcoming.append((d, e))
        return sorted(upcoming, key=lambda x: x[0]), tbd

    def agenda(self, limit=None):
        """Meetups, skipped meetups, and special events in date order; undated events last."""
        start, end = self.schedule_times()
        times = fmt_time_range(start, end, self.style)
        rows = []
        first = True
        for d, skip in self.occurrences:
            if skip:
                rows.append((d, {"kind": "No meetup", "title": skip, "skipped": True}))
                continue
            rows.append((d, {"kind": "Next meetup" if first else self.cfg["terms"]["meetup_label"],
                             "title": self.meetup.get("venue") or "Club meetup",
                             "where": " · ".join(x for x in (self.meetup.get("address"), self.meetup.get("room")) if x),
                             "details": self.meetup.get("first_time", "") if first else "",
                             "time": times, "tag": self.meetup.get("rsvp", ""), "meetup": True}))
            first = False
        dated, tbd = self.special_events()
        for d, e in dated:
            rows.append((d, dict(e, kind=e.get("kind") or "Special event", where=e.get("location", ""))))
        rows.sort(key=lambda r: r[0])
        rows += [(None, dict(e, kind=e.get("kind") or "Special event", where=e.get("location", ""))) for _, e in tbd]
        return rows[:limit] if limit else rows

    def agenda_html(self, limit=None):
        rows = self.agenda(limit)
        if not rows:
            return '<p class="muted">No upcoming dates posted yet. Check back soon!</p>'
        out = []
        for d, e in rows:
            cls = "event" + (" event-skipped" if e.get("skipped") else "") + (" event-special" if not e.get("meetup") and not e.get("skipped") else "")
            when = fmt_day(d, self.style) if d else "Date TBA"
            day = DAYS_FULL[d.weekday()] if d else ""
            if e.get("end_date") and d:
                end = dt.date.fromisoformat(e["end_date"])
                if end != d:
                    when = f"{fmt_day(d, self.style)} – {fmt_day(end, self.style)}"
                    day = f"{DAYS[d.weekday()]} – {DAYS[end.weekday()]}"
            sub = " · ".join(x for x in (day, e.get("time", "")) if x)
            details = f'<p>{esc(e["details"])}</p>' if e.get("details") else ""
            where = f'<p class="event-where">{esc(e["where"])}</p>' if e.get("where") else ""
            link = f'<p>{ext_link(e["url"], e.get("url_label") or "More info", "more")}</p>' if e.get("url") else ""
            tag = f'<span class="event-tag">{esc(e["tag"])}</span>' if e.get("tag") else ""
            out.append(f'<li class="{cls}"><div class="event-body"><span class="event-kind">{esc(e["kind"])}</span>'
                       f'<h3>{esc(e["title"])}</h3>{where}{details}{link}</div>'
                       f'<div class="event-when"><span class="event-day">{esc(when)}</span>'
                       f'<span class="event-sub">{esc(sub)}</span>{tag}</div></li>')
        return '<ul class="event-list">\n' + "\n".join(out) + "\n</ul>"

    def event_jsonld(self):
        start, end = self.schedule_times()
        free = bool(self.cfg["cost"].get("free"))
        place = {"@type": "Place", "name": self.meetup.get("venue") or self.area(),
                 "address": self.meetup.get("address") or self.area()}
        org = {"@type": "Organization", "name": self.name}
        if self.base_url:
            org["url"] = self.base_url
        def stamp(d, t):
            if not t:
                return d.isoformat()
            return dt.datetime.combine(d, t, tzinfo=self.tz).isoformat() if self.tz else dt.datetime.combine(d, t).isoformat()
        items = []
        for d, skip in self.occurrences:
            if skip:
                continue
            ev = {"@context": "https://schema.org", "@type": "Event", "name": f"{self.name} {self.cfg['terms']['meetup_label'].title()}",
                  "description": self.fill(self.cfg["program"]["meetup_blurb"]), "startDate": stamp(d, start),
                  "eventStatus": "https://schema.org/EventScheduled",
                  "eventAttendanceMode": "https://schema.org/OfflineEventAttendanceMode",
                  "location": place, "organizer": org, "isAccessibleForFree": free}
            if end:
                ev["endDate"] = stamp(d, end)
            items.append(ev)
        for d, e in self.special_events()[0]:
            ev = {"@context": "https://schema.org", "@type": "Event", "name": e["title"], "startDate": d.isoformat(),
                  "eventStatus": "https://schema.org/EventScheduled",
                  "eventAttendanceMode": "https://schema.org/OfflineEventAttendanceMode",
                  "location": {"@type": "Place", "name": e.get("location") or place["name"],
                               "address": e.get("location") or place["address"]}, "organizer": org}
            if e.get("end_date"):
                ev["endDate"] = e["end_date"]
            if e.get("details"):
                ev["description"] = e["details"]
            if e.get("url"):
                ev["url"] = e["url"]
            items.append(ev)
        return items

    def partners_html(self):
        cards = []
        for p in self.cfg.get("partners", []):
            code = (f'<p class="code-box"><span class="label">Discount code</span><strong>{esc(p["code"])}</strong></p>'
                    if p.get("code") else "")
            label = p.get("label") or "Visit " + p["name"]
            link = f'<p>{ext_link(p["url"], label, "more")}</p>' if p.get("url") else ""
            cards.append(f'\n  <div class="card"><h3>{esc(p["name"])}</h3><p>{esc(p.get("text", ""))}</p>{code}{link}</div>')
        return f'<div class="cards cards-3">{"".join(cards)}\n</div>' if cards else ""

    # ------------------------------------------------------------ pages (one function each)

    def page_index(self):
        c, g = self.cfg, self.club
        eyebrow = " · ".join(x for x in ((f"Est. {g['founded']}" if g.get("founded") else ""), self.area()) if x)
        d = self.next_meetup()
        stats = []
        summary = self.meetup_summary()
        if summary:
            stats.append((summary.split(",")[0], "Meetups"))
        stats.append((c["cost"]["summary"], "Cost"))
        stats.append((c["program"]["ages_short"], "Who can come"))
        if g.get("founded"):
            stats.append((f"Est. {g['founded']}", self.area() or "Founded"))
        stats_html = "".join(f'<li><strong>{esc(v)}</strong><span>{esc(k)}</span></li>' for v, k in stats)
        next_html = ""
        if d:
            times = fmt_time_range(*self.schedule_times(), self.style)
            map_url = self.meetup.get("map_url")
            next_html = f"""<section class="section section-alt">
  <div class="wrap">
    <div class="next-meetup">
      <div>
        <p class="eyebrow">Next meetup</p>
        <h2>{esc(fmt_date(d, self.style))}</h2>
        <p class="next-time">{esc(" · ".join(x for x in (times, self.venue_line()) if x))}</p>
        <p>{esc(self.meetup.get("address", ""))}</p>
        <p>{esc(self.fill(self.meetup.get("first_time", "")))}</p>
      </div>
      <p class="btn-col"><a class="btn btn-primary" href="meetups.html">All meetup dates</a>{ext_link(map_url, "Get directions", "btn btn-outline") if map_url else ""}</p>
    </div>
  </div>
</section>"""
        about = "".join(f"<p>{esc(self.fill(p))}</p>" for p in c["program"]["about"])
        partners = self.partners_html()
        partners_html = f"""
<section class="section">
  <div class="wrap">
    <p class="eyebrow center">Partners</p>
    <h2 class="center">Shop &amp; Support the Club</h2>
    {partners}
  </div>
</section>""" if partners else ""
        featured = [(d2, e) for d2, e in self.special_events()[0] if e.get("featured")][:1]
        feature_html = ""
        if featured:
            fd, fe = featured[0]
            link = ext_link(fe["url"], fe.get("url_label") or "Learn more", "btn btn-accent") if fe.get("url") else \
                '<a class="btn btn-accent" href="meetups.html">See details</a>'
            meta = " · ".join(x for x in (fmt_date(fd, self.style), fe.get("time", ""), fe.get("location", "")) if x)
            feature_html = f"""
<section class="feature">
  <div class="wrap">
    <p class="eyebrow">{esc(fe.get("kind") or "Coming up")}</p>
    <h2>{esc(fe["title"])}</h2>
    <p class="feature-meta">{esc(meta)}</p>
    {f'<p>{esc(fe["details"])}</p>' if fe.get("details") else ""}
    <p class="btn-row">{link}</p>
  </div>
</section>"""
        body = f"""<section class="hero">
  <div class="wrap">
    {f'<p class="eyebrow">{esc(eyebrow)}</p>' if eyebrow else ''}
    <img class="hero-mark" src="emblem.svg" alt="{esc(self.name)} logo" width="132" height="132">
    <h1>{esc(self.name)}</h1>
    <p class="tagline">{esc(g.get("tagline", ""))}</p>
    <p class="lede">{esc(g.get("description", ""))}</p>
    {f'<p class="slogan">{esc(g["slogan"])}</p>' if g.get("slogan") else ''}
    <div class="btn-row">
      <a class="btn btn-accent" href="meetups.html">See Upcoming Meetups</a>
      <a class="btn btn-ghost" href="about.html">About Us</a>
    </div>
  </div>
</section>

<section class="stats" aria-label="At a glance">
  <div class="wrap"><ul>{stats_html}</ul></div>
</section>
{next_html}
<section class="section">
  <div class="wrap narrow">
    <p class="eyebrow">About us</p>
    <h2>{esc(c["program"]["about_title"])}</h2>
    {about}
    {self.chips()}
    <p><a class="more" href="about.html">More about the club</a></p>
  </div>
</section>
{feature_html}
<section class="section section-alt">
  <div class="wrap">
    <p class="eyebrow center">What we do</p>
    <h2 class="center">Come Throw With Us</h2>
    {self.cards(c["program"]["pillars"], "cards cards-4")}
    <p class="center"><a class="btn btn-primary" href="learn.html">Start learning</a></p>
  </div>
</section>
{partners_html}"""
        org = {"@context": "https://schema.org", "@type": "SportsOrganization", "name": self.name,
               "description": g.get("description", ""), "email": c["contact"]["email"],
               "sport": c["terms"]["sport"],
               "address": {"@type": "PostalAddress", "addressLocality": g.get("city", ""), "addressRegion": g.get("region", "")}}
        if self.base_url:
            org["url"] = self.base_url
            org["logo"] = self.base_url + "apple-touch-icon.png"
        if g.get("founded"):
            org["foundingDate"] = g["founded"]
        if self.socials():
            org["sameAs"] = [s["url"] for s in self.socials()]
        return "Home", g.get("description", ""), body, org

    def page_about(self):
        c, g = self.cfg, self.club
        about = "".join(f"<p>{esc(self.fill(p))}</p>" for p in c["program"]["about"])
        history = "".join(f"<p>{esc(p)}</p>" for p in g.get("history", []))
        facts = []
        if g.get("founded"):
            facts.append(("Founded", g["founded"]))
        if self.area():
            facts.append(("Area", self.area()))
        if self.meetup_summary():
            facts.append(("Meetups", self.meetup_summary()))
        if self.meetup.get("venue"):
            facts.append(("Where", self.venue_line()))
        facts.append(("Cost", c["cost"]["summary"]))
        facts.append(("Who", c["program"]["ages_short"]))
        facts_html = "".join(f'<div class="card glance"><span class="label">{esc(k)}</span><p class="value">{esc(v)}</p></div>'
                             for k, v in facts)
        docs = [doc for doc in c.get("documents", []) if doc.get("about")]
        docs_html = ""
        if docs:
            docs_html = f"""
<section class="section">
  <div class="wrap">
    <p class="eyebrow center">Club documents</p>
    <h2 class="center">How the Club Runs</h2>
    {self.documents_html(docs)}
  </div>
</section>"""
        body = f"""{self.page_head("About us", c["program"]["about_title"], g.get("description", ""))}

<section class="section">
  <div class="wrap narrow">
    {about}
    {self.chips()}
  </div>
</section>

<section class="section section-alt">
  <div class="wrap">
    <h2 class="center">At a Glance</h2>
    <div class="cards cards-3">{facts_html}</div>
  </div>
</section>
{f'''
<section class="section">
  <div class="wrap narrow">
    <h2>Our Story</h2>
    {history}
  </div>
</section>''' if history else ''}
<section class="section{' section-alt' if history else ''}">
  <div class="wrap">
    <h2 class="center">What We Do</h2>
    {self.cards(c["program"]["pillars"], "cards cards-4")}
  </div>
</section>
{docs_html}
<section class="section section-alt">
  <div class="wrap narrow">
    <h2>{esc(c["safety"]["title"])}</h2>
    <ul class="checklist">{"".join(f"<li>{esc(self.fill(p))}</li>" for p in c["safety"]["points"])}</ul>
    <p><a class="more" href="conduct.html">Read our code of conduct</a></p>
  </div>
</section>"""
        return "About", f"About {self.name}: who we are, what we play, and how the club runs.", body, None

    def page_meetups(self):
        c, m = self.cfg, self.meetup
        summary = self.meetup_summary()
        intro_bits = []
        if summary:
            intro_bits.append(f"{summary} at {self.venue_line() or 'our meetup spot'}.")
        intro_bits.append(c["cost"]["summary"] + ".")
        if m.get("rsvp"):
            intro_bits.append(m["rsvp"] + ".")
        if m.get("loaners", True) and (c.get("loaners") or {}).get("yes"):
            intro_bits.append(self.fill(c["loaners"]["yes"]))
        embed = c.get("calendar", {}).get("embed_url", "")
        frame = ""
        if embed:
            if not embed.startswith("https://calendar.google.com/"):
                warnings.append("calendar.embed_url should start with https://calendar.google.com/ (ignored).")
            else:
                frame = (f'<h2>Calendar</h2>\n    <iframe class="cal-frame" title="{esc(self.name)} calendar" src="{esc(embed)}" loading="lazy"></iframe>\n'
                         f'    <p class="muted center">Calendar not loading? Email {mailto(c["contact"]["email"])} for dates.</p>')
        where = ""
        if m.get("venue") or m.get("address"):
            map_link = f'<p>{ext_link(m["map_url"], "Open in maps", "more")}</p>' if m.get("map_url") else ""
            directions = "".join(f"<p>{esc(p)}</p>" for p in m.get("directions", []))
            where = f"""
<section class="section section-alt">
  <div class="wrap narrow">
    <h2>Where We Meet</h2>
    <div class="card">
      <h3>{esc(m.get("venue", ""))}</h3>
      {f'<p>{esc(m["room"])}</p>' if m.get("room") else ''}
      <p>{esc(m.get("address", ""))}</p>
      {directions}
      {map_link}
    </div>
  </div>
</section>"""
        season = f' <strong>Season:</strong> {esc(m["season"])}.' if m.get("season") else ""
        body = f"""{self.page_head("Schedule", "Meetups & Events", summary or "Meetups, workshops, and special events.")}

<section class="section">
  <div class="wrap">
    <p class="intro">{esc(" ".join(intro_bits))}{season} Questions? Email {mailto(c["contact"]["email"])}.</p>
    {self.agenda_html()}
    <ul class="pill-row" aria-label="Good to know">{"".join(f"<li>{esc(t)}</li>" for t in c["program"]["badges"])}</ul>
    {frame}
  </div>
</section>
{where}"""
        return "Meetups", f"{self.name} meetups and events: {summary or 'dates, times, and place'}.", body, self.event_jsonld()

    def page_learn(self):
        c = self.cfg
        L = c["learn"]
        levels = []
        for lv in L.get("levels", []):
            tricks = "".join(f"<li>{esc(t)}</li>" for t in lv.get("tricks", []))
            levels.append(f'\n  <div class="card level"><span class="label">{esc(lv.get("label", ""))}</span>'
                          f'<h3>{esc(lv["name"])}</h3><p>{esc(lv.get("text", ""))}</p><ul class="tricks">{tricks}</ul></div>')
        divisions = ""
        if L.get("divisions"):
            rows = "".join(f'<tr><th scope="row">{esc(d["code"])}</th><td>{esc(d["name"])}</td><td>{esc(d["text"])}</td></tr>'
                           for d in L["divisions"])
            divisions = f"""
<section class="section">
  <div class="wrap narrow">
    <h2>{esc(L.get("divisions_title", "Contest Styles"))}</h2>
    <p>{esc(L.get("divisions_intro", ""))}</p>
    <div class="table-wrap"><table><thead><tr><th scope="col">Style</th><th scope="col">Name</th><th scope="col">What it is</th></tr></thead>
    <tbody>{rows}</tbody></table></div>
  </div>
</section>"""
        links = self.link_groups(L.get("links", []))
        body = f"""{self.page_head("Learn", L.get("title", "Learn to Throw"), L.get("intro", ""))}

<section class="section">
  <div class="wrap">
    <h2 class="center">Start Here</h2>
    {self.cards(L.get("basics", []), "cards cards-4")}
  </div>
</section>

<section class="section section-alt">
  <div class="wrap">
    <h2 class="center">{esc(L.get("levels_title", "Trick Path"))}</h2>
    <p class="center intro">{esc(L.get("levels_intro", ""))}</p>
    <div class="cards cards-3">{"".join(levels)}
    </div>
  </div>
</section>
{divisions}
<section class="section{' section-alt' if divisions else ''}">
  <div class="wrap">
    <h2 class="center">Tutorials &amp; Tools</h2>
    {links}
    <p class="center muted">{esc(self.fill(L.get("outro", "")))}</p>
  </div>
</section>"""
        return "Learn", f"Learn {c['terms']['toy']} tricks with {self.name}: first steps, a trick path, and tutorials.", body, None

    def page_team(self):
        c = self.cfg
        cards = []
        for o in c.get("officers", []):
            if o.get("open"):
                cards.append(f'\n  <div class="card person person-open"><div class="avatar" aria-hidden="true">+</div>'
                             f'<span class="label">Open role</span><h3>{esc(o["role"])}</h3>'
                             f'<p>{esc(o.get("bio", ""))}</p><p><a class="more" href="mailto:{esc(c["contact"]["email"])}?subject=Volunteering">Volunteer for this role</a></p></div>')
                continue
            name = o.get("name", "")
            initials = "".join(w[0] for w in re.findall(r"[^\W\d_]+", name)[:2]).upper() or "?"
            extra = []
            if o.get("handle"):
                extra.append(f'<p class="handle">{esc(o["handle"])}</p>')
            if o.get("email"):
                extra.append(f"<p>{mailto(o['email'])}</p>")
            cards.append(f'\n  <div class="card person"><div class="avatar" aria-hidden="true">{esc(initials)}</div>'
                         f'<span class="label">{esc(o["role"])}</span><h3>{esc(name)}</h3>'
                         f'<p>{esc(o.get("bio", ""))}</p>{"".join(extra)}</div>')
        grid = f'<div class="cards cards-3">{"".join(cards)}\n</div>' if cards else \
            f'<p class="muted center">Our team list is coming soon. Want to help run the club? Email {mailto(c["contact"]["email"])}.</p>'
        body = f"""{self.page_head("Leadership", "Meet the Team", "The volunteers who keep the club running.")}

<section class="section">
  <div class="wrap">
    {grid}
  </div>
</section>

<section class="section section-alt">
  <div class="wrap narrow center">
    <h2>Help Run the Club</h2>
    <p>{esc(self.fill(c["program"]["volunteer"]))}</p>
    <p><a class="btn btn-primary" href="mailto:{esc(c["contact"]["email"])}?subject=Volunteering">Email us to help</a></p>
  </div>
</section>"""
        return "Team", f"Meet the volunteers who run {self.name}.", body, None

    def page_gallery(self):
        c = self.cfg
        figs = []
        for ph in c.get("gallery", []):
            src = ROOT / "assets" / ph["src"]
            if not src.exists():
                warnings.append(f'Gallery photo not found: assets/{ph["src"]}')
                continue
            size = image_size(src)
            if not size:
                warnings.append(f'Could not read the size of {ph["src"]}; use a JPG, PNG, GIF, or WebP file.')
                continue
            if src.stat().st_size > 500_000:
                warnings.append(f'{ph["src"]} is {src.stat().st_size // 1024} KB; resize it under 500 KB so pages load fast.')
            if not ph.get("alt"):
                warnings.append(f'{ph["src"]} has no "alt" description; screen-reader users need one.')
            cap = ""
            if ph.get("caption") or ph.get("text"):
                strong = f'<strong>{esc(ph["caption"])}</strong>' if ph.get("caption") else ""
                span = f'<span>{esc(ph["text"])}</span>' if ph.get("text") else ""
                cap = f"<figcaption>{strong}{span}</figcaption>"
            figs.append(f'<figure><img src="{esc(ph["src"])}" alt="{esc(ph.get("alt", ""))}" width="{size[0]}" '
                        f'height="{size[1]}" loading="lazy" decoding="async">{cap}</figure>')
        grid = (f'<div class="gallery-grid">\n' + "\n".join(figs) + "\n</div>") if figs else \
            '<p class="muted center">Photos coming soon.</p>'
        socials = "".join(f"<li>{ext_link(s['url'], s['name'], 'btn btn-outline')}</li>" for s in self.socials())
        more = f"""
<section class="section section-alt">
  <div class="wrap center">
    <h2>More Photos &amp; Videos</h2>
    <p>Follow along for the latest from every meetup.</p>
    <ul class="btn-list">{socials}</ul>
  </div>
</section>""" if socials else ""
        body = f"""{self.page_head("Photos", "Gallery", "Meetups, workshops, contests, and good times.")}

<section class="section">
  <div class="wrap">
    <p class="notice">Photos taken at our events may show attendees. Want a photo removed? Email {mailto(c["contact"]["email"])} and we'll take it down. See our <a href="privacy.html">photo policy</a>.</p>
    {grid}
  </div>
</section>
{more}"""
        return "Gallery", f"Photos from {self.name} meetups and events.", body, None

    def documents_html(self, docs):
        cards = []
        for doc in docs:
            f = ROOT / "assets" / doc["file"]
            if not f.exists():
                warnings.append(f'Document not found: assets/{doc["file"]}')
                continue
            kind = f.suffix.lstrip(".").upper() or "file"
            cards.append(f'\n  <div class="card link-card"><h3>{esc(doc["title"])}</h3><p>{esc(doc.get("text", ""))}</p>'
                         f'<p><a class="more" href="{esc(doc["file"])}">View {esc(kind)}</a></p></div>')
        return f'<div class="cards cards-3">{"".join(cards)}\n</div>' if cards else ""

    def page_resources(self):
        c = self.cfg
        sections = []
        docs = self.documents_html(c.get("documents", []))
        if docs:
            sections.append(("Downloads", "Guides & Documents", docs))
        partners = self.partners_html()
        if partners:
            sections.append(("Partners", "Shops That Support Us", partners))
        mine = self.link_cards(c.get("links", []))
        if mine:
            sections.append(("Our links", "Club Links", mine))
        groups = self.link_groups(c.get("resources", []))
        if groups:
            sections.append(("Community", "Around the Community", groups))
        sisters = c.get("sister_clubs", [])
        if sisters:
            sections.append(("Nearby", "Sister Clubs & Local Groups", self.link_groups([{"title": "Clubs near us", "links": sisters}])))
        donate = self.donate()
        if donate:
            sections.append(("Support", "Help Keep Meetups Free",
                             f'<p class="center">{esc(self.fill(c["program"]["donate_text"]))}</p>'
                             f'<p class="center">{ext_link(donate["url"], donate.get("label") or "Support the club", "btn btn-accent")}</p>'))
        html_parts = []
        for i, (eyebrow, title, inner) in enumerate(sections):
            html_parts.append(f"""
<section class="section{' section-alt' if i % 2 else ''}">
  <div class="wrap">
    <p class="eyebrow center">{esc(eyebrow)}</p>
    <h2 class="center">{esc(title)}</h2>
    {inner}
  </div>
</section>""")
        body = f"""{self.page_head("Learn & reference", "Resources", f"Downloads, shops, and trusted links for {c['terms']['players']} of every level. Looking for tutorials? See the Learn page.")}
{"".join(html_parts) or '<section class="section"><div class="wrap"><p class="center"><a href="learn.html">Start with the Learn page</a></p></div></section>'}"""
        return "Resources", f"Downloads, shops, and trusted {c['terms']['toy']} links from {self.name}.", body, None

    def page_faq(self):
        c = self.cfg
        groups = {}
        for f in list(c.get("faq", [])) + list(c.get("faq_extra", [])):
            groups.setdefault(f.get("group") or "More Questions", []).append((self.fill(f["q"]), self.fill(f["a"])))
        blocks, qa_all = [], []
        for title, qa in groups.items():
            qa_all += qa
            items = "".join(f'\n  <details class="faq-item"><summary>{esc(q)}</summary><p>{esc(a)}</p></details>' for q, a in qa)
            blocks.append(f'<h2 class="faq-group">{esc(title)}</h2>\n    <div class="faq-list">{items}\n    </div>')
        ld = {"@context": "https://schema.org", "@type": "FAQPage", "mainEntity": [
            {"@type": "Question", "name": q, "acceptedAnswer": {"@type": "Answer", "text": a}} for q, a in qa_all]}
        body = f"""{self.page_head("FAQ", "Frequently Asked Questions", "Got a question? It's probably answered below. If not, email us.")}

<section class="section">
  <div class="wrap narrow">
    {"".join(blocks)}
    <p class="center">Still wondering? Email {mailto(c["contact"]["email"])}.</p>
  </div>
</section>"""
        return "FAQ", f"{self.name} FAQ: meetups, cost, what to bring, and more.", body, ld

    def page_contact(self):
        c, m = self.cfg, self.meetup
        phone = c["contact"].get("phone")
        phone_html = f'<p>Phone: <a href="tel:{esc(re.sub(r"[^0-9+]", "", phone))}">{esc(phone)}</a></p>' if phone else ""
        socials = "".join(f'<li>{ext_link(s["url"], s["name"])}'
                          + (f' <span class="muted">{esc(s["text"])}</span>' if s.get("text") else "") + "</li>"
                          for s in self.socials())
        social_html = f'<div class="card"><h2>Online</h2><ul class="plain-list">{socials}</ul></div>' if socials else ""
        donate = self.donate()
        donate_html = (f'<p>{ext_link(donate["url"], donate.get("label") or "Support the club", "btn btn-accent")}</p>'
                       if donate else "")
        meet = ""
        if self.meetup_summary() or m.get("venue"):
            meet = (f'<p><strong>Meetups:</strong> {esc(self.meetup_summary())}<br>{esc(self.venue_line())}'
                    f'{"<br>" + esc(m["address"]) if m.get("address") else ""}</p>')
        body = f"""{self.page_head("Get in touch", "Contact Us", "Questions about the club, meetups, or getting started? We'd love to hear from you.")}

<section class="section">
  <div class="wrap">
    <div class="cards cards-2">
      <div class="card contact-card">
        <h2>Email</h2>
        <p class="big-email">{mailto(c["contact"]["email"])}</p>
        {phone_html}
        {meet}
        <p>{esc(self.fill(c["program"]["contact_note"]))}</p>
        {donate_html}
      </div>
      {social_html}
    </div>
  </div>
</section>"""
        return "Contact", f"Contact {self.name}: email, meetup time and place, and social links.", body, None

    def page_conduct(self):
        c = self.cfg
        cc = c["conduct"]
        def ul(items):
            return "<ul>" + "".join(f"<li>{esc(self.fill(i))}</li>" for i in items) + "</ul>"
        version = " · ".join(x for x in ((f"Effective {cc['effective']}" if cc.get("effective") else ""),
                                          (f"Version {cc['version']}" if cc.get("version") else "")) if x)
        body = f"""{self.page_head("Community standards", "Code of Conduct", f"Applies to all {self.name} meetups, events, and online spaces.")}

<section class="section">
  <div class="wrap narrow prose">
    {f'<p class="label">{esc(version)}</p>' if version else ''}
    <p>{esc(self.fill(cc["intro"]))}</p>
    <h2>The Short Version</h2>
    <p class="callout">{esc(self.fill(cc["short"]))}</p>
    <h2>Who This Applies To</h2>
    {ul(cc["applies"])}
    <h2>Expected Behavior</h2>
    {ul(cc["expected"])}
    <h2>Not Okay</h2>
    {ul(cc["unacceptable"])}
    <h2>Equipment Safety</h2>
    {ul(cc["equipment"])}
    <h2>Reporting a Problem</h2>
    <p>{esc(self.fill(cc["reporting"]))} Email {mailto(c["contact"]["email"], "Code of conduct")}.</p>
    <h2>What Happens Next</h2>
    <p>{esc(self.fill(cc["consequences"]))}</p>
  </div>
</section>"""
        return "Code of Conduct", f"The {self.name} code of conduct for meetups, events, and online spaces.", body, None

    def page_privacy(self):
        c = self.cfg
        cal = (" The Meetups page shows a Google Calendar, covered by the "
               + ext_link("https://policies.google.com/privacy", "Google Privacy Policy") + ".") if self.has_calendar else ""
        body = f"""{self.page_head("Your information", "Privacy & Safety", "How this website handles information, and how we keep meetups safe.")}

<section class="section">
  <div class="wrap narrow prose">
    <h2>What This Website Collects</h2>
    <p>Nothing. This site has no sign-up forms, cookies, analytics, ads, or tracking. It is hosted on
      GitHub Pages, which may log basic technical data for security under the
      {ext_link("https://docs.github.com/en/site-policy/privacy-policies/github-general-privacy-statement", "GitHub Privacy Statement")}.{cal}</p>
    <p>Links to shops, social media, and other sites follow those sites' own privacy policies.</p>
    <h2>When You Email Us</h2>
    <p>We use your name, email, and anything you share only to answer you and run club activities. We never sell or share it.</p>
    <h2>{esc(c["safety"]["title"])}</h2>
    <ul>{"".join(f"<li>{esc(self.fill(p))}</li>" for p in c["safety"]["points"])}</ul>
    <h2>Photos</h2>
    <p>{esc(self.fill(c["safety"]["photos"]))}</p>
    <p>Want a photo taken down? Email {mailto(c["contact"]["email"], "Photo removal")} and we'll remove it promptly.</p>
  </div>
</section>"""
        return "Privacy & Safety", f"How {self.name} handles your information and keeps meetups safe.", body, None

    def page_404(self):
        root = self.base_path
        body = f"""{self.page_head("404", "Page Not Found", "That page doesn't exist. It may have moved.")}

<section class="section">
  <div class="wrap center">
    <p class="btn-row"><a class="btn btn-primary" href="{root}index.html">Go to Home</a>
      <a class="btn btn-primary" href="{root}meetups.html">See Meetups</a></p>
  </div>
</section>"""
        return "Page Not Found", f"Page not found — {self.name}.", body, None

    # ------------------------------------------------------------ generated files

    def theme_css(self):
        t = self.theme
        on_accent = "#111111" if contrast(t["accent"], "#111111") >= contrast(t["accent"], "#ffffff") else "#ffffff"
        checks = [("white text on your primary color", "#ffffff", t["primary"]),
                  ("text on your background color", t["ink"], t["background"]),
                  ("headings (primary color) on your background color", t["primary"], t["background"]),
                  ("labels (accent color) on your background color", t["accent"], t["background"]),
                  ("top bar text on your accent color", on_accent, t["accent"])]
        for what, fg, bg in checks:
            ratio = contrast(fg, bg)
            if ratio < 4.5:
                warnings.append(f"Hard to read: {what} has contrast {ratio:.1f}:1 (needs 4.5:1). Try a darker or lighter color.")
        corners = {"sharp": "0", "soft": "6px", "round": "14px"}.get(t.get("corners", "sharp"), "0")
        return f"""/* Generated by build.py from your theme colors. Edit colors in site.jsonc, not here. */
:root {{
  --primary: {t["primary"]};
  --primary-dark: {darken(t["primary"])};
  --accent: {t["accent"]};
  --accent-dark: {darken(t["accent"], 0.8)};
  --on-accent: {on_accent};
  --bg: {t["background"]};
  --ink: {t["ink"]};
  --radius: {corners};
}}
"""

    def emblem_svg(self):
        """A yo-yo with the club's initials, on a string. Replace with assets/emblem.svg for your own logo."""
        t = self.theme
        label = (self.club.get("short_name") or "".join(w[0] for w in re.findall(r"[A-Za-z0-9]+", self.name))[:3]).upper()[:4]
        size = {1: 34, 2: 28, 3: 22, 4: 17}.get(len(label), 17)
        return f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100" width="100" height="100" role="img" aria-label="{esc(self.name)}">
  <rect x="48.5" y="0" width="3" height="22" fill="{t["primary"]}"/>
  <circle cx="50" cy="58" r="41" fill="{t["accent"]}"/>
  <circle cx="50" cy="58" r="34" fill="{t["primary"]}"/>
  <circle cx="50" cy="58" r="27" fill="none" stroke="{t["accent"]}" stroke-width="1.5" stroke-dasharray="4 3"/>
  <text x="50" y="58" text-anchor="middle" dominant-baseline="central" font-family="system-ui, -apple-system, 'Segoe UI', Roboto, sans-serif" font-weight="800" font-size="{size}" fill="#ffffff">{esc(label)}</text>
</svg>
"""

    def build(self):
        if OUT.exists():
            shutil.rmtree(OUT)
        shutil.copytree(ROOT / "assets", OUT)
        (OUT / ".nojekyll").write_text("")
        (OUT / "theme.css").write_text(self.theme_css())
        if not (OUT / "emblem.svg").exists():                       # your own assets/emblem.svg wins
            (OUT / "emblem.svg").write_text(self.emblem_svg())
        if not (OUT / "favicon.svg").exists():
            shutil.copy(OUT / "emblem.svg", OUT / "favicon.svg")
        t = self.theme
        if not (OUT / "og-card.png").exists():                     # your own assets/og-card.png wins
            (OUT / "og-card.png").write_bytes(yoyo_png(1200, 630, t["primary"], t["accent"], t["background"]))
        if not (OUT / "apple-touch-icon.png").exists():
            (OUT / "apple-touch-icon.png").write_bytes(yoyo_png(180, 180, t["primary"], t["accent"], t["background"]))
        (OUT / "site.webmanifest").write_text(json.dumps({
            "name": self.name, "short_name": self.club.get("short_name") or self.name[:24],
            "start_url": "./", "display": "browser", "background_color": t["background"],
            "theme_color": t["primary"],
            "icons": [{"src": "apple-touch-icon.png", "sizes": "180x180", "type": "image/png"},
                      {"src": "emblem.svg", "sizes": "any", "type": "image/svg+xml"}]}, indent=2))
        for slug, _ in self.footer_pages + [("404", "")]:
            title, desc, body, ld = getattr(self, f"page_{slug}")()
            robots = "noindex, follow" if slug == "404" or getattr(self, "noindex", False) else "index, follow"
            (OUT / f"{slug}.html").write_text(self.layout(slug, title, desc, body, ld, robots), encoding="utf-8")
        robots = "User-agent: *\nAllow: /\n"
        if self.base_url:
            robots += f"\nSitemap: {self.base_url}sitemap.xml\n"
            urls = "".join(f"  <url><loc>{esc(self.url(s))}</loc><lastmod>{self.today.isoformat()}</lastmod></url>\n"
                           for s, _ in self.footer_pages)
            (OUT / "sitemap.xml").write_text('<?xml version="1.0" encoding="UTF-8"?>\n'
                                             '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n' + urls + "</urlset>\n")
        else:
            warnings.append("No site URL set, so canonical links, social previews, and sitemap.xml were skipped. "
                            "(Automatic on GitHub Pages; or set site.url in site.jsonc.)")
        (OUT / "robots.txt").write_text(robots)
        # The base path lets scripts/check_site.py resolve 404.html's absolute links.
        if OUT == ROOT / "_site":
            (ROOT / ".build-base-path").write_text(self.base_path)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--base-url", default=os.environ.get("SITE_URL", ""), help="public address, e.g. https://example.org/")
    ap.add_argument("--serve", action="store_true", help="preview at http://localhost:8000/ after building")
    ap.add_argument("--config", default="site.jsonc", help="settings file (default: site.jsonc)")
    ap.add_argument("--out", default="_site", help="output folder (default: _site)")
    ap.add_argument("--noindex", action="store_true", help="ask search engines not to list the site (demos)")
    ap.add_argument("--today", help="pretend today is YYYY-MM-DD (for testing meetup dates)")
    args = ap.parse_args()
    global OUT
    OUT = (ROOT / args.out).resolve()
    cfg = load_config((ROOT / args.config).resolve())
    base_url = (args.base_url or cfg["site"].get("url") or "").strip()
    if base_url and not base_url.endswith("/"):
        base_url += "/"
    if base_url.startswith("http://"):
        # GitHub Pages reports http:// until "Enforce HTTPS" is on; the site is still served over HTTPS.
        base_url = "https://" + base_url[len("http://"):]
        warnings.append(f"Using {base_url} (https). On GitHub Pages, tick Settings > Pages > Enforce HTTPS.")
    if base_url and urlparse(base_url).scheme != "https":
        warnings.append(f"Site URL {base_url} should start with https://")
    site = Site(cfg, base_url)
    if args.today:
        site.today = dt.date.fromisoformat(args.today)
        site.occurrences = site.meetup_occurrences()
    site.noindex = args.noindex
    site.build()
    nxt = site.next_meetup()
    print(f"Built {cfg.get('preset_name', cfg.get('preset'))} site for {site.name} into {OUT.relative_to(ROOT)}/"
          + (f" (address: {base_url})" if base_url else "")
          + (f"\n  Next meetup: {fmt_date(nxt, site.style)}" if nxt else ""))
    for w in dict.fromkeys(warnings):          # each warning once, in order
        print("  WARNING:", w)
    if args.serve:
        os.chdir(OUT)
        print("Preview: http://localhost:8000/   (Ctrl+C to stop)")
        http.server.ThreadingHTTPServer(("127.0.0.1", 8000), http.server.SimpleHTTPRequestHandler).serve_forever()


if __name__ == "__main__":
    main()
