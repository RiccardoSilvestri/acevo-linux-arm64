(function () {
  "use strict";
  const { $, $$, esc, fmtMs, fmtSec, fmtGap, fmtDate, colorOf, enc, getJSON } = ACE;
  ACE.header("records");
  const live = new ACE.Live();
  let track = new URLSearchParams(location.search).get("track") || "";
  const open = new Set();

  async function load() {
    const d = await getJSON("/api/leaderboard" + (track ? "?track=" + enc(track) : ""));
    track = d.track;
    const showSec = (d.sectors || 0) > 1;
    $("#tracks").innerHTML = d.tracks.map((t) => `<span class="pill ${t === d.track ? "on" : ""}" data-t="${esc(t)}">${esc(t)}${t === d.current_track ? ' <i class="live-dot" title="current track"></i>' : ""}</span>`).join("")
      || '<span class="muted">No lap times recorded yet.</span>';
    $$("#tracks .pill").forEach((p) => p.addEventListener("click", () => { track = p.dataset.t; history.replaceState(null, "", "?track=" + enc(track)); load(); }));
    const o = d.overall;
    $("#stats").innerHTML = [
      ["Track record", o ? fmtMs(o.time_ms) : "–", o ? esc(o.driver) + " · " + esc(o.car) : ""],
      ["Drivers", d.stats.drivers_count, ""], ["Cars", d.stats.cars_count, ""], ["Times saved", d.stats.laps_saved, ""],
    ].map(([k, v, s]) => `<div class="stat"><div class="k">${k}</div><div class="v">${v}</div><div class="muted small">${s}</div></div>`).join("");

    const all = d.cars.flatMap((c) => c.entries);
    const best = [0, 1, 2].map((i) => Math.min(...all.map((e) => (e.splits && e.splits[i]) || Infinity)));
    const secs = (e) => !showSec ? "" : [0, 1, 2].map((i) => {
      const v = e.splits && e.splits[i];
      return `<td class="c num sec hide-sm ${v != null && best[i] === v ? "p" : ""}">${v != null ? fmtSec(v) : "–"}</td>`;
    }).join("");

    $("#cars").innerHTML = d.cars.length ? d.cars.map((c) => {
      const isOpen = open.has(c.car), lead = c.entries[0].time_ms;
      return `<div class="carblock ${isOpen ? "open" : ""}"><div class="fi click" data-c="${esc(c.car)}">
        <span class="swatch" style="background:${colorOf(c.record.driver)};height:30px"></span>
        <div class="tx"><b>${esc(c.car)}</b><small>${esc(c.record.driver)} · ${c.drivers} ${c.drivers === 1 ? "driver" : "drivers"}</small></div>
        <span class="num best-purple">${fmtMs(c.record.time_ms)}</span><span class="muted chev">${isOpen ? "▴" : "▾"}</span></div>
        ${isOpen ? `<table><tbody>${c.entries.map((e, i) => `<tr class="click" data-href="/driver/${enc(e.driver)}"><td class="pos num">${i + 1}</td><td>${esc(e.driver)}</td>
          <td class="r num">${fmtMs(e.time_ms)}</td><td class="r num muted">${i ? fmtGap(e.time_ms - lead) : "—"}</td>${secs(e)}<td class="r muted hide-sm">${esc(fmtDate(e.date))}</td></tr>`).join("")}</tbody></table>
          <div class="morelink"><a class="muted" href="/car/${enc(c.car)}?track=${enc(d.track)}">Open car leaderboard →</a></div>` : ""}</div>`;
    }).join("") : '<div class="empty">No lap times on this track.</div>';
    $$("#cars [data-c]").forEach((r) => r.addEventListener("click", () => { open.has(r.dataset.c) ? open.delete(r.dataset.c) : open.add(r.dataset.c); load(); }));

    const lead = d.top10.length ? d.top10[0].time_ms : 0;
    $("#top").innerHTML = d.top10.length ? `<table><tbody>${d.top10.map((e, i) => `<tr class="click" data-href="/driver/${enc(e.driver)}"><td class="pos num ${i < 3 ? "p" + (i + 1) : ""}">${i + 1}</td>
      <td><div class="who"><span class="swatch" style="background:${colorOf(e.driver)}"></span><div><div class="n">${esc(e.driver)}</div><div class="s">${esc(e.car)}</div></div></div></td>
      <td class="r num ${i === 0 ? "best-purple" : ""}">${fmtMs(e.time_ms)}</td><td class="r num muted hide-sm">${i ? fmtGap(e.time_ms - lead) : "—"}</td>${secs(e)}</tr>`).join("")}</tbody></table>` : '<div class="empty">—</div>';
    $("#hist").innerHTML = d.record_history.length ? d.record_history.map((h) => `<div class="fi"><span class="tm wide">${esc(fmtDate(h.date))}</span><span class="ic" style="background:var(--purple)"></span>
      <div class="tx"><b>${esc(h.driver)}</b> <span class="num">${fmtMs(h.time_ms)}</span><small>${esc(h.car)}</small></div></div>`).join("") : '<div class="empty">No record has been broken yet.</div>';
  }
  load();
  live.on("lap", (l) => { if (l.valid) setTimeout(load, 600); });
})();
