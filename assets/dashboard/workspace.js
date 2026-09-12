(() => {
  "use strict";
  const data = JSON.parse(document.getElementById("workspace-data").textContent);
  const $ = (id) => document.getElementById(id);
  const nodes = data.nodes;
  const byId = new Map(nodes.map(n => [n.note_id, n]));
  const learnable = nodes.filter(n => n.learnable);
  const colors = ["#c4e895", "#73955b", "#394c31"];
  let budget = 25;
  let plan = [];
  let toastTimeout;
  const formatPercent = (v) => `${Math.round(v * 100)}%`;
  const escapeHTML = (value) => String(value ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;", "<":"&lt;", ">":"&gt;", '"':"&quot;", "'":"&#39;"}[c]));
  const kindNames = {definition:"定义", concept:"概念", principle:"原理", procedure:"步骤", method:"方法", application:"应用", example:"示例", moc:"目录", literature:"文献", stub:"待补全"};
  const label = n => n.due_kind === "overdue" ? `逾期 ${n.overdue_days} 天` : n.due_kind === "due" ? "今日复习" : n.due_kind === "new" ? "新概念" : "已排期";
  const pill = n => `<span class="pill ${n.due_kind === "overdue" ? "overdue" : n.due_kind === "new" ? "new" : ""}">${label(n)}</span>`;
  function toast(message) {
    $("toast").textContent = message;
    $("toast").hidden = false;
    clearTimeout(toastTimeout);
    toastTimeout = setTimeout(() => { $("toast").hidden = true; }, 5000);
  }
  function setView(view) {
    if (!["today", "library", "insights"].includes(view)) view = "today";
    document.querySelectorAll(".view").forEach(el => { el.hidden = el.id !== `${view}-view`; });
    document.querySelectorAll(".nav-item").forEach(el => {
      el.classList.toggle("active", el.dataset.view === view);
      if (el.dataset.view === view) el.setAttribute("aria-current", "page"); else el.removeAttribute("aria-current");
    });
    $("view-label").textContent = {today:"今日学习", library:"知识库", insights:"学习洞察"}[view];
    if (view === "library") renderLibrary();
  }
  document.querySelectorAll(".nav-item").forEach(button => button.addEventListener("click", () => {
    location.hash = button.dataset.view;
    setView(button.dataset.view);
  }));
  window.addEventListener("hashchange", () => setView(location.hash.slice(1)));
  $("date-label").textContent = `${data.today.replaceAll("-", ".")} / ${data.weekday} / KEEP GROWING`;
  $("data-mode").textContent = data.demo ? "示例数据 · 离线演示" : "本地数据 · 只读快照";
  $("snapshot-label").textContent = `快照生成于 ${data.generated_at} · ${data.demo ? "合成示例，非真实学习记录" : "评分后请重新生成"}`;
  const dueCount = learnable.filter(n => n.due_kind === "due" || n.due_kind === "overdue").length;
  const newCount = learnable.filter(n => n.due_kind === "new").length;
  const mastered = learnable.filter(n => n.mastery >= data.threshold).length;
  const avg = learnable.length ? learnable.reduce((s,n) => s + n.mastery, 0) / learnable.length : 0;
  $("nav-due").textContent = dueCount;
  $("nav-total").textContent = nodes.length;
  const statCards = [
    ["待复习概念", dueCount, "个", `${learnable.filter(n => n.due_kind === "overdue").length} 个逾期 · ${newCount} 个未开始`, "◷"],
    ["已掌握概念", mastered, "个", `共 ${learnable.length} 个可学习概念`, "◇"],
    ["平均掌握度", Math.round(avg * 100), "%", "BKT 模型估计 · 非考试分数", "↗"],
    ["连续学习", data.streak, "天", `今天已复习 ${data.today_reviews} 次`, "◈"]
  ];
  $("stats").innerHTML = statCards.map(([title,value,unit,note,symbol]) => `<div class="stat-card"><div class="stat-top">${title}<span class="stat-symbol" aria-hidden="true">${symbol}</span></div><div class="stat-value">${value}<span class="stat-unit">${unit}</span></div><div class="stat-bottom">${note}</div></div>`).join("");
  function renderPlan() {
    let remaining = budget;
    plan = [];
    for (const id of data.queue) {
      const n = byId.get(id);
      if (n.minutes <= remaining) { plan.push(n); remaining -= n.minutes; }
    }
    const used = budget - remaining;
    $("plan-count").textContent = plan.length;
    $("hero-count").textContent = plan.length;
    $("plan-estimate").textContent = `预计 ${used} / ${budget} 分钟`;
    $("hero-title").textContent = plan.length ? `${budget} 分钟，给知识浇点水。` : learnable.length ? "今天，留一点空间给自己。" : "你的下一段学习，从这里开始。";
    $("hero-copy").textContent = plan.length ? `为你选好了 ${plan.length} 个概念。从「${plan[0].title}」开始，先回忆，再核对笔记。` : learnable.length ? "当前没有可安排的概念。可以查看知识库，或等下一次复习到期。" : "还没有学习数据。配置笔记库并扫描后，再生成工作台即可开始。";
    $("start-focus").disabled = !plan.length;
    $("export-plan").disabled = !plan.length;
    $("plan-list").innerHTML = plan.length ? plan.map((n,i) => `<article class="plan-item"><span class="plan-index">${String(i+1).padStart(2,"0")}</span><div class="plan-info"><button class="plan-title" data-note="${escapeHTML(n.note_id)}">${escapeHTML(n.title)}</button><div class="plan-meta">${pill(n)}<span>掌握度 ${formatPercent(n.mastery)}</span><span class="mini-bar" aria-hidden="true"><i style="width:${n.mastery*100}%"></i></span></div></div><span class="plan-minutes">约 ${n.minutes} 分钟</span></article>`).join("") : '<div class="empty">没有可安排的学习项。现在休息一下也很好。</div>';
    $("plan-footnote").textContent = `估算仅供参考 · 还有 ${Math.max(0,data.queue.length-plan.length)} 项可安排${data.blocked_count ? ` · ${data.blocked_count} 个新概念需先补强前置知识` : ""} · 评分请使用原有复习入口`;
  }
  document.querySelectorAll("[data-budget]").forEach(button => button.addEventListener("click", () => {
    budget = Number(button.dataset.budget);
    document.querySelectorAll("[data-budget]").forEach(b => {b.classList.toggle("selected", b === button); b.setAttribute("aria-pressed", String(b === button));});
    renderPlan();
  }));
  function renderLibrary() {
    const query = $("search").value.trim().toLocaleLowerCase();
    const filter = $("filter").value;
    const filtered = nodes.filter(n => {
      const match = `${n.title} ${n.note_id} ${kindNames[n.concept_type] || n.concept_type || ""}`.toLocaleLowerCase().includes(query);
      return match && (filter === "all" || filter === "due" && n.learnable && ["due","overdue"].includes(n.due_kind) || filter === "new" && n.learnable && n.due_kind === "new" || filter === "mastered" && n.learnable && n.mastery >= data.threshold);
    });
    $("library-summary").textContent = `显示 ${filtered.length} / ${nodes.length} 个概念${filtered.length > 200 ? " · 仅显示前 200 个，请搜索缩小范围" : ""}`;
    $("library-list").innerHTML = filtered.slice(0,200).map(n => `<button class="knowledge-card" data-note="${escapeHTML(n.note_id)}"><span class="card-kind">${escapeHTML(kindNames[n.concept_type] || n.concept_type || "未分类")}</span><h3>${escapeHTML(n.title)}</h3><div class="card-detail">掌握度 ${formatPercent(n.mastery)} · ${n.learnable ? label(n) : "非学习项"}</div><div class="full-progress" aria-hidden="true"><i style="width:${n.mastery*100}%"></i></div></button>`).join("") || '<div class="empty">没有匹配的概念。试试其他关键词或筛选条件。</div>';
  }
  $("search").addEventListener("input", renderLibrary);
  $("filter").addEventListener("change", renderLibrary);
  function openDetail(id) {
    const n = byId.get(id);
    if (!n) return;
    $("detail-title").textContent = n.title;
    const prerequisites = data.edges.filter(e => e.target_id === id && e.edge_type === "prerequisite");
    $("detail-content").innerHTML = `<div class="detail-grid"><div><small>掌握度</small>${formatPercent(n.mastery)}</div><div><small>概念难度</small>${n.difficulty} / 5</div><div><small>下次复习</small>${escapeHTML(n.next_review || "尚未安排")}</div><div><small>类型</small>${escapeHTML(kindNames[n.concept_type] || n.concept_type || "未分类")}</div></div><div class="detail-label">回忆提示</div><div class="detail-note">不看笔记，用自己的话解释「${escapeHTML(n.title)}」。它解决什么问题？能举一个例子吗？</div>${n.excerpt ? `<div class="detail-label">示例笔记摘要</div><div class="detail-note">${escapeHTML(n.excerpt)}</div>` : ""}<div class="detail-label">前置知识</div>${prerequisites.length ? prerequisites.map(e => byId.has(e.source_id) ? `<button class="prereq-button" data-note="${escapeHTML(e.source_id)}">${escapeHTML(byId.get(e.source_id).title)} · ${formatPercent(byId.get(e.source_id).mastery)}</button>` : `<span class="muted">${escapeHTML(e.source_id)}（缺失）</span>`).join("") : '<span class="muted">暂无已记录的前置依赖</span>'}${n.blockers.length ? `<p>前置知识尚未就绪：${n.blockers.map(x => escapeHTML(byId.get(x)?.title || x)).join("、")}。建议先补强这些概念。</p>` : ""}${n.file_path ? `<div class="detail-label">本地笔记路径（仅显示，不会自动打开）</div><div class="detail-path">${escapeHTML(n.file_path)}</div>` : ""}<p>此工作台为只读快照；请在命令行复习中评分，之后重新生成。</p>`;
    if (!$("detail-dialog").open) $("detail-dialog").showModal();
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
  // Timers use a deadline so background-tab throttling cannot accumulate drift.
  let duration = 25 * 60;
  let remaining = duration;
  let deadline = null;
  function renderTimer() {
    if (deadline !== null) {
      remaining = Math.max(0, Math.ceil((deadline - Date.now()) / 1000));
      if (!remaining) { deadline = null; $("timer-status").textContent = "这段专注完成了。起来走走，再继续。"; toast("专注计时结束。记得休息，也别忘了在复习入口记录评分。"); }
    }
    $("timer-text").textContent = `${String(Math.floor(remaining / 60)).padStart(2,"0")}:${String(remaining % 60).padStart(2,"0")}`;
    $("timer-toggle").textContent = deadline !== null ? "暂停" : remaining === duration ? "开始计时" : remaining === 0 ? "再来一轮" : "继续";
  }
  function resetTimer() { deadline = null; duration = Number($("timer-duration").value)*60; remaining = duration; $("timer-status").textContent = "一次只做一件事，就很好。"; renderTimer(); }
  function startTimer() { if (remaining === 0) remaining = duration; deadline = Date.now()+remaining*1000; $("timer-status").textContent = "专注当下。把其他事情，留给稍后。"; renderTimer(); }
  $("timer-toggle").addEventListener("click", () => {if (deadline !== null) {renderTimer(); deadline = null; $("timer-status").textContent = "已暂停，准备好后再继续。"; renderTimer();} else startTimer();});
  $("timer-reset").addEventListener("click", resetTimer);
  $("timer-duration").addEventListener("change", resetTimer);
  $("start-focus").addEventListener("click", () => {if (!plan.length) return; if (deadline === null) startTimer(); openDetail(plan[0].note_id);});
  setInterval(renderTimer, 250);
  document.addEventListener("visibilitychange", renderTimer);
  window.addEventListener("beforeunload", event => {if (deadline !== null) {event.preventDefault(); event.returnValue = "";}});
  $("export-plan").addEventListener("click", () => {
    const lines = [`Study Planner · ${data.today}`, data.demo ? "合成示例计划，不是真实学习数据" : "只读快照计划，不会写入笔记", `时间预算：${budget} 分钟（估算）`, "", ...plan.map((n,i) => `${i+1}. ${n.title.replace(/[\r\n]+/g," ")} | ${label(n)} | 约 ${n.minutes} 分钟`), "", "请使用原有命令行复习入口记录评分。"];
    const blob = new Blob([lines.join("\n")], {type:"text/plain;charset=utf-8"});
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a"); link.href = url; link.download = `study-plan-${data.today}.txt`; link.click(); setTimeout(() => URL.revokeObjectURL(url), 1000);
    toast("学习计划已导出为文本文件。");
  });
  $("calendar-chart").innerHTML = data.calendar.map(([day,count]) => `<span class="heat-cell l${count === 0 ? 0 : count < 3 ? 1 : count < 5 ? 2 : count < 8 ? 3 : 4}" title="${day} · ${count} 次复习"></span>`).join("");
  const activity = data.calendar.reduce((sum,[,count]) => sum+count, 0);
  $("activity-total").textContent = `${activity} 次`;
  $("calendar-chart").setAttribute("aria-label", `截至 ${data.today} 的最近 84 天，共 ${activity} 次复习。每列连续七天。`);
  const familiar = learnable.filter(n => n.mastery >= Math.min(.3,data.threshold) && n.mastery < data.threshold).length;
  const learning = learnable.length-mastered-familiar;
  const first = learnable.length ? mastered/learnable.length*100 : 0;
  const second = learnable.length ? (mastered+familiar)/learnable.length*100 : 0;
  $("distribution-chart").innerHTML = `<div class="donut" role="img" aria-label="已掌握 ${mastered} 个，熟悉中 ${familiar} 个，待巩固 ${learning} 个" style="background:conic-gradient(${colors[0]} 0% ${first}%,${colors[1]} ${first}% ${second}%,${colors[2]} ${second}% 100%)"><div class="donut-hole"><strong>${formatPercent(avg)}</strong><small>平均掌握度</small></div></div>`;
  $("mastery-legend").innerHTML = [[`已掌握 · ≥ ${formatPercent(data.threshold)}`,mastered],["熟悉中",familiar],["待巩固",learning]].map(([name,count],i) => `<div class="legend-row"><span class="legend-dot" style="background:${colors[i]}"></span>${name}<strong>${count} 个</strong></div>`).join("");
  const maxForecast = Math.max(1,...data.forecast.map(d => d[1]));
  $("forecast-chart").innerHTML = data.forecast.map(([day,count]) => `<div class="bar-column"><span>${count}</span><i style="height:${count/maxForecast*150}px" aria-hidden="true"></i><small>${day.slice(5)}</small></div>`).join("");
  $("rating-chart").innerHTML = data.ratings.map(([name,count]) => `<div class="insight-row"><span>${name}</span><strong>${count} 次</strong></div>`).join("");
  $("mastery-chart").innerHTML = data.changes.length ? data.changes.map(n => `<div class="insight-row"><span>${escapeHTML(n.title)}</span><strong>${formatPercent(n.before)} → ${formatPercent(n.after)}</strong></div>`).join("") : '<div class="empty">至少两次复习后，才能观察变化。</div>';
  const relations = data.edges.filter(e => e.edge_type === "prerequisite" && byId.has(e.source_id) && byId.has(e.target_id));
  $("graph-chart").innerHTML = relations.length ? relations.slice(0,8).map(e => `<div class="relation-row"><button data-note="${escapeHTML(e.source_id)}">${escapeHTML(byId.get(e.source_id).title)}</button><span>→</span><button data-note="${escapeHTML(e.target_id)}">${escapeHTML(byId.get(e.target_id).title)}</button></div>`).join("") + (relations.length > 8 ? '<p class="muted">显示前 8 组关系。完整前置关系可在概念详情中查看。</p>' : "") : '<div class="empty">还没有前置知识关系。</div>';
  renderPlan();
  renderLibrary();
  setView(location.hash.slice(1) || "today");
  renderTimer();
})();
