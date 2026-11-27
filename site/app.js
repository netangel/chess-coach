// Dashboard: renders dashboard.json (built by `python -m pipeline site`). No dependencies.

const SKILL_RU = {
  "tactics.fork": "Вилка",
  "tactics.pin": "Связка",
  "tactics.skewer": "Сквозной удар",
  "tactics.discoveredAttack": "Вскрытое нападение",
  "tactics.doubleCheck": "Двойной шах",
  "tactics.hangingPiece": "Незащищённые фигуры",
  "tactics.backRankMate": "Мат по последней горизонтали",
  "tactics.mateIn1": "Мат в 1 ход",
  "tactics.mateIn2": "Мат в 2 хода",
  "tactics.mateIn3": "Мат в 3 хода",
  "tactics.deflection": "Отвлечение",
  "tactics.attraction": "Завлечение",
  "tactics.sacrifice": "Жертва",
  "tactics.zugzwang": "Цугцванг",
  "tactics.other": "Тактика (прочее)",
  "calculation.defensive-resources": "Защитные ресурсы",
  "calculation.candidate-moves": "Проверка ходов-кандидатов",
  "calculation.visualization": "Счёт вариантов",
  "middlegame.conversion": "Реализация преимущества",
  "middlegame.defence": "Защита",
  "middlegame.attack-on-king": "Атака на короля",
  "middlegame.time-management": "Распределение времени",
  "endgame.pawn": "Пешечный эндшпиль",
  "endgame.rook": "Ладейный эндшпиль",
  "endgame.minor-piece": "Эндшпиль лёгких фигур",
  "endgame.queen": "Ферзевый эндшпиль",
  "endgame.theoretical-positions": "Теоретические позиции",
  "endgame.technique": "Техника эндшпиля",
  "opening.repertoire-white": "Дебютный репертуар белыми",
  "opening.repertoire-black": "Дебютный репертуар чёрными",
  "opening.early-deviations": "Ошибки в дебюте",
  "psychology.tilt": "Тильт",
  "psychology.rushing": "Спешка",
  "psychology.passivity": "Пассивность",
};
const CONF_RU = { low: "низкая уверенность", medium: "средняя", high: "высокая" };
const PERF_RU = { rapid: "рапид", classical: "классика", blitz: "блиц", correspondence: "переписка", puzzle: "задачи" };

