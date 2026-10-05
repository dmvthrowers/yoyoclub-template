#!/usr/bin/env python3
"""Build this template's own showcase site into _site/: the "how to deploy" guide page
(showcase/index.html) plus live example sites in _site/examples/<name>/.

Used only by the original template repository (see .github/workflows/deploy.yml).
Copies of the template build their own site with build.py instead.
"""
import os
import shutil
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "_site"
EXAMPLES = [                               # (folder name, settings file)
    ("dmv-throwers", "examples/dmv-throwers.jsonc"),
    ("demo-yoyo-club", "site.jsonc"),
    ("demo-skill-toy", "examples/demo-skill-toy.jsonc"),
    ("demo-kendama", "examples/demo-kendama.jsonc"),
    ("demo-youth-program", "examples/demo-youth-program.jsonc"),
]

base_url = os.environ.get("SITE_URL", "").strip()
if base_url.startswith("http://"):          # GitHub Pages reports http:// until HTTPS is enforced
    base_url = "https://" + base_url[len("http://"):]
if base_url and not base_url.endswith("/"):
    base_url += "/"

if OUT.exists():
    shutil.rmtree(OUT)
shutil.copytree(ROOT / "showcase", OUT)
(OUT / ".nojekyll").write_text("")
robots = "User-agent: *\nAllow: /\n"
if base_url:
    robots += f"\nSitemap: {base_url}sitemap.xml\n"
    (OUT / "sitemap.xml").write_text('<?xml version="1.0" encoding="UTF-8"?>\n'
                                     '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
                                     f"  <url><loc>{base_url}</loc></url>\n</urlset>\n")
(OUT / "robots.txt").write_text(robots)

for name, config in EXAMPLES:
    url = f"{base_url}examples/{name}/" if base_url else ""
    out = f"_site/examples/{name}"
    subprocess.run([sys.executable, "build.py", "--config", config, "--out", out, "--base-url", url, "--noindex"],
                   cwd=ROOT, check=True)
    base_path = urlparse(url).path if url else "/"
    subprocess.run([sys.executable, "scripts/check_site.py", out, base_path], cwd=ROOT, check=True)

print(f"Showcase built into _site/ with {len(EXAMPLES)} examples" + (f" at {base_url}" if base_url else ""))
