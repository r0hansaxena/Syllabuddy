/* Syllabuddy frontend: vanilla JS, no build step. */

const VIEWS = ["home", "plan", "quests", "oracle", "setup"];
const S = { agent: [], agentBusy: false, data: null, view: VIEWS.includes(location.hash.slice(1)) ? location.hash.slice(1) : "home", chat: [], busy: false };
const $ = (sel) => document.querySelector(sel);
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

// ---------- pixel sprites ----------
const SPR = {
  boy: [
    "....############....",
    "...##############...",
    "..################..",
    "..##.#.##.##.#.###..",
    "..#..............#..",
    "..#..............#..",
    "..#...##....##...#..",
    "..#...##....##...#..",
    "##................##",
    "##.......##.......##",
    "..#..............#..",
    "..#....######....#..",
    "...#............#...",
    "....#..........#....",
    ".....##########.....",
    ".......#....#.......",
    ".......#....#.......",
    "....####....####....",
    "..##..#......#..##..",
    ".#....#......#....#.",
  ],
  girl: [
    "......########......",
    "....############....",
    "...##############...",
    "..################..",
    "..####.######.####..",
    "..##............##..",
    "..##............##..",
    "..#...##....##...#..",
    "..#...##....##...#..",
    "..#..............#..",
    "..#......##......#..",
    "..#..............#..",
    "..##...######...##..",
    "..###..........###..",
    "..####........####..",
    "..#####.####.#####..",
    "..####..#..#..####..",
    "..###...#..#...###..",
    ".###..##....##..###.",
    "#....#........#....#",
  ],
  other: [
    "......########......",
    "....############....",
    "...##############...",
    "..################..",
    "..#####..####.####..",
    "..###..........###..",
    "..##............##..",
    "..#.#####..#####.#..",
    "..#.#...####...#.#..",
    "..#.#.#.#..#.#.#.#..",
    "..#..###....###..#..",
    "...#............#...",
    "...#.....##.....#...",
    "....#..........#....",
    ".....#..####..#.....",
    "......#......#......",
    ".......######.......",
    "....####....####....",
    "..##..#......#..##..",
    ".#....#......#....#.",
  ],
  heart: [".##.##.", "#######", "#######", ".#####.", "..###..", "...#..."],
  star: ["...#...", "..###..", "#######", ".#####.", "..###..", ".##.##.", "##...##"],
  home: ["...##...", "..####..", ".######.", "########", ".#....#.", ".#.##.#.", ".#.##.#.", ".######."],
  cal: [".#....#.", "########", "#......#", "#.#.#.##", "#......#", "#.#.#.##", "#......#", "########"],
  flag: ["#######.", "########", "#######.", "#.......", "#.......", "#.......", "#......."],
  eye: ["..#####..", ".#.....#.", "#..###..#", "#..###..#", ".#.....#.", "..#####.."],
  gear: ["..#..#..", ".######.", "##....##", ".#.##.#.", ".#.##.#.", "##....##", ".######.", "..#..#.."],
};
function sprite(name) {
  const rows = SPR[name];
  let r = "";
  rows.forEach((row, y) => [...row].forEach((c, x) => { if (c === "#") r += `<rect x="${x}" y="${y}" width="1.02" height="1.02"/>`; }));
  return `<svg class="spr" viewBox="0 0 ${rows[0].length} ${rows.length}" aria-hidden="true">${r}</svg>`;
}

// ---------- api ----------
async function api(path, opts = {}) {
  if (opts.json) { opts.body = JSON.stringify(opts.json); opts.headers = { "Content-Type": "application/json" }; }
  const res = await fetch(path, opts);
  const body = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(body.detail || res.statusText);
  return body;
}
async function refresh() { S.data = await api("/api/state"); render(); }

// ---------- helpers ----------
const pad = (n) => String(n).padStart(2, "0");
const D = (s) => new Date(s);
const hhmm = (s) => s.slice(11, 16);
const isoDay = (d) => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
const today = () => isoDay(new Date());
const dayLabel = (d) => d.toLocaleDateString("en-GB", { weekday: "short", day: "2-digit", month: "short" }).toUpperCase();
const mins = (s) => Math.round((D(s.end) - D(s.start)) / 60000);
const dueLabel = (g) => `${dayLabel(D(g.deadline + "T00:00"))}${g.due_time ? " " + g.due_time : ""}`;
const daysLeft = (g) => Math.round((D(g.deadline + "T00:00") - D(today() + "T00:00")) / 86400000);
const topic = (id) => S.data.goals.flatMap((g) => g.topics).find((t) => t.id === id) || { name: "?", summary: "", sources: [] };
const goal = (id) => S.data.goals.find((g) => g.id === id);
const srcLabel = (s) => `${esc(s.filename)}${s.heading ? " › " + esc(s.heading) : ""}${s.page ? " · p." + s.page : ""}`;

// Progress = share of the goal's study hours covered: ticked topics count fully,
// unticked ones count the learning sessions finished on them so far.
function goalStats(g) {
  const doneSessions = S.data.sessions.filter((s) => s.goal_id === g.id && s.done);
  let total = 0, covered = 0;
  for (const t of g.topics) {
    const est = t.est_hours * 60;
    const learned = doneSessions.filter((s) => s.topic_id === t.id && s.kind === "learn").reduce((a, s) => a + mins(s), 0);
    total += est;
    covered += t.done ? est : Math.min(est, learned);
  }
  const topicsDone = g.topics.filter((t) => t.done).length;
  return { progress: total ? Math.round((100 * covered) / total) : 0, topicsDone, topics: g.topics.length };
}

// ---------- shell ----------
const APPS = [["home", "home", "Today"], ["plan", "cal", "Plan"], ["quests", "flag", "Quests"], ["oracle", "eye", "Atlas"], ["setup", "gear", "Setup"]];

function renderSoundBtn() {
  const b = $("#sound-btn");
  b.textContent = sfx.muted ? "🔇" : "🔊";
  b.title = sfx.muted ? "Sound off: click to turn on" : "Sound on: click to mute";
}

function render() {
  renderSoundBtn();
  $("#nav").innerHTML = APPS.map(([id, icon, label]) =>
    `<button class="px" data-go="${id}" ${S.view === id ? 'aria-current="page"' : ""}>${sprite(icon)}<span>${label}</span></button>`).join("");
  const chip = $("#llm-chip");
  chip.className = "chip px " + (S.data.ai ? "on" : "off");
  chip.lastElementChild.textContent = S.data.ai ? "Atlas on" : "Offline mode";
  chip.title = !S.data.ai_ready ? "Atlas isn't connected to an AI. Set it up in Setup"
    : `Atlas uses ${S.data.ai_config.label} · ${S.data.ai_config.model}. Click to ${S.data.ai ? "switch to offline mode" : "turn Atlas on"}`;
  $("#nav").hidden = !S.data.settings.name;
  $("#view").innerHTML = !S.data.settings.name ? viewWelcome()
    : { home: viewHome, plan: viewPlan, quests: viewQuests, oracle: viewOracle, setup: viewSetup }[S.view]();
  const log = $("#chatlog");
  if (log) log.scrollTop = log.scrollHeight;
}

