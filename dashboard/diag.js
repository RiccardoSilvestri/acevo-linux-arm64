(function () {
  "use strict";
  const { esc, fmtRun, fmtDelta, colorOf, ago, speed, speedUnit, fmtSpeed, SITE } = ACE;

  const LOC = { Track: "On track", Pitlane: "Pit lane", Pitentry: "Pit entry", Pitexit: "Pit exit", Unassigned: "—" };
  const PIT = { None: "—", Steady: "In box", Entering: "Entering pits", Inside: "In pit lane", Pitting: "Pit stop", OutOfTolerance: "Leaving box" };
  const ELEC = [
    ["tc_level", "TC"], ["tc_cut_level", "TC cut"], ["abs_level", "ABS"], ["esc_level", "ESC"],
    ["ebb_level", "Engine brake"], ["brake_bias", "Brake bias", (v) => (v * 100).toFixed(1) + "%"],
    ["engine_map_level", "Engine map"], ["diff_power_level", "Diff power"], ["diff_coast_level", "Diff coast"],
    ["turbo_level", "Turbo", (v) => (+v).toFixed(2)], ["ers_deployment_map", "ERS deploy"],
    ["ers_recharge_map", "ERS recharge", (v) => (+v).toFixed(2)], ["active_performance_mode", "Perf. mode"],
  ];
  const FLAGS = [["is_ignition_on", "Ignition"], ["is_pitlimiter_on", "Pit limiter"], ["is_drs_open", "DRS"],
    ["is_ers_overtake_mode_on", "ERS overtake"], ["is_ers_heat_charging_on", "ERS heat"]];
  const DAMPERS = [["front_bump_damper_level", "Front bump"], ["front_rebound_damper_level", "Front rebound"],
    ["rear_bump_damper_level", "Rear bump"], ["rear_rebound_damper_level", "Rear rebound"]];
  const ASSISTS = [["auto_gear", "Auto gear"], ["auto_clutch", "Auto clutch"], ["auto_blip", "Auto blip"],
    ["auto_pit_limiter", "Auto pit limiter"], ["standing_start_assist", "Start assist"],
    ["arcade_stability_control", "Stability aid"], ["auto_steer", "Steering aid"], ["damage_rate", "Damage rate"]];
  const CORNERS = ["FL", "FR", "RL", "RR"];

  const pct = (v, max) => Math.max(0, Math.min(100, (v / max) * 100));
  const heat = (p) => `hsl(${Math.round(140 - Math.min(100, p) * 1.4)} 75% 52%)`;

  function param(label, value, cls) {
    return `<div class="param ${cls || ""}"><span>${esc(label)}</span><b>${value}</b></div>`;
  }
  const empty = (txt) => `<div class="tile-empty">${esc(txt)}</div>`;

  function carSvg(d) {
    const dmg = d.damage || {}, ty = d.tyres || null;
    const z = (k) => { const p = pct(dmg[k] || 0, 100); return p > 0.5 ? `fill="${heat(p)}" fill-opacity="${0.25 + p / 140}"` : 'fill="#1c2434"'; };
    const tyre = (i, x, y) => {
      const w = ty ? ty.wear[i] : null;
      const fill = w == null ? "#2a3347" : heat(pct(w, 100));
      const hurt = ty && ty.damage[i] > 0;
      return `<rect x="${x}" y="${y}" width="16" height="30" rx="4" fill="${fill}" stroke="${hurt ? "#ff4d5e" : "#0b0f17"}" stroke-width="${hurt ? 3 : 2}"/>`;
    };
    return `<svg viewBox="0 0 120 200" class="carsvg" aria-label="car diagram">
      <rect x="22" y="14" width="76" height="172" rx="26" fill="#141b29" stroke="#2c3750" stroke-width="2"/>
      <path d="M30 40 Q60 6 90 40 L90 52 L30 52 Z" ${z("front")}/>
      <path d="M30 150 L90 150 L90 160 Q60 194 30 160 Z" ${z("rear")}/>
      <rect x="25" y="56" width="12" height="90" rx="5" ${z("left")}/>
      <rect x="83" y="56" width="12" height="90" rx="5" ${z("right")}/>
      <rect x="42" y="64" width="36" height="74" rx="10" ${z("center")}/>
      <rect x="48" y="76" width="24" height="22" rx="5" fill="#0d121c" stroke="#2c3750"/>
      ${tyre(0, 4, 34)}${tyre(1, 100, 34)}${tyre(2, 4, 136)}${tyre(3, 100, 136)}
      <text x="60" y="10" text-anchor="middle" class="svgt">FRONT</text>
    </svg>`;
  }

  function damageLevel(d) {
    const zones = Object.values(d.damage || {});
    const body = zones.length ? Math.max(...zones) : 0;
    const tyre = d.tyres ? d.tyres.damage.some((v) => v > 0) : false;
    if (!d.damage && !d.tyres) return null;
    if (body >= 40 || tyre) return { k: "heavy", label: "Heavy damage" };
    if (body >= 3) return { k: "light", label: "Light damage" };
    return { k: "none", label: "No damage" };
  }
  function levelBadge(d) {
    const l = damageLevel(d);
    return l ? `<span class="dmg-badge ${l.k}">${l.label}</span>` : "";
  }

  function tyreCard(t, i) {
    const w = t.wear[i], dirt = t.dirt[i], wet = t.wet[i], dm = t.damage[i];
    const chips = [];
    if (dm) chips.push('<span class="cs bad" title="The game reports damage on this tyre / corner">damaged</span>');
    if (dirt) chips.push(`<span class="cs dirt" title="Dirt picked up off track">dirty ${Math.round(pct(dirt, 255))}%</span>`);
    if (wet) chips.push(`<span class="cs wet">wet ${Math.round(pct(wet, 255))}%</span>`);
    if (!chips.length) chips.push('<span class="cs ok">clean</span>');
    return `<div class="tcard t${i} ${dm ? "hurt" : ""}">
      <div class="tc-h"><b>${CORNERS[i]}</b><span class="num" title="Tread wear index reported by the game (rises lap after lap, resets with new tyres)">wear ${w}</span></div>
      <i class="tbar"><em style="width:${Math.max(3, pct(w, 100))}%;background:${heat(pct(w, 100))}"></em></i>
      <div class="tc-chips">${chips.join("")}</div></div>`;
  }
  function tyresBlock(d) {
    const t = d.tyres;
    if (!t) return `<div class="tgrid"><div class="tcar">${carSvg(d)}</div></div>${empty("No tyre data yet")}`;
    return `<div class="tgrid">${tyreCard(t, 0)}<div class="tcar">${carSvg(d)}</div>${tyreCard(t, 1)}${tyreCard(t, 2)}${tyreCard(t, 3)}</div>
      <div class="note">Bodywork colours show damage per zone. Suspension and engine damage are simulated on the driver's PC and are not sent to the server.</div>`;
  }

  function tyresTable(t) {
    if (!t) return empty("No tyre data yet");
    const row = (lbl, arr, fmt, hint) => `<tr><th title="${esc(hint || "")}">${lbl}</th>${arr.map((v) => `<td class="num">${fmt(v)}</td>`).join("")}</tr>`;
    return `<table class="mini"><thead><tr><th></th>${CORNERS.map((c) => `<th>${c}</th>`).join("")}</tr></thead><tbody>
      ${row("Wear", t.wear, (v) => `<span class="wear"><b>${v}</b><i style="width:${Math.max(4, pct(v, 100))}%;background:${heat(pct(v, 100))}"></i></span>`, "Tread wear index reported by the game (rises lap after lap, resets with new tyres)")}
      ${row("Dirt", t.dirt, (v) => (v ? Math.round(pct(v, 255)) + "%" : "–"), "Dirt on the tyre (rises when leaving the track)")}
      ${row("Wet", t.wet, (v) => (v ? Math.round(pct(v, 255)) + "%" : "–"), "Tyre wetness")}
      ${row("Damage", t.damage, (v) => (v ? v : "–"), "Tyre damage index")}
    </tbody></table>`;
  }

  function bodyPanel(d) {
    const dm = d.damage;
    const zones = ["front", "rear", "left", "right", "center"];
    const bars = dm ? zones.map((k) => {
      const p = pct(dm[k] || 0, 100);
      return `<div class="bar"><span>${k[0].toUpperCase() + k.slice(1)}</span><i><em style="width:${p}%;background:${heat(p)}"></em></i><b class="num">${p < 0.5 ? "OK" : Math.round(p) + "%"}</b></div>`;
    }).join("") : empty("No damage data yet");
    const bd = d.body_dirt;
    const dirt = bd ? Math.round(pct(Math.max(...bd), 255)) : null;
    const c = d.contacts || {};
    const contacts = c.total
      ? `<div class="note">Contacts: ${c.lap} this lap · ${c.total} total${c.last_kmh ? ` · last ${fmtSpeed(c.last_kmh)} vs ${c.last_with === "car" ? "car" : "barrier"}${c.last_ts ? " (" + ago(c.last_ts) + ")" : ""}` : ""}</div>`
      : `<div class="note">No contacts with barriers or cars (floor scrapes are ignored)</div>`;
    return `${bars}${dirt != null ? `<div class="bar"><span>Body dirt</span><i><em style="width:${dirt}%;background:#a07a4a"></em></i><b class="num">${dirt}%</b></div>` : ""}${contacts}`;
  }

  function electronics(e) {
    if (!e) return empty("Electronics not reported yet");
    const val = (k, f) => (typeof e[k] === "number" && e[k] < 0 && k !== "brake_bias") ? '<span class="muted">n/a</span>' : esc(f ? f(e[k]) : e[k]);
    const out = ELEC.filter(([k]) => e[k] != null).map(([k, l, f]) => param(l, val(k, f)));
    const flags = FLAGS.filter(([k]) => k in e).map(([k, l]) => `<span class="flag ${e[k] ? "on" : ""}">${l}</span>`);
    return `<div class="params">${out.join("")}</div>${flags.length ? `<div class="flags">${flags.join("")}</div>` : ""}`;
  }

  function dampers(e) {
    if (!e || !DAMPERS.some(([k]) => e[k] != null)) return empty("Damper settings not reported");
    const max = Math.max(10, ...DAMPERS.map(([k]) => e[k] || 0));
    return DAMPERS.filter(([k]) => e[k] != null).map(([k, l]) =>
      e[k] < 0 ? `<div class="bar"><span>${l}</span><i></i><b class="muted">n/a</b></div>`
        : `<div class="bar"><span>${l}</span><i><em style="width:${pct(e[k], max)}%;background:var(--blue)"></em></i><b class="num">${e[k]}</b></div>`).join("");
  }

  function pitSession(d) {
    const p = d.pit || {}, rows = [];
    if (d.loc) rows.push(param("Location", LOC[d.loc] || esc(d.loc)));
    if (p.step) rows.push(param("Pit state", PIT[p.step] || esc(p.step)));
    if (p.slot != null) rows.push(param("Pit box", "#" + p.slot));
    if (p.time_ms) rows.push(param("Pit stop time", (p.time_ms / 1000).toFixed(0) + " s"));
    rows.push(param("Returns to pits", d.resets || 0));
    if (d.bop) {
      if (d.bop.ballast) rows.push(param("Ballast", d.bop.ballast + " kg"));
      if (d.bop.restrictor) rows.push(param("Restrictor", Math.round(d.bop.restrictor * 100) + "%"));
    }
    const plan = d.plan;
    let planHtml = "";
    if (plan && Object.keys(plan).length) {
      const items = [];
      if (plan.change_front_tyres || plan.change_rear_tyres) items.push("tyres " + [plan.change_front_tyres && "front", plan.change_rear_tyres && "rear"].filter(Boolean).join(" + "));
      if (plan.fuel_to_add) items.push(`+${Math.round(plan.fuel_to_add)} L fuel`);
      if (plan.repair_body) items.push("bodywork"); if (plan.repair_suspensions) items.push("suspension"); if (plan.repair_engine) items.push("engine");
      if (plan.predicted_pit_time) items.push(`≈${Math.round(plan.predicted_pit_time)} s`);
      if (items.length) planHtml = `<div class="note">Pit plan: ${esc(items.join(" · "))}</div>`;
    }
    const a = d.assists;
    let assist = "";
    if (a && Object.keys(a).length) {
      const on = ASSISTS.filter(([k]) => a[k]).map(([, l]) => l);
      assist = `<div class="note">Assists: ${on.length ? esc(on.join(", ")) : "none"}</div>`;
    }
    return `<div class="params">${rows.join("")}</div>${planHtml}${assist}`;
  }

  const gearName = (g) => (g == null ? "–" : g === 0 ? "R" : g === 1 ? "N" : String(g - 1));
  const rpmTop = new Map();

  class DiagPanel {
    constructor(el) { this.el = el; this.cid = null; this.sig = ""; }
    render(cid, meta, diag, car) {
      this.cid = cid;
      if (!cid) {
        this.el.innerHTML = `<div class="tile-empty big">No car on track.<br><span>Telemetry and diagnostics appear here as soon as a driver joins.</span></div>`;
        this.sig = ""; return;
      }
      const d = diag || {};
      const sig = cid + JSON.stringify(d);
      if (sig !== this.sig) {
        this.sig = sig;
        this.el.innerHTML = `
        <div class="diag-grid">
          <section class="tile live-tile">
            <h3>Live</h3>
            <div class="dash">
              <div class="gear"><b id="dg-gear">–</b><small>gear</small></div>
              <div><div class="speed"><b id="dg-speed" class="num">–</b><small>${speedUnit}</small></div>
                <div class="rpm"><b id="dg-rpm" class="num">–</b> rpm</div></div>
            </div>
            <div class="rpmbar"><i id="dg-rpmbar"></i></div>
            <div class="pedals">
              <div class="ped"><span>Throttle</span><i><em id="dg-thr" class="thr"></em></i></div>
              <div class="ped"><span>Brake</span><i><em id="dg-brk" class="brk"></em></i></div>
              <div class="ped"><span>Steering</span><i class="steer"><em id="dg-steer"></em></i></div>
            </div>
            <div class="params">
              ${param("Current lap", '<span id="dg-lap" class="num">–</span>')}
              ${param("Delta to reference", '<span id="dg-delta" class="num delta">–</span>')}
              ${param("Lap", '<span id="dg-lapno">–</span>')}
              ${param("Altitude", '<span id="dg-alt" class="num">–</span>')}
            </div>
            <div class="prog"><i id="dg-prog"></i><span id="dg-progt">Lap progress</span></div>
            <div id="dg-valid" class="valid-line"></div>
          </section>
          <section class="tile"><h3>Electronics</h3>${electronics(d.elec)}</section>
          <section class="tile tyres-tile"><h3>Tyres &amp; bodywork ${levelBadge(d)}</h3>${tyresBlock(d)}</section>
          <section class="tile"><h3>Damage ${levelBadge(d)}</h3>${bodyPanel(d)}</section>
          <section class="tile"><h3>Suspension</h3>${dampers(d.elec)}</section>
          <section class="tile"><h3>Pit &amp; session</h3>${pitSession(d)}</section>
        </div>`;
      }
      this.live(car);
    }
    live(c) {
      const q = (id) => this.el.querySelector("#" + id);
      const sp = q("dg-speed"); if (!sp) return;
      sp.textContent = c ? speed(c.v) : "–";
      const t = c && c.tl;
      q("dg-gear").textContent = t ? gearName(t[0]) : "–";
      q("dg-rpm").textContent = t ? t[1].toLocaleString(SITE.locale) : "–";
      let top = 0;
      if (t) { top = Math.max(rpmTop.get(this.cid) || 6000, t[1]); rpmTop.set(this.cid, top); }
      const rf = t ? Math.min(1, t[1] / top) : 0;
      const rb = q("dg-rpmbar"); rb.style.width = rf * 100 + "%"; rb.className = rf > 0.95 ? "hot" : rf > 0.85 ? "warm" : "";
      q("dg-thr").style.width = (t ? (t[2] / 255) * 100 : 0) + "%";
      q("dg-brk").style.width = (t ? (t[3] / 255) * 100 : 0) + "%";
      const st = q("dg-steer"), s = t ? Math.max(-1, Math.min(1, t[4] / 127)) : 0;
      st.style.left = (s < 0 ? 50 + s * 50 : 50) + "%"; st.style.width = Math.abs(s) * 50 + "%";
      q("dg-lap").textContent = c && c.el != null ? fmtRun(c.el) : "–";
      const dl = q("dg-delta");
      dl.textContent = c && c.dl != null ? fmtDelta(c.dl) : "–";
      dl.className = "num delta " + (c && c.dl != null ? (c.dl <= 0 ? "neg" : "pos") : "");
      q("dg-lapno").textContent = c && c.l ? c.l : "–";
      q("dg-alt").textContent = c && c.y != null ? Math.round(c.y) + " m" : "–";
      const p = c && c.pr != null ? c.pr * 100 : null;
      q("dg-prog").style.width = (p || 0) + "%";
      q("dg-progt").textContent = p != null ? `${p.toFixed(1)}% of the lap` : (c && c.pl ? "In the pit lane" : "Lap progress");
      const v = q("dg-valid");
      if (!c) { v.textContent = ""; v.className = "valid-line"; }
      else if (c.ok === false) { v.textContent = c.w === "cut" ? "Lap invalidated — track limits" : "Lap not valid"; v.className = "valid-line bad"; }
      else { v.textContent = "Lap valid so far"; v.className = "valid-line ok"; }
    }
  }

  function elevation(el, trace, cars, metaFor) {
    const pts = (trace && trace.pts) || [];
    if (pts.length < 30 || pts[0].length < 3 || pts[0][2] == null) {
      el.innerHTML = `<div class="tile-empty">The elevation profile is recorded with the next valid lap.</div>`;
      return;
    }
    if (el._trace !== trace) {
      el._trace = trace;
      let dist = 0; const xy = [[0, pts[0][2]]];
      for (let i = 1; i < pts.length; i++) {
        dist += Math.hypot(pts[i][0] - pts[i - 1][0], pts[i][1] - pts[i - 1][1]);
        xy.push([dist, pts[i][2]]);
      }
      const ys = xy.map((p) => p[1]), lo = Math.min(...ys), hi = Math.max(...ys);
      let climb = 0; for (let i = 1; i < ys.length; i++) if (ys[i] > ys[i - 1]) climb += ys[i] - ys[i - 1];
      const W = 600, H = 120, pad = 4, span = Math.max(5, hi - lo);
      const X = (d) => pad + (d / dist) * (W - 2 * pad), Y = (y) => H - pad - ((y - lo) / span) * (H - 2 * pad - 10);
      const line = xy.map((p, i) => (i ? "L" : "M") + X(p[0]).toFixed(1) + " " + Y(p[1]).toFixed(1)).join(" ");
      el._geo = { X, Y, xy, dist };
      el.innerHTML = `<svg viewBox="0 0 ${W} ${H}" preserveAspectRatio="none" class="elev">
          <defs><linearGradient id="eg" x1="0" x2="0" y1="0" y2="1"><stop offset="0" stop-color="#4da3ff" stop-opacity=".45"/><stop offset="1" stop-color="#4da3ff" stop-opacity="0"/></linearGradient></defs>
          <path d="${line} L${X(dist)} ${H} L${X(0)} ${H} Z" fill="url(#eg)"/>
          <path d="${line}" fill="none" stroke="#4da3ff" stroke-width="1.6"/>
          <g class="elev-cars"></g></svg>
        <div class="elev-stats"><span>Min <b>${Math.round(lo)} m</b></span><span>Max <b>${Math.round(hi)} m</b></span>
          <span>Height difference <b>${Math.round(hi - lo)} m</b></span><span>Total climb <b>${Math.round(climb)} m</b></span>
          <span>Recorded length <b>${(dist / 1000).toFixed(2)} km</b></span></div>`;
    }
    const g = el.querySelector(".elev-cars"), geo = el._geo;
    if (!g) return;
    g.innerHTML = (cars || []).filter((c) => c.pr != null).map((c) => {
      const d = c.pr * geo.dist;
      let k = 0; while (k < geo.xy.length - 1 && geo.xy[k][0] < d) k++;
      const m = metaFor(c.i) || {};
      return `<circle cx="${geo.X(d).toFixed(1)}" cy="${geo.Y(geo.xy[k][1]).toFixed(1)}" r="4.5" fill="${m.color || "#fff"}" stroke="#0a0e15" stroke-width="1.5"/>`;
    }).join("");
  }

  window.ACEDiag = { DiagPanel, elevation, LOC, damageLevel, gearName };
})();
