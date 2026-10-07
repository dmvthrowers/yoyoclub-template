# Instructions for AI coding agents

You're helping someone launch a website for a yo-yo, kendama, diabolo, spin top, or juggling club, a
mixed skill toy meetup, or a youth program from this template. The human-facing guide is [README.md](README.md). Read it, then follow this.

## Goal
Get a correct, live site in one session (15–30 minutes) with as few human steps as possible.

## Steps
1. **Collect facts from the user**:
   - preset (`yoyo-club`, `kendama-club`, `diabolo-club`, `spintop-club`, `juggling-club`,
     `skill-toy-club`, `youth-program`)
   - which toys they play, if that differs from the preset (`"toys": ["yo-yo", "kendama"]`)
   - club name, city, region, and how they describe their area
   - the meetup rule (e.g. "3rd Sunday, 1–4 PM"), venue, room, address, and time zone
   - whether they bring loaners
   - a shared contact email, social links, and an optional donate link
   - cost (free or not)
   - officers (with their consent)
   - upcoming special events, partner shops (with any discount code), and documents

   Never invent facts. Leave a value empty (`""`), or use "to be announced", rather than guess.
2. **Edit `site.jsonc` only** for content. `examples/dmv-throwers.jsonc` is a complete real-world
   example; it's a good model for how fields are filled in. Keep `//` comments on their own lines.
   Change preset wording by adding the same key to `site.jsonc`, not by editing the preset.
3. **Never hard-code meetup dates.** Express the repeating rule in `meetup.schedule` and use
   `meetup.skip` for exceptions. Check the result: the build prints the next meetup date. Confirm it
   with the user. `python3 build.py --today YYYY-MM-DD` previews any day.
4. **Build and check locally:** `python3 build.py && python3 scripts/check_site.py`. Fix every
   WARNING the build prints (contrast, missing photos or documents, bad dates) and every check failure.
5. **Deploy (GitHub Pages):** the human must:
   - create the repository from the template ("Use this template")
   - set **Settings → Pages → Source: GitHub Actions**

   Then push to `main`. The workflow builds, checks, and deploys, and rebuilds daily so meetup dates
   roll forward. Confirm the run is green and the page URL loads (HTTP 200, the club name in `<title>`).
6. **Report** the live URL and anything the user still needs to do. Typical items: adding a custom
   domain, a logo (`assets/emblem.svg`), photos, and turning on two-factor login.

## Rules
- **Privacy:**
  - No full names of children anywhere. Photos of kids only with the user's confirmation of
    written parent/guardian permission.
  - Resize photos to ~1200px and under 500 KB, and strip EXIF/GPS metadata.
  - Meetup places are public venues. Never publish a home address. Avoid personal phone numbers
    unless the person explicitly agrees.
  - Player maps or lists stay city-level.
- **Security:**
  - No inline `<script>`, `<style>`, `style=""`, or `on*=` handlers. The CSP blocks them and the check fails.
  - No `http://` links.
  - No trackers, analytics, embeds, or third-party scripts unless the user asks. If they do, update
    the CSP in `Site.csp()` in `build.py` and the Privacy page text.
- **Look:** the default style is square corners and flat cards with no shadows, matching DMV
  Throwers. Change it through `theme.corners` in `site.jsonc`, not by editing `style.css`, unless asked.
- **Trademarks:** don't add brand or league logos unless the user supplies them and confirms they may use them.
- **Consistency:** every page shares one header (with the next-meetup bar) and footer, built by
  `Site.layout` and `Site.footer`. The check fails if they differ.
- **Pages:** each page is one `page_<slug>()` method in `build.py`. To add a page, add a method
  and an entry in `self.pages`.
- **Optional pages:** `loaner_page.show` adds a Loaners page and `schools.show` adds a For Schools page (both off by
  default). Ask the user before turning either on: only enable For Schools if the club will answer school requests, and
  `loaner_page.accepts_donations` only if it takes donated gear.
- **Extra content:** `content/<slug>.html` is appended to that page. Plain HTML only.
- **Toys:** set `toys` in `site.jsonc` instead of rewriting preset text toy by toy. When the list differs
  from the preset's, the build rewrites the Learn page, FAQ, loaner, safety, and conduct text from
  `presets/_toys.json` (a preset's `"mix"` block can replace that shared text). Write toy words in
  presets as `{toys}`, `{toy}`, and `{Toy}`, not hard-coded "yo-yo". The check fails if any
  `{placeholder}` is left unfilled.
- **Facts in presets:** keep tips generic and safe. Link only to sources you've checked load, and
  don't describe a real shop, league, or person as a fact you can't verify.
- **Showcase:** `showcase/`, `examples/`, and `scripts/build_showcase.py` only run in the original
  template repository. Ignore them (or delete them) in a user's copy.
- **No dependencies:** keep `build.py` and `scripts/check_site.py` standard-library Python 3.9+.

## Useful commands
```sh
python3 build.py --serve                     # build + preview at http://localhost:8000/
python3 build.py --base-url https://x.org/   # build for a specific address (canonical URLs, sitemap)
python3 build.py --today 2026-12-21          # pretend it's another day (check meetup dates)
python3 scripts/check_site.py                # must print "OK"
```

- **Accessibility check:** after changing markup or styles, run `python3 scripts/build_showcase.py && node scripts/a11y_test.js` (needs Playwright and axe-core; see `.github/workflows/a11y.yml`). It fails on serious or critical axe problems at 360px and 1100px.