const avatar = () => sprite(["boy", "girl"].includes(S.data.settings.gender) ? S.data.settings.gender : "other");

// ---------- WELCOME / PROFILE ----------
function profileForm(submitLabel) {
  const s = S.data.settings;
  const pick = s.gender || "boy";
  return `<form id="profile-form">
    <div class="field"><label class="px" for="pn">Your name</label><input id="pn" type="text" name="name" maxlength="40" required value="${esc(s.name)}" placeholder="e.g. Pankaj"></div>
    <div class="field"><span class="px" style="font-size:13px">Choose your character</span>
      <div class="avatars" role="radiogroup">${[["boy", "Boy"], ["girl", "Girl"], ["other", "Other"]].map(([g, label]) => `
        <label class="avatar-pick"><input type="radio" name="gender" value="${g}" ${pick === g ? "checked" : ""}>
          <span class="portrait">${sprite(g)}<span class="name px">${label}</span></span></label>`).join("")}
      </div></div>
    <button class="btn primary">${submitLabel}</button></form>`;
}

function viewWelcome() {
  return `<div style="max-width:640px;margin:0 auto" class="col">
    <div class="dialog"><h3 class="px">Welcome to Syllabuddy!</h3>
      <p>Tell it your exams and deadlines, upload your notes, and it builds a day-by-day study plan from your own material, with spaced reviews so you remember it.</p></div>
    ${win("Create your profile", profileForm("▶ Start"))}
  </div>`;
}

const win = (title, body, tools = "") => `<section class="win"><div class="win-title px"><span>${title}</span><span class="lines"></span>${tools}</div><div class="win-body">${body}</div></section>`;

const newQuestBtn = `<button class="btn primary" data-act="new-goal">+ New quest</button>`;

function emptyToday() {
  const name = esc(S.data.settings.name);
  return `<div class="desk">
    <div class="col">${win("Player.sys", `<button class="portrait clickable" data-go="setup" title="Edit profile">${avatar()}<span class="name px">${name}</span></button>`)}</div>
    <div class="col">
      <div class="dialog"><h3 class="px">Hi ${name}!</h3><p>You don't have any quests yet. Describe your exam to the assistant, or follow the steps below.</p></div>
      ${assistantBox()}
      ${win("How it works", `<ol class="steps">
        <li><b>Create a quest</b>: what you're studying for and the deadline.</li>
        <li><b>Upload your notes</b>: PDF, Word, Markdown or text.</li>
        <li><b>Follow your plan</b>: tick sessions off each day. Reviews are spaced out so you remember.</li>
      </ol><p style="margin-top:12px">${newQuestBtn}</p>`)}
    </div></div>`;
}

function emptyPlan() {
  return `<div class="plan-head"><p class="plan-line">No study plan yet</p>${newQuestBtn}</div>
    <div class="day-grid">
      <section class="win day-card ghost"><div class="win-title px"><span>Your days</span><span class="lines"></span></div>
        <div class="win-body"><p>Once you add a quest, each day's study sessions show up here as cards, with a time, a topic and a tick box.</p>
        ${[1, 2, 3].map(() => `<div class="agenda-row"><span class="tickbox"></span><span class="ghost-line"></span></div>`).join("")}</div></section>
    </div>`;
}

function emptyQuests() {
  return `<div class="dialog light"><h3 class="px">No quests yet</h3>
    <p>A quest is one exam or deadline. Add one, upload your notes, and its topics will be listed here so you can tick them off.</p></div>`;
}

// ---------- TODAY ----------
function viewHome() {
  const d = S.data;
  if (!d.goals.length) return emptyToday();
  const t = today();
  const todays = d.sessions.filter((s) => s.start.slice(0, 10) === t);
  const nextDay = d.sessions.find((s) => !s.done && s.start.slice(0, 10) > t)?.start.slice(0, 10);
  const shown = todays.length ? todays : d.sessions.filter((s) => s.start.slice(0, 10) === nextDay);
  const label = todays.length ? "Today" : nextDay ? `Next up · ${dayLabel(D(nextDay + "T00:00"))}` : "All clear";
  const slots = shown.map((s, i) => {
    const tp = topic(s.topic_id), g = goal(s.goal_id);
    return `<button class="slot ${s.done ? "done" : ""}" data-sess="${s.id}">
      <span class="tag px">SLOT ${String.fromCharCode(65 + (i % 26))}<small>${hhmm(s.start)}</small></span>
      <span class="main"><span class="t"><span class="kind px ${s.kind}">${s.kind}</span>${esc(tp.name)}</span>
        <span class="sub">${esc(g?.title || "")} · ${mins(s)} min</span></span>
      <span class="st px" data-tick="${s.id}" data-done="${!s.done}" role="checkbox" aria-checked="${s.done}" title="${s.done ? "Mark not done" : "Mark done"}">${s.done ? "☑" : "☐"}</span></button>`;
  }).join("") || `<div class="boxed px" style="text-align:center">${d.goals.every((g) => g.topics.every((t) => t.done)) ? "-All topics done. Nice work!-" : "-No sessions scheduled-"}</div>`;

  return `${warnings()}<div class="desk">
    <div class="col">${playerSheet()}</div>
    <div class="col">
      ${assistantBox()}
      ${upNext() || recap(todays)}
      ${win(`Quest log · ${label}`, `<div class="slots">${slots}</div>`)}
      ${win("Deadlines", d.goals.map((g) => {
        const st = goalStats(g);
        return `<div class="goal-head clickable" data-go="quests" style="margin-bottom:12px"><div class="dday px">D-${daysLeft(g)}</div>
          <div style="flex:1;min-width:160px">${esc(g.title)}${g.due_time ? ` <span class="muted">· due ${daysLeft(g) === 0 ? "today" : dueLabel(g)} ${daysLeft(g) === 0 ? g.due_time : ""}</span>` : ""}
            <div class="kv"><div class="bar dith" style="grid-column:1/3"><i style="width:${st.progress}%"></i></div><span>${st.progress}%</span></div>
            <div class="muted" style="font-size:13px">${st.topicsDone}/${st.topics} topics done</div></div></div>`;
      }).join(""))}
    </div></div>`;
}

