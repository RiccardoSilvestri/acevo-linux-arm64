(function () {
  "use strict";
  const esc = ACE.esc;
  const speedOf = ACE.speed || ((v) => Math.round(v));
  const unit = ACE.speedUnit || "km/h";
  const gearName = (g) => (ACEDiag.gearName ? ACEDiag.gearName(g) : String(g));
  const SITE = ACE.SITE || {};
  const WHEEL_DEG = +SITE.wheelDeg || 270;
  const FX = -1;
  const TAU = Math.PI * 2;
  const BRAKE_ON = 30, BRAKE_OFF = 12, THROTTLE_ON = 100, MIN_EVENT_KMH = 40;
  const TRAIL_S = 45, MARK_S = 60;
  const COL = { brake: "#ff4d5e", throttle: "#21d3a0", coast: "#ffb020", ref: "rgba(190,205,255,.55)" };

  function wheelSvg() {
    const leds = Array.from({ length: 12 }, (_, i) => {
      const a = (-58 + i * (116 / 11)) * Math.PI / 180;
      return `<circle class="led" data-i="${i}" cx="${(100 + Math.sin(a) * 92).toFixed(1)}" cy="${(108 - Math.cos(a) * 92).toFixed(1)}" r="5"/>`;
    }).join("");
    return `<svg viewBox="0 0 200 200" class="wheel" aria-label="steering wheel">
      <g class="leds">${leds}</g>
      <g class="rot">
        <path class="rim" d="M38 70 Q40 34 100 30 Q160 34 162 70 L168 118 Q170 150 140 162 L60 162 Q30 150 32 118 Z"/>
        <path class="spoke" d="M44 104 L80 104 L88 128 L112 128 L120 104 L156 104"/>
        <path class="spoke" d="M88 128 L92 158 M112 128 L108 158"/>
        <rect class="topmark" x="96" y="25" width="8" height="12" rx="2"/>
        <circle class="hub" cx="100" cy="112" r="30"/>
      </g>
      <text class="wg" x="100" y="116" text-anchor="middle">–</text>
      <text class="ws" x="100" y="134" text-anchor="middle">–</text>
    </svg>`;
  }

  function pedal(cls, label, na) {
    return `<div class="pedal ${cls} ${na ? "na" : ""}" title="${na ? "The game does not send the clutch position" : ""}">
      <b class="pv">${na ? "n/a" : "0%"}</b><div class="plate"><i></i></div><span>${label}</span></div>`;
  }

  class Cockpit {
    constructor(el) {
      this.el = el;
      this.cid = null;
      this.trace = null;
      this.samples = [];
      this.marks = [];
      this.car = null;
      this.span = 220;
      this.head = 0;
      this.rpmTop = 6000;
      this.phase = { braking: false, after: false, minV: null, minAt: null };
      el.innerHTML = `
        <section class="tile cockpit-tile"><h3>Cockpit</h3>
          <div class="cp-row">${wheelSvg()}
            <div class="pedals3">${pedal("clutch", "Clutch", true)}${pedal("brake", "Brake")}${pedal("throttle", "Throttle")}</div>
          </div>
        </section>
        <section class="tile chase-tile"><h3>Onboard view <span class="sp zoombtns"><span class="pill sm" data-z="-1">−</span><span class="pill sm" data-z="1">+</span></span></h3>
          <div class="chasebox"><canvas class="chase"></canvas><div class="chase-msg"></div></div>
          <div class="chase-legend"><span><i style="background:${COL.brake}"></i>braking</span><span><i style="background:${COL.throttle}"></i>throttle</span><span><i style="background:${COL.coast}"></i>coasting</span><span><i class="dash"></i>reference lap</span>
            <span><b class="mk b">B</b>brake point</span><span><b class="mk a">◆</b>min speed</span><span><b class="mk t">T</b>back on throttle</span></div>
        </section>`;
      this.q = (s) => el.querySelector(s);
      this.cv = this.q("canvas.chase");
      this.ctx = this.cv.getContext("2d");
      this.dpr = Math.min(window.devicePixelRatio || 1, 2);
      new ResizeObserver(() => this._resize()).observe(this.cv);
      el.querySelectorAll("[data-z]").forEach((b) => b.addEventListener("click", () => {
        this.span = Math.max(90, Math.min(600, this.span * (b.dataset.z === "1" ? 0.75 : 1.33)));
      }));
      this._resize();
      requestAnimationFrame((t) => this._frame(t));
    }

    setTrace(doc) {
      this.trace = doc && doc.pts && doc.pts.length > 30 ? doc.pts : null;
    }

    select(cid) {
      if (cid === this.cid) return;
      this.cid = cid;
      this.samples = []; this.marks = []; this.car = null; this.rpmTop = 6000;
      this.phase = { braking: false, after: false, minV: null, minAt: null };
    }

    live(c) {
      this._inputs(c);
      if (!c) { this.car = null; return; }
      const now = performance.now();
      if (!this.car) this.car = { x: c.x, z: c.z };
      Object.assign(this.car, { sx: c.x, sz: c.z, v: c.v || 0, h: c.h || 0, t0: now });
      const t = c.tl;
      const thr = t ? t[2] : null, brk = t ? t[3] : null;
      const last = this.samples[this.samples.length - 1];
      if (!last || Math.hypot(last.x - c.x, last.z - c.z) > 0.6) {
        if (last && Math.hypot(last.x - c.x, last.z - c.z) > 120) this.samples = [];
        this.samples.push({ x: c.x, z: c.z, thr, brk, v: c.v, t: now });
      }
      while (this.samples.length && now - this.samples[0].t > TRAIL_S * 1000) this.samples.shift();
      if (t) this._events(c, thr, brk, now);
      this.marks = this.marks.filter((m) => now - m.t < MARK_S * 1000);
    }

    _events(c, thr, brk, now) {
      const p = this.phase;
      if (!p.braking && brk >= BRAKE_ON && c.v >= MIN_EVENT_KMH) {
        p.braking = true; p.after = false; p.minV = c.v; p.minAt = [c.x, c.z];
        this.marks.push({ k: "b", x: c.x, z: c.z, v: c.v, t: now });
      }
      if (p.braking || p.after) {
        if (p.minV == null || c.v < p.minV) { p.minV = c.v; p.minAt = [c.x, c.z]; }
      }
      if (p.braking && brk <= BRAKE_OFF) { p.braking = false; p.after = true; }
      if ((p.braking || p.after) && c.v < 8) { p.braking = false; p.after = false; p.minV = null; p.minAt = null; }
      if (p.after && thr >= THROTTLE_ON) {
        p.after = false;
        if (p.minAt) this.marks.push({ k: "a", x: p.minAt[0], z: p.minAt[1], v: p.minV, t: now });
        this.marks.push({ k: "t", x: c.x, z: c.z, v: c.v, t: now });
        p.minV = null; p.minAt = null;
      }
      if (this.marks.length > 18) this.marks.splice(0, this.marks.length - 18);
    }

    _inputs(c) {
      const t = c && c.tl;
      const rot = this.q(".wheel .rot");
      const s = t ? Math.max(-1, Math.min(1, t[4] / 127)) : 0;
      rot.style.transform = `rotate(${(s * WHEEL_DEG).toFixed(1)}deg)`;
      this.q(".wheel .wg").textContent = t ? gearName(t[0]) : "–";
      this.q(".wheel .ws").textContent = c ? `${speedOf(c.v)} ${unit}` : "–";
      let frac = 0;
      if (t) { this.rpmTop = Math.max(this.rpmTop, t[1]); frac = t[1] / this.rpmTop; }
      const lit = Math.round(Math.max(0, (frac - 0.55) / 0.43) * 12);
      this.el.querySelectorAll(".wheel .led").forEach((l, i) => {
        l.setAttribute("class", "led" + (i < lit ? (frac > 0.97 ? " on flash" : i < 4 ? " on g" : i < 8 ? " on y" : " on r") : ""));
      });
      [["brake", 3], ["throttle", 2]].forEach(([k, i]) => {
        const v = t ? Math.round((t[i] / 255) * 100) : 0;
        const p = this.q(`.pedal.${k}`);
        p.querySelector("i").style.height = v + "%";
        p.querySelector(".pv").textContent = t ? v + "%" : "–";
        p.classList.toggle("act", v > 4);
      });
    }

    _resize() {
      const r = this.cv.getBoundingClientRect();
      this.W = Math.max(50, r.width); this.H = Math.max(50, r.height);
      this.cv.width = this.W * this.dpr; this.cv.height = this.H * this.dpr;
    }

    _frame() {
      requestAnimationFrame((t) => this._frame(t));
      if (document.hidden || !this.W) return;
      const g = this.ctx, W = this.W, H = this.H, now = performance.now();
      g.setTransform(this.dpr, 0, 0, this.dpr, 0, 0);
      g.clearRect(0, 0, W, H);
      const msg = this.q(".chase-msg");
      const c = this.car;
      if (!c) { msg.textContent = this.cid ? "Waiting for the car's position…" : "Select a car on track"; return; }
      msg.textContent = "";
      const age = Math.min(0.35, (now - c.t0) / 1000);
      const sp = c.v / 3.6, hr = c.h * Math.PI / 180;
      const px = c.sx + Math.sin(hr) * sp * age, pz = c.sz + Math.cos(hr) * sp * age;
      if (Math.hypot(px - c.x, pz - c.z) > 60) { c.x = px; c.z = pz; }
      c.x += (px - c.x) * 0.25; c.z += (pz - c.z) * 0.25;
      if (c.v > 6) {
        const target = Math.atan2(FX * Math.sin(hr), Math.cos(hr));
        let d = target - this.head;
        d = Math.atan2(Math.sin(d), Math.cos(d));
        this.head += d * 0.12;
      }
      const k = W / this.span, cos = Math.cos(this.head), sin = Math.sin(this.head);
      const ox = W / 2, oy = H * 0.68;
      const tx = (x, z) => {
        const ux = FX * (x - c.x), uy = z - c.z;
        return [ox + (ux * cos - uy * sin) * k, oy - (ux * sin + uy * cos) * k];
      };
      g.lineCap = "round"; g.lineJoin = "round";
      if (this.trace) {
        const path = new Path2D();
        let started = false;
        const lim = this.span * 1.6;
        for (const p of this.trace) {
          if (Math.abs(p[0] - c.x) > lim || Math.abs(p[1] - c.z) > lim) { started = false; continue; }
          const [x, y] = tx(p[0], p[1]);
          if (started) path.lineTo(x, y); else { path.moveTo(x, y); started = true; }
        }
        g.strokeStyle = "#323d56"; g.lineWidth = Math.max(10, 15 * k); g.stroke(path);
        g.strokeStyle = "#171e2d"; g.lineWidth = Math.max(8, 12 * k); g.stroke(path);
        g.strokeStyle = COL.ref; g.lineWidth = 1.5; g.setLineDash([6, 6]); g.stroke(path); g.setLineDash([]);
      }
      const s = this.samples;
      g.lineWidth = Math.max(3, Math.min(6, 1.6 * k));
      for (let i = 1; i < s.length; i++) {
        const a = s[i - 1], b = s[i];
        if (Math.abs(b.x - c.x) > this.span * 1.6 || Math.abs(b.z - c.z) > this.span * 1.6) continue;
        const fade = Math.max(0.25, 1 - (now - b.t) / (TRAIL_S * 1000));
        let col = COL.coast;
        if (b.brk != null && b.brk >= BRAKE_OFF) col = COL.brake;
        else if (b.thr != null && b.thr >= 40) col = COL.throttle;
        const [x1, y1] = tx(a.x, a.z), [x2, y2] = tx(b.x, b.z);
        g.globalAlpha = fade;
        g.strokeStyle = col;
        g.beginPath(); g.moveTo(x1, y1); g.lineTo(x2, y2); g.stroke();
      }
      g.globalAlpha = 1;
      g.font = "700 11px Inter,system-ui,sans-serif"; g.textAlign = "center"; g.textBaseline = "middle";
      for (const m of this.marks) {
        const [x, y] = tx(m.x, m.z);
        if (x < -40 || y < -40 || x > W + 40 || y > H + 40) continue;
        const a = Math.max(0.35, 1 - (now - m.t) / (MARK_S * 1000));
        g.globalAlpha = a;
        const col = m.k === "b" ? COL.brake : m.k === "t" ? COL.throttle : "#ffffff";
        g.fillStyle = col;
        if (m.k === "a") { g.beginPath(); g.moveTo(x, y - 7); g.lineTo(x + 7, y); g.lineTo(x, y + 7); g.lineTo(x - 7, y); g.closePath(); g.fill(); }
        else { g.beginPath(); g.arc(x, y, 9, 0, TAU); g.fill(); g.fillStyle = "#0b0f17"; g.fillText(m.k === "b" ? "B" : "T", x, y + 0.5); }
        const label = `${speedOf(m.v)}`;
        g.fillStyle = "rgba(8,11,17,.85)";
        const w = g.measureText(label).width + 8;
        g.fillRect(x + 12, y - 8, w, 16);
        g.fillStyle = col; g.textAlign = "left"; g.fillText(label, x + 16, y); g.textAlign = "center";
      }
      g.globalAlpha = 1;
      g.save(); g.translate(ox, oy);
      g.fillStyle = "#fff"; g.strokeStyle = "#0a0e15"; g.lineWidth = 2;
      g.beginPath(); g.moveTo(0, -12); g.lineTo(8, 9); g.lineTo(0, 5); g.lineTo(-8, 9); g.closePath(); g.fill(); g.stroke();
      g.restore();
      const bar = this.span / 4, bw = bar * k;
      g.strokeStyle = "rgba(200,210,235,.6)"; g.lineWidth = 2;
      g.beginPath(); g.moveTo(12, H - 14); g.lineTo(12 + bw, H - 14); g.stroke();
      g.fillStyle = "rgba(200,210,235,.75)"; g.textAlign = "left"; g.font = "600 10px Inter,system-ui,sans-serif";
      g.fillText(`${Math.round(bar)} m`, 12, H - 24);
    }
  }

  window.ACECockpit = Cockpit;
})();
