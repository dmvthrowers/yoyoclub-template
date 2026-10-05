# Extra page content (optional)

Put an HTML file here named after a page, and the build adds it as a new section at the bottom of
that page:

| File | Added to |
| --- | --- |
| `index.html` | Home |
| `about.html` | About |
| `meetups.html` | Meetups |
| `learn.html` | Learn |
| `team.html` | Team |
| `gallery.html` | Gallery |
| `resources.html` | Resources |
| `faq.html` | FAQ |
| `contact.html` | Contact |
| `conduct.html` | Code of Conduct |
| `privacy.html` | Privacy & Safety |

Example `content/about.html`:

```html
<h2>Our History</h2>
<p>We started in 2025 with four players on a park bench.
  Today 30 people come to a typical meetup.</p>
<ul>
  <li>2025: First meetup</li>
  <li>2026: First club trick battle</li>
</ul>
```

Use plain HTML. No `<script>`, `<style>`, or `style="…"` attributes; the site's security policy
blocks them, and the automatic check will fail. Add CSS to `assets/style.css` instead. This
README itself is ignored by the build.
