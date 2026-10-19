(function () {
  "use strict";
  const { $, $$, esc, fmtMs, fmtRun, fmtSec, fmtGap, fmtDelta, fmtClock, fmtSpeed, colorOf, enc, getJSON, secText } = ACE;
  ACE.header("live");
  const live = new ACE.Live();
  const sessbar = new ACESession.SessionBar($("#sessbar"), live);
  sessbar.names = (cid) => { const d = driverByCid(cid); return d ? d.name : null; };
  const raceCar = (cid) => (live.race && cid ? (live.race.cars || []).find((c) => c.cid === cid) : null);

  let status = null, timing = { rows: [], sector_best: [], sector_best_by: [], sectors: 3 };
  let selected = null;
  let trackKey = null, trace = null;
  const feed = [], feedKeys = new Set();

  function driverByCid(cid) {
    const d = ((status && status.drivers) || []).find((x) => x.cid === cid);
    if (d) return { name: d.name, car: d.car };
    const r = (timing.rows || []).find((x) => x.cid === cid);
    return r ? { name: r.name, car: r.car } : null;
  }
  const metaFor = (cid) => {
    const d = driverByCid(cid), c = live.cars.get(cid);
    const name = d ? d.name : null;
    const rc = live.race && live.race.sort === "Race" ? raceCar(cid) : null;
    const base = name ? name.split(" ")[0].slice(0, 14) : (c && c.n != null ? "#" + c.n : "");
    return { name, car: d && d.car, color: colorOf(name || cid), label: rc && rc.pos ? `P${rc.pos} ${base}` : base };
  };
  const onTrack = () => [...live.cars.keys()];

  const map = new TrackMap($("#map"), {});
  map.meta = metaFor;
  const tip = $("#tip");
  map.onSelect = (cid) => select(cid);
  map.onHover = (cid, x, y) => {
    const c = cid && live.cars.get(cid);
    if (!c) { tip.classList.add("hide"); return; }
    const m = metaFor(cid);
    tip.innerHTML = `<b style="color:${m.color}">${esc(m.name || "Driver")}</b><span class="muted">${esc(m.car || "")}</span><br>
      <span class="num">${fmtSpeed(c.v)}</span>${c.el != null ? ` · <span class="num">${fmtRun(c.el)}</span>` : ""}${c.dl != null ? ` <span class="num delta ${c.dl <= 0 ? "neg" : "pos"}">${fmtDelta(c.dl)}</span>` : ""}<br>
      ${c.ok === false ? `<span style="color:var(--red)">${c.w === "cut" ? "lap invalidated (track limits)" : "lap not valid"}</span>` : '<span style="color:var(--green)">lap valid so far</span>'}${c.pl ? " · pit lane" : ""}`;
    tip.style.left = x + "px"; tip.style.top = y + "px"; tip.classList.remove("hide");
  };
  $$(".tg[data-opt]").forEach((b) => b.addEventListener("click", () => {
    const o = b.dataset.opt; map.opts[o] = !map.opts[o]; b.classList.toggle("on", map.opts[o]);
  }));
  $("#resetmap").addEventListener("click", () => map.reset());
  const tower = new ACETower($("#f1tower"), live, {
    selected: () => selected,
    onSelect: (cid, name) => { if (cid && live.cars.has(cid)) select(cid); else if (name) location.href = "/driver/" + enc(name); },
  });

  async function loadTrace() {
    if (!status) return;
    try { trace = await getJSON("/api/map?track=" + enc(trackKey)); map.setTrace(trace); } catch (e) { trace = null; }
    cockpit.setTrace(trace);
    renderTrack(); mapMsg();
  }
  function mapMsg() {
    const el = $("#mapmsg"), tag = $("#lwtag");
    let t = "";
    if (!live.lw) { t = "The network observer is offline.<br>The live map is temporarily unavailable."; tag.textContent = "OFFLINE"; tag.className = "tag inv"; }
    else {
      const n = live.cars.size;
      tag.textContent = n ? `${n} on track` : "waiting"; tag.className = "tag " + (n ? "ok" : "box");
      if (!n && !map.hasTrace()) t = "Waiting for drivers…";
      else if (!map.hasTrace()) t = "The track outline draws itself<br>after the first valid lap.";
    }
    el.innerHTML = t;
  }

  function secCell(r, i) {
    const v = r.best_splits && r.best_splits[i];
    if (v == null) return '<td class="c hide-sm sec-col sec muted">–</td>';
    return `<td class="c hide-sm sec-col num sec ${timing.sector_best[i] === v ? "p" : ""}">${fmtSec(v)}</td>`;
  }
  function stateTag(cs, r) {
    const dl = cs && live.diag.get(cs.i) ? ACEDiag.damageLevel(live.diag.get(cs.i)) : null;
    const dmg = dl && dl.k === "heavy" ? ' <span class="tag inv">DAMAGED</span>' : "";
    return baseTag(cs, r) + dmg + ACESession.badges(raceCar(cs ? cs.i : r.cid));
  }
  function baseTag(cs, r) {
    if (cs) {
      if (cs.ok === false) return cs.w === "cut" ? '<span class="tag cut">TRACK LIMITS</span>' : '<span class="tag inv">INVALID</span>';
      if (cs.pl || cs.loc === "Pitlane") return '<span class="tag box">PIT</span>';
      return '<span class="tag ontrack">ON TRACK</span>';
    }
    return r.status === "track" ? '<span class="tag ontrack">ON TRACK</span>' : '<span class="tag box">PIT</span>';
  }
  function liveCell(cs) {
    if (!cs || cs.el == null) return '<td class="r num muted" data-lv="">–</td>';
    return `<td class="r num livecell" data-lv="${esc(cs.i)}">${liveHtml(cs)}</td>`;
  }
  const inPit = (cs) => cs.pl || cs.loc === "Pitlane" || (cs.v < 3 && cs.p && cs.p !== "None" && cs.p !== "OutOfTolerance");
  const liveHtml = (cs) => inPit(cs) ? '<span class="muted">In pit</span>'
    : `${fmtRun(cs.el)}${cs.dl != null ? `<small class="delta ${cs.dl <= 0 ? "neg" : "pos"}">${fmtDelta(cs.dl)}</small>` : ""}`;

  function renderTower() {
    const body = $("#tbody");
    const rows = (timing.rows || []).slice();
    const names = new Set(rows.map((r) => r.name));
    ((status && status.drivers) || []).forEach((d) => {
      if (!names.has(d.name)) rows.push({ name: d.name, car: d.car, cid: d.cid, laps: 0, valid: 0, best_ms: null, status: d.status });
    });
    $("#towerEmpty").classList.toggle("hide", rows.length > 0);
    $("#tower").classList.toggle("no-sec", (timing.sectors || 3) < 2);
    const overall = Math.min(...rows.map((r) => r.best_ms || Infinity));
    const gaps = ACESession.raceGaps(live.race), raceMode = gaps.size > 0;
    if (raceMode) rows.sort((a, b) => ((gaps.get(a.cid) || {}).pos || 999) - ((gaps.get(b.cid) || {}).pos || 999));
    let html = "", pos = 0;
    for (const r of rows) {
      const hasBest = r.best_ms != null;
      if (hasBest) pos++;
      const rg = raceMode ? gaps.get(r.cid) : null;
      const shownPos = raceMode ? (rg ? rg.pos : null) : (hasBest ? pos : null);
      const lastCls = r.last_ok === false ? "bad" : (r.last_ms != null && r.last_ms === r.best_ms ? "best-green" : "");
      const cs = r.cid ? live.cars.get(r.cid) : null;
      html += `<tr class="click ${selected && r.cid === selected ? "sel" : ""}" data-cid="${esc(r.cid || "")}" data-name="${esc(r.name)}">
        <td class="pos num ${shownPos && shownPos <= 3 ? "p" + shownPos : ""}">${shownPos || "–"}</td>
        <td><div class="who"><span class="swatch" style="background:${colorOf(r.name)}"></span><div style="min-width:0">
          <div class="n">${esc(r.name)} ${stateTag(cs, r)}</div><div class="s">${esc(r.car || "")}</div>
          ${r.cid ? `<div class="spd num" data-sp="${esc(r.cid)}">${spdText(cs)}</div>` : ""}</div></div></td>
        <td class="r num ${hasBest && r.best_ms === overall ? "best-purple" : ""}">${hasBest ? fmtMs(r.best_ms) : "–"}</td>
        <td class="r num ${lastCls}">${r.last_ms != null ? fmtMs(r.last_ms) : "–"}</td>
        <td class="r num muted col-gap">${raceMode ? (rg ? rg.gap + (rg.int ? `<small class="int">${rg.int}</small>` : "") : "–") : (hasBest ? fmtGap(r.gap_ms) : "–")}</td>
        ${secCell(r, 0)}${secCell(r, 1)}${secCell(r, 2)}
        <td class="c num">${r.valid || 0}<span class="muted">/${r.laps || 0}</span></td>
        ${liveCell(cs)}</tr>`;
    }
    body.innerHTML = html;
    $$("tr.click", body).forEach((tr) => tr.addEventListener("click", () => {
      const cid = tr.dataset.cid;
      if (!cid || !live.cars.has(cid) || selected === cid) { location.href = "/driver/" + enc(tr.dataset.name); return; }
      select(cid);
    }));
  }
  let fastT = 0;
  const spdText = (c) => (c ? fmtSpeed(c.v) + (c.tl ? " · " + ACEDiag.gearName(c.tl[0]) : "") : "");
  function fastUpdate() {
    const now = performance.now(); if (now - fastT < 250) return; fastT = now;
    $$("#tbody [data-sp]").forEach((el) => { const c = live.cars.get(el.dataset.sp); el.textContent = spdText(c); el.classList.toggle("still", !c || c.v < 5); });
    $$("#tbody [data-lv]").forEach((td) => { const c = live.cars.get(td.dataset.lv); if (c && c.el != null) td.innerHTML = liveHtml(c); });
  }

  const panel = new ACEDiag.DiagPanel($("#diag"));
  const cockpit = new ACECockpit($("#cockpit"));
  function select(cid) {
    selected = cid || null; map.select(selected);
    renderTower(); renderDiag(true); tower.render();
  }
  function renderDiag() {
    const ids = onTrack();
    if (selected && !ids.includes(selected)) selected = null;
    if (!selected && ids.length) { selected = ids[0]; map.select(selected); }
    const m = selected ? metaFor(selected) : null;
    $("#dgwho").innerHTML = m ? `<span class="swatch dot-s" style="background:${m.color}"></span>${esc(m.name || "Driver")} <span class="muted">· ${esc(m.car || "")}</span>` : "";
    $("#dgpick").innerHTML = ids.length > 1 ? ids.map((cid) => { const mm = metaFor(cid); return `<span class="pill sm ${cid === selected ? "on" : ""}" data-cid="${esc(cid)}">${esc(mm.label || cid)}</span>`; }).join("") : "";
    $$("#dgpick .pill").forEach((p) => p.addEventListener("click", () => select(p.dataset.cid)));
    panel.render(selected, m, selected ? live.diag.get(selected) : null, selected ? live.cars.get(selected) : null);
    cockpit.select(selected);
  }

  function renderTrack() {
    if (!status) return;
    const km = status.track_length ? (status.track_length / 1000).toFixed(3) + " km" : "–";
    const sec = timing.sectors > 1 ? timing.sectors : 1;
    const rec = status.overall;
    $("#trackinfo").innerHTML = `<div class="params">
      <div class="param"><span>Circuit</span><b>${esc([status.track, status.layout].filter(Boolean).join(" "))}</b></div>
      <div class="param"><span>Length</span><b class="num">${km}</b></div>
      <div class="param"><span>Timed sectors</span><b>${sec}</b></div>
      <div class="param"><span>Mode</span><b>${esc(modeName(status.mode))}</b></div>
      <div class="param"><span>Weather</span><b>${esc(cap(status.weather))}</b></div>
      <div class="param"><span>Session</span><b>${status.session_duration_min ? status.session_duration_min + " min" : "–"}</b></div>
      <div class="param"><span>Track record</span><b class="num best-purple">${rec ? fmtMs(rec.time_ms) : "–"}</b></div>
      <div class="param"><span>Reference lap</span><b class="num">${trace && trace.ms ? fmtMs(trace.ms) : "–"}</b></div>
    </div>`;
    ACEDiag.elevation($("#elev"), trace, [...live.cars.values()], metaFor);
  }
  const cap = (s) => (s ? s.charAt(0) + s.slice(1).toLowerCase().replace(/_/g, " ") : "–");
  const modeName = (m) => ({ HOTLAP: "Hotlap", PRACTICE: "Practice", RACE: "Race", QUALIFY: "Qualifying" }[m] || cap(m));

  function renderRecent() {
    const ls = live.laps.filter((l) => !trackKey || l.track === trackKey).slice(-8).reverse();
    $("#recentlaps").innerHTML = ls.length ? ls.map((l) => `<div class="lapmini click" data-href="/driver/${enc(l.driver)}">
      <span class="swatch" style="background:${colorOf(l.driver)};height:30px"></span>
      <div class="nm">${esc(l.driver)}<div class="secs">${esc(l.car)}${secText(l.splits) ? " · " + secText(l.splits) : ""}</div></div>
      <span class="num ${l.valid ? "" : "bad"}">${fmtMs(l.ms)}</span>
      ${l.valid ? (l.pb ? '<span class="tag pb">PB</span>' : '<span class="tag ok">VALID</span>') : '<span class="tag inv">INVALID</span>'}</div>`).join("")
      : '<div class="empty">Completed laps on this track appear here.</div>';
  }

  function pushFeed(key, ts, cls, html, isNew) {
    if (feedKeys.has(key)) return;
    feedKeys.add(key);
    feed.push({ ts, cls, html, isNew });
    feed.sort((a, b) => b.ts - a.ts);
    if (feed.length > 80) feed.length = 80;
    renderFeed();
  }
  function renderFeed() {
    $("#feed").innerHTML = feed.map((f) => `<div class="fi ${f.cls} ${f.isNew ? "new" : ""}"><span class="tm">${fmtClock(f.ts)}</span><span class="ic"></span><div class="tx">${f.html}</div></div>`).join("")
      || '<div class="empty">Waiting for activity…</div>';
    feed.forEach((f) => (f.isNew = false));
  }
  function lapItem(l, isNew) {
    if (trackKey && l.track && l.track !== trackKey) return;
    const ok = l.valid;
    const why = !ok ? (l.cuts ? `${l.cuts} track-limit warning${l.cuts > 1 ? "s" : ""}` : "lap not valid") : "";
    const parts = [secText(l.splits), why].filter(Boolean);
    pushFeed("lap" + l.id, l.ts, ok ? (l.pb ? "pb" : "lap") : "lap_invalid",
      `<b>${esc(l.driver)}</b> — <span class="num ${ok ? "" : "bad"}">${fmtMs(l.ms)}</span> ${ok ? (l.pb ? '<span class="tag pb">PERSONAL BEST</span>' : "") : '<span class="tag inv">INVALIDATED</span>'}${parts.length ? `<small>${parts.join(" · ")}</small>` : ""}`, isNew);
  }
  function incItem(i, isNew) {
    if (trackKey && i.track && i.track !== trackKey) return;
    if (i.k === "rc") {
      rcLive.unshift({ ts: i.ts, kind: i.kind === "penalty" ? "penalty" : "investigation", msg: (i.name ? i.name + " — " : "") + i.text });
      if (rcLive.length > 30) rcLive.length = 30;
      if (status) renderRC(status);
      pushFeed("rc" + i.ts + i.cid + i.text, i.ts, "penalty", `<b>Race control</b> ${esc(i.text)}${i.name ? `<small>${esc(i.name)}</small>` : ""}`, isNew);
      return;
    }
    if (i.k === "pit_in" || i.k === "pit_out" || i.k === "penalty") {
      const H = ACESession.human;
      const t = i.k === "pit_in" ? "entered the pit box"
        : i.k === "pit_out" ? `left the pits${[i.tyres ? i.tyres + " tyres" : "", i.fuel ? "fuel" : ""].filter(Boolean).length ? " (" + [i.tyres ? i.tyres + " tyres" : "", i.fuel ? "fuel" : ""].filter(Boolean).join(", ") + ")" : ""}`
        : `penalty: ${esc(H(i.pen))}${i.pen_ms ? " " + i.pen_ms / 1000 + " s" : ""}${i.why ? " — " + esc(H(i.why)) : ""}`;
      pushFeed("inc" + i.ts + i.cid + i.k, i.ts, i.k, `<b>${esc(i.name)}</b> ${t}${i.lap ? `<small>lap ${i.lap}</small>` : ""}`, isNew);
      return;
    }
    const txt = i.k === "cut" ? "exceeded track limits" : i.k === "reset" ? `returned to the pits${i.repair ? " (car repaired)" : ""}` : `impact at ${i.v ? fmtSpeed(i.v) : "?"}`;
    pushFeed("inc" + i.ts + i.cid + i.k, i.ts, i.k, `<b>${esc(i.name)}</b> ${txt}${i.lap ? `<small>lap ${i.lap}</small>` : ""}`, isNew);
  }
  function statusFeed(s) {
    (s.events || []).forEach((e) => {
      if (e.kind === "join" || e.kind === "leave" || e.kind === "session")
        pushFeed("ev" + e.ts + e.msg, e.ts, e.kind, esc(e.msg) + (e.extra ? `<small>${esc(e.extra)}</small>` : ""), false);
    });
  }

  const rcLive = [];
  function renderRC(s) {
    const rc = rcLive.concat(s.race_control || []).sort((a, b) => (b.ts || 0) - (a.ts || 0)).slice(0, 25);
    $("#rc").innerHTML = rc.length ? rc.map((r) => `<div class="rc ${r.kind}"><span class="tm num muted">${fmtClock(r.ts)}</span><span>${esc(r.msg)}</span></div>`).join("")
      : '<div class="empty">No messages from race control.</div>';
  }
  function renderTop(s) {
    const t = s.top10 || [];
    $("#top10").innerHTML = t.length ? `<table><tbody>${t.map((e, i) => `<tr class="click" data-href="/driver/${enc(e.driver)}"><td class="pos num ${i < 3 ? "p" + (i + 1) : ""}">${i + 1}</td>
      <td><div class="who"><span class="swatch" style="background:${colorOf(e.driver)}"></span><div><div class="n">${esc(e.driver)}</div><div class="s">${esc(e.car)}</div></div></div></td>
      <td class="r num ${i === 0 ? "best-purple" : ""}">${fmtMs(e.time_ms)}</td></tr>`).join("")}</tbody></table>`
      : '<div class="empty">No lap times on this track yet.</div>';
  }

  live.on("hello", (m) => {
    (m.laps || []).slice(-40).forEach((l) => lapItem(l, false));
    (m.inc || []).slice(-40).forEach((i) => incItem(i, false));
    (m.inc || []).filter((i) => i.k === "cut" && (!i.track || i.track === trackKey)).forEach((i) => map.addIncident(i));
    renderRecent(); renderDiag(); mapMsg(); sessbar.render();
  });
  live.on("status", (s) => {
    sessbar.render();
    status = s; timing = s.timing || timing;
    renderTower(); renderRC(s); renderTop(s); statusFeed(s);
    $("#sessinfo").textContent = [modeName(s.mode), cap(s.weather), s.session_duration_min ? s.session_duration_min + " min" : ""].filter(Boolean).join(" · ");
    const key = [s.track, s.layout].filter(Boolean).join(" ");
    if (key !== trackKey) { trackKey = key; loadTrace(); renderRecent(); } else renderTrack();
    renderDiag(); mapMsg();
  });
  let elevT = 0;
  live.on("cars", (list) => {
    map.setCars(list); fastUpdate(); mapMsg();
    const anySlow = list.some((c) => c.sl);
    if (anySlow !== live._slow) { live._slow = anySlow; sessbar.render(); }
    if (selected) panel.live(live.cars.get(selected));
    cockpit.live(selected ? live.cars.get(selected) : null);
    const ids = onTrack().join();
    if (ids !== renderDiag._ids) { renderDiag._ids = ids; renderDiag(); renderTower(); }
    const now = performance.now();
    if (now - elevT > 500) { elevT = now; ACEDiag.elevation($("#elev"), trace, list, metaFor); }
  });
  live.on("diag", (m) => { if (m.cid === selected) renderDiag(); renderTower(); });
  live.on("lw", () => mapMsg());
  live.on("yellow", (m) => {
    sessbar.render();
    if (m.on) pushFeed("yl" + m.ts + m.cid, m.ts, "penalty", `<b>Yellow flag</b> — ${esc(m.name)} slow on track${m.pr != null ? `<small>${Math.round(m.pr * 100)}% of the lap</small>` : ""}`, true);
  });
  let lastPhase = null;
  live.on("race", (r) => {
    sessbar.render(); renderTower();
    if (!r || !r.phase) return;
    const k = r.session + "|" + r.phase;
    if (lastPhase && k !== lastPhase && !/Waiting_For_(Players|Start|Ai)|Request_Quit/.test(r.phase))
      pushFeed("ph" + k + Math.round(live.serverNow() / 30), live.serverNow(), "session", `<b>${esc(r.session)}</b> — ${esc(ACESession.phaseText(r.phase))}`, true);
    lastPhase = k;
  });
  live.on("lap", (l) => { lapItem(l, true); renderTower(); renderRecent(); });
  live.on("inc", (i) => { incItem(i, true); if (i.k === "cut" && (!i.track || i.track === trackKey)) map.addIncident(i); });
  live.on("trace", () => loadTrace());
  setInterval(renderFeed, 30000);
})();