// ---------- assistant (home screen) ----------
function assistantBox() {
  const last = S.agent.slice(-2);  // only the latest exchange, to keep the page calm
  const body = !S.data.ai
    ? `<p class="muted">Atlas ${S.data.ai_ready ? "is off" : "isn't connected to an AI yet"}. ${S.data.ai_ready ? "Turn it on" : "Connect one"} in <button class="linkish" data-go="setup">Setup</button>.</p>`
    : `${last.map((m) => m.role === "user" ? `<p class="you">› ${esc(m.content)}</p>`
        : `<p>${fmt(m.content)}</p>${m.actions?.length ? `<ul class="did">${m.actions.map((a) => `<li>✓ ${esc(a)}</li>`).join("")}</ul>` : ""}`).join("")}
      ${S.agentBusy ? `<p class="loading muted">Working on it</p>` : ""}
      <form class="prompt" id="agent-form">
        <span class="caret px">&gt;</span>
        <input type="text" name="msg" required autocomplete="off" ${S.agentBusy ? "disabled" : ""}
          placeholder="Tell me what to do, e.g. “add my Maths final on 20 Nov”">
        <button class="btn primary" ${S.agentBusy ? "disabled" : ""}>Go</button>
      </form>`;
  return win("Atlas", body);
}

// The one thing to do now: the next unfinished session today.
function upNext() {
  const now = new Date();
  const s = S.data.sessions.find((x) => !x.done && x.start.slice(0, 10) === today() && D(x.end) > now);
  if (!s) return "";
  const live = D(s.start) <= now;
  return `<div class="dialog up-next"><h3 class="px">${live ? "Now" : "Up next · " + hhmm(s.start)}</h3>
    <p><span class="kind px ${s.kind}">${s.kind}</span>${esc(topic(s.topic_id).name)} · ${mins(s)} min</p>
    <p style="margin-top:10px">${F && F.id === s.id ? `<button class="btn" data-act="focus-expand">⏱ Open timer</button>` : `<button class="btn" data-focus="${s.id}">▶ Start</button>`}</p></div>`;
}

// Shown once today's sessions are over.
function recap(todays) {
  if (!todays.length) return "";
  const done = todays.filter((s) => s.done);
  const studied = done.reduce((a, s) => a + mins(s), 0);
  const first = S.data.sessions.find((s) => !s.done && s.start.slice(0, 10) > today());
  return `<div class="dialog light"><h3 class="px">Today's recap</h3>
    <p>You finished <b>${done.length} of ${todays.length}</b> sessions${studied ? ` (${dur(studied)} of study)` : ""}.
    ${done.length === todays.length ? "Great day!" : "Unfinished ones will move to your next study days."}</p>
    ${first ? `<p style="margin-top:6px">First up ${dayLabel(D(first.start)).slice(0, 3) === dayLabel(new Date(Date.now() + 864e5)).slice(0, 3) ? "tomorrow" : dayLabel(D(first.start))}: <b>${esc(topic(first.topic_id).name)}</b> at ${hhmm(first.start)}.</p>` : ""}</div>`;
}

// ---------- focus timer ----------
// The timer lives in a dock outside the page views, so switching tabs never resets it.
// It's stored as an end timestamp in localStorage, so it even survives a page refresh.
let F = null;  // {id, name, kind, total, endsAt, pausedLeft, finished}
try { F = JSON.parse(localStorage.getItem("sq-focus")); } catch {}

function saveFocus() {
  try { F ? localStorage.setItem("sq-focus", JSON.stringify(F)) : localStorage.removeItem("sq-focus"); } catch {}
}
const focusLeft = () => (F.pausedLeft != null ? F.pausedLeft : Math.max(0, Math.round((F.endsAt - Date.now()) / 1000)));
const clockText = (sec) => `${pad(Math.floor(sec / 60))}:${pad(sec % 60)}`;

function startFocus(id) {
  const s = S.data.sessions.find((x) => x.id === id);
  F = { id, name: topic(s.topic_id).name, kind: s.kind, total: mins(s) * 60, endsAt: Date.now() + mins(s) * 60000, pausedLeft: null, finished: false };
  saveFocus();
  drawFocus();
  openFocusView();
}

function stopFocus() {
  F = null;
  saveFocus();
  drawFocus();
  if ($("#focus-full")) closeModal();
}

function focusTools(small) {
  const cls = small ? "btn small" : "btn";
  if (F.finished) return `<button class="${cls} primary" data-toggle="${F.id}" data-done="true">✓ Mark done</button><button class="${cls}" data-act="focus-stop">Dismiss</button>`;
  return `<button class="${cls}" data-act="focus-pause">${F.pausedLeft != null ? "▶ Resume" : "❚❚ Pause"}</button><button class="${cls}" data-act="focus-stop">■ Stop</button>`;
}

function openFocusView() {
  modal("Focus", `<div class="focus" id="focus-full">
    <p><span class="kind px ${F.kind}">${F.kind}</span><b>${esc(F.name)}</b></p>
    <div class="clock px" id="focus-clock"></div>
    <div class="bar dith tall"><i id="focus-bar"></i></div>
    <p class="muted" id="focus-hint"></p>
    <div class="win-tools" id="focus-tools"></div></div>`);
  drawFocus();
}

// Full redraw: when the timer starts, pauses, finishes or stops.
function drawFocus() {
  const dock = $("#focus-dock");
  dock.hidden = !F;
  if (!F) { dock.innerHTML = ""; return; }
  dock.innerHTML = `<button class="dock-main" data-act="focus-expand" title="Open timer">
      <span class="px dock-label">${F.finished ? "Done!" : F.pausedLeft != null ? "Paused" : "Focus"}</span>
      <span class="dock-name">${esc(F.name)}</span><span class="dock-clock px" id="dock-clock"></span></button>
    <span class="dock-tools">${focusTools(true)}</span>`;
  if ($("#focus-full")) {
    $("#focus-tools").innerHTML = focusTools(false);
    $("#focus-hint").textContent = F.finished ? "Time's up! Nice focus." : "You can switch tabs: the timer keeps running in the bar at the bottom.";
  }
  tickFocus();
}

// Every second: only the numbers change, so buttons never flicker under the cursor.
function tickFocus() {
  if (!F) return;
  const left = focusLeft();
  if (left === 0 && !F.finished) {
    F.finished = true;
    saveFocus();
    sfx.play("fanfare");
    toast("Time's up!", `Focus on ${F.name} finished.`);
    return drawFocus();
  }
  $("#dock-clock").textContent = clockText(left);
  if ($("#focus-full")) {
    $("#focus-clock").textContent = clockText(left);
    $("#focus-bar").style.width = `${100 * (1 - left / F.total)}%`;
  }
}
setInterval(tickFocus, 1000);