const $ = (id) => document.getElementById(id);
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
const safeUrl = (u) => (/^https:\/\//.test(u || "") ? u : "#");
const pct = (x) => (x == null ? "—" : `${Math.round(x * 100)}%`);
const skillName = (k) => SKILL_RU[k] || k;
const dayWord = (n) => (n % 10 === 1 && n % 100 !== 11 ? "день" : [2, 3, 4].includes(n % 10) && ![12, 13, 14].includes(n % 100) ? "дня" : "дней");

function taskItem({ title, minutes, url, note, count, steps }) {
  const badge = minutes ? `${minutes}′` : count ? `×${count}` : "•";
  const label = url ? `<a href="${esc(safeUrl(url))}" target="_blank" rel="noopener">${esc(title)}</a>` : `<b>${esc(title)}</b>`;
  const list = steps?.length ? `<ol class="steps">${steps.map((st) => `<li>${esc(st)}</li>`).join("")}</ol>` : "";
  return `<li><span class="min">${esc(badge)}</span><span>${label}${note ? `<span class="note">${esc(note)}</span>` : ""}${list}</span></li>`;
}

const RESULT_RU = { win: "победа", loss: "поражение", draw: "ничья" };
const STATUS_RU = { mate: "мат", resign: "сдача", outoftime: "по времени", timeout: "соперник покинул игру", draw: "ничья", stalemate: "пат", aborted: "отменена" };
const CLASS_RU = { blunder: "зевок", mistake: "ошибка" };

function renderLatest(d) {
  const g = d.latestGame;
  if (!g) { $("latest-body").innerHTML = `<p class="muted">Партий пока нет.</p>`; return; }
  const date = new Date(g.date + "T12:00:00").toLocaleDateString("ru-RU", { day: "numeric", month: "long", year: "numeric" });
  const meta = [PERF_RU[g.perf] || g.perf, g.clock, g.rated ? "рейтинговая" : "товарищеская", date].filter(Boolean).join(" · ");
  const opp = `${esc(g.opponent)}${g.opponentRating ? ` (${esc(g.opponentRating)})` : ""}`;
  const result = `<span class="result ${esc(g.result)}">${esc(RESULT_RU[g.result])}</span>${g.status && STATUS_RU[g.status] ? ` <span class="muted small">(${esc(STATUS_RU[g.status])})</span>` : ""}`;
  let body;
  if (!g.analysed) {
    const why = {
      perf: `Партии «${esc(PERF_RU[g.perf] || g.perf)}» не анализируются: конвейер разбирает рапид и классику.`,
      short: "Партия слишком короткая для анализа (меньше 10 ходов).",
      pending: "Анализ появится после ночного запуска конвейера (около 04:00 по Праге).",
    }[g.notAnalysed] || "Партия ещё не проанализирована.";
    body = `<p class="small muted">${why}</p>`;
  } else {
    const s = g.summary;
    const stats = `<p class="small">Точность ${esc(s.accuracy ?? "—")}% · зевков ${esc(s.blunders)} · ошибок ${esc(s.mistakes)}</p>`;
    // the plan asks for 3 turning points: show the 3 costliest in game order, the rest folded
    const top = new Set([...g.moments].sort((a, b) => b.winDrop - a.winDrop).slice(0, 3));
    const item = (m) => `<li><a href="${esc(safeUrl(m.url))}" target="_blank" rel="noopener">${esc(m.label)}</a> <span class="muted small">— сыграно ${esc(m.played)}, −${Math.round(m.winDrop)}%</span></li>`;
    const rest = g.moments.filter((m) => !top.has(m));
    const moments = g.moments.length
      ? `<p class="small muted">Переломные моменты для сверки${g.moments.some((m) => m.inStudy) ? " (открываются в учебном разборе)" : ""}:</p>
         <ul class="moments">${g.moments.filter((m) => top.has(m)).map(item).join("")}</ul>
         ${rest.length ? `<details><summary class="small">ещё ${rest.length}</summary><ul class="moments">${rest.map(item).join("")}</ul></details>` : ""}`
      : `<p class="small">Критических моментов нет — чистая партия. Достаточно быстро просмотреть.</p>`;
    body = stats + moments;
  }
  $("latest-body").innerHTML = `
    <p><b>${g.color === "white" ? "Белыми" : "Чёрными"} против ${opp}</b> — ${result}</p>
    <p class="small muted">${esc(meta)}</p>
    ${body}
    <p class="small"><a href="${esc(safeUrl(g.url))}" target="_blank" rel="noopener">Открыть партию на Lichess →</a></p>`;
}

function renderToday(d) {
  const items = [];
  const plan = d.plan;
  const daily = plan?.daily || [];
  daily.forEach((t) => items.push(taskItem({ ...t, note: t.rule })));
  const hasStudy = daily.some((t) => (t.url || "").includes("/study/"));
  if (d.study.url && !hasStudy) {
    items.push(taskItem({
      title: "Разбор своих ошибок",
      minutes: 7,
      url: d.study.url,
      note: `${Math.min(d.study.perDay, d.study.chapters)} позиций в день · всего в разборе ${d.study.chapters}`,
    }));
  }
  const minimum = plan?.minimum_day || "3 позиции из разбора или 1 забег Storm";
  const streak = d.activity.streak;
  $("today-body").innerHTML = `
    ${plan ? "" : `<p class="muted small">План на неделю ещё не составлен — пока базовый набор.</p>`}
    <ul class="tasks">${items.join("")}</ul>
    <div class="fallback"><b>Минимальный день:</b> ${esc(minimum)}</div>
    <p class="small muted">${streak ? `Серия: ${streak} ${dayWord(streak)} подряд` : "Серии пока нет"}${d.activity.activeToday ? " · сегодня уже есть активность ✓" : ""}</p>
    ${plan?.focus?.length ? `<p class="small">Фокус недели: ${plan.focus.map((f) => `<span class="badge focus">${esc(skillName(f))}</span>`).join(" ")}</p>` : ""}
    ${plan?.html ? `<details><summary class="small">Почему такой план</summary><div class="prose small">${plan.html}</div></details>` : ""}`;
}

function renderWeek(d) {
  const a = d.activity;
  const weekly = d.plan?.weekly || [];
  const gamesPlanned = weekly.find((w) => w.count)?.count ?? d.budget.games_per_week;
  const main = a.gamesByPerf[d.mainPerf] || 0;
  const others = Object.entries(a.gamesByPerf).filter(([p]) => p !== d.mainPerf).map(([p, n]) => `${PERF_RU[p] || p}: ${n}`).join(", ");
  const rev = a.reviews.correct + a.reviews.wrong;
  $("week-body").innerHTML = `
    <div class="stats">
      <div class="stat"><div class="v">${main} / ${gamesPlanned}</div><div class="l">партий (${PERF_RU[d.mainPerf] || d.mainPerf})</div>${others ? `<div class="t">ещё ${esc(others)}</div>` : ""}</div>
      <div class="stat"><div class="v">${a.puzzles}</div><div class="l">задач решено</div><div class="t">${a.puzzles ? `верно ${pct(a.puzzleWins / a.puzzles)}` : "&nbsp;"}</div></div>
      <div class="stat"><div class="v">${rev ? `${a.reviews.correct} / ${rev}` : "—"}</div><div class="l">разбор: верно</div><div class="t">по итогам check-in</div></div>
    </div>
    ${weekly.length ? `<ul class="tasks" style="margin-top:10px">${weekly.map((w) => taskItem({ ...w, note: w.rule })).join("")}</ul>` : ""}
    <p class="small muted">Неделя ${esc(a.week)}${d.plan?.week && d.plan.week !== a.week ? ` · план составлен на ${esc(d.plan.week)}` : ""}</p>`;
}

function lineChart(title, points, { fmt = (v) => v, note = "" } = {}) {
  const pts = points.filter((p) => p[1] != null);
  if (pts.length < 2) {
    return `<div class="chart"><h3>${esc(title)}</h3><p class="small muted">Мало данных${pts.length ? ` (${pts.length} точка)` : ""}. ${esc(note)}</p></div>`;
  }
  const W = 600, H = 120, P = 22;
  const ys = pts.map((p) => p[1]);
  let lo = Math.min(...ys), hi = Math.max(...ys);
  if (lo === hi) { lo -= 1; hi += 1; }
  const x = (i) => P + (i * (W - 2 * P)) / (pts.length - 1);
  const y = (v) => H - P - ((v - lo) * (H - 2 * P)) / (hi - lo);
  const path = pts.map((p, i) => `${i ? "L" : "M"}${x(i).toFixed(1)},${y(p[1]).toFixed(1)}`).join(" ");
  const last = pts[pts.length - 1];
  return `<div class="chart"><h3>${esc(title)} <span class="muted small">· сейчас ${esc(fmt(last[1]))}</span></h3>
    <svg viewBox="0 0 ${W} ${H}" preserveAspectRatio="none" role="img" aria-label="${esc(title)}">
      <line class="axis" x1="${P}" x2="${W - P}" y1="${H - P}" y2="${H - P}"/>
      <path class="line" d="${path}" vector-effect="non-scaling-stroke"/>
      <circle class="dot" cx="${x(pts.length - 1)}" cy="${y(last[1])}" r="3"/>
      <text x="${P}" y="${H - 6}">${esc(pts[0][0])}</text>
      <text x="${W - P}" y="${H - 6}" text-anchor="end">${esc(last[0])}</text>
      <text x="2" y="${y(hi) + 4}">${esc(fmt(hi))}</text>
      <text x="2" y="${y(lo) + 4}">${esc(fmt(lo))}</text>
    </svg>${note ? `<p class="small muted">${esc(note)}</p>` : ""}</div>`;
}

function renderTrends(d) {
  const main = d.mainPerf;
  const series = d.weeklySeries || [];
  const charts = [];
  const rating = d.ratings[main] || [];
  charts.push(lineChart(`Рейтинг (${PERF_RU[main] || main})`, rating.map(([dt, r]) => [dt, r]), { note: rating.length ? "" : "Рейтинговых партий пока нет." }));
  charts.push(lineChart(`Зевки за партию (${PERF_RU[main] || main})`, series.map((s) => [s.week, s[`${main}.blundersPerGame`]]), { fmt: (v) => v.toFixed(1) }));
  charts.push(lineChart("Доля ошибок в цейтноте", series.map((s) => [s.week, s[`${main}.timePressureErrorShare`]]), { fmt: pct }));
  charts.push(lineChart("Задачи: решено верно (по неделям)", series.map((s) => [s.week, s["puzzles.winRate"]]), { fmt: pct }));
  charts.push(lineChart("Рейтинг задач", (d.ratings.puzzle || []).map(([dt, r]) => [dt, r])));
  if (d.storm?.n) charts.push(`<div class="chart"><h3>Storm</h3><p class="small">Лучший за 30 дней: <b>${esc(d.storm.best30d)}</b> · рекорд ${esc(d.storm.high ?? "—")}</p></div>`);
  $("trends-body").innerHTML = charts.join("");
}

function renderDiagnosis(d) {
  const diag = d.diagnosis;
  if (!diag) { $("diagnosis-body").innerHTML = `<p class="muted">Диагноз ещё не построен.</p>`; return; }
  const focus = new Set(d.plan?.focus || []);
  const rows = diag.weaknesses.slice(0, 6).map((w) => `
    <li>
      <div class="head"><span class="skill">${esc(skillName(w.skill))}</span>
        <span>${focus.has(w.skill) ? `<span class="badge focus">в фокусе</span> ` : ""}<span class="badge">${esc(CONF_RU[w.confidence] || w.confidence)}</span></span></div>
      <div class="bar"><span style="width:${Math.round(w.score * 100)}%"></span></div>
      <details><summary class="small">почему${w.url ? "" : ""}</summary><ul>${w.evidence.map((e) => `<li>${esc(e)}</li>`).join("")}</ul></details>
      ${w.url ? `<a class="small" href="${esc(safeUrl(w.url))}" target="_blank" rel="noopener">тренировать на Lichess →</a>` : ""}
    </li>`).join("");
  $("diagnosis-body").innerHTML = `
    <p class="small muted">Основа: ${esc(diag.sampleSize.games)} партий, ${esc(diag.sampleSize.puzzles)} задач · ${esc(diag.asOf)}</p>
    <ul class="weak">${rows}</ul>`;
}

function renderJournal(d) {
  const j = d.journal;
  $("journal-body").innerHTML = j ? j.html : `<p class="muted">Записей пока нет.</p>`;
}

function renderFooter(d) {
  const sync = d.sync.lastSyncAt ? new Date(d.sync.lastSyncAt).toLocaleString("ru-RU") : "—";
  let token = "";
  if (d.sync.tokenExpiresAt) {
    const days = Math.round((d.sync.tokenExpiresAt - Date.now()) / 86400000);
    token = days < 30 ? ` · <span class="warn">токен Lichess истекает через ${days} дн.</span>` : ` · токен действует ещё ${days} дн.`;
  }
  $("footer").innerHTML = `Синхронизация: ${esc(sync)} · сборка ${esc(d.generatedAt)}${token}`;
  $("subtitle").textContent = `${d.username} · ${PERF_RU[d.mainPerf] || d.mainPerf} 15+10${d.plan?.week ? ` · план ${d.plan.week}` : ""}`;
}

async function main() {
  try {
    const res = await fetch("dashboard.json", { cache: "no-store" });
    const d = await res.json();
    for (const fn of [renderToday, renderLatest, renderWeek, renderTrends, renderDiagnosis, renderJournal, renderFooter]) {
      try { fn(d); } catch (e) { console.error(fn.name, e); }
    }
  } catch (e) {
    $("subtitle").textContent = "Не удалось загрузить данные";
    console.error(e);
  }
}
main();
