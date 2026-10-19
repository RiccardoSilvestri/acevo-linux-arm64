(function () {
  "use strict";
  const { $, esc, fmtMs, fmtDate, ago, colorOf, enc, getJSON, secText } = ACE;
  ACE.header("");
  const live = new ACE.Live();
  const name = decodeURIComponent(location.pathname.replace(/^\/driver\//, ""));
  $("#name").textContent = name;
  document.title = ACE.SITE.name + " — " + name;

  async function load() {
    let d;
    try { d = await getJSON("/api/driver?name=" + enc(name)); } catch (e) { $("#sub").textContent = "Driver not found."; return; }
    $("#sub").innerHTML = d.cars.map((c) => `<span class="chip">${esc(c)}</span>`).join(" ");
    $("#name").style.color = colorOf(d.name);
    const stat = (k, v, s, hint) => `<div class="stat" title="${esc(hint || "")}"><div class="k">${k}</div><div class="v">${v}${s ? ` <small>${s}</small>` : ""}</div></div>`;
    $("#stats").innerHTML = stat("Laps", d.laps) + stat("Valid", d.valid, d.valid_rate != null ? d.valid_rate + "%" : "")
      + stat("Invalidated", d.invalid)
      + stat("Consistency", d.consistency_ms != null ? "±" + (d.consistency_ms / 1000).toFixed(2) : "–", d.consistency_ms != null ? "s" : "",
        "Standard deviation of the recent clean laps (within 7% of the best)")
      + stat("Track-limit laps", d.cut_laps != null ? d.cut_laps : d.cuts, "", "Laps where the game reported at least one track-limit violation");
    $("#records").innerHTML = d.records.length ? `<table><thead><tr><th>Track / car</th><th class="r">Lap time</th><th class="c">Pos.</th><th class="r hide-sm">Date</th></tr></thead><tbody>${d.records.map((r) => `<tr class="click" data-href="/records?track=${enc(r.track)}">
      <td><div class="n">${esc(r.track)}</div><div class="s muted">${esc(r.car)}</div></td><td class="r num ${r.pos === 1 ? "best-purple" : ""}">${fmtMs(r.time_ms)}</td>
      <td class="c num">${r.pos}<span class="muted">/${r.of}</span></td><td class="r muted hide-sm">${esc(fmtDate(r.date))}</td></tr>`).join("")}</tbody></table>` : '<div class="empty">No records yet.</div>';
    const rec = d.recent;
    const okLaps = rec.filter((l) => l.valid);
    const bestMs = okLaps.length ? Math.min(...okLaps.map((l) => l.ms)) : null;
    const chrono = rec.slice().reverse();
    const lo = bestMs || (chrono.length ? Math.min(...chrono.map((l) => l.ms)) : 1), hi = lo * 1.12;
    $("#bars").innerHTML = chrono.map((l) => {
      const h = Math.max(8, Math.min(100, 100 - ((l.ms - lo) / (hi - lo)) * 85));
      return `<i class="${l.valid ? "" : "bad"}" style="height:${l.valid ? h : 30}%" title="${fmtMs(l.ms)}${l.valid ? "" : " (invalidated)"} · ${esc(l.track || "")}"></i>`;
    }).join("");
    const anySec = rec.some((l) => (l.splits || []).length > 1);
    $("#recent").innerHTML = rec.length ? `<table class="${anySec ? "" : "no-sec"}"><thead><tr><th>When</th><th class="r">Lap time</th><th class="hide-sm sec-col">Sectors</th><th class="c">Result</th></tr></thead><tbody>${rec.map((l) => `<tr>
      <td class="muted">${ago(l.ts)}<div class="small">${esc(l.track || "")} · ${esc(l.car || "")}</div></td>
      <td class="r num ${l.valid ? (l.ms === bestMs ? "best-purple" : "") : "bad"}">${fmtMs(l.ms)}</td>
      <td class="num sec hide-sm sec-col">${secText(l.splits) || '<span class="muted">–</span>'}</td>
      <td class="c">${l.valid ? '<span class="tag ok">VALID</span>' : '<span class="tag inv">INVALIDATED</span>'}</td></tr>`).join("")}</tbody></table>` : '<div class="empty">No recent laps.</div>';
  }
  load();
  live.on("lap", (l) => { if (l.driver.toLowerCase() === name.toLowerCase()) setTimeout(load, 700); });
})();
