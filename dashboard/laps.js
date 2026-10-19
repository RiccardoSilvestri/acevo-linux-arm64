(function () {
  "use strict";
  const { $, $$, esc, fmtMs, fmtClock, colorOf, enc, getJSON, secText } = ACE;
  ACE.header("laps");
  const live = new ACE.Live();
  let laps = [], filter = "all", q = "";
  const seen = new Set();

  function render(newId) {
    const f = laps.filter((l) => (filter === "all" || (filter === "valid") === l.valid)
      && (!q || (l.driver + " " + l.car + " " + (l.track || "")).toLowerCase().includes(q)));
    $("#empty").classList.toggle("hide", f.length > 0);
    $("#lapstable").classList.toggle("no-sec", !f.some((l) => (l.splits || []).length > 1));
    $("#rows").innerHTML = f.slice(0, 300).map((l) => `<tr class="click ${l.id === newId ? (l.valid ? "flash" : "flash-bad") : ""}" data-href="/driver/${enc(l.driver)}">
      <td class="muted num" title="${new Date(l.ts * 1000).toLocaleString(ACE.SITE.locale)}">${fmtClock(l.ts)}</td>
      <td><div class="who"><span class="swatch" style="background:${colorOf(l.driver)};height:22px"></span><span class="n">${esc(l.driver)}</span></div></td>
      <td class="muted">${esc(l.car)}</td><td class="muted hide-sm">${esc(l.track || "")}</td>
      <td class="r num ${l.valid ? "" : "bad"}">${fmtMs(l.ms)}</td>
      <td class="num sec hide-sm sec-col">${secText(l.splits) || '<span class="muted">–</span>'}</td>
      <td class="c">${l.valid ? (l.pb ? '<span class="tag pb">RECORD</span>' : '<span class="tag ok">VALID</span>') : '<span class="tag inv">INVALIDATED</span>'}</td>
      <td class="c num hide-sm">${l.cuts || 0}</td></tr>`).join("");
  }
  async function init() {
    try { laps = (await getJSON("/api/laps?limit=300")).laps; laps.forEach((l) => seen.add(l.id)); } catch (e) {}
    render();
  }
  $$(".pill[data-f]").forEach((p) => p.addEventListener("click", () => {
    $$(".pill[data-f]").forEach((x) => x.classList.remove("on")); p.classList.add("on"); filter = p.dataset.f; render();
  }));
  $("#q").addEventListener("input", (e) => { q = e.target.value.toLowerCase(); render(); });
  live.on("lap", (l) => { if (seen.has(l.id)) return; seen.add(l.id); laps.unshift(l); render(l.id); });
  init();
})();
