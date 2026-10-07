# Updating your copy

A club site made with **Use this template** is its own repository. It doesn't update by itself, and it has no shared history with the template, so an update is a short, careful copy of the files that are the template's, leaving the files that are yours alone.

## What is yours and what is the template's

| Yours (keep these) | The template's (these are what an update replaces) |
| --- | --- |
| site.jsonc, content/, assets/emblem.svg, assets/images/, assets/documents/, .github/ISSUE_TEMPLATE (if you added any) | build.py, scripts/check_site.py, assets/style.css, assets/site.js, presets/, .github/workflows/deploy.yml |

If you changed one of the template's files on purpose, you'll see your change in the comparison below. Keep it, or move it into your settings if there's a setting for it.

## Before you start

1. Read [CHANGELOG.md](../CHANGELOG.md) in the template, from the release you started on to the newest. It says what's new and whether anything needs a change in your settings file.
2. Work on a branch, not on `main`, so the live site stays as it is until you're happy.

## The update

From a clone of your repository:

```sh
git checkout -b update-template
git remote add template https://github.com/dmvthrowers/yoyoclub-template.git
git fetch template --tags
git diff HEAD template/main --stat -- build.py scripts/check_site.py assets/style.css assets/site.js presets/ .github/workflows/deploy.yml
```

The `--stat` list shows which of the template's files differ from yours. For each one, look at the change (`git diff HEAD template/main -- <file>`), then take the template's version:

```sh
git checkout template/main -- <file>
```

Don't take `site.jsonc`, your `content/` or images: those are yours. If the changelog mentions a new setting you want, copy the commented block for it from the template's `site.jsonc` into yours.

## Check it

```sh
python3 build.py
python3 scripts/check_site.py
```

Both must finish cleanly, with no warnings you don't understand. Then open the built site and look at a few pages at phone width. When it looks right, commit, open a pull request, and merge it. Your site rebuilds by itself.

## Pinning to a release

Releases are tagged `v1.0.0`, `v1.1.0` and so on. To update to a specific one instead of the newest, use its tag where the commands say `template/main`: for example `git diff HEAD v1.1.0 --stat`. Starting from a tag also keeps your update reproducible.

## If something breaks

Nothing is final until you merge. Discard the branch (`git checkout main && git branch -D update-template`) and start again, or take one file at a time. If a change in the template's `build.py` stops your settings from building, the error message names the setting; compare it with the commented example in the template's `site.jsonc`.
