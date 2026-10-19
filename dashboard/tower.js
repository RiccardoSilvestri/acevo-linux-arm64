(function () {
  "use strict";
  const { esc, fmtMs, colorOf } = ACE;
  const ROW_H = 34;
  const FLAG_DSQ = 8, FLAG_OUT = 16, FLAG_DNF = 32;

  function code(name) {
    const parts = String(name || "?").trim().split(/\s+/).filter(Boolean);
    const base = parts.length > 1 ? parts[parts.length - 1] : parts[0] || "?";
    return base.replace(/[^\p{L}\p{N}]/gu, "").slice(0, 3).toUpperCase() || "???";
  }
  const secs = (ms) => (ms / 1000).toFixed(3);
  const gapTxt = (ms) => (ms == null ? "" : "+" + (ms >= 60000 ? fmtMs(ms) : (ms / 1000).toFixed(3)));

  class Tower {
    constructor(el, live, opts) {
      this.el = el; this.live = live; this.opts = opts || {};
      this.mode = "int";
      this.cur = new Map();
      this.grid = new Map();
      this.gridKey = null;
      this.rows = new Map();
      this.prevPos = new Map();
      this.flash = new Map();
      this.sessBest = null;
      this.fastest = null;
      this.sessKey = null;
      this.queue = [];
      this.bannerBusy = false;
      this.phaseKey = null;
      el.innerHTML = `<div class="tw-flag"></div>
        <div class="tw-head"><div class="tw-title"><b id="tw-sess">Timing</b><span id="tw-info" class="num"></span></div>
        <div class="tw-modes"><span data-m="int" class="on">Gap</span><span data-m="lead">To P1</span><span data-m="best">Best</span><span data-m="last">Last</span></div></div>
        <div class="tw-body"><div class="tw-list"></div><div class="tw-empty">Nobody on track yet</div></div>
        <div class="tw-banner"></div>`;
      this.list = el.querySelector(".tw-list");
      this.banner = el.querySelector(".tw-banner");
      el.querySelectorAll("[data-m]").forEach((b) => b.addEventListener("click", () => {
        this.mode = b.dataset.m;
        el.querySelectorAll("[data-m]").forEach((x) => x.classList.toggle("on", x === b));
        this.render();
      }));
      live.on("split", (m) => this._split(m));
      live.on("lap", (l) => this._lap(l));
      live.on("inc", (i) => this._inc(i));
      live.on("race", (r) => this._phase(r));
      ["status", "race", "hello"].forEach((t) => live.on(t, () => this.render()));
      live.on("cars", () => { const now = performance.now(); if (now - (this._t || 0) > 500) { this._t = now; this.render(); } });
      setInterval(() => this._info(), 500);
    }

    _sessionKey() {
      const r = this.live.race;
      return r ? (r.session || "") + "|" + (r.session_start || "") : "";
    }

    _split(m) {
      let c = this.cur.get(m.cid);
      if (!c || c.done || c.lap !== m.lap) { c = { lap: m.lap, s: [], done: false }; this.cur.set(m.cid, c); }
      if (m.ms > 0) c.s.push({ ms: m.ms, ok: m.ok });
      if (m.fin) c.done = true;
      this.render();
    }

    _lap(l) {
      const k = this._sessionKey();
      if (k !== this.sessKey) { this.sessKey = k; this.sessBest = null; this.fastest = null; }
      const r = this.live.race;
      if (r && r.session_start && l.ts < r.session_start - 5) return;
      if (l.valid && l.ms && (this.sessBest == null || l.ms < this.sessBest)) {
        const first = this.sessBest == null;
        this.sessBest = l.ms;
        this.fastest = l.cid;
        if (!first || (r && r.session === "Race")) this._banner("fastest", "Fastest lap", code(l.driver), fmtMs(l.ms), l.driver);
      }
      this.render();
    }

    _inc(i) {
      if (i.k === "pit_in") this._banner("pit", "Pit stop", code(i.name), "", i.name);
      else if (i.k === "penalty") this._banner("pen", "Penalty", code(i.name), (ACESession.PEN[i.pen] || i.pen || "").replace(/_/g, " "), i.name);
    }

    _phase(r) {
      if (!r || !r.phase) return;
      const k = r.session + "|" + r.phase;
      if (this.phaseKey && k !== this.phaseKey) {
        const map = { Start_Countdown_Lights_Off: ["go", "Lights out", "GO GO GO"], RollingStart_Start_Green_Flag: ["go", "Green flag", "RACE START"],
          Overtime_Waiting_For_Leader: ["white", "Final lap", ""], Waiting_Last_Lap: ["white", "Time is up", "FINAL LAP"],
          Overtime_Waiting_For_Others: ["chequer", "Chequered flag", ""], Ended: ["chequer", "Session over", ""] };
        const b = map[r.phase];
        if (b) this._banner(b[0], b[1], b[2] || (r.session || "").toUpperCase(), "", "");
      }
      this.phaseKey = k;
      let kind = (ACESession.phaseKind ? ACESession.phaseKind(r.phase) : "wait");
      if (kind === "green" && [...this.live.cars.values()].some((c) => c.sl)) kind = "yellow";
      this.el.querySelector(".tw-flag").className = "tw-flag " + kind;
    }

    _banner(kind, label, main, sub, title) {
      this.queue.push({ kind, label, main, sub, title });
      if (this.queue.length > 4) this.queue.shift();
      if (!this.bannerBusy) this._nextBanner();
    }

    _nextBanner() {
      const b = this.queue.shift();
      if (!b) { this.bannerBusy = false; return; }
      this.bannerBusy = true;
      this.banner.className = "tw-banner " + b.kind;
      this.banner.title = b.title || "";
      this.banner.innerHTML = `<small>${esc(b.label)}</small><b>${esc(b.main)}</b>${b.sub ? `<span class="num">${esc(b.sub)}</span>` : ""}`;
      void this.banner.offsetWidth;
      this.banner.classList.add("show");
      setTimeout(() => { this.banner.classList.remove("show"); setTimeout(() => this._nextBanner(), 450); }, 5200);
    }

    _data() {
      const st = this.live.status || {}, race = this.live.race, timing = st.timing || {};
      const rows = (timing.rows || []).map((r) => Object.assign({}, r));
      const names = new Set(rows.map((r) => r.name));
      (st.drivers || []).forEach((d) => {
        if (!names.has(d.name)) rows.push({ name: d.name, car: d.car, cid: d.cid, laps: 0, valid: 0, best_ms: null, last_ms: null });
      });
      const rc = new Map(((race && race.cars) || []).map((c) => [c.cid, c]));
      const isRace = !!(race && race.sort === "Race" && race.session === "Race");
      if (isRace) {
        const gaps = ACESession.raceGaps(race);
        rows.forEach((r) => { const g = gaps.get(r.cid); r.pos = g ? g.pos : null; r.g = g; });
        rows.sort((a, b) => (a.pos || 999) - (b.pos || 999));
        const k = race.session + "|" + (race.session_start || "");
        if (this.gridKey !== k && /Session|Overtime/.test(race.phase || "")) { this.gridKey = k; this.grid.clear(); }
        rows.forEach((r) => { if (r.pos && !this.grid.has(r.cid) && this.gridKey === k) this.grid.set(r.cid, r.pos); });
      } else {
        rows.sort((a, b) => (a.best_ms == null) - (b.best_ms == null) || (a.best_ms || 0) - (b.best_ms || 0));
        rows.forEach((r, i) => { r.pos = r.best_ms != null ? i + 1 : null; });
      }
      return { rows, rc, isRace, timing, race, st };
    }

    _gap(r, i, rows, d) {
      if (d.isRace) {
        if (!r.g) return "";
        if (this.mode === "int") return i === 0 ? "Interval" : (r.g.int || r.g.gap);
        if (this.mode === "lead") return i === 0 ? "Leader" : r.g.gap;
      }
      if (this.mode === "last") return r.last_ms != null ? fmtMs(r.last_ms) : "";
      if (this.mode === "best" || i === 0) return r.best_ms != null ? fmtMs(r.best_ms) : "";
      const lead = rows[0] && rows[0].best_ms, prev = rows[i - 1] && rows[i - 1].best_ms;
      if (r.best_ms == null || lead == null) return "";
      return gapTxt(this.mode === "int" ? r.best_ms - prev : r.best_ms - lead);
    }

    _sectors(r, d) {
      const best = d.timing.sector_best || [];
      const pb = r.best_splits || [];
      const n = Math.max(1, d.timing.sectors || 3);
      const c = this.cur.get(r.cid);
      let out = "";
      for (let k = 0; k < Math.min(n, 3); k++) {
        const s = c && c.s[k];
        let cls = "";
        if (s) cls = !s.ok ? "bad" : best[k] != null && s.ms <= best[k] ? "p" : pb[k] != null && s.ms <= pb[k] ? "g" : "y";
        out += `<i class="${cls}" title="${s ? "S" + (k + 1) + " " + secs(s.ms) : ""}"></i>`;
      }
      return out;
    }

    _status(rc, car) {
      const f = (rc && rc.flags) || 0;
      if (f & FLAG_DSQ) return '<em class="st dsq">DSQ</em>';
      if (f & FLAG_DNF) return '<em class="st dnf">OUT</em>';
      if ((car && (car.pl || car.loc === "Pitlane")) || (rc && rc.loc === "Pitlane")) return '<em class="st pit">PIT</em>';
      if (car && car.sl) return '<em class="st slow">SLOW</em>';
      if (rc && (rc.pen || []).length) return `<em class="st pen" title="${esc((rc.pen || []).map((p) => p.type).join(", "))}">${esc(ACESession.PEN[rc.pen[0].type] || "PEN")}</em>`;
      return "";
    }

    render() {
      const d = this._data();
      const { rows, rc, isRace } = d;
      const k = this._sessionKey();
      if (k !== this.sessKey) { this.sessKey = k; this.sessBest = null; this.fastest = null; }
      this.el.classList.toggle("race", isRace);
      this.el.querySelector(".tw-empty").style.display = rows.length ? "none" : "";
      this.el.querySelector('[data-m="int"]').textContent = isRace ? "Interval" : "Gap";
      this.el.querySelector('[data-m="lead"]').textContent = isRace ? "Leader" : "To P1";
      const overall = Math.min(...rows.map((r) => r.best_ms || Infinity));
      const flId = this.fastest || (isFinite(overall) ? (rows.find((r) => r.best_ms === overall) || {}).cid : null);
      const now = performance.now();
      const seen = new Set();
      rows.forEach((r, i) => {
        const key = r.cid || "n:" + r.name;
        seen.add(key);
        let el = this.rows.get(key);
        if (!el) {
          el = document.createElement("div");
          el.className = "tw-row";
          el.addEventListener("click", () => this.opts.onSelect && this.opts.onSelect(r.cid, r.name));
          this.list.appendChild(el);
          this.rows.set(key, el);
          el.style.transform = `translateY(${i * ROW_H}px)`;
        }
        const prev = this.prevPos.get(key);
        if (isRace && prev && r.pos && prev !== r.pos) this.flash.set(key, { cls: r.pos < prev ? "gain" : "loss", until: now + 2600 });
        if (r.pos) this.prevPos.set(key, r.pos);
        const fl = this.flash.get(key);
        const car = r.cid ? this.live.cars.get(r.cid) : null;
        const rcar = rc.get(r.cid);
        const g0 = this.grid.get(r.cid);
        const delta = isRace && g0 && r.pos ? g0 - r.pos : 0;
        const isFl = !!(r.cid && r.cid === flId && r.best_ms != null);
        const lastCls = r.last_ok === false ? "bad" : r.last_ms != null && r.last_ms === overall ? "p" : r.last_ms != null && r.last_ms === r.best_ms ? "g" : "";
        el.classList.toggle("sel", !!(this.opts.selected && this.opts.selected() === r.cid));
        el.classList.toggle("off", !car);
        el.classList.toggle("fl", isFl);
        el.classList.toggle("gain", !!(fl && fl.until > now && fl.cls === "gain"));
        el.classList.toggle("loss", !!(fl && fl.until > now && fl.cls === "loss"));
        el.innerHTML = `<span class="tw-pos">${r.pos || "–"}</span>
          <span class="tw-bar" style="background:${colorOf(r.name)}"></span>
          <span class="tw-code" title="${esc(r.name)} · ${esc(r.car || "")}">${esc(code(r.name))}</span>
          <span class="tw-delta ${delta > 0 ? "up" : delta < 0 ? "down" : ""}">${delta > 0 ? "▲" + delta : delta < 0 ? "▼" + -delta : ""}</span>
          <span class="tw-sec">${this._sectors(r, d)}</span>
          <span class="tw-gap num ${this.mode === "last" ? lastCls : this.mode === "best" && isFl ? "p" : ""}">${esc(this._gap(r, i, rows, d))}</span>
          <span class="tw-tail">${isFl ? '<b class="flb" title="Fastest lap">⏱</b>' : ""}${this._status(rcar, car)}</span>`;
        el.style.transform = `translateY(${i * ROW_H}px)`;
      });
      for (const [k2, el] of this.rows) if (!seen.has(k2)) { el.remove(); this.rows.delete(k2); }
      this.list.style.height = rows.length * ROW_H + "px";
      this._info();
      if (this.live.race) this._phase(this.live.race);
    }

    _info() {
      const r = this.live.race, st = this.live.status || {}, w = st.weekend || {};
      const s = this.el.querySelector("#tw-sess"), info = this.el.querySelector("#tw-info");
      s.textContent = (r && r.session) || "Timing";
      let t = "";
      if (r && r.session === "Race" && w.race_laps) {
        const lead = (r.cars || []).find((c) => c.pos === 1);
        t = lead && lead.laps != null ? `LAP ${Math.min(w.race_laps, lead.laps + 1)}/${w.race_laps}` : `${w.race_laps} LAPS`;
      } else if (r && r.phase_end) {
        const left = Math.max(0, Math.floor(r.phase_end - this.live.serverNow()));
        t = `${Math.floor(left / 60)}:${String(left % 60).padStart(2, "0")}`;
      }
      info.textContent = t;
    }
  }

  window.ACETower = Tower;
})();