function playerSheet() {
  const d = S.data;
  const done = d.sessions.filter((s) => s.done);
  const hours = (done.reduce((a, s) => a + mins(s), 0) / 60).toFixed(1);
  const left = d.sessions.filter((s) => !s.done && s.start.slice(0, 10) >= today()).length;
  return win("Player.sys", `
    <button class="portrait clickable" data-go="setup" title="Edit profile">${avatar()}<span class="name px">${esc(d.settings.name)}</span></button>
    <div class="statline">
      <button class="bigstat clickable" data-go="plan" title="See your plan">${sprite("heart")}<span><span class="n">${done.length}</span><span class="lbl px">Sessions done</span></span></button>
      <button class="bigstat right clickable" data-go="plan" title="See your plan"><span><span class="n">${hours}</span><span class="lbl px">Hours studied</span></span>${sprite("star")}</button>
    </div>
    <div class="banner px">Progress</div>
    ${d.goals.map((g) => `<button class="kv clickable" data-go="quests" title="Open quest"><span class="k px">${esc(g.title.slice(0, 10))}</span><span class="bar"><i style="width:${goalStats(g).progress}%"></i></span><span>${goalStats(g).progress}%</span></button>`).join("")}
    <div class="banner px">Remaining</div>
    <button class="boxed px clickable" data-go="plan" style="width:100%;font-size:14px">${left} sessions to go ›</button>`);
}

function warnings() {
  return S.data.settings.warnings.map((w) => `<div class="dialog light" style="margin-bottom:16px"><h3 class="px">⚠ Not enough time</h3><p>${esc(w)}</p></div>`).join("");
}

// ---------- PLAN ----------
const dur = (m) => (m >= 60 ? `${Math.floor(m / 60)}h${m % 60 ? " " + (m % 60) + "m" : ""}` : `${m}m`);

function viewPlan() {
  const d = S.data;
  if (!d.goals.length) return emptyPlan();
  const t = today();
  const upcoming = d.sessions.filter((s) => s.start.slice(0, 10) >= t);
  const left = upcoming.filter((s) => !s.done);
  const byDay = {};
  upcoming.forEach((s) => (byDay[s.start.slice(0, 10)] ||= []).push(s));
  const next = [...d.goals].filter((g) => daysLeft(g) >= 0).sort((a, b) => a.deadline.localeCompare(b.deadline))[0];

  const summary = `<p class="plan-line"><b>${left.length}</b> sessions left · <b>${dur(left.reduce((a, s) => a + mins(s), 0))}</b> of study${next ? ` · <b>${esc(next.title)}</b> in ${daysLeft(next)} day${daysLeft(next) === 1 ? "" : "s"}` : ""}</p>`;

  // Every day from today until the last quest is due, so free days and due days show too.
  const lastDue = d.goals.map((g) => g.deadline).sort().pop();
  const allDays = [];
  for (let x = t; x <= lastDue; x = nextDay(x)) allDays.push(x);

  const days = allDays.map((day) => {
    const list = byDay[day] || [];
    const dueHere = d.goals.filter((g) => g.deadline === day);
    const dueNote = dueHere.map((g) => `<p class="deadline-note px">★ Due${g.due_time ? " " + g.due_time : ""}: ${esc(g.title)}</p>`).join("");
    if (!list.length) {
      return `<section class="win day-card quiet ${day === t ? "is-today" : ""}">
        <div class="win-title px"><span>${day === t ? "Today · " : ""}${dayLabel(D(day + "T00:00"))}</span><span class="lines"></span></div>
        <div class="win-body">${dueNote || `<p class="muted">Free day: nothing scheduled.</p>`}</div></section>`;
    }
    const total = list.reduce((a, s) => a + mins(s), 0);
    const doneCount = list.filter((s) => s.done).length;
    return `<section class="win day-card ${day === t ? "is-today" : ""}">
      <div class="win-title px"><span>${day === t ? "Today · " : ""}${dayLabel(D(day + "T00:00"))}</span><span class="lines"></span>
        <span>${doneCount}/${list.length} · ${dur(total)}</span></div>
      <div class="win-body">${list.map((s) => `
        <div class="agenda-row ${s.done ? "done" : ""}">
          <button class="tickbox" data-tick="${s.id}" data-done="${!s.done}" aria-label="${s.done ? "Mark not done" : "Mark done"}">${s.done ? "✓" : ""}</button>
          <button class="agenda-main" data-sess="${s.id}">
            <span class="when">${hhmm(s.start)}–${hhmm(s.end)} · ${dur(mins(s))}${s.pinned ? " · your time" : ""}</span>
            <span class="what"><span class="kind px ${s.kind}">${s.kind}</span>${esc(topic(s.topic_id).name)}</span>
            <span class="goal muted">${esc(goal(s.goal_id)?.title || "")}</span>
          </button>
        </div>`).join("")}
        ${dueNote}
      </div></section>`;
  }).join("");

  // Topics whose study time didn't fit before the deadline.
  const unfit = d.goals.flatMap((g) => g.topics.filter((tp) => !tp.done).map((tp) => {
    const planned = d.sessions.filter((s) => s.topic_id === tp.id && s.kind === "learn").reduce((a, s) => a + mins(s), 0);
    return { tp, g, left: Math.round(tp.est_hours * 60) - planned };
  })).filter((x) => x.left >= 15);
  const unfitCard = unfit.length ? `<section class="win day-card unfit">
      <div class="win-title px"><span>Doesn't fit yet</span><span class="lines"></span><span>${dur(unfit.reduce((a, x) => a + x.left, 0))}</span></div>
      <div class="win-body"><p class="muted" style="margin-top:0">Not enough time before the deadline for these. Tick off topics you'll skip in Quests, or move the deadline.</p>
        ${unfit.map((x) => `<div class="agenda-row"><span class="what">${esc(x.tp.name)}</span><span class="muted" style="margin-left:auto;white-space:nowrap">${dur(x.left)}</span></div>`).join("")}
      </div></section>` : "";

  return `${warnings()}<div class="plan-head">${summary}
      <button class="btn small" data-act="rebuild" title="Moves missed sessions to upcoming days">⟳ Rebuild</button></div>
    <p class="muted plan-key"><span class="kind px learn">learn</span> study it from your notes · <span class="kind px review">review</span> quick recap · tick ☐ when done</p>
    <div class="day-grid">${days}${unfitCard}</div>`;
}

function nextDay(iso) {
  const x = D(iso + "T00:00");
  x.setDate(x.getDate() + 1);
  return isoDay(x);
}

