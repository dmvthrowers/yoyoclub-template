/* Opens and closes the phone menu. The rest of the site works without JavaScript. */
(function () {
  var toggle = document.querySelector(".nav-toggle");
  var nav = document.getElementById("site-nav");
  if (!toggle || !nav) return;
  function setOpen(open) {
    nav.classList.toggle("open", open);
    toggle.setAttribute("aria-expanded", open ? "true" : "false");
  }
  toggle.addEventListener("click", function () {
    setOpen(!nav.classList.contains("open"));
  });
  // Escape closes the menu and puts focus back on the menu button.
  document.addEventListener("keydown", function (e) {
    if (e.key === "Escape" && nav.classList.contains("open")) {
      setOpen(false);
      toggle.focus();
    }
  });
})();

/* Old guide links (guide.html#section) jump to the part page that now holds the section. */
(function () {
  var raw = document.body.getAttribute("data-guide-map");
  if (!raw || !location.hash) return;
  try {
    var target = JSON.parse(raw)[decodeURIComponent(location.hash.slice(1))];
    if (target) location.replace(target);
  } catch (e) { /* keep the current page */ }
})();
