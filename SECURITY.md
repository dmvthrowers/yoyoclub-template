# Security

This template builds a static site: no logins, forms, databases, cookies, or tracking.

Built-in protections:
- A strict Content Security Policy on every page: only the site's own files, plus Google Calendar
  if you configure one. No inline scripts or styles.
- An automatic check (`scripts/check_site.py`) runs before every deploy. It blocks inline
  scripts, styles and event handlers, `http://` links, and broken links.
- GitHub Actions are pinned to exact commit SHAs and kept current by Dependabot. The deploy job
  gets only the `pages: write` and `id-token: write` permissions it needs.

**Reporting a problem with the template:** open a GitHub issue. For anything sensitive, use
GitHub's private vulnerability reporting (Security tab) if the maintainer has enabled it.

**For sites built from this template:** report problems to that group's contact email, listed on
its Contact page.
