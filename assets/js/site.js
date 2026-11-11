// Site-wide behaviour: dark-mode toggle + copy buttons on code cards.
(function () {
  var KEY = 'prefers-color-scheme';
  var root = document.documentElement;
  var media = window.matchMedia ? window.matchMedia('(prefers-color-scheme: dark)') : null;

  function saved() { try { return localStorage.getItem(KEY); } catch (e) { return null; } }
  function isDark() {
    var t = root.getAttribute('data-theme');
    if (t) return t === 'dark';
    return !!(media && media.matches);
  }

  function init() {
    var btn = document.getElementById('theme-toggle');
    if (btn) {
      btn.setAttribute('aria-pressed', String(isDark()));
      btn.addEventListener('click', function () {
        var next = isDark() ? 'light' : 'dark';
        root.setAttribute('data-theme', next);
        try { localStorage.setItem(KEY, next); } catch (e) {}
        btn.setAttribute('aria-pressed', String(next === 'dark'));
      });
    }
    // No explicit choice saved → keep following the OS when it changes.
    if (media && media.addEventListener) {
      media.addEventListener('change', function () {
        var s = saved();
        if (s !== 'dark' && s !== 'light') {
          root.removeAttribute('data-theme');
          if (btn) btn.setAttribute('aria-pressed', String(isDark()));
        }
      });
    }
  }

  var reduceMotion = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;

  // Scroll reveal. Elements marked .reveal in the templates (home sections,
  // card grids, syllabus phases) get .in as they come into view; CSS fades
  // them in, draws rules, and staggers cards / lesson rows through --i.
  // Inside article bodies, headings, figures, code and tables are tagged
  // here — but only those still below the fold, so nothing visible flickers.
  function reveals() {
    var vh = window.innerHeight;
    Array.prototype.forEach.call(document.querySelectorAll(
      '.content > h2, .content > h3, .content > figure, .content > .code-card, .content > table, .content > blockquote, .content > p > img:only-child, .pager'
    ), function (el) {
      if (el.getBoundingClientRect().top > vh) el.classList.add('reveal', 'fx');
    });
    var els = Array.prototype.slice.call(document.querySelectorAll('.reveal'));
    els.forEach(function (el) {
      Array.prototype.forEach.call(el.querySelectorAll('.card, .lesson-row'), function (c, i) { c.style.setProperty('--i', Math.min(i, 12)); });
    });
    if (reduceMotion || !('IntersectionObserver' in window)) {
      els.forEach(function (el) { el.classList.add('in'); });
      return;
    }
    var io = new IntersectionObserver(function (entries) {
      entries.forEach(function (en) {
        if (en.isIntersecting) { en.target.classList.add('in'); io.unobserve(en.target); }
      });
    }, { rootMargin: '0px 0px -10% 0px', threshold: 0 });  // 0: tall blocks must trigger too
    els.forEach(function (el) { io.observe(el); });
  }

  // Reading progress: a thin blue bar along the top edge (pages that carry
  // [data-progress]; lesson pages run their own bar in lesson-ui.js).
  function progress() {
    var bar = document.querySelector('[data-progress] > span');
    if (!bar) return;
    var ticking = false;
    function paint() {
      ticking = false;
      var max = document.documentElement.scrollHeight - window.innerHeight;
      bar.style.width = (max > 0 ? Math.min(100, (window.scrollY / max) * 100) : 0).toFixed(2) + '%';
    }
    function onScroll() { if (!ticking) { ticking = true; requestAnimationFrame(paint); } }
    window.addEventListener('scroll', onScroll, { passive: true });
    window.addEventListener('resize', onScroll, { passive: true });
    paint();
  }

  // Spotlight on cards and syllabus rows: feed the cursor position (relative
  // to the hovered element) to CSS as --mx / --my, at most once per frame.
  var raf = 0, card = null, px = 0, py = 0;
  document.addEventListener('pointermove', function (e) {
    if (e.pointerType === 'touch') return;
    var c = e.target.closest && e.target.closest('.card, .spot');
    if (!c) return;
    card = c; px = e.clientX; py = e.clientY;
    if (!raf) raf = requestAnimationFrame(function () {
      raf = 0;
      var r = card.getBoundingClientRect();
      card.style.setProperty('--mx', (px - r.left) + 'px');
      card.style.setProperty('--my', (py - r.top) + 'px');
    });
  }, { passive: true });

  // Copy button for the code-card render hook.
  document.addEventListener('click', function (e) {
    var btn = e.target.closest && e.target.closest('.code-copy');
    if (!btn) return;
    var card = btn.closest('.code-card');
    var pre = card && card.querySelector('pre');
    if (!pre || !navigator.clipboard) return;
    navigator.clipboard.writeText(pre.innerText).then(function () {
      var old = btn.textContent;
      btn.textContent = 'Copied';
      btn.classList.add('copied');
      setTimeout(function () { btn.textContent = old; btn.classList.remove('copied'); }, 1500);
    });
  });

  function boot() { init(); reveals(); progress(); }
  if (document.readyState !== 'loading') boot();
  else document.addEventListener('DOMContentLoaded', boot);
})();
