(function () {
  "use strict";
  const { $, esc, fmtMs, fmtSec, fmtGap, fmtDate, colorOf, enc, getJSON } = ACE;
  ACE.header("records");
  new ACE.Live();
  const car = decodeURIComponent(location.pathname.replace(/^\/car\//, ""));
  const track = new URLSearchParams(location.search).get("track") || "";
  $("#name").textContent = car;
  document.title = ACE.SITE.name + " — " + car;
  (async () => {
    const d = await getJSON("/api/leaderboard" + (track ? "?track=" + enc(track) : ""));
    $("#sub").textContent = d.track;
    const c = d.cars.find((x) => x.car === car);
    if (!c) { $("#rows").innerHTML = '<tr><td class="empty" colspan="8">No lap times for this car on this track.</td></tr>'; return; }
    const lead = c.entries[0].time_ms;
    $("#cartable").classList.toggle("no-sec", (d.sectors || 0) < 2);
    const best = [0, 1, 2].map((i) => Math.min(...c.entries.map((e) => (e.splits && e.splits[i]) || Infinity)));
    $("#rows").innerHTML = c.entries.map((e, i) => `<tr class="click" data-href="/driver/${enc(e.driver)}"><td class="pos num ${i < 3 ? "p" + (i + 1) : ""}">${i + 1}</td>
      <td><div class="who"><span class="swatch" style="background:${colorOf(e.driver)}"></span><span class="n">${esc(e.driver)}</span></div></td>
      <td class="r num ${i === 0 ? "best-purple" : ""}">${fmtMs(e.time_ms)}</td><td class="r num muted hide-sm">${i ? fmtGap(e.time_ms - lead) : "—"}</td>
      ${[0, 1, 2].map((k) => `<td class="c num sec hide-sm sec-col ${e.splits && best[k] === e.splits[k] ? "p" : ""}">${e.splits && e.splits[k] != null ? fmtSec(e.splits[k]) : "–"}</td>`).join("")}
      <td class="r muted hide-sm">${esc(fmtDate(e.date))}</td></tr>`).join("");
  })();
})();
