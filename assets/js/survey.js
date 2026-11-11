// Survey page: filter the paper list by subfield (or a pair "a+b"), by flags
// (benchmarks, people I follow) and by free text, 30 at a time. Figure 1 rows,
// subfield cards, subfield pairs and rising terms all drive the same filters.
// Figure 4 (methods x tasks) filters by what a paper proposes (m) and for which task (t).
// State lives in the URL hash (#tag=tables&q=ocr&bench=1&m=rl&t=htr), so views can be shared.
(function () {
  var list = document.getElementById('survey-list');
  if (!list) return;
  var cards = Array.prototype.slice.call(list.querySelectorAll('.paper'));
  var q = document.getElementById('survey-q');
  var more = document.getElementById('survey-more');
  var count = document.getElementById('survey-count');
  var empty = document.getElementById('survey-empty');
  var chips = Array.prototype.slice.call(document.querySelectorAll('.chips .chip[data-filter]'));
  var flags = Array.prototype.slice.call(document.querySelectorAll('.chips .chip[data-flag]'));
  var papersSection = document.getElementById('papers');
  var weeks = Array.prototype.slice.call(list.querySelectorAll('.wk'));
  var STEP = 30;
  var FLAGS = ['bench', 'watch', 'venue', 'code', 'app', 'pick', 'fresh'];   // each matches data-<flag>="true"
  var state = { tag: '', text: '', m: '', t: '', shown: STEP };
  FLAGS.forEach(function (f) { state[f] = false; });
  var texts = cards.map(function (c) { return c.textContent.toLowerCase().replace(/\s+/g, ' '); });
  var tagsOf = cards.map(function (c) { return (c.getAttribute('data-tags') || '').split(' '); });
  var mechOf = cards.map(function (c) { return (c.getAttribute('data-mech') || '').split(' '); });
  var taskOf = cards.map(function (c) { return (c.getAttribute('data-task') || '').split(' '); });
  var mxState = document.getElementById('survey-mx');
  var mxBtns = Array.prototype.slice.call(document.querySelectorAll('.mx [data-m], .mx [data-t]'));
  var mxName = { m: {}, t: {} };
  mxBtns.forEach(function (b) {
    if (!b.classList.contains('mx-h')) return;
    var k = b.hasAttribute('data-m') ? 'm' : 't';
    mxName[k][b.getAttribute('data-' + k)] = b.textContent.trim();
  });

  // "New since your last visit": remember the newest paper date this browser
  // has seen. (Per-viewer convenience only; silently off if storage is blocked.)
  (function markFresh() {
    var newest = cards.reduce(function (m, c) { var d = c.getAttribute('data-date') || ''; return d > m ? d : m; }, '');
    var prev = null;
    try {
      prev = sessionStorage.getItem('survey-prev');
      if (prev === null) {
        prev = localStorage.getItem('survey-last-seen') || '';
        sessionStorage.setItem('survey-prev', prev);   // keep the marks across reloads in this session
      }
      if (newest) localStorage.setItem('survey-last-seen', newest);
    } catch (e) { prev = ''; }
    if (!prev) return;
    var n = 0;
    cards.forEach(function (c) {
      if ((c.getAttribute('data-date') || '') > prev) {
        c.setAttribute('data-fresh', 'true');
        var b = c.querySelector('.badge.fresh');
        if (b) b.hidden = false;
        n++;
      }
    });
    if (!n) return;
    var since = document.getElementById('survey-since');
    since.textContent = n + (n === 1 ? ' paper is' : ' papers are') + ' new since your last visit — ';
    var a = document.createElement('button');
    a.type = 'button'; a.className = 'linkish'; a.setAttribute('data-flag', 'fresh'); a.textContent = 'show them';
    since.appendChild(a);
    since.hidden = false;
    var chip = document.querySelector('.chip[data-flag="fresh"]');
    if (chip) chip.hidden = false;
  })();

  function readHash() {
    var h = new URLSearchParams(location.hash.slice(1));
    state.tag = h.get('tag') || '';
    state.text = (h.get('q') || '').toLowerCase();
    state.m = h.get('m') || '';
    state.t = h.get('t') || '';
    FLAGS.forEach(function (f) { state[f] = h.get(f) === '1'; });
    q.value = h.get('q') || '';
  }
  function writeHash() {
    var h = new URLSearchParams();
    if (state.tag) h.set('tag', state.tag);
    if (state.text) h.set('q', state.text);
    if (state.m) h.set('m', state.m);
    if (state.t) h.set('t', state.t);
    FLAGS.forEach(function (f) { if (state[f]) h.set(f, '1'); });
    var s = h.toString();
    history.replaceState(null, '', s ? '#' + s : location.pathname + location.search);
  }

  function render() {
    var need = state.tag ? state.tag.split('+') : [];
    var words = state.text.split(/\s+/).filter(Boolean);
    var match = 0, visible = 0;
    cards.forEach(function (c, i) {
      var ok = need.every(function (t) { return tagsOf[i].indexOf(t) >= 0; })
        && FLAGS.every(function (f) { return !state[f] || c.getAttribute('data-' + f) === 'true'; })
        && (!state.m || mechOf[i].indexOf(state.m) >= 0)
        && (!state.t || taskOf[i].indexOf(state.t) >= 0)
        && words.every(function (w) { return texts[i].indexOf(w) >= 0; });
      if (ok) match++;
      var show = ok && match <= state.shown;
      c.hidden = !show;
      if (show) visible++;
    });
    // week headings: show one only if a paper of its week is visible
    var seenWk = {};
    cards.forEach(function (c) { if (!c.hidden) seenWk[c.getAttribute('data-wk')] = true; });
    weeks.forEach(function (h) { h.hidden = !seenWk[h.getAttribute('data-wk')]; });
    count.textContent = visible < match ? visible + ' of ' + match : match + (match === 1 ? ' paper' : ' papers');
    more.hidden = match <= state.shown;
    empty.hidden = match > 0;
    chips.forEach(function (b) { b.setAttribute('aria-pressed', String(b.getAttribute('data-filter') === state.tag)); });
    flags.forEach(function (b) { b.setAttribute('aria-pressed', String(!!state[b.getAttribute('data-flag')])); });
    mxBtns.forEach(function (b) {
      var bm = b.getAttribute('data-m') || '', bt = b.getAttribute('data-t') || '';
      b.setAttribute('aria-pressed', String(!!(state.m || state.t) && bm === state.m && bt === state.t));
    });
    if (mxState) {
      mxState.hidden = !(state.m || state.t);
      if (!mxState.hidden) {
        var mn = mxName.m[state.m] || state.m, tn = mxName.t[state.t] || state.t;
        mxState.textContent = state.m && state.t ? 'Papers proposing ' + mn + ' for ' + tn + ' — '
          : state.m ? 'Papers proposing ' + mn + ' — ' : 'Papers on ' + tn + ' that propose a method — ';
        var x = document.createElement('button');
        x.type = 'button'; x.className = 'linkish'; x.setAttribute('data-mxclear', ''); x.textContent = 'clear';
        mxState.appendChild(x);
      }
    }
  }
  function update(jump) {
    state.shown = STEP; writeHash(); render();
    if (jump) papersSection.scrollIntoView({ behavior: 'smooth', block: 'start' });
  }

  document.addEventListener('click', function (e) {
    var t = e.target.closest ? e.target : null;
    if (!t) return;
    var f = t.closest('[data-filter]');
    if (f) {
      state.tag = f.getAttribute('data-filter');
      if (!state.tag) { state.m = ''; state.t = ''; }       // the "all" chip clears Figure 4 too
      update(!f.classList.contains('chip')); return;
    }
    var mx = t.closest('[data-m], [data-t]');
    if (mx) {
      var nm = mx.getAttribute('data-m') || '', nt = mx.getAttribute('data-t') || '';
      var same = nm === state.m && nt === state.t;
      state.m = same ? '' : nm; state.t = same ? '' : nt;   // a second click on the same cell clears it
      update(!same); return;
    }
    if (t.closest('[data-mxclear]')) { state.m = ''; state.t = ''; update(false); return; }
    var fl = t.closest('[data-flag]');
    if (fl) { var k = fl.getAttribute('data-flag'); state[k] = !state[k]; update(!fl.classList.contains('chip')); return; }
    var term = t.closest('[data-term]');
    if (term) { q.value = term.getAttribute('data-term'); state.text = q.value.toLowerCase(); state.tag = ''; update(true); }
  });
  more.addEventListener('click', function () { state.shown += STEP; render(); });
  var timer = 0;
  q.addEventListener('input', function () {
    clearTimeout(timer);
    timer = setTimeout(function () { state.text = q.value.trim().toLowerCase(); update(false); }, 150);
  });
  window.addEventListener('hashchange', function () { readHash(); state.shown = STEP; render(); });

  readHash();
  render();
  if (location.hash.length > 1 && (state.tag || state.text || state.m || state.t || FLAGS.some(function (f) { return state[f]; }))) {
    papersSection.classList.add('in');
    setTimeout(function () { papersSection.scrollIntoView({ block: 'start' }); }, 0);
  }
})();
