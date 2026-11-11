// Catalog page: "my feed". The subfields a viewer follows are kept in this browser
// (localStorage) and can be moved to another device with a link (#follow=field/sub,...).
// Nothing is sent anywhere: the papers are already in the page.
(function () {
  var dataEl = document.getElementById('catalog-data');
  if (!dataEl) return;
  var KEY = 'ls-follow';
  var fields = JSON.parse(dataEl.textContent || '{}');
  var boxes = Array.prototype.slice.call(document.querySelectorAll('input[data-follow]'));
  var known = {};
  boxes.forEach(function (b) { known[b.getAttribute('data-follow')] = b; });

  // Old links to the single-map site (…/#tag=ocr&q=…) go on to the map they meant.
  var legacy = JSON.parse((document.getElementById('catalog-legacy') || {}).textContent || '""');
  var h = new URLSearchParams(location.hash.slice(1));
  if (legacy && fields[legacy] && ['tag', 'q', 'm', 't', 'bench', 'venue', 'code', 'watch', 'pick', 'app'].some(function (k) { return h.has(k); })) {
    location.replace(fields[legacy].path + location.hash);
    return;
  }

  function load() {
    try { return JSON.parse(localStorage.getItem(KEY) || '[]'); } catch (e) { return []; }
  }
  function save(list) {
    try { localStorage.setItem(KEY, JSON.stringify(list)); } catch (e) { /* storage blocked: the page still works */ }
  }
  function selected() {
    return boxes.filter(function (b) { return b.checked; }).map(function (b) { return b.getAttribute('data-follow'); });
  }

  // A shared link wins over what this browser had, once.
  var follow = h.has('follow') ? h.get('follow').split(',').filter(function (k) { return known[k]; }) : load();
  if (h.has('follow')) { save(follow); history.replaceState(null, '', location.pathname + location.search); }
  follow.forEach(function (k) { if (known[k]) known[k].checked = true; });

  function el(tag, cls, text) {
    var e = document.createElement(tag);
    if (cls) e.className = cls;
    if (text) e.textContent = text;
    return e;
  }

  function render() {
    var keys = selected();
    var feed = document.getElementById('feed');
    document.getElementById('feed-empty').hidden = keys.length > 0;
    feed.hidden = keys.length === 0;
    if (!keys.length) return;
    var want = {};
    keys.forEach(function (k) { var p = k.split('/'); (want[p[0]] = want[p[0]] || {})[p[1]] = true; });
    var items = [];
    Object.keys(want).forEach(function (fid) {
      var f = fields[fid];
      if (!f) return;
      (f.papers || []).forEach(function (p) {
        var hit = p.tags.filter(function (t) { return want[fid][t]; });
        if (hit.length) items.push({ p: p, f: f, fid: fid, hit: hit });
      });
    });
    items.sort(function (a, b) { return a.p.date < b.p.date ? 1 : a.p.date > b.p.date ? -1 : 0; });
    var seen = {};
    items = items.filter(function (x) { if (seen[x.p.id]) return false; seen[x.p.id] = true; return true; });

    var list = document.getElementById('feed-list');
    list.textContent = '';
    items.forEach(function (x) {
      var a = el('article', 'card paper');
      var k = el('div', 'card-kicker');
      k.appendChild(el('time', '', x.p.date));
      k.appendChild(el('span', '', x.f.title.split(':')[0]));
      if (x.p.venue) k.appendChild(el('span', 've', x.p.venue));
      a.appendChild(k);
      var t = el('h3', 'card-title');
      var link = el('a', 'stretch', x.p.title);
      link.href = 'https://arxiv.org/abs/' + x.p.id;
      link.rel = 'noopener';
      t.appendChild(link);
      a.appendChild(t);
      a.appendChild(el('p', 'card-au', x.p.authors.join(', ')));
      var foot = el('div', 'card-foot');
      foot.textContent = x.hit.map(function (s) { var b = known[x.fid + '/' + s]; return b ? b.getAttribute('data-name') : s; }).join(' · ');
      a.appendChild(foot);
      list.appendChild(a);
    });
    document.getElementById('feed-summary').textContent = items.length
      ? items.length + (items.length === 1 ? ' paper' : ' papers') + ' in the ' + keys.length + (keys.length === 1 ? ' subfield' : ' subfields') + ' you follow.'
      : 'No new papers in the subfields you follow yet.';

    var rss = document.getElementById('feed-rss');
    rss.textContent = '';
    keys.forEach(function (key, i) {
      if (i) rss.appendChild(document.createTextNode(' · '));
      var r = el('a', '', known[key].getAttribute('data-name'));
      r.href = known[key].getAttribute('data-rss');
      rss.appendChild(r);
    });
  }

  boxes.forEach(function (b) { b.addEventListener('change', function () { save(selected()); render(); }); });
  var share = document.getElementById('feed-share');
  if (share) share.addEventListener('click', function () {
    var url = location.origin + location.pathname + '#follow=' + selected().join(',');
    var done = function () { share.textContent = 'Link copied'; setTimeout(function () { share.textContent = 'Copy a link to this selection'; }, 2000); };
    if (navigator.clipboard) navigator.clipboard.writeText(url).then(done, function () { prompt('Copy this link', url); });
    else prompt('Copy this link', url);
  });
  render();
})();
