/* Orthogonal edge routing for the map. Pure: boxes in, polylines out (no DOM), so tests can run it under node.
   An edge leaves the middle of one side of its source box, runs only through the empty ground between boxes
   (the lines of a sparse grid placed on box centres and on the middle of every gap), and enters the middle of one
   side of its target box. It never crosses a box and never crosses the title of a zone (obstacles).
   Three more rules: a run never lies along a zone border (it may cross one); parallel runs of different edges that
   share a stretch of ground are at least SEP px apart (the routed paths are spread after the search); and a route
   prefers not to turn back on itself (left after right, up after down): each reversal costs REVERSE, so a straight
   gutter wins over a loop unless the loop is more than REVERSE px shorter.
   route(boxes, obstacles, edges, W, H, zones) -> {paths: [pts|null], labels: [rect|null]}
     boxes     [{id, l, r, t, b}]            the node boxes (px, same origin)
     obstacles [{l, r, t, b}]                other things a line must not cross (zone titles)
     zones     [{l, r, t, b}]                zone panels: lines cross their border but never run along it (optional)
     edges     [{a, b, lw?, lh?}]            box ids; lw/lh = size of the label to place, when it has one
     pts       [[x, y], ...]                 first point on the source box side, last on the target box side
     rect      {l, r, t, b}                  empty ground for the label, centred on a horizontal run of the path */