// ---------- QUESTS ----------
function viewQuests() {
  const goals = S.data.goals.map((g) => win(`Quest · ${esc(g.title)}`, `
    <div class="goal-head" style="margin-bottom:10px">
      <div class="dday px">D-${daysLeft(g)}</div>
      <div style="flex:1;min-width:180px">Due ${dueLabel(g)}</div>
      <button class="btn small danger" data-delete="${g.id}">Delete quest</button>
    </div>
    <div class="banner px">Study material</div>
    ${g.documents.map((doc) => `<div class="doc"><span style="flex:1">${esc(doc.filename)}</span><span class="muted">${doc.n_chunks} chunks</span></div>`).join("")}
    <div class="banner px">Topics · ${g.topics.filter((t) => t.done).length}/${g.topics.length} done</div>
    <p class="muted" style="margin:0 0 6px;font-size:13px">Tick a topic when you've finished it. Its remaining sessions are removed from your plan.</p>
    <div class="table-scroll"><table class="topics">
      <thead><tr><th>Done</th><th>Topic</th><th>Difficulty</th><th>Est.</th></tr></thead>
      <tbody>${g.topics.map((t) => `<tr class="${t.done ? "topic-done" : ""}"><td class="n"><input type="checkbox" class="tick" data-topic="${t.id}" ${t.done ? "checked" : ""} aria-label="Mark ${esc(t.name)} done"></td>
        <td><span class="tname">${esc(t.name)}</span><div class="muted" style="font-size:13px">${esc(t.summary)}</div></td>
        <td class="n"><span class="pips">${[1, 2, 3, 4, 5].map((n) => `<i class="${n <= t.difficulty ? "on" : ""}"></i>`).join("")}</span></td>
        <td class="n">${t.est_hours}h</td></tr>`).join("")}</tbody></table></div>`)).join("");
  return `<div class="win-tools" style="margin-bottom:16px"><span class="grow"></span><button class="btn primary" data-act="new-goal">+ New quest</button></div>
    <div class="col">${goals || emptyQuests()}</div>`;
}

// ---------- ATLAS (ask your notes) ----------
function fmt(t) {
  return esc(t).replace(/\*\*(.+?)\*\*/g, "<b>$1</b>").replace(/\[(\d+)\]/g, '<span class="cite">$1</span>').replace(/\n/g, "<br>");
}
// One collapsed "Sources" box listing only the passages the answer actually cites.
function citedSources(m) {
  const cited = new Set([...(m.text || "").matchAll(/\[(\d+)\]/g)].map((x) => +x[1]));
  const list = (m.sources || []).map((s, i) => ({ ...s, n: i + 1 })).filter((s) => cited.has(s.n));
  if (!list.length) return "";
  return `<div class="sources"><details><summary class="px" style="font-size:13px">Sources (${list.length})</summary>
    ${list.map((s) => `<p style="margin:8px 0 0"><b>[${s.n}]</b> ${srcLabel(s)}<br><span class="muted">${esc(s.text)}…</span></p>`).join("")}
  </details></div>`;
}

function viewOracle() {
  const msgs = S.chat.map((m) => m.role === "user"
    ? `<div class="msg-user">${esc(m.text)}</div>`
    : `<div class="msg-bot"><div class="dialog"><h3 class="px">Atlas</h3><div class="md-body">${fmt(m.text)}</div></div>
        ${citedSources(m)}</div>`).join("");
  return win("Atlas.exe · ask your notes", `
    <div class="chatlog" id="chatlog">${msgs || `<div class="dialog light"><h3 class="px">Ask anything</h3><p>Answers come from the notes you uploaded, with numbered citations.</p></div>`}
      ${S.busy ? `<div class="msg-bot"><div class="dialog"><p class="loading">Reading your notes</p></div></div>` : ""}</div>
    <form class="prompt" id="ask-form">
      <span class="caret px">&gt;</span>
      <input type="text" name="q" placeholder="Ask Atlas…" autocomplete="off" required ${S.busy ? "disabled" : ""}>
      <select name="goal" style="width:auto"><option value="">All quests</option>${S.data.goals.map((g) => `<option value="${g.id}">${esc(g.title)}</option>`).join("")}</select>
      <button class="btn primary" ${S.busy ? "disabled" : ""}>Ask</button>
    </form>`);
}

// ---------- SETUP ----------
const THEMES = [["ink", "Navy ink"], ["peach", "Peach"], ["sage", "Sage"], ["mono", "Mono"], ["night", "Night"]];
const THEME_COLORS = {  // preview swatches: ink, paper, accent
  ink: ["#1f2a44", "#efe6d2", "#c8433a"], peach: ["#3d4257", "#f2e1d3", "#b86a5f"], sage: ["#33402f", "#e3e6d6", "#6e8659"],
  mono: ["#3c3d41", "#eceae5", "#85868c"], night: ["#d5cab4", "#1f2b31", "#b9826f"],
};

function setTheme(t) {
  document.documentElement.dataset.theme = t;
  try { localStorage.setItem("sq-theme", t); } catch {}
}

// Atlas's AI connection: status, what the scan found, and a form for any OpenAI-compatible provider.
function atlasSettings() {
  const d = S.data, c = d.ai_config;
  const cur = c.auto ? "auto" : c.provider;
  const status = d.ai_ready
    ? `<div class="dialog light ai-status"><p>● Connected to <b>${esc(c.label)}</b> · ${esc(c.model)}${c.auto ? " (found automatically)" : ""}</p></div>`
    : `<div class="dialog light ai-status"><p>○ Not connected. Log in to Claude Code or start Ollama / LM Studio and press <b>Scan</b>, or pick a provider below. Until then Atlas runs in offline mode.</p></div>`;
  const found = d.ai_detected.length ? `<div class="win-tools found"><span class="px muted">Found:</span>
    ${d.ai_detected.map((f, i) => `<button type="button" class="btn small" data-ai-pick="${i}" title="Use this">${esc(f.label)} · ${esc(f.model)}</button>`).join("")}</div>` : "";
  const models = d.ai_detected.find((f) => f.provider === cur)?.models || [];
  return win("AI mode", `
    <div class="win-tools" style="margin-bottom:10px">
      <button class="btn ${d.ai ? "primary" : ""}" data-act="ai-on" ${d.ai_ready ? "" : "disabled"}>Atlas</button>
      <button class="btn ${d.ai ? "" : "primary"}" data-act="ai-off">Offline</button>
    </div>
    <p>${d.ai ? "Atlas reads your notes to find topics, writes answers and runs quick commands."
      : "Topics come from the headings in your notes, study time is estimated from how much text each has, and Atlas shows the matching passages instead of written answers."}</p>
    ${status}${found}
    <form id="ai-form" class="ai-form">
      <div class="field"><label class="px" for="ai-p">Provider</label>
        <select id="ai-p" name="provider"><option value="auto" ${cur === "auto" ? "selected" : ""}>Auto-detect</option>
          ${d.ai_providers.map((p) => `<option value="${p.id}" ${cur === p.id ? "selected" : ""}>${esc(p.label)}</option>`).join("")}</select></div>
      <div class="manual">
        <div class="field"><label class="px" for="ai-m">Model</label>
          <input id="ai-m" type="text" name="model" list="ai-models" autocomplete="off" value="${esc(c.auto ? "" : c.model)}" placeholder="e.g. llama3.1">
          <datalist id="ai-models">${models.map((m) => `<option value="${esc(m)}">`).join("")}</datalist></div>
        <div class="field"><label class="px" for="ai-u">Server address</label>
          <input id="ai-u" type="text" name="base_url" autocomplete="off" value="${esc(c.auto ? "" : c.base_url)}" placeholder="Filled in from the provider"></div>
        <div class="field"><label class="px" for="ai-k">API key</label>
          <input id="ai-k" type="password" name="key" autocomplete="off" placeholder="${!c.auto && c.has_key ? "Saved. Leave blank to keep it" : "Not needed for Ollama or LM Studio"}"></div>
      </div>
      <div class="win-tools">
        <button class="btn primary">▶ Connect</button>
        <button class="btn small" type="button" data-act="ai-models">Models</button>
        <button class="btn small" type="button" data-act="ai-test">Test</button>
        <button class="btn small" type="button" data-act="ai-detect">Scan</button>
      </div>
    </form>
    <p class="muted" style="font-size:13px;margin-top:10px">Your Claude Code login works with no key, as does any OpenAI-compatible AI: local (Ollama, LM Studio, llama.cpp) or hosted (Gemini, OpenAI, Groq, OpenRouter, Anthropic). Keys never leave this computer.</p>`);
}

