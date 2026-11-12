(() => {
  "use strict";
  const data = JSON.parse(document.getElementById("quest-data").textContent);
  const $ = (id) => document.getElementById(id);
  const byId = new Map(data.nodes.map(n => [n.note_id, n]));
  const territories = data.territories;
  const terrById = new Map(territories.map(t => [t.note_id, t]));
  const colors = {established:"#86efac", building:"#fbbf24", ruins:"#475569"};
  const encounterColors = {1:"#86efac", 2:"#a3e635", 3:"#fbbf24", 4:"#fb923c", 5:"#f87171"};
  let budget = 25;
  let plan = [];
  let toastTimeout;

  const escapeHTML = (v) => String(v ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;","'":"&#39;"}[c]));
  const formatPct = (v) => `${Math.round(v * 100)}%`;

  // ═══ Territory status helpers (Minecraft-like progression) ═══
  const statusIcon = {established:"⬡", building:" ◐", ruins:" ○"};
  const kindNames = {definition:"定义",concept:"概念",principle:"原理",procedure:"步骤",method:"方法",application:"应用",example:"示例",moc:"目录",literature:"文献",stub:"待补全"};

  // ═══ Star Valley style day rhythm ═══
  const dayPhase = (() => {
    const hour = new Date(data.today + "T00:00:00").getDay(); // not real hour; we use streak/context
    // Use review count and streak to set the "time of day" metaphor
    if (data.streak >= 14) return {name:"丰收季", icon:"🌾", desc:"你的坚持已经开花结果。"};
    if (data.streak >= 7) return {name:"盛夏", icon:"☀", desc:"热情正在燃烧，每一天都比昨天更充实。"};
    if (data.streak >= 3) return {name:"初春", icon:"🌱", desc:"种子已经发芽，保持浇灌。"};
    if (data.today_reviews > 0) return {name:"破晓", icon:"🌅", desc:"新的一天，新的可能。"};
    return {name:"黎明前", icon:"🌙", desc:"出发吧，第一缕光就在前方。"};
  })();

  function toast(msg) {
    $("toast").textContent = msg;
    $("toast").hidden = false;
    clearTimeout(toastTimeout);
    toastTimeout = setTimeout(() => { $("toast").hidden = true; }, 5000);
  }

  // ═══ Navigation ═══
  function setView(view) {
    if (!["journey","achievements","territories","insights"].includes(view)) view = "journey";
    document.querySelectorAll(".view").forEach(el => { el.hidden = el.id !== `${view}-view`; });
    document.querySelectorAll(".nav-item").forEach(el => {
      el.classList.toggle("active", el.dataset.view === view);
      if (el.dataset.view === view) el.setAttribute("aria-current","page");
      else el.removeAttribute("aria-current");
    });
    $("view-label").textContent = {journey:"冒险地图",achievements:"成就之墙",territories:"知识领地",insights:"星图洞察"}[view];
    if (view === "territories") renderTerritories();
    if (view === "achievements") renderAchievements();
    if (view === "insights") renderInsights();
  }
  document.querySelectorAll(".nav-item").forEach(btn => btn.addEventListener("click", () => {
    location.hash = btn.dataset.view;
    setView(btn.dataset.view);
  }));
  window.addEventListener("hashchange", () => setView(location.hash.slice(1)));

  // ═══ Date + mode labels ═══
  $("date-label").textContent = `${data.today.replaceAll("-",".")} / ${data.weekday} / ${dayPhase.icon} ${dayPhase.name}`;
  $("data-mode").textContent = data.demo ? "示例数据 · 离线演示" : "本地数据 · 只读快照";
  $("snapshot-label").textContent = `快照生成于 ${data.generated_at} · ${data.demo ? "合成示例" : "评分后请重新生成"}`;

  // ═══ Sidebar profile (Star Valley character card) ═══
  $("side-profile").innerHTML = `
    <div class="sp-level">LEVEL ${data.level_index + 1}</div>
    <div class="sp-name">${escapeHTML(data.level_name)}</div>
    <div class="sp-xp">${data.xp} XP · ${escapeHTML(data.level_title)}</div>
    <div class="sp-bar"><i style="width:${data.level_progress * 100}%"></i></div>
  `;

  // ═══ Level card ═══
  $("level-badge").textContent = data.level_index + 1;
  $("level-name").textContent = data.level_name;
  $("level-title").textContent = data.level_title;
  $("level-desc").textContent = data.level_desc;
  $("xp-fill").style.width = `${data.level_progress * 100}%`;
  $("xp-text").textContent = `${data.xp} XP`;
  $("xp-detail").textContent = data.next_level_xp
    ? `下一级 ${data.level_name === "传奇" ? "已达最高等级" : data.next_level_xp - data.xp + " XP 到达下一级"}`
    : "已达最高等级 ✦";

  // ═══ Campfire (Stardew Valley style streak fire) ═══
  $("campfire").setAttribute("data-level", String(data.campfire_level));
  $("campfire-streak").textContent = data.streak;
  const campfireSubs = ["篝火尚未点燃","火星微弱，但已开始","火焰在跳动","篝火正旺，照亮四周","烈焰冲天，温暖四方","传说中的永恒之火"];
  $("campfire-sub").textContent = campfireSubs[data.campfire_level] || campfireSubs[0];

  // ═══ Stat cards (Delta Force style mission stats) ═══
  const dueCount = territories.filter(t => t.due_kind === "due" || t.due_kind === "overdue").length;
  const mastered = data.territory_stats.established;
  const total = data.territory_stats.total;
  const avg = total ? territories.reduce((s,t) => s + t.mastery, 0) / total : 0;
  $("nav-quest").textContent = dueCount;
  $("nav-ach").textContent = `${data.achievement_count}/${data.achievement_total}`;
  $("nav-total").textContent = total;

  const statCards = [
    ["待远征领地", dueCount, "个", `${territories.filter(t => t.due_kind === "overdue").length} 个逾期 · ${territories.filter(t => t.due_kind === "new").length} 个未开拓`, "⚔"],
    ["已建成领地", mastered, "个", `共 ${total} 个可建设领地`, "⬡"],
    ["本周经验值", data.weekly_xp, "XP", `等级 ${data.level_name} · ${data.level_title}`, "✦"],
    ["连续冒险", data.streak, "天", `今日已探索 ${data.today_reviews} 次`, data.streak >= 7 ? "🔥" : data.streak >= 3 ? "✨" : "◈"]
  ];
  $("stats").innerHTML = statCards.map(([title,value,unit,note,symbol]) =>
    `<div class="stat-card"><div class="stat-top">${title}<span class="stat-symbol" aria-hidden="true">${symbol}</span></div><div class="stat-value">${value}<span class="stat-unit">${unit}</span></div><div class="stat-bottom">${note}</div></div>`
  ).join("");

  // ═══ Narrative banner ═══
  $("narrative-text").textContent = data.narrative[Math.floor(Math.random() * data.narrative.length)];
  const ctx = data.narrative_context;
  let ctxText = "";
  if (ctx.failures_survived > 0) ctxText += `你从 ${ctx.failures_survived} 次失败中站了起来。`;
  if (ctx.hardships_endured > 0) ctxText += ` ${ctx.hardships_endured} 次困难没能阻止你。`;
  if (mastered > 0) ctxText += ` ${mastered} 片领地因你而繁荣。`;
  if (!ctxText) ctxText = "每一次出发，都值得被记住。";
  $("narrative-context").textContent = ctxText;

  // ═══ Quest list (Delta Force mission briefing style) ═══
  function renderQuest() {
    let remaining = budget;
    plan = [];
    for (const id of data.adventure_queue) {
      const t = terrById.get(id);
      if (t && t.minutes <= remaining) { plan.push(t); remaining -= t.minutes; }
    }
    const used = budget - remaining;
    $("quest-count").textContent = plan.length;
    $("quest-estimate").textContent = `预计 ${used} / ${budget} 分钟`;

    // Journey title adapts to state (Minecraft day/night rhythm)
    if (plan.length === 0) {
      $("journey-title").textContent = territories.length ? "今天，留一片空地给自己。" : "你的冒险，从这里开始。";
      $("journey-subtitle").textContent = territories.length ? "当前没有急切的远征。去领地页面探索新领域吧。" : "配置笔记库并扫描后，再生成工作台即可开始。";
    } else {
      $("journey-title").textContent = `${budget} 分钟，踏上一段小冒险。`;
      $("journey-subtitle").textContent = `为你选好了 ${plan.length} 片领地。从「${plan[0].title}」开始——先回忆，再翻笔记。`;
    }

    $("quest-list").innerHTML = plan.length ? plan.map((t,i) => {
      const pillClass = t.due_kind === "overdue" ? "overdue" : t.due_kind === "new" ? "new" : "due";
      const label = t.due_kind === "overdue" ? `呼唤你回去 · ${t.overdue_days}天` : t.due_kind === "new" ? "全新领域" : "今日召唤";
      const barColor = colors[t.status];
      return `<article class="quest-item">
        <span class="quest-index">${String(i+1).padStart(2,"0")}</span>
        <div class="quest-info">
          <button class="quest-title" data-note="${escapeHTML(t.note_id)}">${escapeHTML(t.title)}</button>
          <div class="quest-meta">
            <span class="quest-pill ${pillClass}">${label}</span>
            <span class="quest-encounter">${t.encounter} · 掌握度 ${formatPct(t.mastery)}</span>
            <span class="mini-bar" aria-hidden="true"><i style="width:${t.mastery*100}%;background:${barColor}"></i></span>
          </div>
        </div>
        <span class="quest-minutes">约 ${t.minutes} 分钟</span>
      </article>`;
    }).join("") : '<div class="empty">今天没有需要远征的领地。休息也是一种策略。去探索新领域吧 →</div>';

    $("quest-footnote").textContent = `估算仅供参考 · 还有 ${Math.max(0, data.adventure_queue.length - plan.length)} 项可安排${data.blocked_count ? ` · ${data.blocked_count} 个新领地需先补强前置知识` : ""} · 评分请使用原有复习入口`;
  }

  document.querySelectorAll("[data-budget]").forEach(btn => btn.addEventListener("click", () => {
    budget = Number(btn.dataset.budget);
    document.querySelectorAll("[data-budget]").forEach(b => {b.classList.toggle("selected", b === btn); b.setAttribute("aria-pressed", String(b === btn));});
    renderQuest();
  }));

  // ═══ Territory grid (Minecraft map style — ruins/building/established) ═══
  function renderTerritories() {
    const query = $("search").value.trim().toLocaleLowerCase();
    const filter = $("filter").value;
    const filtered = territories.filter(t => {
      const match = `${t.title} ${t.note_id} ${kindNames[t.concept_type] || t.concept_type || ""}`.toLocaleLowerCase().includes(query);
      if (!match) return false;
      if (filter === "all") return true;
      if (filter === "overdue") return t.due_kind === "overdue";
      if (filter === "due") return t.due_kind === "due";
      if (filter === "new") return t.due_kind === "new";
      return t.status === filter;
    });

    // Stats bar
    const ts = data.territory_stats;
    $("territory-stats-bar").innerHTML = `
      <div class="ts-item ruins"><div class="ts-label">待开拓</div><div class="ts-value">${ts.ruins}</div></div>
      <div class="ts-item building"><div class="ts-label">建设中</div><div class="ts-value">${ts.building}</div></div>
      <div class="ts-item established"><div class="ts-label">已建成</div><div class="ts-value">${ts.established}</div></div>
      <div class="ts-item total"><div class="ts-label">总领地</div><div class="ts-value">${ts.total}</div></div>
    `;

    $("territory-list").innerHTML = filtered.slice(0, 200).map(t => {
      const barColor = colors[t.status];
      const statusText = {established:"ESTABLISHED", building:"BUILDING", ruins:"RUINS"}[t.status];
      return `<button class="territory-card ${t.status}" data-note="${escapeHTML(t.note_id)}">
        <div class="tc-status">${statusIcon[t.status]} ${statusText}</div>
        <h3>${escapeHTML(t.title)}</h3>
        <div class="tc-encounter">${t.encounter} · ${t.quest_label}</div>
        <div class="tc-narrative">${escapeHTML(t.narrative)}</div>
        <div class="tc-progress"><i style="width:${t.mastery * 100}%;background:${barColor}"></i></div>
      </button>`;
    }).join("") || '<div class="empty">没有匹配的领地。试试其他关键词或筛选条件。</div>';
  }
  $("search").addEventListener("input", renderTerritories);
  $("filter").addEventListener("change", renderTerritories);

  // ═══ Achievement wall (Stardew Valley collection style) ═══
  function renderAchievements() {
    const unlocked = new Set(data.achievements.map(a => a.id));
    // Full achievement list is in the data from quest.py
    const allAch = [
      ["first_step","第一步","◈","完成第一次复习"],
      ["streak_3","篝火初燃","🔥","连续 3 天学习"],
      ["streak_7","一周不熄","✨","连续 7 天学习"],
      ["streak_30","月之守护","🌙","连续 30 天学习"],
      ["reviews_50","半百之旅","⚔","累计 50 次复习"],
      ["reviews_200","二百征途","🗻","累计 200 次复习"],
      ["master_1","第一块领地","⬡","掌握 1 个概念"],
      ["master_5","领主","▲","掌握 5 个概念"],
      ["master_10","建筑师","★","掌握 10 个概念"],
      ["hard_won","逆风前行","→","在困难中坚持（10 次 Hard）"],
      ["survivor","不屈之心","♥","从失败中站起（5 次 Again）"],
      ["easy_master","轻松自如","◇","10 次 Easy 评分"],
      ["explorer","星图开拓","◎","学习 10 个不同概念"],
      ["comeback","浴火重生","✦","中断后重新开始"],
      ["budget_45","深度探索","◈","完成一次 45 分钟专注"],
    ];
    $("achievement-summary").innerHTML = `<div class="as-count">${data.achievement_count}<span class="as-total"> / ${data.achievement_total}</span></div><div class="as-total">枚徽章已解锁</div>`;
    $("achievement-grid").innerHTML = allAch.map(([id,name,icon,desc]) => {
      const got = unlocked.has(id);
      return `<div class="achievement-card ${got ? "" : "locked"}">
        <div class="achievement-icon">${got ? icon : "🔒"}</div>
        <div class="achievement-name">${escapeHTML(name)}</div>
        <div class="achievement-desc">${escapeHTML(desc)}</div>
      </div>`;
    }).join("");
  }

  // ═══ Insights (star map) ═══
  function renderInsights() {
    // XP trend bar chart
    const maxXp = Math.max(1, ...data.weekly_xp_trend.map(d => d[1]));
    $("xp-chart").innerHTML = data.weekly_xp_trend.map(([day, xp]) =>
      `<div class="bar-column"><span>${xp}</span><i style="height:${xp/maxXp * 130}px"></i><small>${day.slice(5)}</small></div>`
    ).join("");

    // Forecast
    const maxForecast = Math.max(1, ...data.forecast.map(d => d[1]));
    $("forecast-chart").innerHTML = data.forecast.map(([day, count]) =>
      `<div class="bar-column"><span>${count}</span><i style="height:${count/maxForecast * 130}px"></i><small>${day.slice(5)}</small></div>`
    ).join("");

    // Encounter distribution
    const encLabels = {1:"轻松漫步", 2:"小有挑战", 3:"中等难关", 4:"险峻高峰", 5:"终极试炼"};
    $("encounter-chart").innerHTML = data.encounter_counts.length ? data.encounter_counts.map(([level, count]) =>
      `<div class="insight-row"><span>${encLabels[level] || `等级 ${level}`} <i style="display:inline-block;width:8px;height:8px;border-radius:50%;background:${encounterColors[level]};margin-left:4px"></i></span><strong>${count} 片领地</strong></div>`
    ).join("") : '<div class="empty">暂无数据。</div>';

    // Territory progress
    const ts = data.territory_stats;
    const total = Math.max(1, ts.total);
    const pcts = {ruins: ts.ruins/total, building: ts.building/total, established: ts.established/total};
    $("territory-progress").innerHTML = `
      <div class="insight-row"><span><i style="display:inline-block;width:8px;height:8px;border-radius:50%;background:${colors.ruins};margin-right:6px"></i>待开拓（废墟）</span><strong>${ts.ruins} 片 · ${formatPct(pcts.ruins)}</strong></div>
      <div class="insight-row"><span><i style="display:inline-block;width:8px;height:8px;border-radius:50%;background:${colors.building};margin-right:6px"></i>建设中（脚手架）</span><strong>${ts.building} 片 · ${formatPct(pcts.building)}</strong></div>
      <div class="insight-row"><span><i style="display:inline-block;width:8px;height:8px;border-radius:50%;background:${colors.established};margin-right:6px"></i>已建成（灯塔）</span><strong>${ts.established} 片 · ${formatPct(pcts.established)}</strong></div>
      <p class="muted" style="margin-top:12px">从废墟到大厦，每一片领地都是你亲手建造的。保持复习，让更多灯塔亮起来。</p>
    `;
  }

  // ═══ Detail dialog ═══
  function openDetail(id) {
    const t = terrById.get(id);
    const n = byId.get(id);
    if (!t && !n) return;
    const target = t || n;
    $("detail-title").textContent = target.title;
    $("detail-eyebrow").textContent = t ? `TERRITORY · ${t.status_label.toUpperCase()}` : "KNOWLEDGE NOTE";
    const prereqs = data.edges.filter(e => e.target_id === id && e.edge_type === "prerequisite");
    const mastery = t ? t.mastery : _n(n);
    const difficulty = t ? t.difficulty : 2;
    const narrative = t ? t.narrative : "概念详情";
    const encounter = t ? t.encounter : "";
    const nextReview = t ? t.next_review : (n?.next_review || "尚未安排");
    const type = t ? (kindNames[t.concept_type] || t.concept_type || "未分类") : (kindNames[n?.concept_type] || n?.concept_type || "未分类");

    $("detail-content").innerHTML = `
      <div class="detail-grid">
        <div><small>领地状态</small>${t ? t.status_label : "未知"}</div>
        <div><small>遭遇难度</small>${encounter || `${difficulty} / 5`}</div>
        <div><small>下次远征</small>${escapeHTML(nextReview)}</div>
        <div><small>概念类型</small>${escapeHTML(type)}</div>
      </div>
      <div class="detail-label">领地叙事</div>
      <div class="detail-note">${escapeHTML(narrative)}</div>
      <div class="detail-label">掌握进度</div>
      <div class="detail-note">${formatPct(mastery)} ${mastery >= data.threshold ? "— 灯塔已点亮 ✦" : mastery >= 0.3 ? "— 脚手架已搭起" : "— 仍在清理废墟"}</div>
      ${t && t.excerpt ? `<div class="detail-label">示例笔记</div><div class="detail-note">${escapeHTML(t.excerpt)}</div>` : ""}
      <div class="detail-label">前置领地</div>
      ${prereqs.length ? prereqs.map(e => {
        const src = byId.get(e.source_id);
        return src ? `<button class="prereq-button" data-note="${escapeHTML(e.source_id)}">${escapeHTML(src.title)} · ${formatPct(src.mastery)}</button>` : "";
      }).join("") : '<span class="muted">暂无已记录的前置依赖</span>'}
      ${t && t.blockers.length ? `<p style="margin-top:8px;color:var(--warm)">⚠ 前置领地尚未就绪：${t.blockers.map(x => escapeHTML(byId.get(x)?.title || x)).join("、")}。建议先去建设这些领地。</p>` : ""}
      ${n && n.file_path ? `<div class="detail-label">本地笔记路径</div><div class="detail-path">${escapeHTML(n.file_path)}</div>` : ""}
      <p style="margin-top:16px;font-size:11px;color:var(--muted)">此工作台为只读快照；请在命令行复习中评分，之后重新生成。</p>
    `;
    if (!$("detail-dialog").open) $("detail-dialog").showModal();
  }
  function _n(node) {
    if (!node) return 0;
    return typeof node.mastery === "number" ? node.mastery : 0;
  }

  document.addEventListener("click", event => {
    const button = event.target.closest("[data-note]");
    if (button) openDetail(button.dataset.note);
  });
  $("close-detail").addEventListener("click", () => $("detail-dialog").close());
  $("help").addEventListener("click", () => $("help-dialog").showModal());
  $("close-help").addEventListener("click", () => $("help-dialog").close());
  document.querySelectorAll("dialog").forEach(dialog => dialog.addEventListener("click", event => {
    const box = dialog.getBoundingClientRect();
    if (event.target === dialog && (event.clientX < box.left || event.clientX > box.right || event.clientY < box.top || event.clientY > box.bottom)) dialog.close();
  }));

  // ═══ Timer (focus enchantment) ═══
  let duration = 25 * 60;
  let remaining = duration;
  let deadline = null;
  function renderTimer() {
    if (deadline !== null) {
      remaining = Math.max(0, Math.ceil((deadline - Date.now()) / 1000));
      if (!remaining) {
        deadline = null;
        $("timer-status").textContent = "专注结界完成。起来走走，吸收刚学到的一切。";
        toast("✦ 专注结界完成！你获得了宝贵的经验值。记得在复习入口记录评分。");
      }
    }
    $("timer-text").textContent = `${String(Math.floor(remaining / 60)).padStart(2,"0")}:${String(remaining % 60).padStart(2,"0")}`;
    $("timer-toggle").textContent = deadline !== null ? "暂停" : remaining === duration ? "开始计时" : remaining === 0 ? "再来一轮" : "继续";
  }
  function resetTimer() { deadline = null; duration = Number($("timer-duration").value)*60; remaining = duration; $("timer-status").textContent = "一次只做一件事，就很好。"; renderTimer(); }
  function startTimer() { if (remaining === 0) remaining = duration; deadline = Date.now()+remaining*1000; $("timer-status").textContent = "专注当下。让世界安静下来。"; renderTimer(); }
  $("timer-toggle").addEventListener("click", () => {
    if (deadline !== null) { renderTimer(); deadline = null; $("timer-status").textContent = "已暂停，准备好后再继续。"; renderTimer(); }
    else startTimer();
  });
  $("timer-reset").addEventListener("click", resetTimer);
  $("timer-duration").addEventListener("change", resetTimer);
  $("start-focus")?.addEventListener("click", () => { if (!plan.length) return; if (deadline === null) startTimer(); openDetail(plan[0].note_id); });
  setInterval(renderTimer, 250);
  document.addEventListener("visibilitychange", renderTimer);
  window.addEventListener("beforeunload", event => { if (deadline !== null) { event.preventDefault(); event.returnValue = ""; } });

  // ═══ Activity heatmap ═══
  $("calendar-chart").innerHTML = data.calendar.map(([day, count]) =>
    `<span class="heat-cell l${count === 0 ? 0 : count < 3 ? 1 : count < 5 ? 2 : count < 8 ? 3 : 4}" title="${day} · ${count} 次探索"></span>`
  ).join("");
  const activity = data.calendar.reduce((sum, [, c]) => sum + c, 0);
  $("activity-total").textContent = `${activity} 次探索`;
  $("calendar-chart").setAttribute("aria-label", `截至 ${data.today} 的最近 84 天，共 ${activity} 次探索。`);

  // ═══ Keyboard shortcuts ═══
  document.addEventListener("keydown", (e) => {
    const tag = document.activeElement?.tagName;
    const typing = tag === "INPUT" || tag === "SELECT";
    if (typing && e.key === "Escape") { document.activeElement.blur(); return; }
    if (typing) return;
    if (e.key === " ") { e.preventDefault(); $("timer-toggle").click(); }
    else if (e.key === "r" || e.key === "R") { $("timer-reset").click(); }
    else if (e.key === "1") { location.hash = "journey"; setView("journey"); }
    else if (e.key === "2") { location.hash = "achievements"; setView("achievements"); }
    else if (e.key === "3") { location.hash = "territories"; setView("territories"); }
    else if (e.key === "4") { location.hash = "insights"; setView("insights"); }
    else if (e.key === "/") { e.preventDefault(); location.hash = "territories"; setView("territories"); $("search").focus(); }
  });

  // ═══ Init ═══
  renderQuest();
  setView(location.hash.slice(1) || "journey");
  renderTimer();
})();
