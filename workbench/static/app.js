/* 工作台交互：页签、图片兜底、lightbox。无外部依赖。 */
(function () {
  'use strict';

  var tabs = Array.prototype.slice.call(document.querySelectorAll('.wb-tab'));
  var panels = Array.prototype.slice.call(document.querySelectorAll('.wb-panel'));

  function activate(id, push) {
    tabs.forEach(function (b) { b.classList.toggle('is-active', b.dataset.tab === id); });
    panels.forEach(function (p) { p.classList.toggle('is-active', p.dataset.panel === id); });
    if (push) { history.replaceState(null, '', '#' + id); }
  }
  tabs.forEach(function (b) {
    b.addEventListener('click', function () { activate(b.dataset.tab, true); });
  });
  var hash = location.hash.replace('#', '');
  if (hash && panels.some(function (p) { return p.dataset.panel === hash; })) {
    activate(hash, false);
  }

  /* 原图路径失效时回退到内嵌缩略图 / 海报 */
  window.wbFallback = function (img) {
    var fb = img.getAttribute('data-fallback');
    if (fb && img.getAttribute('src') !== fb) {
      img.removeAttribute('onerror');
      img.setAttribute('src', fb);
    }
  };

  var lb = document.getElementById('wb-lb');
  if (!lb) { return; }
  var lbImg = lb.querySelector('img');
  var counter = lb.querySelector('.wb-lb-count');
  var group = [];
  var idx = 0;

  function collect(el) {
    var key = el.dataset.lb;
    return Array.prototype.slice.call(document.querySelectorAll('img.wb-media'))
      .filter(function (i) { return i.dataset.lb === key; });
  }
  function show() {
    if (!group.length) { return; }
    lbImg.setAttribute('src', group[idx].getAttribute('src'));
    counter.textContent = (idx + 1) + ' / ' + group.length;
  }
  function open(el) {
    group = collect(el);
    idx = Math.max(0, group.indexOf(el));
    show();
    lb.hidden = false;
    document.body.classList.add('wb-lb-open');
  }
  function close() {
    lb.hidden = true;
    lbImg.removeAttribute('src');
    document.body.classList.remove('wb-lb-open');
  }
  function step(delta) {
    if (!group.length) { return; }
    idx = (idx + delta + group.length) % group.length;
    show();
  }

  document.addEventListener('click', function (e) {
    var img = e.target && e.target.closest && e.target.closest('img.wb-media[data-lb]');
    if (img) { open(img); return; }
    if (e.target === lb || (e.target.closest && e.target.closest('.wb-lb-close'))) { close(); }
  });
  document.addEventListener('keydown', function (e) {
    if (lb.hidden) { return; }
    if (e.key === 'Escape') { close(); }
    else if (e.key === 'ArrowRight') { step(1); }
    else if (e.key === 'ArrowLeft') { step(-1); }
  });
})();