async function testAI() {
  try {
    const r = await api("/api/ai/test", { method: "POST" });
    sfx.play("done");
    toast("Atlas is connected", `${r.label} · ${r.model} replied.`);
  } catch (err) { toast("Error", err.message); }
}

function viewSetup() {
  const s = S.data.settings;
  return `<div class="desk"><div class="col">
    ${win("Profile", profileForm("Save profile"))}
    ${win("Theme", `<div class="themes">${THEMES.map(([k, label]) => `
      <button class="theme-pick px" data-theme-pick="${k}" aria-pressed="${(document.documentElement.dataset.theme || "ink") === k}">
        <span class="swatch">${THEME_COLORS[k].map((c) => `<i style="background:${c}"></i>`).join("")}</span>${label}</button>`).join("")}</div>`)}
  </div><div class="col">
    ${atlasSettings()}
    ${win("Start over", `
      <p>See the welcome screen again, or erase everything and start fresh like a new user.</p>
      <div class="win-tools">
        <button class="btn" data-act="reset-profile">↺ Back to welcome</button>
        <button class="btn danger" data-act="reset-all">✕ Erase everything</button>
      </div>`)}
  </div></div>`;
}

// ---------- modals ----------
function modal(title, body) {
  $("#modal-root").innerHTML = `<div class="overlay" data-overlay><div class="win" role="dialog" aria-modal="true" aria-label="${esc(title)}">
    <div class="win-title px"><span>${esc(title)}</span><span class="lines"></span><button class="x" data-close aria-label="Close">✕</button></div>
    <div class="win-body">${body}</div></div></div>`;
}
const closeModal = () => ($("#modal-root").innerHTML = "");

function openSession(id) {
  const s = S.data.sessions.find((x) => x.id === id);
  const t = topic(s.topic_id);
  modal("Session", `
    <p><span class="kind px ${s.kind}">${s.kind}</span><b>${esc(t.name)}</b></p>
    <p class="muted">${dayLabel(D(s.start))} · ${hhmm(s.start)}–${hhmm(s.end)} · ${esc(goal(s.goal_id)?.title)}</p>
    <p>${esc(t.summary)}</p>
    ${t.sources.length ? `<div class="banner px">From your notes</div><div class="sources">${t.sources.map((src) =>
      `<details><summary>${srcLabel(src)}</summary><div class="muted">${esc(src.snippet)}…</div></details>`).join("")}</div>` : ""}
    <p class="win-tools" style="margin-top:14px"><button class="btn primary" data-toggle="${s.id}" data-done="${!s.done}">${s.done ? "↶ Mark not done" : "✓ Mark done"}</button>
      ${s.done ? "" : `<button class="btn" data-focus="${s.id}">▶ Start focus</button>`}</p>
    ${s.done ? "" : `<div class="banner px">Change time${s.pinned ? " · set by you" : ""}</div>
    <form id="move-form" data-id="${s.id}" class="row" style="align-items:end">
      <div class="field" style="margin:0"><label class="px" for="mv-d">Day</label><input id="mv-d" type="date" name="day" required value="${s.start.slice(0, 10)}" min="${today()}" max="${goal(s.goal_id).due_time ? goal(s.goal_id).deadline : dayBefore(goal(s.goal_id).deadline)}"></div>
      <div class="field" style="margin:0"><label class="px" for="mv-t">Start time</label>${timeField("mv-t", "time", hhmm(s.start), true)}</div>
      <div style="flex:0"><button class="btn">Save time</button></div>
    </form>
    <p class="hint">It keeps its ${dur(mins(s))} length. Other sessions are planned around it when the plan rebuilds.</p>`}`);
}

function dayBefore(iso) {
  const x = D(iso + "T00:00");
  x.setDate(x.getDate() - 1);
  return isoDay(x);
}

// 12-hour time box + AM/PM. Plain text so an empty box shows "00:00", not a browser-filled time.
function timeField(id, name, value24 = "", required = false) {
  let t = "", ap = "AM";
  if (value24) {
    const [h, m] = value24.split(":").map(Number);
    ap = h >= 12 ? "PM" : "AM";
    t = `${pad(h % 12 || 12)}:${pad(m)}`;
  }
  return `<span class="time12">
    <input id="${id}" type="text" name="${name}__t" value="${t}" inputmode="numeric" placeholder="00:00" maxlength="5"
      pattern="(0?[1-9]|1[0-2]):[0-5][0-9]" title="12-hour time, e.g. 7:30" ${required ? "required" : ""}>
    <select name="${name}__ap" aria-label="AM or PM">${["AM", "PM"].map((x) => `<option ${x === ap ? "selected" : ""}>${x}</option>`).join("")}</select>
  </span>`;
}

// Reads a timeField back out of form data as 24-hour "HH:MM" ("" if left blank).
function time24(fd, name) {
  const t = (fd.get(name + "__t") || "").trim();
  const pm = fd.get(name + "__ap") === "PM";
  fd.delete(name + "__t"); fd.delete(name + "__ap");
  if (!t) return "";
  const [h, m] = t.split(":").map(Number);
  return `${pad((h % 12) + (pm ? 12 : 0))}:${pad(m)}`;
}

