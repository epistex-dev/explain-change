/* Lane fit: where the markers of one lane go. Pure (numbers in, numbers out), so tests run it under node without a browser.
   orders: the `order` of each event in list order; W: track width; mk: marker size; gap: space between markers; lo, hi: first and last order on the page.
   Positions are whole pixels (a rounded position cannot eat into the gap). Returns {cap, items}: items are {x, i: [event indexes]}, x the left edge. Neighbouring items are at least mk + gap apart and every item lies inside [0, W - mk].
   More events than cap = floor((W + gap) / (mk + gap)) merge into count items: the closest neighbours first, so a cluster is the part of the lane that was crowded. */
const SessionFit = (() => {
  function fit(orders, W, mk, gap, lo, hi) {
    const pitch = Math.ceil(mk + gap), cap = Math.max(1, Math.floor((W + gap) / pitch)), span = Math.max(0, Math.floor(W - mk));
    let items = orders.map((o, i) => ({ x: hi > lo ? Math.round((o - lo) / (hi - lo) * span) : 0, i: [i] }));
    while (items.length > cap) {
      let b = 0, best = Infinity;
      for (let j = 0; j < items.length - 1; j++) {
        const k = (items[j + 1].x - items[j].x) * 1000 + items[j].i.length + items[j + 1].i.length;
        if (k < best) { best = k; b = j; }
      }
      const a = items[b], c = items[b + 1], n = a.i.length + c.i.length;
      items.splice(b, 2, { x: Math.round((a.x * a.i.length + c.x * c.i.length) / n), i: a.i.concat(c.i) });
    }
    for (let j = 1; j < items.length; j++) items[j].x = Math.max(items[j].x, items[j - 1].x + pitch);
    const last = items.length - 1;
    if (last >= 0 && items[last].x > span) {
      items[last].x = span;
      for (let j = last - 1; j >= 0; j--) items[j].x = Math.min(items[j].x, items[j + 1].x - pitch);
    }
    return { cap, items };
  }
  return { fit };
})();
if (typeof module !== 'undefined') module.exports = SessionFit;
