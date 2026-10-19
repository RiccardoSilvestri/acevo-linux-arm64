(function () {
  "use strict";
  const { esc } = ACE;

  const PHASE = {
    Waiting_For_Players: ["Waiting for drivers", "wait"],
    Waiting_For_Start: ["Waiting for the start", "wait"],
    Start_Spawn_On_Position: ["Cars on the grid", "grid"],
    Start_Countdown_No_Lights: ["Get ready", "grid"],
    Start_Countdown_Lights_On: ["Lights on", "lights"],
    Start_Countdown_Lights_Off: ["Lights out — go!", "go"],
    RollingStart_Start_Formation: ["Formation lap", "formation"],
    RollingStart_Change_Line: ["Formation lap — change lines", "formation"],
    RollingStart_Start_Green_Flag: ["Green flag", "green"],
    RollingStart_End_Green_Flag: ["Green flag", "green"],
    Session: ["Green flag", "green"],
    Waiting_Last_Lap: ["Time is up — last lap", "white"],
    Overtime_Waiting_For_Leader: ["Last lap for the leader", "white"],
    Overtime_Waiting_For_Others: ["Chequered flag", "chequer"],
    Waiting_For_Ai: ["Chequered flag", "chequer"],
    Waiting_For_PitBox: ["Session over — back to the pits", "chequer"],
    Ended: ["Session over", "chequer"],
    Request_Quit: ["Session over", "chequer"],
  };
  const SEMA = { Green: "green", Red: "red", Yellow: "yellow" };
  const FLAG_DSQ = 8, FLAG_OUT = 16, FLAG_DNF = 32;
  const PEN = { Drive_Through: "DT", Stop_And_Go: "SG", Time_Penalty_Seconds: "+T", Disqualification: "DSQ",
    Warning: "WARN", Reprimand: "REP", InvalidLap: "INV LAP", InvalidNextLap: "INV NEXT", Remove_Best_Laptime: "NO BEST",
    MP_TeleportToPit: "TO PIT", Penalty_Laps: "+LAP", Start_From_Pitlane: "PIT START", Drop_Of_Grid_Position: "GRID",
    Drop_Of_Place_In_Classification: "-POS", Fine: "FINE" };
  const human = (s) => String(s || "").replace(/_/g, " ").toLowerCase().replace(/^\w/, (c) => c.toUpperCase());

  function clock(sec) {
    sec = Math.max(0, Math.floor(sec));
    const h = Math.floor(sec / 3600), m = Math.floor((sec % 3600) / 60), s = sec % 60;
    return (h ? h + ":" + String(m).padStart(2, "0") : m) + ":" + String(s).padStart(2, "0");
  }

  function flagIcon(kind) {
    if (kind === "lights" || kind === "go" || kind === "grid") {
      const on = kind === "lights";
      return `<span class="lights ${kind}">${"<i></i>".repeat(5)}</span>`.replace(/<i>/g, on ? '<i class="on">' : "<i>");
    }
    return `<span class="flagicon ${kind}"></span>`;
  }

  function schedule(status, race) {
    const w = (status && status.weekend) || {};
    if (!status || status.mode !== "RACE_WEEKEND") return "";
    const items = [];
    if (w.practice_min) items.push(["Practice", w.practice_min + "′"]);
    if (w.qualify_min) items.push(["Qualifying", w.qualify_min + "′"]);
    if (w.race_laps) items.push(["Race", w.race_laps + " laps"]);
    else if (w.race_min) items.push(["Race", w.race_min + "′"]);
    const cur = race && race.session;
    return `<div class="sb-sched">${items.map(([n, d]) => `<span class="${n === cur ? "on" : ""}">${n} <b>${d}</b></span>`).join('<i class="sep">›</i>')}</div>`;
  }

  class SessionBar {
    constructor(el, live) {
      this.el = el; this.live = live; this.key = "";
      setInterval(() => this.tick(), 500);
    }
    yellowCars() {
      return [...this.live.cars.values()].filter((c) => c.sl);
    }
    render() {
      const r = this.live.race, s = this.live.status;
      if (!r || !r.session) {
        this.el.innerHTML = s && s.mode ? `<div class="sb-in"><span class="sb-sess">${esc(human(s.mode))}</span><span class="sb-phase muted">Session state not received yet</span>${schedule(s, r)}</div>` : "";
        this.key = ""; return;
      }
      let [txt, kind] = PHASE[r.phase] || [human(r.phase), "wait"];
      const slow = kind === "green" ? this.yellowCars() : [];
      if (slow.length) {
        const who = slow.map((c) => (this.names && this.names(c.i)) || "a car").join(", ");
        const where = slow[0].pr != null ? ` at ${Math.round(slow[0].pr * 100)}% of the lap` : "";
        txt = `Yellow flag — slow car: ${who}${where}`;
        kind = "yellow";
      }
      const rows = ((s && s.timing) || {}).rows || [];
      const fast = rows.filter((x) => x.best_ms).sort((x, y) => x.best_ms - y.best_ms)[0];
      const key = [r.session, r.phase, kind, txt, r.pit_semaphore, s && s.mode, fast && fast.best_ms, fast && fast.name].join("|");
      if (key !== this.key) {
        this.key = key;
        const sema = r.pit_semaphore && SEMA[r.pit_semaphore]
          ? `<span class="sb-sema" title="Pit exit light"><i class="${SEMA[r.pit_semaphore]}"></i>Pit exit</span>` : "";
        this.el.innerHTML = `<div class="sb-in ${kind}">
          <span class="sb-sess ${r.session === "Race" ? "race" : r.session === "Qualifying" ? "quali" : ""}">${esc(r.session)}</span>
          ${flagIcon(kind)}<span class="sb-phase">${esc(txt)}</span>
          <span class="sb-time num" id="sb-time"></span>${sema}
          ${fast ? `<span class="sb-fast" title="Fastest lap of the session">⏱ <b class="num">${ACE.fmtMs(fast.best_ms)}</b> ${esc(fast.name)}</span>` : ""}${schedule(s, r)}</div>`;
      }
      this.tick();
    }
    tick() {
      const el = this.el.querySelector("#sb-time"), r = this.live.race;
      if (!el || !r) return;
      const s = this.live.status || {}, w = s.weekend || {};
      if (r.session === "Race" && w.race_laps && (r.phase === "Session" || /Overtime/.test(r.phase || ""))) {
        const lead = (r.cars || []).find((c) => c.pos === 1);
        const lap = lead && lead.laps != null ? Math.min(w.race_laps, lead.laps + 1) : null;
        el.textContent = lap ? `Lap ${lap} / ${w.race_laps}` : `${w.race_laps} laps`;
        return;
      }
      el.textContent = r.phase_end ? clock(r.phase_end - this.live.serverNow()) + " left" : "";
    }
  }

  function badges(rc) {
    if (!rc) return "";
    const out = [];
    const f = rc.flags || 0;
    if (f & FLAG_DSQ) out.push('<span class="tag inv">DSQ</span>');
    else if (f & FLAG_DNF) out.push('<span class="tag box">DNF</span>');
    (rc.pen || []).forEach((p) => out.push(`<span class="tag pen" title="${esc(human(p.type))}${p.why ? " — " + esc(human(p.why)) : ""}${p.time_ms ? " (" + p.time_ms / 1000 + " s)" : ""}">${esc(PEN[p.type] || "PEN")}${p.type === "Time_Penalty_Seconds" && p.time_ms ? (p.time_ms / 1000) + "s" : ""}</span>`));
    if ((rc.inv || []).length) out.push(`<span class="tag invest" title="Under investigation: ${esc(rc.inv.map(human).join(", "))}">INV</span>`);
    if (rc.pits) out.push(`<span class="tag pits" title="Pit stops">PIT ${rc.pits}</span>`);
    if (f & FLAG_OUT) out.push('<span class="tag out" title="Out lap">OUT</span>');
    return out.length ? " " + out.join(" ") : "";
  }

  function raceGaps(race) {
    const m = new Map();
    if (!race || race.sort !== "Race") return m;
    const cars = (race.cars || []).filter((c) => c.pos != null).sort((a, b) => a.pos - b.pos);
    let cum = 0;
    const lead = cars[0];
    cars.forEach((c, i) => {
      if (i === 0) { m.set(c.cid, { pos: 1, gap: "Leader", int: "" }); return; }
      const ahead = cars[i - 1];
      const lapsDown = lead && lead.laps != null && c.laps != null ? lead.laps - c.laps : 0;
      if (c.ahead_ms != null && c.ahead_ms >= 0) cum += c.ahead_ms;
      const gms = c.gap_ms != null ? c.gap_ms : c.ahead_ms != null ? cum : null;
      const ims = c.int_ms != null ? c.int_ms : c.ahead_ms;
      const gap = lapsDown >= 1 ? `+${lapsDown} lap${lapsDown > 1 ? "s" : ""}` : gms != null && gms >= 0 ? "+" + (gms / 1000).toFixed(1) : "–";
      const int = ahead && ims != null && ims >= 0 ? "+" + (ims / 1000).toFixed(1) : "";
      m.set(c.cid, { pos: c.pos, gap, int });
    });
    return m;
  }

  function phaseText(phase) { return (PHASE[phase] || [human(phase)])[0]; }

  const phaseKind = (phase) => (PHASE[phase] || [null, "wait"])[1];

  window.ACESession = { SessionBar, badges, raceGaps, phaseText, phaseKind, PEN, human };
})();