const fmt12 = (hhmm24) => { const [h, m] = hhmm24.split(":").map(Number); return `${h % 12 || 12}:${pad(m)} ${h >= 12 ? "PM" : "AM"}`; };

function openNewGoal() {
  modal("New quest", `<form id="goal-form">
    <div class="field"><label class="px" for="gt">What are you studying for?</label><input id="gt" type="text" name="title" required></div>
    <div class="row">
      <div class="field"><label class="px" for="gd">Deadline</label><input id="gd" type="date" name="deadline" required min="${today()}"></div>
      <div class="field"><label class="px" for="gtm">Due time (optional)</label>${timeField("gtm", "due_time")}</div>
    </div>
    <p class="hint" style="margin-top:-4px">Add a time if it's due at a specific hour, even later today. Without one, you study until the day before.</p>
    <div class="row">
      <div class="field"><label class="px" for="gh">Study hours per day</label><input id="gh" type="number" name="daily_hours" min="0.25" max="12" step="0.25" placeholder="0"></div>
      <div class="field"><label class="px" for="gs">Start studying at</label>${timeField("gs", "day_start")}</div>
    </div>
    <p class="hint" style="margin-top:-4px">Optional. Sets your study time for all quests. Today's sessions start right away; this start time is for the following days. Leave blank to keep ${dur(S.data.settings.daily_minutes)} a day from ${fmt12(S.data.settings.day_start)}.</p>
    <div class="field"><label class="px" for="gf">Notes / syllabus (PDF, DOCX, MD, TXT)</label><input id="gf" type="file" name="files" multiple required accept=".pdf,.docx,.md,.txt"></div>
    <p id="goal-status" class="muted"></p>
    <button class="btn primary">▶ Start quest</button>
  </form>`);
}

function toast(title, text) {
  if (/^(Error|Atlas unavailable)/.test(title)) sfx.play("error");
  const el = document.createElement("div");
  el.className = "toast";
  el.innerHTML = `<div class="dialog"><h3 class="px">${esc(title)}</h3><p>${esc(text)}</p></div>`;
  $("#toasts").append(el);
  setTimeout(() => el.remove(), 3500);
}

// ---------- events ----------
// Generic click sounds. Results (done, saved, error...) play their own sound later.
document.addEventListener("click", (e) => {
  const el = e.target.closest("button, summary, input[type=radio], input[type=checkbox], a");
  if (!el || el.disabled) return;
  if (el.id === "sound-btn" || el.dataset.tick || el.dataset.toggle || el.dataset.topic) return;
  if (["toggle-ai", "ai-on", "ai-off", "rebuild"].includes(el.dataset.act)) return;
  if (el.dataset.delete || el.dataset.act === "reset-all") sfx.play("warn");
  else if (el.dataset.focus) sfx.play("on");
  else if (el.dataset.act === "focus-expand") sfx.play("open");
  else if (el.dataset.act === "focus-pause") sfx.play("click");
  else if (el.dataset.act === "focus-stop") sfx.play("off");
  else if (el.dataset.go) sfx.play("nav");
  else if (el.dataset.sess || el.dataset.act === "new-goal" || el.tagName === "SUMMARY") sfx.play("open");
  else if (el.matches("[data-close]")) sfx.play("close");
  else if (el.type === "radio" || el.dataset.themePick) sfx.play("select");
  else if (el.type !== "submit") sfx.play("click");
}, true);

document.addEventListener("click", async (e) => {
  if (e.target.closest("#sound-btn")) {
    sfx.setMuted(!sfx.muted); renderSoundBtn(); sfx.play("select"); return;
  }
  const t = e.target.closest("[data-focus],[data-theme-pick],[data-tick],[data-go],[data-act],[data-sess],[data-close],[data-overlay],[data-toggle],[data-delete],[data-ai-pick]");
  if (!t || (t.matches("[data-overlay]") && e.target !== t)) return;
  try {
    if (t.dataset.tick) {
      await api(`/api/sessions/${t.dataset.tick}`, { method: "PATCH", json: { done: t.dataset.done === "true" } });
      sfx.play(t.dataset.done === "true" ? "done" : "undo");
      await refresh();
      if (t.dataset.done === "true") toast("Session complete", "Nice work. Keep going!");
    }
    else if (t.dataset.focus) startFocus(+t.dataset.focus);
    else if (t.dataset.act === "focus-expand") openFocusView();
    else if (t.dataset.act === "focus-pause") {
      if (F.pausedLeft != null) { F.endsAt = Date.now() + F.pausedLeft * 1000; F.pausedLeft = null; }
      else F.pausedLeft = focusLeft();
      saveFocus(); drawFocus();
    }
    else if (t.dataset.act === "focus-stop") stopFocus();
    else if (t.dataset.themePick) { setTheme(t.dataset.themePick); render(); }
    else if (t.dataset.go) { S.view = t.dataset.go; history.replaceState(null, "", "#" + S.view); render(); }
    else if (t.matches("[data-close],[data-overlay]")) { if (t.matches("[data-overlay]")) sfx.play("close"); closeModal(); }
    else if (t.dataset.sess) openSession(+t.dataset.sess);
    else if (t.dataset.toggle) {
      await api(`/api/sessions/${t.dataset.toggle}`, { method: "PATCH", json: { done: t.dataset.done === "true" } });
      sfx.play(t.dataset.done === "true" ? "done" : "undo");
      if (F && F.id === +t.dataset.toggle && t.dataset.done === "true") { F = null; saveFocus(); drawFocus(); }
      closeModal(); await refresh();
      if (t.dataset.done === "true") toast("Session complete", "Nice work. Keep going!");
    }
    else if (t.dataset.delete) {
      if (!confirm("Delete this quest and its sessions?")) return;
      await api(`/api/goals/${t.dataset.delete}`, { method: "DELETE" }); await refresh();
    }
    else if (["toggle-ai", "ai-on", "ai-off"].includes(t.dataset.act)) {
      const on = t.dataset.act === "toggle-ai" ? !S.data.ai : t.dataset.act === "ai-on";
      if (on && !S.data.ai_ready) { S.view = "setup"; history.replaceState(null, "", "#setup"); render(); return toast("Atlas unavailable", "Connect an AI below first."); }
      await api("/api/ai", { method: "PUT", json: { on } }); sfx.play(on ? "on" : "off"); await refresh();
      toast(on ? "Atlas on" : "Offline mode", on ? "Atlas will read your notes and answer questions." : "Using your notes' structure and passage search.");
    }
    else if (t.dataset.aiPick) {
      const f = S.data.ai_detected[+t.dataset.aiPick];
      await api("/api/ai/config", { method: "PUT", json: { provider: f.provider, base_url: f.base_url, model: f.model } });
      await refresh(); await testAI();
    }
    else if (t.dataset.act === "ai-test") await testAI();
    else if (t.dataset.act === "ai-detect") {
      const r = await api("/api/ai/detect", { method: "POST" });
      await refresh();
      toast(r.found ? `Found ${r.found} AI${r.found > 1 ? "s" : ""}` : "Nothing found", r.found ? "Pick one next to “Found”." : "Start Ollama or LM Studio, or pick a provider and add a key.");
    }
    else if (t.dataset.act === "ai-models") {
      const f = $("#ai-form");
      const r = await api("/api/ai/models", { method: "POST", json: { provider: f.provider.value, base_url: f.base_url.value, key: f.key.value || null } });
      $("#ai-models").innerHTML = r.models.map((m) => `<option value="${esc(m)}">`).join("");
      if (!f.model.value && r.models.length) f.model.value = r.models[0];
      toast(`${r.models.length} model${r.models.length === 1 ? "" : "s"} available`, r.models.slice(0, 4).join(", "));
    }
    else if (t.dataset.act === "reset-profile" || t.dataset.act === "reset-all") {
      const all = t.dataset.act === "reset-all";
      if (all && !confirm("Erase all quests, notes, sessions and settings? This can't be undone.")) return;
      await api("/api/reset", { method: "POST", json: { everything: all } });
      if (all) { S.chat = []; S.agent = []; F = null; saveFocus(); drawFocus(); }
      S.view = "home"; history.replaceState(null, "", "#home");
      sfx.play("close"); await refresh();
    }
    else if (t.dataset.act === "new-goal") openNewGoal();
    else if (t.dataset.act === "rebuild") { await api("/api/plan", { method: "POST" }); sfx.play("sweep"); await refresh(); toast("Plan rebuilt", "Missed sessions moved forward."); }
  } catch (err) { toast("Error", err.message); }
});

