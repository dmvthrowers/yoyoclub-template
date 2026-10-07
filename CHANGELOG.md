# Changelog

What changed in each release of this template. Newest first. Copies of the template can use it to see what is new before they update (see [docs/UPDATING.md](docs/UPDATING.md)).

## Unreleased

Nothing yet. Changes that merge after 1.0.0 are listed here until the next tag.

## 1.0.0

The first tagged release: a club website built from one settings file.

- Ten pages from `site.jsonc` and a preset: home, about, meetups, learn, team, gallery, resources, FAQ, contact, code of conduct, plus privacy and a 404.
- Meetup dates roll forward on their own from a repeating rule; `meetup.skip` handles exceptions and the site rebuilds daily.
- Seven presets (yo-yo, kendama, diabolo, spin top, juggling, mixed skill toys, youth program) and a `toys` setting that rewrites the text for any mix of toys.
- Generated emblem, icons and share card in your colors; strict security policy; no cookies, trackers or outside fonts.
- `scripts/check_site.py` checks links, alt text, headers and footers, the security policy and unfilled `{placeholders}`.
- The build fails on an empty contact email; Escape closes the phone menu.
- A How to Yo-Yo link and a small DMV Throwers thank-you on the Resources page (delete the two lines to remove it).

