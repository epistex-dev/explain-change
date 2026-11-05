(function () {
  var FAILED = __FAILED__;
  var BASE_FONT = 14, MIN_SCALE = 12 / BASE_FONT;
  function setup(fig, svg) {
    var vb = svg.viewBox && svg.viewBox.baseVal;
    var w = vb && vb.width ? vb.width : svg.getBoundingClientRect().width;
    var h = vb && vb.height ? vb.height : svg.getBoundingClientRect().height;
    var fit = Math.max(MIN_SCALE, Math.min(1, (fig.querySelector('.dscroll').clientWidth - 26) / w));
    var scale = fit;
    function apply() { svg.style.width = (w * scale) + 'px'; svg.style.height = (h * scale) + 'px'; svg.removeAttribute('width'); svg.removeAttribute('height'); }
    apply();
    fig.querySelectorAll('[data-zoom]').forEach(function (b) {
      b.addEventListener('click', function () {
        var k = b.getAttribute('data-zoom');
        scale = k === 'in' ? Math.min(scale * 1.25, 3) : k === 'out' ? Math.max(scale / 1.25, MIN_SCALE) : fit;
        apply();
      });
    });
  }
  if (!window.mermaid) { document.querySelectorAll('.diagram .dfail').forEach(function (p) { p.hidden = false; }); return; }
  window.mermaid.initialize({
    startOnLoad: false, securityLevel: 'strict', theme: 'base',
    themeVariables: { fontFamily: 'system-ui, -apple-system, Segoe UI, Roboto, sans-serif', fontSize: '14px',
      primaryColor: '#ffffff', primaryTextColor: '#14181f', primaryBorderColor: '#8a94a6', lineColor: '#566070',
      secondaryColor: '#e8f0fc', tertiaryColor: '#f5f6f8', actorBkg: '#ffffff', actorBorder: '#566070', actorTextColor: '#14181f',
      signalColor: '#14181f', signalTextColor: '#14181f', noteBkgColor: '#eef1f6', noteBorderColor: '#8a94a6', noteTextColor: '#14181f' },
    sequence: { useMaxWidth: false, wrap: true, width: 170, height: 56, actorMargin: 20, messageFontSize: 14, actorFontSize: 14, noteFontSize: 14, mirrorActors: false, messageMargin: 40, boxMargin: 8, noteMargin: 8 },
    flowchart: { useMaxWidth: false, htmlLabels: true, wrappingWidth: 170, nodeSpacing: 32, rankSpacing: 40, padding: 8 }
  });
  var n = 0;
  var jobs = Array.prototype.map.call(document.querySelectorAll('.diagram'), function (fig) {
    var src = fig.querySelector('.mermaid-src').textContent;
    var box = fig.querySelector('.dscroll');
    return window.mermaid.render('mm' + (n++), src).then(function (r) {
      box.insertAdjacentHTML('beforeend', r.svg);
      setup(fig, box.querySelector('svg'));
    }).catch(function () {
      fig.querySelector('.dfail').hidden = false;
      fig.querySelector('.dsrc').open = true;
    });
  });
  Promise.all(jobs).then(function () { document.documentElement.setAttribute('data-diagrams', 'ready'); });
})();
