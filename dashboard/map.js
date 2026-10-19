(function () {
  "use strict";
  const TAU = Math.PI * 2;
  const FX = -1;

  class TrackMap {
    constructor(canvas, opts) {
      this.cv = canvas;
      this.ctx = canvas.getContext("2d");
      this.opts = Object.assign({ names: true, trails: false, incidents: true }, opts || {});
      this.meta = () => ({});
      this.onSelect = () => {};
      this.onHover = () => {};
      this.trace = null; this.marks = [];
      this.cars = new Map();
      this.inc = [];
      this.crumbs = new Map();
      this.bounds = null;
      this.zoom = 1; this.pan = { x: 0, y: 0 };
      this.sel = null; this.hover = null;
      this.dpr = Math.min(window.devicePixelRatio || 1, 2);
      this.bg = document.createElement("canvas");
      this.bgDirty = true;
      this.crumbN = 0;
      this._bind();
      this._resize();
      this._last = performance.now();
      requestAnimationFrame((t) => this._frame(t));
    }

    setTrace(doc) {
      this.trace = doc && doc.pts && doc.pts.length > 30 ? doc.pts : null;
      this.marks = (doc && doc.marks) || [];
      this._fitBounds();
      this.bgDirty = true;
    }
    hasTrace() { return !!this.trace; }
    setCars(list) {
      const now = performance.now();
      const seen = new Set();
      for (const c of list) {
        seen.add(c.i);
        let s = this.cars.get(c.i);
        if (!s) { s = { x: c.x, z: c.z, trail: [], lt: 0 }; this.cars.set(c.i, s); }
        s.sx = c.x; s.sz = c.z; s.v = c.v; s.h = c.h; s.ok = c.ok; s.lap = c.l; s.pl = c.pl; s.sl = c.sl;
        s.cuts = c.c; s.n = c.n; s.pit = c.p; s.t0 = now;
        if (!this.trace) this._crumb(c.x, c.z);
      }
      for (const k of this.cars.keys()) if (!seen.has(k)) this.cars.delete(k);
      if (!this.trace && this.crumbs.size) this._fitBounds();
    }
    addIncident(i) {
      if (i.x == null || i.z == null) return;
      this.inc.push({ x: i.x, z: i.z, k: i.k, t: performance.now(), v: i.v });
      if (this.inc.length > 120) this.inc.shift();
    }
    select(cid) { this.sel = cid; }

    _crumb(x, z) {
      const key = Math.round(x / 5) + "," + Math.round(z / 5);
      if (!this.crumbs.has(key)) { this.crumbs.set(key, [x, z]); this.crumbN++; if (this.crumbN % 40 === 0) this.bgDirty = true; }
    }
    _fitBounds() {
      let pts = this.trace;
      if (!pts) pts = [...this.crumbs.values()];
      if (!pts.length) { this.bounds = null; return; }
      let a = 1e9, b = -1e9, c = 1e9, d = -1e9;
      for (const p of pts) { if (p[0] < a) a = p[0]; if (p[0] > b) b = p[0]; if (p[1] < c) c = p[1]; if (p[1] > d) d = p[1]; }
      const padx = Math.max(60, (b - a) * 0.08), padz = Math.max(60, (d - c) * 0.08);
      this.bounds = { x0: a - padx, x1: b + padx, z0: c - padz, z1: d + padz };
    }

    _base() {
      const w = this.W, h = this.H, B = this.bounds || { x0: -500, x1: 500, z0: -500, z1: 500 };
      const s = Math.min(w / (B.x1 - B.x0), h / (B.z1 - B.z0));
      return { s, cx: (B.x0 + B.x1) / 2, cz: (B.z0 + B.z1) / 2 };
    }
    _tx(x, z) {
      const b = this._base(), k = b.s * this.zoom;
      return [this.W / 2 + FX * (x - b.cx) * k + this.pan.x, this.H / 2 - (z - b.cz) * k + this.pan.y];
    }
    _inv(px, py) {
      const b = this._base(), k = b.s * this.zoom;
      return [FX * (px - this.W / 2 - this.pan.x) / k + b.cx, -(py - this.H / 2 - this.pan.y) / k + b.cz];
    }
    reset() { this.zoom = 1; this.pan = { x: 0, y: 0 }; this.bgDirty = true; }

    _resize() {
      const r = this.cv.getBoundingClientRect();
      this.W = Math.max(50, r.width); this.H = Math.max(50, r.height);
      this.cv.width = this.W * this.dpr; this.cv.height = this.H * this.dpr;
      this.bg.width = this.cv.width; this.bg.height = this.cv.height;
      this.bgDirty = true;
    }

    _bind() {
      new ResizeObserver(() => this._resize()).observe(this.cv);
      this.cv.addEventListener("wheel", (e) => {
        e.preventDefault();
        const r = this.cv.getBoundingClientRect(), px = e.clientX - r.left, py = e.clientY - r.top;
        const [wx, wz] = this._inv(px, py);
        this.zoom = Math.min(12, Math.max(0.6, this.zoom * Math.exp(-e.deltaY * 0.0015)));
        const [nx, ny] = this._tx(wx, wz);
        this.pan.x += px - nx; this.pan.y += py - ny;
        this.bgDirty = true;
      }, { passive: false });
      let drag = null, moved = 0;
      this.cv.addEventListener("pointerdown", (e) => { drag = { x: e.clientX, y: e.clientY }; moved = 0; this.cv.setPointerCapture(e.pointerId); });
      this.cv.addEventListener("pointermove", (e) => {
        const r = this.cv.getBoundingClientRect(), px = e.clientX - r.left, py = e.clientY - r.top;
        if (drag) {
          const dx = e.clientX - drag.x, dy = e.clientY - drag.y;
          moved += Math.abs(dx) + Math.abs(dy);
          this.pan.x += dx; this.pan.y += dy; drag = { x: e.clientX, y: e.clientY }; this.bgDirty = true;
        } else {
          const id = this._pick(px, py);
          if (id !== this.hover) { this.hover = id; }
          this.onHover(id, px, py);
        }
      });
      this.cv.addEventListener("pointerup", (e) => {
        if (drag && moved < 5) {
          const r = this.cv.getBoundingClientRect();
          const id = this._pick(e.clientX - r.left, e.clientY - r.top);
          this.sel = id === this.sel ? null : id; this.onSelect(this.sel);
        }
        drag = null;
      });
      this.cv.addEventListener("pointerleave", () => { this.hover = null; this.onHover(null); });
      this.cv.addEventListener("dblclick", () => this.reset());
    }

    _pick(px, py) {
      let best = null, bd = 18 * 18;
      for (const [id, s] of this.cars) {
        const [x, y] = this._tx(s.x, s.z);
        const d = (x - px) * (x - px) + (y - py) * (y - py);
        if (d < bd) { bd = d; best = id; }
      }
      return best;
    }

    _drawBg() {
      const g = this.bg.getContext("2d");
      g.setTransform(this.dpr, 0, 0, this.dpr, 0, 0);
      g.clearRect(0, 0, this.W, this.H);
      g.lineCap = "round"; g.lineJoin = "round";
      if (this.trace) {
        const path = new Path2D();
        this.trace.forEach((p, i) => { const [x, y] = this._tx(p[0], p[1]); i ? path.lineTo(x, y) : path.moveTo(x, y); });
        const a = this.trace[0], z = this.trace[this.trace.length - 1];
        const closed = Math.hypot(a[0] - z[0], a[1] - z[1]) < 90;
        if (closed) path.closePath();
        const k = Math.max(0.75, Math.min(2.2, this._base().s * this.zoom * 14));
        g.strokeStyle = "rgba(110,135,190,.10)"; g.lineWidth = 26 * k; g.stroke(path);
        g.strokeStyle = "#313b52"; g.lineWidth = 15 * k; g.stroke(path);
        g.strokeStyle = "#1a2132"; g.lineWidth = 11 * k; g.stroke(path);
        g.strokeStyle = "rgba(200,210,235,.22)"; g.lineWidth = 1; g.setLineDash([6, 9]); g.stroke(path); g.setLineDash([]);
        if (!closed) {
          const [x1, y1] = this._tx(z[0], z[1]), [x2, y2] = this._tx(a[0], a[1]);
          g.strokeStyle = "rgba(77,163,255,.55)"; g.lineWidth = 3; g.setLineDash([2, 7]);
          g.beginPath(); g.moveTo(x1, y1); g.lineTo(x2, y2); g.stroke(); g.setLineDash([]);
          g.fillStyle = "rgba(160,190,230,.8)"; g.font = "700 10px Inter,system-ui,sans-serif"; g.textAlign = "center";
          g.fillText("PIT LANE (untimed)", (x1 + x2) / 2, (y1 + y2) / 2 - 8);
        }
        this._drawMarks(g, k);
      } else {
        g.fillStyle = "rgba(120,140,185,.45)";
        for (const p of this.crumbs.values()) { const [x, y] = this._tx(p[0], p[1]); g.fillRect(x - 2, y - 2, 4, 4); }
      }
      this.bgDirty = false;
    }
    _dirAt(x, z) {
      let bi = 0, bd = 1e18;
      this.trace.forEach((p, i) => { const d = (p[0] - x) ** 2 + (p[1] - z) ** 2; if (d < bd) { bd = d; bi = i; } });
      const a = this.trace[bi], b = this.trace[(bi + 3) % this.trace.length];
      return Math.atan2(b[1] - a[1], b[0] - a[0]);
    }
    _drawMarks(g, k) {
      for (const m of this.marks) {
        const [x, y] = this._tx(m.x, m.z);
        if (m.k === "fin") {
          const ang = this._dirAt(m.x, m.z);
          const nx = -Math.sin(ang), ny = Math.cos(ang);
          const half = 13 * k;
          g.save(); g.translate(x, y); g.rotate(Math.atan2(-Math.sin(ang), FX * Math.cos(ang)) + Math.PI / 2);
          for (let i = -3; i < 3; i++) for (let j = 0; j < 2; j++) {
            g.fillStyle = (i + j) % 2 ? "#fff" : "#10131b";
            g.fillRect(i * half / 3, j * 4 - 4, half / 3, 4);
          }
          g.restore();
        } else if (m.k === "start") {
          g.fillStyle = "#21d3a0"; g.beginPath(); g.arc(x, y, 6, 0, TAU); g.fill();
          g.fillStyle = "#d8fff3"; g.font = "700 10px Inter,system-ui,sans-serif"; g.textAlign = "center";
          g.fillText("START", x, y - 10);
        } else {
          g.fillStyle = "#4da3ff"; g.beginPath(); g.arc(x, y, 5, 0, TAU); g.fill();
          g.fillStyle = "#cfe3ff"; g.font = "700 10px Inter,system-ui,sans-serif"; g.textAlign = "center";
          g.fillText(m.k.toUpperCase(), x, y - 9);
        }
      }
    }

    _frame(t) {
      requestAnimationFrame((tt) => this._frame(tt));
      if (document.hidden) return;
      const dt = Math.min(0.1, (t - this._last) / 1000); this._last = t;
      if (this.bgDirty) this._drawBg();
      const c = this.ctx;
      c.setTransform(this.dpr, 0, 0, this.dpr, 0, 0);
      c.clearRect(0, 0, this.W, this.H);
      c.drawImage(this.bg, 0, 0, this.W, this.H);
      const now = performance.now();

      if (this.opts.incidents) {
        this.inc = this.inc.filter((i) => now - i.t < 90000);
        for (const i of this.inc) {
          const a = 1 - (now - i.t) / 90000, [x, y] = this._tx(i.x, i.z);
          c.globalAlpha = Math.max(0.15, a);
          if (i.k === "cut") { c.fillStyle = "#ff4d5e"; c.beginPath(); c.moveTo(x, y - 6); c.lineTo(x + 6, y + 5); c.lineTo(x - 6, y + 5); c.closePath(); c.fill(); }
          else { c.strokeStyle = "#ffb020"; c.lineWidth = 2; c.beginPath(); c.moveTo(x - 4, y - 4); c.lineTo(x + 4, y + 4); c.moveTo(x + 4, y - 4); c.lineTo(x - 4, y + 4); c.stroke(); }
        }
        c.globalAlpha = 1;
      }

      const order = [...this.cars.entries()].sort((a, b) => (a[0] === this.sel) - (b[0] === this.sel));
      for (const [id, s] of order) {
        const age = Math.min(0.35, (now - s.t0) / 1000);
        const sp = (s.v || 0) / 3.6, hr = (s.h || 0) * Math.PI / 180;
        const px = s.sx + Math.sin(hr) * sp * age, pz = s.sz + Math.cos(hr) * sp * age;
        if (Math.hypot(px - s.x, pz - s.z) > 80) { s.x = px; s.z = pz; }
        const k = 1 - Math.exp(-dt * 14);
        s.x += (px - s.x) * k; s.z += (pz - s.z) * k;
        if (now - s.lt > 90) { s.lt = now; s.trail.push([s.x, s.z]); if (s.trail.length > 110) s.trail.shift(); }
        const [x, y] = this._tx(s.x, s.z);
        const m = this.meta(id) || {}, col = m.color || "#4da3ff", isSel = id === this.sel, isHov = id === this.hover;

        if ((this.opts.trails || isSel) && s.trail.length > 2) {
          for (let i = 1; i < s.trail.length; i++) {
            const [ax, ay] = this._tx(s.trail[i - 1][0], s.trail[i - 1][1]), [bx, by] = this._tx(s.trail[i][0], s.trail[i][1]);
            c.strokeStyle = col; c.globalAlpha = (i / s.trail.length) * 0.55; c.lineWidth = isSel ? 3 : 2;
            c.beginPath(); c.moveTo(ax, ay); c.lineTo(bx, by); c.stroke();
          }
          c.globalAlpha = 1;
        }
        const r = isSel ? 9 : isHov ? 8 : 6.5;
        if (isSel) { c.fillStyle = col; c.globalAlpha = 0.18; c.beginPath(); c.arc(x, y, 20, 0, TAU); c.fill(); c.globalAlpha = 1; }
        if (s.v > 8) {
          c.save(); c.translate(x, y); c.rotate(FX * hr);
          c.fillStyle = col; c.beginPath(); c.moveTo(0, -r - 6); c.lineTo(4, -r - 0.5); c.lineTo(-4, -r - 0.5); c.closePath(); c.fill(); c.restore();
        }
        c.globalAlpha = s.pl ? 0.55 : 1;
        c.fillStyle = col; c.beginPath(); c.arc(x, y, r, 0, TAU); c.fill();
        c.lineWidth = 2; c.strokeStyle = "#0a0e15"; c.stroke();
        c.globalAlpha = 1;
        if (s.sl) {
          c.strokeStyle = "#ffd200"; c.lineWidth = 3; c.globalAlpha = 0.6 + 0.4 * Math.sin(now / 160);
          c.beginPath(); c.arc(x, y, r + 7, 0, TAU); c.stroke(); c.globalAlpha = 1;
        }
        if (s.ok === false) { c.strokeStyle = "#ff4d5e"; c.lineWidth = 2; c.setLineDash([3, 3]); c.beginPath(); c.arc(x, y, r + 4, 0, TAU); c.stroke(); c.setLineDash([]); }
        if (this.opts.names || isSel || isHov) {
          const label = m.label || (s.n != null ? "#" + s.n : "");
          if (label) {
            c.font = "700 11px Inter,system-ui,sans-serif"; c.textAlign = "left";
            const w = c.measureText(label).width;
            c.fillStyle = "rgba(8,11,17,.82)"; c.fillRect(x + r + 4, y - 17, w + 8, 16);
            c.fillStyle = "#fff"; c.fillText(label, x + r + 8, y - 5);
          }
        }
      }
    }
  }

  window.TrackMap = TrackMap;
})();