const EdgeRouter = (() => {
  const EPS = .5, BEND = 26, REUSE = 70, REVERSE = 250, CLEAR = 2, SEP = 8, BORDER = 6, MINRUN = 8;
  const DIRS = [[1, 0], [-1, 0], [0, 1], [0, -1]]; // right, left, down, up

  function heap() {
    const a = [];
    return {
      get size() { return a.length; },
      push(k, v) {
        a.push([k, v]);
        let i = a.length - 1;
        while (i > 0) { const p = (i - 1) >> 1; if (a[p][0] <= a[i][0]) break; [a[p], a[i]] = [a[i], a[p]]; i = p; }
      },
      pop() {
        const top = a[0], last = a.pop();
        if (a.length) {
          a[0] = last;
          let i = 0;
          for (;;) {
            let l = 2 * i + 1, r = l + 1, m = i;
            if (l < a.length && a[l][0] < a[m][0]) m = l;
            if (r < a.length && a[r][0] < a[m][0]) m = r;
            if (m === i) break;
            [a[m], a[i]] = [a[i], a[m]]; i = m;
          }
        }
        return top;
      },
    };
  }

  const uniq = list => [...new Set(list.map(v => Math.round(v * 2) / 2))].sort((p, q) => p - q);

  function route(boxes, obstacles, edges, W, H, zones = []) {
    const rects = boxes.concat(obstacles);
    const hits = (x1, y1, x2, y2) => { // does the axis-parallel segment enter a rect (open interior)?
      const lo = Math.min(x1, x2), hi = Math.max(x1, x2), top = Math.min(y1, y2), bot = Math.max(y1, y2);
      return rects.some(r => hi > r.l + EPS && lo < r.r - EPS && bot > r.t + EPS && top < r.b - EPS);
    };
    const overlap = (a1, a2, b1, b2) => Math.min(Math.max(a1, a2), Math.max(b1, b2)) - Math.max(Math.min(a1, a2), Math.min(b1, b2));
    const alongBorder = (x1, y1, x2, y2) => zones.concat(obstacles).some(z => x1 === x2 // a run closer than BORDER to a zone side or a zone title, parallel to it and over it
      ? (Math.abs(x1 - z.l) < BORDER || Math.abs(x1 - z.r) < BORDER) && overlap(y1, y2, z.t, z.b) > EPS
      : y1 === y2 && (Math.abs(y1 - z.t) < BORDER || Math.abs(y1 - z.b) < BORDER) && overlap(x1, x2, z.l, z.r) > EPS);
    const segOk = (x1, y1, x2, y2) => !hits(x1, y1, x2, y2) && !alongBorder(x1, y1, x2, y2);
    // grid lines: box centres, the middle of every gap between a box side and the next box side, the outer margin
    const xl = [-10, W + 10], yl = [-10, H + 10];
    for (const n of rects) {
      xl.push((n.l + n.r) / 2); yl.push((n.t + n.b) / 2);
      let nx = Infinity, px = -Infinity, ny = Infinity, py = -Infinity;
      for (const m of rects) {
        if (m.l > n.r + 2) nx = Math.min(nx, m.l);
        if (m.r < n.l - 2) px = Math.max(px, m.r);
        if (m.t > n.b + 2) ny = Math.min(ny, m.t);
        if (m.b < n.t - 2) py = Math.max(py, m.b);
      }
      if (nx < Infinity) xl.push((n.r + nx) / 2);
      if (px > -Infinity) xl.push((px + n.l) / 2);
      if (ny < Infinity) yl.push((n.b + ny) / 2);
      if (py > -Infinity) yl.push((py + n.t) / 2);
    }
    for (const z of zones) { // the channel between a zone and the next zone is a line too
      let nx = Infinity, px = -Infinity, ny = Infinity, py = -Infinity;
      for (const m of zones) {
        if (m.l > z.r + 2) nx = Math.min(nx, m.l);
        if (m.r < z.l - 2) px = Math.max(px, m.r);
        if (m.t > z.b + 2) ny = Math.min(ny, m.t);
        if (m.b < z.t - 2) py = Math.max(py, m.b);
      }
      if (nx < Infinity) xl.push((z.r + nx) / 2);
      if (px > -Infinity) xl.push((px + z.l) / 2);
      if (ny < Infinity) yl.push((z.b + ny) / 2);
      if (py > -Infinity) yl.push((py + z.t) / 2);
    }
    const X = uniq(xl), Y = uniq(yl), nx = X.length, ny = Y.length;
    const vid = (i, j) => j * nx + i;
    const okV = new Uint8Array(nx * ny);
    for (let j = 0; j < ny; j++) for (let i = 0; i < nx; i++) okV[vid(i, j)] = rects.some(r => X[i] > r.l + EPS && X[i] < r.r - EPS && Y[j] > r.t + EPS && Y[j] < r.b - EPS) ? 0 : 1;
    // step[v*4+d]: free unit step from vertex v in direction d
    const step = new Uint8Array(nx * ny * 4);
    for (let j = 0; j < ny; j++) for (let i = 0; i < nx; i++) {
      const v = vid(i, j);
      if (!okV[v]) continue;
      DIRS.forEach(([dx, dy], d) => {
        const i2 = i + dx, j2 = j + dy;
        if (i2 < 0 || j2 < 0 || i2 >= nx || j2 >= ny || !okV[vid(i2, j2)]) return;
        step[v * 4 + d] = segOk(X[i], Y[j], X[i2], Y[j2]) ? 1 : 0;
      });
    }
    const used = new Map(); // unit steps already taken by an earlier edge: later edges pay to share them
    const key = (v, d) => (d === 1 || d === 3) ? (v + (d === 1 ? -1 : -nx)) * 2 + (d === 1 ? 0 : 1) : v * 2 + (d === 0 ? 0 : 1);

    // the four ports of a box and the grid vertex each one leaves to
    const ports = b => {
      const half = v => Math.round(v * 2) / 2, cx = half((b.l + b.r) / 2), cy = half((b.t + b.b) / 2), out = [];
      const spec = [[b.r, cy, 0], [b.l, cy, 1], [cx, b.b, 2], [cx, b.t, 3]];
      for (const [px, py, d] of spec) {
        let i = -1, j = -1;
        if (d === 0) { i = X.findIndex(x => x > px + EPS); j = Y.indexOf(py); }
        else if (d === 1) { for (let k = nx - 1; k >= 0; k--) if (X[k] < px - EPS) { i = k; break; } j = Y.indexOf(py); }
        else if (d === 2) { j = Y.findIndex(y => y > py + EPS); i = X.indexOf(px); }
        else { for (let k = ny - 1; k >= 0; k--) if (Y[k] < py - EPS) { j = k; break; } i = X.indexOf(px); }
        if (i < 0 || j < 0 || !okV[vid(i, j)] || !segOk(px, py, X[i], Y[j])) continue;
        out.push({ px, py, d, i, j, cost: Math.abs(X[i] - px) + Math.abs(Y[j] - py) });
      }
      return out;
    };

    const byId = new Map(boxes.map(b => [b.id, b]));
    const paths = edges.map(e => {
      const A = byId.get(e.a), B = byId.get(e.b);
      if (!A || !B || A === B) return null;
      const src = ports(A), dst = ports(B);
      if (!src.length || !dst.length) return null;
      const goal = new Map(dst.map(p => [vid(p.i, p.j) * 4 + p.d, p])); // arrive at the out vertex, then step back into the port
      const dist = new Map(), prev = new Map(), pq = heap();
      // search state = vertex, last direction, last horizontal sense (0 none, 1 right, 2 left), last vertical sense (0 none, 1 down, 2 up)
      const sk = (v, d, hz, vz) => ((v * 4 + d) * 3 + hz) * 3 + vz;
      const sense = d => d === 0 ? [1, 0] : d === 1 ? [2, 0] : d === 2 ? [0, 1] : [0, 2];
      const turn = (hz, vz, d) => { // [hz, vz, cost] after a step in direction d: turning back on an axis costs REVERSE
        const [h, v] = sense(d);
        return [h || hz, v || vz, (h && hz && hz !== h) || (v && vz && vz !== v) ? REVERSE : 0];
      };
      for (const p of src) { const [h, v] = sense(p.d), s = sk(vid(p.i, p.j), p.d, h, v), c = p.cost; if (c < (dist.get(s) ?? Infinity)) { dist.set(s, c); prev.set(s, { port: p }); pq.push(c, s); } }
      let end = null;
      while (pq.size) {
        const [c, s] = pq.pop();
        if (c > dist.get(s)) continue;
        const v = (s / 36) | 0, d = ((s / 9) | 0) % 4, hz = ((s / 3) | 0) % 3, vz = s % 3;
        for (const [pk, p] of goal) { // finish: the vertex is an out vertex of the target; the last hop goes against p.d
          if (((pk / 4) | 0) !== v) continue;
          const inward = p.d ^ 1, total = c + (d === inward ? 0 : BEND) + p.cost + turn(hz, vz, inward)[2];
          if (!end || total < end.total) end = { total, s, p };
        }
        if (end && c > end.total) break;
        const i = v % nx, j = (v / nx) | 0;
        for (let nd = 0; nd < 4; nd++) {
          if (nd === (d ^ 1) || !step[v * 4 + nd]) continue;
          const i2 = i + DIRS[nd][0], j2 = j + DIRS[nd][1], v2 = vid(i2, j2);
          const len = Math.abs(X[i2] - X[i]) + Math.abs(Y[j2] - Y[j]);
          const [hz2, vz2, rev] = turn(hz, vz, nd);
          const nc = c + len + (nd === d ? 0 : BEND) + rev + (used.has(key(v, nd)) ? REUSE : 0);
          const s2 = sk(v2, nd, hz2, vz2);
          if (nc < (dist.get(s2) ?? Infinity)) { dist.set(s2, nc); prev.set(s2, { from: s }); pq.push(nc, s2); }
        }
      }
      if (!end) return null;
      const pts = [[end.p.px, end.p.py]];
      let s = end.s;
      for (;;) {
        const v = (s / 36) | 0;
        pts.push([X[v % nx], Y[(v / nx) | 0]]);
        const pr = prev.get(s);
        if (pr.port) { pts.push([pr.port.px, pr.port.py]); break; }
        const d = ((s / 9) | 0) % 4;
        used.set(key((pr.from / 36) | 0, d), 1);
        s = pr.from;
      }
      pts.reverse();
      const out = [];
      for (const p of pts) { // drop repeated and collinear points
        const n = out.length;
        if (n && out[n - 1][0] === p[0] && out[n - 1][1] === p[1]) continue;
        if (n > 1 && ((out[n - 2][0] === out[n - 1][0] && out[n - 1][0] === p[0]) || (out[n - 2][1] === out[n - 1][1] && out[n - 1][1] === p[1]))) out.pop();
        out.push(p);
      }
      return out;
    });

    // parallel runs of different edges on the same ground: at least SEP apart. Only inner runs move (the first and last run
    // touch a port); two runs from one port share their trunk and are left alone.
    const segs = [];
    paths.forEach((pts, p) => { if (pts) for (let k = 0; k + 1 < pts.length; k++) if (pts[k][0] !== pts[k + 1][0] || pts[k][1] !== pts[k + 1][1]) segs.push({ p, k }); });
    const pts_ = s => paths[s.p], A_ = s => pts_(s)[s.k], B_ = s => pts_(s)[s.k + 1];
    const horiz = s => A_(s)[1] === B_(s)[1];
    const coord = s => horiz(s) ? A_(s)[1] : A_(s)[0];
    const ends = s => [pts_(s)[0], pts_(s)[pts_(s).length - 1]];
    const sameEnd = (s, t) => ends(s).some(u => ends(t).some(w => u[0] === w[0] && u[1] === w[1]) && [A_(s), B_(s)].includes(u) && [A_(t), B_(t)].some(w => w[0] === u[0] && w[1] === u[1])); // the same port: one trunk
    const clashes = (s, c) => segs.filter(t => t.p !== s.p && horiz(t) === horiz(s) && Math.abs(coord(t) - c) < SEP - EPS && !sameEnd(s, t)
      && (horiz(s) ? overlap(A_(s)[0], B_(s)[0], A_(t)[0], B_(t)[0]) : overlap(A_(s)[1], B_(s)[1], A_(t)[1], B_(t)[1])) > 1);
    const place = (s, c) => { // move the run to coordinate c if everything it touches stays free; true when moved
      const pts = pts_(s), h = horiz(s), a = pts[s.k], b = pts[s.k + 1], p0 = pts[s.k - 1], p1 = pts[s.k + 2];
      const na = h ? [a[0], c] : [c, a[1]], nb = h ? [b[0], c] : [c, b[1]];
      const keep = (from, to, old) => { // a neighbour run: same direction as before, not squeezed, not through a box or along a border
        const len = Math.abs(to[0] - from[0]) + Math.abs(to[1] - from[1]);
        const dir = h ? Math.sign(to[1] - from[1]) : Math.sign(to[0] - from[0]), was = h ? Math.sign(old[1] - from[1]) : Math.sign(old[0] - from[0]);
        return len >= MINRUN && dir === was && segOk(from[0], from[1], to[0], to[1]);
      };
      if (!segOk(na[0], na[1], nb[0], nb[1]) || !keep(p0, na, a) || !keep(p1, nb, b)) return false;
      a[h ? 1 : 0] = c; b[h ? 1 : 0] = c;
      return true;
    };
    const movable = s => s.k > 0 && s.k + 2 < pts_(s).length;
    const mov = segs.filter(movable), root = mov.map((_, i) => i);
    const find = i => root[i] === i ? i : (root[i] = find(root[i]));
    mov.forEach((s, i) => mov.forEach((t, j) => { if (j > i && clashes(s, coord(s)).includes(t)) root[find(j)] = find(i); }));
    const groups = new Map();
    mov.forEach((s, i) => groups.set(find(i), (groups.get(find(i)) || []).concat(s)));
    for (const g of groups.values()) { // a bundle of runs in one gutter: spread them evenly around where they were
      if (g.length < 2 || g.some(s => clashes(s, coord(s)).some(t => !movable(t)))) continue;
      g.sort((u, v) => coord(u) - coord(v) || u.p - v.p);
      const mean = g.reduce((a, s) => a + coord(s), 0) / g.length;
      g.forEach((s, i) => place(s, Math.round((mean + (i - (g.length - 1) / 2) * SEP) * 2) / 2));
    }
    for (let pass = 0; pass < 6; pass++) {
      let moved = false;
      for (const s of segs) {
        if (!movable(s)) continue; // touches a port
        const c0 = coord(s), hit = clashes(s, c0);
        if (!hit.length) continue;
        const cand = [];
        for (let d = 1; d <= 6 * SEP; d++) cand.push(c0 + d / 2, c0 - d / 2); // nearest free track first
        for (const c of cand) {
          if (clashes(s, c).length) continue;
          if (place(s, c)) { moved = true; break; }
        }
      }
      if (!moved) break;
    }
    for (let k = 0; k < paths.length; k++) { // drop repeated and collinear points again
      const pts = paths[k];
      if (!pts) continue;
      const out = [];
      for (const p of pts) {
        const n = out.length;
        if (n && out[n - 1][0] === p[0] && out[n - 1][1] === p[1]) continue;
        if (n > 1 && ((out[n - 2][0] === out[n - 1][0] && out[n - 1][0] === p[0]) || (out[n - 2][1] === out[n - 1][1] && out[n - 1][1] === p[1]))) out.pop();
        out.push(p);
      }
      paths[k] = out;
    }

    // labels. Spots, best first: centred on a horizontal run, then beside a run (above or below a horizontal one, left or right of a vertical one). A spot must be free ground:
    // no box, zone title or earlier label under it; ground that other lines or a zone border cross costs extra.
    const placed = [];
    const hitsR = (r, m) => r.r > m.l && r.l < m.r && r.b > m.t && r.t < m.b;
    const labels = edges.map((e, k) => {
      const pts = paths[k];
      if (!pts || !e.lw) return null;
      const w = e.lw + 6, h = (e.lh || 14) + 2 * CLEAR;
      let best = null;
      const try_ = (cx, cy, base) => {
        const r = { l: cx - w / 2, r: cx + w / 2, t: cy - h / 2, b: cy + h / 2 };
        if (r.l < 0 || r.r > W || r.t < 0 || r.b > H || rects.some(m => hitsR(r, m)) || placed.some(m => hitsR(r, m))) return;
        let cost = base;
        paths.forEach((q, j) => { if (q) for (let i = 0; i + 1 < q.length; i++) {
          const sg = { l: Math.min(q[i][0], q[i + 1][0]) - 1, r: Math.max(q[i][0], q[i + 1][0]) + 1, t: Math.min(q[i][1], q[i + 1][1]) - 1, b: Math.max(q[i][1], q[i + 1][1]) + 1 };
          if (j !== k && hitsR(r, sg)) cost += 90;
        } });
        if (zones.some(z => [{ l: z.l - 1, r: z.l + 1, t: z.t, b: z.b }, { l: z.r - 1, r: z.r + 1, t: z.t, b: z.b }, { l: z.l, r: z.r, t: z.t - 1, b: z.t + 1 }, { l: z.l, r: z.r, t: z.b - 1, b: z.b + 1 }].some(sd => hitsR(r, sd)))) cost += 60;
        if (!best || cost < best.cost) best = { cost, r };
      };
      for (let i = 0; i + 1 < pts.length; i++) {
        const [x1, y1] = pts[i], [x2, y2] = pts[i + 1];
        if (y1 === y2) {
          const lo = Math.min(x1, x2), hi = Math.max(x1, x2), mid = (lo + hi) / 2;
          for (let cx = lo + w / 2 + 4; cx <= hi - w / 2 - 4 + .01; cx += 4) try_(cx, y1, (Math.abs(cx - mid) - (hi - lo) * .15) / 8);
          for (let cx = lo + w / 2; cx <= hi - w / 2 + .01; cx += 6) for (const sgn of [-1, 1]) try_(cx, y1 + sgn * (h / 2 + 2), 40 + Math.abs(cx - mid) / 8);
        } else {
          const lo = Math.min(y1, y2), hi = Math.max(y1, y2), mid = (lo + hi) / 2;
          for (let cy = lo + h / 2; cy <= hi - h / 2 + .01; cy += 6) for (const sgn of [-1, 1]) try_(x1 + sgn * (w / 2 + 4), cy, 60 + Math.abs(cy - mid) / 8);
        }
      }
      if (best) placed.push(best.r);
      return best ? best.r : null;
    });
    return { paths, labels };
  }

  /* an SVG path for a polyline: straight runs, corners rounded by r */
  function toPath(pts, r = 7) {
    if (!pts || pts.length < 2) return '';
    let d = 'M' + pts[0][0] + ' ' + pts[0][1];
    for (let i = 1; i < pts.length - 1; i++) {
      const [px, py] = pts[i - 1], [cx, cy] = pts[i], [nx, ny] = pts[i + 1];
      const a = Math.min(r, Math.hypot(cx - px, cy - py) / 2), b = Math.min(r, Math.hypot(nx - cx, ny - cy) / 2);
      const ux = Math.sign(cx - px), uy = Math.sign(cy - py), vx = Math.sign(nx - cx), vy = Math.sign(ny - cy);
      d += 'L' + (cx - ux * a) + ' ' + (cy - uy * a) + 'Q' + cx + ' ' + cy + ' ' + (cx + vx * b) + ' ' + (cy + vy * b);
    }
    const e = pts[pts.length - 1];
    return d + 'L' + e[0] + ' ' + e[1];
  }
  return { route, toPath };
})();
if (typeof module !== 'undefined') module.exports = EdgeRouter;
