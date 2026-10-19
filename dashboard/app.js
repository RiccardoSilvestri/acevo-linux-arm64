(function () {
  "use strict";
  const $ = (s, r) => (r || document).querySelector(s);
  const $$ = (s, r) => Array.from((r || document).querySelectorAll(s));
  const ESC = { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" };
  const esc = (v) => String(v == null ? "" : v).replace(/[&<>"']/g, (c) => ESC[c]);

  const SITE = (() => {
    const base = { name: "ACE Live Timing", locale: "en-GB", speedUnit: "kmh" };
    try { return Object.assign(base, JSON.parse(document.getElementById("site-config").textContent)); } catch (e) { return base; }
  })();
  const speedUnit = SITE.speedUnit === "mph" ? "mph" : "km/h";
  const speed = (kmh) => (kmh == null || isNaN(kmh) ? null : Math.round(SITE.speedUnit === "mph" ? kmh * 0.621371 : kmh));
  const fmtSpeed = (kmh) => { const v = speed(kmh); return v == null ? "–" : v + " " + speedUnit; };

  function fmtMs(ms) {
    if (ms == null || isNaN(ms)) return "–";
    const m = Math.floor(ms / 60000), s = (ms % 60000) / 1000;
    return m ? m + ":" + s.toFixed(3).padStart(6, "0") : s.toFixed(3);
  }
  function fmtRun(ms) {
    if (ms == null || isNaN(ms)) return "–";
    const m = Math.floor(ms / 60000), s = (ms % 60000) / 1000;
    return m ? m + ":" + s.toFixed(1).padStart(4, "0") : s.toFixed(1);
  }
  const fmtSec = (ms) => (ms == null ? "–" : (ms / 1000).toFixed(3));
  function fmtGap(ms) {
    if (ms == null) return "–";
    return ms === 0 ? "—" : "+" + (ms / 1000).toFixed(3);
  }
  function fmtDelta(ms) {
    if (ms == null || isNaN(ms)) return "";
    const v = Math.abs(ms) / 1000;
    return (ms < 0 ? "−" : "+") + (v >= 100 ? v.toFixed(0) : v.toFixed(2));
  }
  function fmtClock(ts) {
    if (!ts) return "";
    return new Date(ts * 1000).toLocaleTimeString(SITE.locale, { hour: "2-digit", minute: "2-digit", second: "2-digit" });
  }
  function ago(ts) {
    const s = Math.max(0, Math.round(Date.now() / 1000 - ts));
    if (s < 5) return "just now";
    if (s < 60) return s + "s ago";
    if (s < 3600) return Math.floor(s / 60) + " min ago";
    if (s < 86400) return Math.floor(s / 3600) + " h ago";
    return Math.floor(s / 86400) + " d ago";
  }
  function fmtDate(d) {
    if (!d) return "";
    const t = new Date(d + "T00:00:00");
    return isNaN(t) ? d : t.toLocaleDateString(SITE.locale, { day: "2-digit", month: "short", year: "numeric" });
  }
  function secText(splits) {
    return splits && splits.length > 1 ? splits.map((s) => fmtSec(s)).join(" · ") : "";
  }

  function hue(str) {
    let h = 2166136261;
    for (let i = 0; i < str.length; i++) { h ^= str.charCodeAt(i); h = Math.imul(h, 16777619); }
    return (h >>> 0) % 360;
  }
  const colorOf = (name) => `hsl(${hue(String(name || "?"))} 78% 62%)`;
  const initials = (name) => String(name || "?").split(/\s+/).map((w) => w[0]).join("").slice(0, 3).toUpperCase();
  const enc = encodeURIComponent;

  async function getJSON(url) {
    const r = await fetch(url, { cache: "no-store" });
    if (!r.ok) throw new Error(r.status);
    return r.json();
  }

  function header(active) {
    const el = $("#hdr");
    if (!el) return;
    const link = (href, id, label) => `<a href="${href}" class="${active === id ? "on" : ""}">${label}</a>`;
    el.className = "hdr";
    el.innerHTML = `<div class="hdr-in">
      <a class="brand" href="/" title="${esc(SITE.name)}"><i></i><span id="brand-name">${esc(SITE.name)}</span></a>
      <nav class="nav">${link("/", "live", "Live")}${link("/records", "records", "Leaderboards")}${link("/laps", "laps", "Laps")}</nav>
      <div class="chips">
        <span class="chip hide-sm" id="c-track">Track <b>–</b></span>
        <span class="chip" id="c-players">Drivers <b>–</b></span>
        <span class="chip" id="c-link"><span class="dot"></span><b>connecting…</b></span>
      </div>
    </div>`;
    footer();
  }
  const GH_ICON = '<svg viewBox="0 0 16 16" width="15" height="15" aria-hidden="true"><path fill="currentColor" d="M8 0C3.58 0 0 3.58 0 8c0 3.54 2.29 6.53 5.47 7.59.4.07.55-.17.55-.38 0-.19-.01-.82-.01-1.49-2.01.37-2.53-.49-2.69-.94-.09-.23-.48-.94-.82-1.13-.28-.15-.68-.52-.01-.53.63-.01 1.08.58 1.23.82.72 1.21 1.87.87 2.33.66.07-.52.28-.87.51-1.07-1.78-.2-3.64-.89-3.64-3.95 0-.87.31-1.59.82-2.15-.08-.2-.36-1.02.08-2.12 0 0 .67-.21 2.2.82.64-.18 1.32-.27 2-.27.68 0 1.36.09 2 .27 1.53-1.04 2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12.51.56.82 1.27.82 2.15 0 3.07-1.87 3.75-3.65 3.95.29.25.54.73.54 1.48 0 1.07-.01 1.93-.01 2.2 0 .21.15.46.55.38A8.013 8.013 0 0016 8c0-4.42-3.58-8-8-8z"/></svg>';
  function footer() {
    const pb = SITE.poweredBy;
    if (!pb || !/^https?:\/\//.test(pb.url) || $("#poweredby")) return;
    let f = $("main footer") || $("footer");
    if (!f) { f = document.createElement("footer"); ($("main") || document.body).appendChild(f); }
    const el = document.createElement("div");
    el.id = "poweredby";
    el.className = "poweredby";
    el.innerHTML = `<a href="${esc(pb.url)}" target="_blank" rel="noopener"><span class="pb-k">Powered by</span>${GH_ICON}<b>${esc(pb.label || "GitHub")}</b><span class="pb-arrow">↗</span></a>`;
    f.appendChild(el);
  }
  function fillHeader(s) {
    if (!s) return;
    if (SITE.nameFromServer && s.server_name && s.server_name !== SITE.name) {
      const prev = SITE.name;
      SITE.name = s.server_name;
      const b = $("#brand-name");
      if (b) { b.textContent = s.server_name; b.parentNode.title = s.server_name; }
      if (document.title.startsWith(prev)) document.title = s.server_name + document.title.slice(prev.length);
    }
    const t = $("#c-track"), p = $("#c-players");
    if (t) t.innerHTML = `Track <b>${esc([s.track, s.layout].filter(Boolean).join(" ") || "–")}</b>`;
    if (p) p.innerHTML = `Drivers <b>${s.players == null ? "–" : s.players}${s.max_players ? " / " + s.max_players : ""}</b>`;
  }

  class Live {
    constructor() {
      this.handlers = {};
      this.status = null;
      this.cars = new Map();
      this.diag = new Map();
      this.laps = [];
      this.inc = [];
      this.lw = false;
      this.race = null;
      this.offset = 0;
      this.mode = "connecting";
      this.lastMsg = 0;
      this.backoff = 800;
      this._connect();
      setInterval(() => this._chip(), 1000);
    }
    serverNow() { return Date.now() / 1000 + this.offset; }
    _clock(ts) { if (ts) this.offset = ts - Date.now() / 1000; }
    on(t, fn) { (this.handlers[t] = this.handlers[t] || []).push(fn); return this; }
    _emit(t, d) { (this.handlers[t] || []).forEach((f) => { try { f(d); } catch (e) { console.error(e); } }); }
    _connect() {
      const proto = location.protocol === "https:" ? "wss" : "ws";
      let ws;
      try { ws = new WebSocket(`${proto}://${location.host}/ws`); } catch (e) { return this._fallback(); }
      this.ws = ws;
      const dead = setTimeout(() => { if (ws.readyState !== 1) { try { ws.close(); } catch (e) {} } }, 8000);
      ws.onopen = () => { clearTimeout(dead); this.mode = "ws"; this.backoff = 800; this._stopPoll(); this._chip(); };
      ws.onmessage = (ev) => { this.lastMsg = Date.now(); this._dispatch(JSON.parse(ev.data)); };
      ws.onclose = () => {
        clearTimeout(dead);
        this.mode = "reconnect"; this._chip(); this._fallback();
        setTimeout(() => this._connect(), this.backoff);
        this.backoff = Math.min(this.backoff * 1.7, 10000);
      };
      ws.onerror = () => { try { ws.close(); } catch (e) {} };
    }
    _fallback() {
      if (this.poll) return;
      const tick = async () => {
        try { const s = await getJSON("/api/status"); this._dispatch({ t: "status", s }); this.lastMsg = Date.now(); } catch (e) {}
      };
      tick();
      this.poll = setInterval(tick, 2000);
    }
    _stopPoll() { if (this.poll) { clearInterval(this.poll); this.poll = null; } }
    _dispatch(m) {
      switch (m.t) {
        case "hello":
          this.race = m.race || null;
          if (m.s) this._clock(m.s.updated_ts);
          this.status = m.s; this.laps = m.laps || []; this.inc = m.inc || []; this.lw = !!m.lw;
          this.cars.clear(); (m.c || []).forEach((c) => this.cars.set(c.i, c));
          this.diag.clear(); Object.entries(m.dg || {}).forEach(([k, v]) => this.diag.set(k, v));
          fillHeader(this.status);
          this._emit("status", this.status); this._emit("hello", m); this._emit("cars", [...this.cars.values()]);
          break;
        case "status": this.status = m.s; this._clock(m.s.updated_ts); if (m.s.race !== undefined && this.mode !== "ws") { this.race = m.s.race; this._emit("race", this.race); } fillHeader(m.s); this._emit("status", m.s); break;
        case "hb": this._clock(m.ts); break;
        case "race": this.race = m.r; this._emit("race", m.r); break;
        case "p":
          this.cars.clear(); m.c.forEach((c) => this.cars.set(c.i, c));
          this._emit("cars", m.c); break;
        case "diag": this.diag.set(m.cid, m.d); this._emit("diag", m); break;
        case "lap": this.laps.push(m); if (this.laps.length > 300) this.laps.shift(); this._emit("lap", m); break;
        case "inc": this.inc.push(m); if (this.inc.length > 200) this.inc.shift(); this._emit("inc", m); break;
        case "lw": this.lw = m.on; if (!m.on) this.cars.clear(); this._emit("lw", m.on); break;
        default: this._emit(m.t, m);
      }
    }
    _chip() {
      const el = $("#c-link"); if (!el) return;
      const age = (Date.now() - this.lastMsg) / 1000;
      let cls = "dot", txt;
      if (this.mode === "ws" && age < 15) { cls += " on"; txt = this.cars.size ? `LIVE · ${this.cars.size} on track` : "LIVE"; }
      else if (this.mode === "ws") { cls += " warn"; txt = "waiting for data"; }
      else if (this.poll && age < 8) { cls += " warn"; txt = "polling every 2 s"; }
      else { cls += " off"; txt = "offline"; }
      el.innerHTML = `<span class="${cls}"></span><b>${txt}</b>`;
    }
  }

  document.addEventListener("click", (e) => {
    const t = e.target.closest && e.target.closest("[data-href]");
    if (t && !e.target.closest("a")) location.href = t.dataset.href;
  });

  window.ACE = { SITE, speed, speedUnit, fmtSpeed, $, $$, esc, fmtMs, fmtRun, fmtSec, fmtGap, fmtDelta, fmtClock, fmtDate, ago, colorOf, initials, enc,
    getJSON, header, Live, fillHeader, secText };
})();