document.addEventListener("change", async (e) => {
  if (e.target.id === "ai-p") {
    const p = S.data.ai_providers.find((x) => x.id === e.target.value), f = e.target.form;
    if (p) {
      f.base_url.value = p.base_url;
      f.model.value = S.data.ai_detected.find((x) => x.provider === p.id)?.model || p.model;
      f.key.placeholder = p.needs_key ? "Paste your API key (or set it on this computer)" : "Not needed for this provider";
    }
    return;
  }
  const id = e.target.dataset.topic;
  if (!id) return;
  try {
    await api(`/api/topics/${id}`, { method: "PATCH", json: { done: e.target.checked } });
    sfx.play(e.target.checked ? "topic" : "undo");
    await refresh();
    toast(e.target.checked ? "Topic done" : "Topic reopened", e.target.checked ? "Its remaining sessions were removed from your plan." : "Sessions for it were added back to your plan.");
  } catch (err) { toast("Error", err.message); }
});

document.addEventListener("submit", async (e) => {
  e.preventDefault();
  const f = e.target;
  if (f.id === "profile-form") {
    const d = new FormData(f);
    const first = !S.data.settings.name;
    try {
      await api("/api/profile", { method: "PUT", json: { name: d.get("name"), gender: d.get("gender") } });
      sfx.play(first ? "fanfare" : "done");
      await refresh();
      toast(first ? `Welcome, ${d.get("name")}!` : "Profile saved", first && !S.data.goals.length ? "Start by creating your first quest." : "");
    } catch (err) { toast("Error", err.message); }
  }
  if (f.id === "goal-form") {
    const btn = f.querySelector("button"); btn.disabled = true;
    $("#goal-status").innerHTML = `<span class="loading">${S.data.ai ? "Atlas is reading" : "Reading"} your notes and building the plan</span>`;
    try {
      const fd = new FormData(f);
      fd.set("due_time", time24(fd, "due_time"));
      fd.set("day_start", time24(fd, "day_start"));
      await api("/api/goals", { method: "POST", body: fd });
      sfx.play("fanfare"); closeModal(); S.view = "plan"; await refresh(); toast("Quest started", "Your plan is ready.");
    } catch (err) { sfx.play("error"); $("#goal-status").textContent = "Error: " + err.message; btn.disabled = false; }
  }
  if (f.id === "agent-form") {
    const msg = f.msg.value.trim();
    if (!msg) return;
    const history = S.agent.map(({ role, content }) => ({ role, content }));
    S.agent.push({ role: "user", content: msg }); S.agentBusy = true; sfx.play("send"); render();
    try {
      const r = await api("/api/agent", { method: "POST", json: { message: msg, history } });
      S.agent.push({ role: "assistant", content: r.reply, actions: r.actions });
      sfx.play(r.actions.length ? "done" : "message");
    } catch (err) { S.agent.push({ role: "assistant", content: "Error: " + err.message }); sfx.play("error"); }
    S.agentBusy = false;
    await refresh();
    $("#agent-form input")?.focus();
  }
  if (f.id === "move-form") {
    const d = new FormData(f);
    const time = time24(d, "time");
    try {
      await api(`/api/sessions/${f.dataset.id}`, { method: "PATCH", json: { start: `${d.get("day")}T${time}` } });
      sfx.play("done"); closeModal(); await refresh();
      toast("Time saved", `Moved to ${dayLabel(D(d.get("day") + "T00:00"))} at ${fmt12(time)}.`);
    } catch (err) { toast("Error", err.message); }
  }
  if (f.id === "ai-form") {
    const auto = f.provider.value === "auto";
    try {
      await api("/api/ai/config", { method: "PUT", json: auto ? { provider: "auto" }
        : { provider: f.provider.value, base_url: f.base_url.value, model: f.model.value, key: f.key.value || null } });
      await refresh();
      if (S.data.ai_ready) await testAI(); else toast("Nothing found", "Start Ollama or LM Studio, or pick a provider and add a key.");
    } catch (err) { toast("Error", err.message); }
  }
  if (f.id === "ask-form") {
    const q = f.q.value, g = f.goal.value;
    S.chat.push({ role: "user", text: q }); S.busy = true; sfx.play("send"); render();
    try {
      const r = await api("/api/chat", { method: "POST", json: { question: q, goal_id: g ? +g : null } });
      S.chat.push({ role: "bot", text: r.answer, sources: r.sources });
      sfx.play("message");
    } catch (err) { S.chat.push({ role: "bot", text: "Error: " + err.message }); }
    S.busy = false; render();
  }
});
document.addEventListener("keydown", (e) => { if (e.key === "Escape") closeModal(); });

const tick = () => { const d = new Date(); $("#clock").textContent = `${dayLabel(d)} ${pad(d.getHours())}:${pad(d.getMinutes())}`; };
setInterval(tick, 10000); tick();
drawFocus();
refresh();
