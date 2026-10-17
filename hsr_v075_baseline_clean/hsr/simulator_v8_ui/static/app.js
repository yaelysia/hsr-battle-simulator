const state = {
  cases: [],
  catalog: null,
  report: null,
  selectedSkill: null,
  selectedUnitId: "",
  selectedEventIndex: null,
  detailMode: "view",
  session: null,
  busy: false,
  examples: [],
  buildOptions: null,
  lightCones: null,
  relicTemplates: null,
  relicSlots: [],
  relicAffixes: {},
  characters: null,
  buildPreviewSource: "",
  selectedTargets: [],
  observationIdentity: null,
};

const el = (id) => document.getElementById(id);

async function api(path, options = {}) {
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  const data = await response.json();
  if (!response.ok) {
    const error = new Error(data.error || response.statusText);
    error.status = response.status;
    throw error;
  }
  return data;
}

async function init() {
  try {
    const health = await api("/api/health");
    el("health").textContent = health.ok ? "已连接" : "未就绪";
    state.examples = (await api("/api/battle/examples")).examples || [];
    await loadCases();
    const current = await api("/api/battle");
    if (current.session_id) {
      acceptBattle(current);
      el("scenarioEditor").value = pretty(current.scenario);
      renderSetup();
      setMessage("已恢复当前战斗。服务重启前可下载战斗记录。", "ok");
      return;
    }
    if (state.cases.length) {
      const first = state.cases.find((item) => item.case_id === "example:arlan_vs_antimatter") || state.cases[0];
      el("caseSelect").value = first.case_id;
      el("caseId").value = first.case_id;
      await loadSelectedCase();
    } else {
      renderAll();
    }
  } catch (error) {
    setMessage(error.message, "bad");
  }
}

async function loadCases() {
  const data = await api("/api/cases");
  state.cases = isLive() ? [
    ...state.examples.map((item) => ({...item, case_id: `example:${item.case_id}`})),
    ...(data.cases || []),
  ] : (data.cases || []);
  const select = el("caseSelect");
  select.innerHTML = "";
  for (const item of state.cases) {
    const option = document.createElement("option");
    option.value = item.case_id;
    const labels = {
      "example:arlan_vs_antimatter": "阿兰 · 单人基础战斗",
      "example:arlan_fleet_vs_antimatter": "阿兰 · 仙舟两件套与速度鞋",
      "example:arlan_natasha_vs_antimatter": "阿兰＋娜塔莎 · 治疗",
      "example:serval_natasha_vs_antimatter": "希露瓦＋娜塔莎 · 感电与治疗",
      "example:arlan_serval_natasha_vs_antimatter": "阿兰＋希露瓦＋娜塔莎 · 三人队",
      "example:arlan_serval_natasha_two_waves": "三人队 · 两波开局清怪",
      "example:arlan_melee_two_waves": "三人队 · 两波近战兵交战",
      "example:serval_natasha_physical_break": "希露瓦＋娜塔莎 · 物理击破交战",
      "example:arlan_march_shield_counter": "阿兰＋三月七 · 护盾与反击",
      "example:arlan_lv20_vs_mixed_antimatter": "阿兰 Lv20 · 混合敌人",
    };
    option.textContent = labels[item.case_id] || `${item.case_id} (${item.route_count || 0})`;
    select.appendChild(option);
  }
}

async function loadSelectedCase() {
  if (state.busy) return;
  const caseId = el("caseSelect").value || el("caseId").value;
  if (!caseId) return;
  const source = el("scenarioEditor").value;
  const observationSource = el("observationsEditor").value;
  state.busy = true;
  renderAll();
  try {
    const example = state.examples.find((item) => `example:${item.case_id}` === caseId);
    const scenario = example ? example.scenario : await api(`/api/cases/${encodeURIComponent(caseId)}`);
    const observations = example ? {} : await api(`/api/observations/${encodeURIComponent(caseId)}`);
    if (el("scenarioEditor").value !== source || el("observationsEditor").value !== observationSource) { setMessage("配置或观测在加载期间发生变化，已保留当前编辑内容。", "warn"); return; }
    el("caseId").value = example ? example.case_id : caseId;
    el("scenarioEditor").value = pretty(scenario);
    el("observationsEditor").value = pretty(observations);
    state.selectedSkill = null;
    state.selectedUnitId = "";
    state.selectedEventIndex = null;
    state.detailMode = "view";
    setMessage(`已加载用例：${caseId}`, "ok");
    renderSetup();
    if (isLive()) setMessage("配置已载入。点击开始战斗；已有战斗只会在重新开战成功后替换。", "ok");
    else await runScenario({ quiet: true });
  } finally {
    state.busy = false;
    renderAll();
  }
}

async function saveCase() {
  if (state.busy) return;
  const caseId = el("caseId").value.trim();
  if (!caseId) throw new Error("需要填写用例编号");
  const source = el("scenarioEditor").value;
  const scenario = parseEditor("scenarioEditor");
  const observations = parseEditor("observationsEditor");
  const observationSource = el("observationsEditor").value;
  state.busy = true;
  renderAll();
  try {
    await api(`/api/cases/${encodeURIComponent(caseId)}`, {method: "PUT", body: JSON.stringify(scenario)});
    try {
      await api(`/api/observations/${encodeURIComponent(caseId)}`, {method: "PUT", body: JSON.stringify(observations)});
    } catch (error) { throw new Error(`配置已保存，但观测记录保存失败：${error.message}`); }
    await loadCases();
    el("caseSelect").value = caseId;
    setMessage(el("scenarioEditor").value === source && el("observationsEditor").value === observationSource ? `已保存用例：${caseId}` : `已保存点击时的配置与观测：${caseId}；之后的编辑尚未保存。`, "ok");
  } finally { state.busy = false; renderAll(); }
}

async function runScenario({ quiet = false } = {}) {
  if (isLive()) return startBattle();
  if (!state.catalog) state.catalog = await api("/api/catalog");
  const scenario = parseEditor("scenarioEditor");
  const observations = parseEditor("observationsEditor");
  const mode = "decision";
  if (!quiet) setMessage("正在运行...");
  const report = await api("/api/run", {
    method: "POST",
    body: JSON.stringify({
      scenario,
      observations,
      options: {
        mode,
        initialize_timeline: el("initTimeline").checked,
        include_raw_transition: true,
        write_tmp_report: el("writeTmp").checked,
      },
    }),
  });
  state.report = report;
  state.selectedSkill = null;
  renderAll();
  const ok = report.validation && report.validation.ok;
  setMessage(`运行${ok ? "通过" : "被阻塞"}：${report.scenario_id}`, ok ? "ok" : "warn");
}

function renderAll() {
  renderTimeline();
  renderBattlefield();
  renderActionPrompt();
  renderRouteList();
  renderEventReplay();
  renderDamageAudit();
  renderBlockedAudit();
  renderRunState();
  renderObservations();
  el("undoRouteBtn").hidden = isLive();
  el("setupPanel").hidden = !isLive();
  el("legacyRunOptions").hidden = isLive();
  el("runBtn").textContent = isLive() ? (state.session ? "按配置重新开战" : "开始战斗") : "运行路线";
  el("downloadBattleBtn").disabled = !state.session || state.busy;
  for (const id of ["battleMode", "loadCaseBtn", "saveCaseBtn", "runBtn", "refreshBattleBtn", "replayBattleBtn", "resumeBattleBtn", "prepareBuildsBtn", "loadLightConesBtn", "loadCharactersBtn"]) {
    el(id).disabled = state.busy;
  }
  el("setupFields").querySelectorAll("input, select, button").forEach((input) => { input.disabled = state.busy; });
  el("partyFormation").querySelectorAll("button, select").forEach((input) => { input.disabled = state.busy; });
  el("stagePanel").querySelectorAll("input, select, button").forEach((input) => { input.disabled = state.busy; });
  el("applyStageBtn").disabled = state.busy || !el("stageChoice").value;
  const forks = state.report?.fork_choices || [];
  el("forkPanel").hidden = !isLive() || !forks.length;
  el("forkChoice").disabled = state.busy;
  el("forkBattleBtn").disabled = state.busy || !forks.length;
}

function renderTimeline() {
  const report = state.report || {};
  const view = report.battlefield_view || {};
  const timeline = view.timeline || {};
  const actionValues = timeline.action_values || {};
  const current = view.current_unit_id || "";
  el("globalAv").textContent = `全局行动值 ${valueText(timeline.global_av)}`;
  const units = (view.units || []).slice().sort((a, b) => Number(a.action_value || 0) - Number(b.action_value || 0));
  el("timelineList").innerHTML = units.map((unit) => `
    <div class="timelineItem ${unit.unit_id === current ? "current" : ""}">
      <div class="eventTitle">
        <span>${escapeHtml(unit.display_name || unit.unit_id)}</span>
        <span class="cardSmall">${escapeHtml(unit.side || "")}</span>
      </div>
      <div class="cardSmall">单位行动值：${escapeHtml(valueText(actionValues[unit.unit_id] ?? unit.action_value))}</div>
      <div class="cardSmall">实体：${escapeHtml(unit.entity_ref || "")}</div>
    </div>
  `).join("") || emptyText("暂无行动条数据");

  const queues = timeline.queues || {};
  const rows = [];
  for (const [queueName, queueValue] of Object.entries(queues)) {
    if (Array.isArray(queueValue)) {
      for (const item of queueValue) {
        rows.push({ queueName, item });
      }
    } else {
      rows.push({ queueName, item: queueValue });
    }
  }
  el("queueList").innerHTML = rows.map(({ queueName, item }) => `
    <div class="queueItem">
      <div class="eventTitle">
        <span>${escapeHtml(queueName)}</span>
        <span class="cardSmall">${escapeHtml(queueLabel(item))}</span>
      </div>
      <div class="cardSmall">${escapeHtml(JSON.stringify(item))}</div>
    </div>
  `).join("") || emptyText("暂无队列项");
}

function renderBattlefield() {
  const view = (state.report && state.report.battlefield_view) || {};
  renderUnitRow("enemyRow", view.enemy_units || []);
  renderUnitRow("allyRow", view.ally_units || []);
}

function renderUnitRow(id, units) {
  el(id).innerHTML = units.map((unit) => unitCard(unit)).join("") || emptyText("暂无单位");
  el(id).querySelectorAll(".unitCard").forEach((card) => {
    card.addEventListener("click", () => handleUnitClick(card.dataset.unitId).catch((error) => setMessage(error.message, "bad")));
  });
}

function unitCard(unit) {
  const current = state.report && state.report.battlefield_view && state.report.battlefield_view.current_unit_id === unit.unit_id;
  const targetable = state.selectedSkill && isPromptTarget(unit.unit_id);
  const hpRatio = Math.max(0, Math.min(1, Number(unit.hp_ratio || 0)));
  return `
    <button class="unitCard ${escapeHtml(unit.side || "")} ${current ? "current" : ""} ${targetable ? "targetable" : ""} ${state.selectedUnitId === unit.unit_id ? "selected" : ""}" type="button" data-unit-id="${escapeHtml(unit.unit_id)}">
      <div class="unitName">
        <span>${escapeHtml(unit.display_name || unit.unit_id)}</span>
        <span class="cardSmall">${current ? "当前" : `站位 ${valueText(unit.position)}`}</span>
      </div>
      <div class="unitMeta">${escapeHtml(unit.unit_id)}</div>
      <div class="bar"><div class="barFill" style="width:${hpRatio * 100}%"></div></div>
      <div class="cardSmall">生命 ${escapeHtml(valueText(unit.hp))} / ${escapeHtml(valueText(unit.max_hp))}</div>
      <div class="unitStats">
        <span>能量 ${escapeHtml(valueText(unit.energy))}/${escapeHtml(valueText(unit.max_energy))}</span>
        <span>护盾 ${escapeHtml(valueText(unit.shield))}</span>
        <span>韧性 ${escapeHtml(valueText(unit.toughness))}/${escapeHtml(valueText(unit.max_toughness))}</span>
        <span>状态 ${escapeHtml(valueText(unit.status_count))}</span>
      </div>
    </button>
  `;
}

function renderActionPrompt() {
  const prompt = (state.report && state.report.action_prompt) || {};
  if (!state.report) {
    el("actionPrompt").innerHTML = `
      <div class="promptHeader">
        <h2>行动选择</h2>
        <span class="mutedText">选择场景并开始战斗</span>
      </div>
    `;
    return;
  }
  const slots = prompt.slots || [];
  const selected = state.selectedSkill;
  el("actionPrompt").innerHTML = `
    <div class="promptHeader">
      <h2>行动选择</h2>
      <span class="mutedText">${escapeHtml(prompt.current_unit_name || prompt.reason || "等待行动")}</span>
    </div>
    ${contentSupportHtml(state.report.content_support)}
    <div class="skillButtons">
      ${slots.map((slot) => skillButton(slot, selected)).join("")}
    </div>
    ${prompt.reason ? `<p>${escapeHtml(prompt.reason)}</p>` : ""}
    ${selected ? `<div class="targetHint">已选择 ${escapeHtml(selected.display_label || selected.label)}，请点击目标卡片。
      <span>已选：${escapeHtml(state.selectedTargets.join("、") || "无")}</span>
      ${selected.target_query.selection_max > 1 ? `<button id="confirmTargetsBtn" type="button"
        ${state.selectedTargets.length < selected.target_query.selection_min || state.selectedTargets.length > selected.target_query.selection_max ? "disabled" : ""}>提交所选目标</button>` : ""}
      <button id="cancelTargetsBtn" type="button">取消选择</button>
    </div>` : ""}
  `;
  el("actionPrompt").querySelectorAll("[data-skill-slot]").forEach((button) => {
    button.addEventListener("click", () => selectSkill(button.dataset.skillSlot).catch((error) => setMessage(error.message, "bad")));
  });
  el("cancelTargetsBtn")?.addEventListener("click", () => {
    state.selectedSkill = null; state.selectedTargets = []; renderActionPrompt(); renderBattlefield();
  });
  el("confirmTargetsBtn")?.addEventListener("click", () => appendRouteStepWithTargets(
    state.selectedSkill, state.selectedTargets, state.selectedTargets.join("、"),
  ).catch((error) => setMessage(error.message, "bad")));
}

function skillButton(slot, selected) {
  const disabled = !slot.available || state.busy;
  const isSelected = selected && selected.slot === slot.slot;
  const label = slot.display_label || slot.label || slot.slot;
  const reason = slot.blocked_reason || "当前不可选";
  return `
    <button
      class="skillButton ${isSelected ? "active" : ""}"
      type="button"
      data-skill-slot="${escapeHtml(slot.slot)}"
      ${disabled ? "disabled" : ""}
      title="${escapeHtml(disabled ? reason : `${slot.action_ref} 等级 ${slot.action_level}`)}"
    >
      ${escapeHtml(slot.actor_name || slot.actor_id || "")} · ${escapeHtml(label)}${!slot.available ? "：当前不可选" : ""}
    </button>
  `;
}

function renderRouteList() {
  let scenario = {};
  try {
    scenario = parseEditor("scenarioEditor");
  } catch {
    el("routeList").innerHTML = emptyText("测试用例 JSON 无法解析");
    return;
  }
  const route = isLive() ? ((state.report || {}).steps || []).map((step) => ({
    ...step.input_command, action_ref: step.input_command.action_id,
  })) : (scenario.route || []);
  el("routeList").innerHTML = route.map((step, index) => `
    <div class="routeItem">
      <div class="eventTitle">
        <span>第 ${index + 1} 步</span>
        <span class="cardSmall">${escapeHtml(step.source || "manual")}</span>
      </div>
      <div class="cardSmall">${escapeHtml(step.actor_id || "")}</div>
      <div><code>${escapeHtml(step.action_ref || "")}</code></div>
      <div class="cardSmall">目标：${escapeHtml((step.target_ids || []).join(", ") || "无")}</div>
    </div>
  `).join("") || emptyText("暂无路线");
}

function renderEventReplay() {
  const events = (state.report && state.report.event_replay_view) || [];
  const restored = state.report?.restored_operation_count || 0;
  const historyNote = restored ? `<p class="mutedText">已恢复 ${escapeHtml(restored)} 步归档。此处显示续打记录，下载归档包含恢复前的完整历史。</p>` : "";
  el("eventReplay").innerHTML = historyNote + (events.map((event, index) => `
    <button class="eventItem ${state.selectedEventIndex === index ? "selected" : ""}" type="button" data-event-index="${index}">
      <div class="eventTitle">
        <span>${escapeHtml(event.title || `第 ${index + 1} 步`)}</span>
        <span class="cardSmall">${escapeHtml(event.actor_id || "")}</span>
      </div>
      <div><code>${escapeHtml(event.action_id || "")}</code></div>
      <div class="cardSmall">目标：${escapeHtml((event.target_ids || []).join(", ") || "无")}</div>
      <span class="pill">伤害 ${escapeHtml(valueText(event.damage_count))}</span>
      <span class="pill">变更 ${escapeHtml(valueText(event.mutation_count))}</span>
      <span class="pill ${event.blocked_count ? "bad" : "ok"}">阻塞 ${escapeHtml(valueText(event.blocked_count))}</span>
      <span class="pill ${event.coverage_gap_count ? "warn" : "ok"}">缺口 ${escapeHtml(valueText(event.coverage_gap_count))}</span>
      <span class="pill">提示 ${escapeHtml(valueText(event.process_notice_count))}</span>
    </button>
  `).join("") || emptyText(restored ? "请选择动作继续战斗。" : "暂无事件"));
  el("eventReplay").querySelectorAll("[data-event-index]").forEach((button) => {
    button.addEventListener("click", () => openEventDetail(Number(button.dataset.eventIndex)).catch((error) => setMessage(error.message, "bad")));
  });
  const selected = el("forkChoice").value;
  const choices = state.report?.fork_choices || [];
  el("forkChoice").innerHTML = choices.map((choice, index) => `<option value="${choice.operation_index}">
    ${index + 1}. ${escapeHtml(choice.actor_id)} · ${escapeHtml(choice.action_id)} · ${escapeHtml(choice.target_ids.join("、") || "无目标")}
    </option>`).join("");
  if (choices.some((choice) => String(choice.operation_index) === selected)) el("forkChoice").value = selected;
}

function renderDamageAudit() {
  const rows = [];
  for (const step of (state.report && state.report.steps) || []) {
    for (const record of step.damage_records || []) {
      rows.push({ step, record });
    }
  }
  el("damageAudit").innerHTML = rows.map(({ step, record }) => `
    <div class="auditItem">
      <div class="eventTitle">
        <span>第 ${Number(step.route_index) + 1} 步</span>
        <span class="cardSmall">${escapeHtml(record.record_type || "")}</span>
      </div>
      <div>最终伤害：<strong>${escapeHtml(valueText(record.final_damage ?? record.amount))}</strong></div>
      <div class="cardSmall">生命：${escapeHtml(valueText(record.target_before_hp))} -> ${escapeHtml(valueText(record.target_after_hp))}</div>
      <div class="cardSmall">公式族：${escapeHtml(record.damage_formula_family || "")}</div>
    </div>
  `).join("") || emptyText("暂无伤害记录");
}

function renderBlockedAudit() {
  const report = state.report || {};
  const blocked = report.blocked_records || [];
  const gaps = report.coverage_gap_records || [];
  const notices = report.process_notice_records || [];
  el("blockedAudit").innerHTML = `
    ${auditGroupHtml("真正阻塞", blocked, "bad", "没有真正阻塞")}
    ${auditGroupHtml("覆盖缺口", gaps, "warn", "没有覆盖缺口")}
    ${auditGroupHtml("过程提示", notices, "", "没有过程提示")}
    ${auditCheckSummaryHtml()}
  `;
}

function renderRunState() {
  if (!state.report) {
    el("runState").textContent = "未运行";
    return;
  }
  const ok = state.report.validation && state.report.validation.ok;
  const steps = state.report.steps || [];
  if (isLive()) {
    const outcome = {victory: "胜利", defeat: "败北"}[state.report.outcome];
    el("runState").textContent = `${outcome || "战斗中"} · ${steps.length} 次提交`;
    return;
  }
  const blocked = (state.report.blocked_records || []).length;
  const gaps = (state.report.coverage_gap_records || []).length;
  const skips = (state.report.auto_skip_records || []).length;
  el("runState").textContent = `${ok ? "通过" : "阻塞"}，${steps.length} 步，阻塞 ${blocked}，缺口 ${gaps}，跳过敌方 ${skips}`;
}

async function selectSkill(slotName) {
  if (state.busy) return;
  const prompt = (state.report && state.report.action_prompt) || {};
  const slot = (prompt.slots || []).find((item) => item.slot === slotName);
  if (!slot || !slot.available) {
    setMessage(slot ? slot.blocked_reason || "动作槽位未接通" : "找不到动作槽位", "warn");
    return;
  }
  const query = slot.target_query || null;
  if (!query) {
    await appendRouteStepWithTargets(slot, [], "无目标控制动作");
    return;
  }
  const candidateIds = Array.isArray(query.candidate_ids) ? query.candidate_ids.filter(Boolean) : [];
  if (query.selection_mode === "automatic") {
    await appendRouteStepWithTargets(slot, [], "内核自动目标组");
    return;
  }
  if (!candidateIds.length) {
    setMessage("内核没有返回合法候选目标", "warn");
    return;
  }
  state.selectedSkill = slot;
  state.selectedTargets = [];
  setMessage(`已选择 ${slot.display_label || slot.label}，请选择目标`, "ok");
  renderActionPrompt();
  renderBattlefield();
}

async function handleUnitClick(unitId) {
  if (state.busy) return;
  const unit = findBattlefieldUnit(unitId);
  if (!unit) return;
  if (state.selectedSkill) {
    if (!isPromptTarget(unit.unit_id)) {
      setMessage("当前单位不是这个动作的合法候选目标", "warn");
      return;
    }
    if (state.selectedSkill.target_query.selection_max > 1) {
      state.selectedTargets = state.selectedTargets.includes(unitId)
        ? state.selectedTargets.filter((id) => id !== unitId) : [...state.selectedTargets, unitId];
      renderActionPrompt();
      return;
    }
    await appendRouteStep(state.selectedSkill, unit);
    return;
  }
  openUnitDetail(unitId);
}

async function appendRouteStep(slot, targetUnit) {
  await appendRouteStepWithTargets(slot, [targetUnit.unit_id], targetUnit.display_name || targetUnit.unit_id);
}

async function appendRouteStepWithTargets(slot, targetIds, targetLabel) {
  if (isLive()) {
    if (!slot.command_template) throw new Error("内核没有返回命令模板，请刷新战斗。");
    return battleRequest("/api/battle/submit", {
      ...battleIdentity(), decision_id: state.report.decision.token?.decision_id,
      command: {...slot.command_template, target_ids: targetIds},
    }, "正在结算动作…");
  }
  const actorId = slot.actor_id || "";
  if (!actorId || !slot.action_ref || slot.action_level === undefined || slot.action_level === null) {
    setMessage("动作槽位未接通，未生成路线", "warn");
    return;
  }
  const scenario = parseEditor("scenarioEditor");
  scenario.route = Array.isArray(scenario.route) ? scenario.route : [];
  const {action_id: actionId, ...template} = slot.command_template;
  scenario.route.push({
    ...template,
    action_ref: actionId,
    target_ids: targetIds,
  });
  el("scenarioEditor").value = pretty(scenario);
  state.selectedSkill = null;
  setMessage(`已追加路线：${slot.actor_name || actorId} 使用 ${slot.display_label || slot.label} -> ${targetLabel}`, "ok");
  await runScenario({ quiet: true });
}

function isPromptTarget(unitId) {
  const query = (state.selectedSkill && state.selectedSkill.target_query) || {};
  return query.selection_mode === "explicit"
    && Array.isArray(query.candidate_ids)
    && query.candidate_ids.includes(unitId);
}

function undoRouteStep() {
  const scenario = parseEditor("scenarioEditor");
  if (!Array.isArray(scenario.route) || scenario.route.length <= 1) {
    setMessage("至少保留一步路线，避免当前 v8 scenario 校验失败", "warn");
    return;
  }
  scenario.route.pop();
  el("scenarioEditor").value = pretty(scenario);
  runScenario({ quiet: true }).catch((error) => setMessage(error.message, "bad"));
}

function openUnitDetail(unitId) {
  const unit = findBattlefieldUnit(unitId);
  if (!unit) return;
  state.selectedUnitId = unitId;
  state.selectedEventIndex = null;
  state.detailMode = "view";
  renderUnitDetail(unitId);
  openDrawer();
  renderBattlefield();
  renderEventReplay();
}

function renderUnitDetail(unitId) {
  const unit = findBattlefieldUnit(unitId);
  if (!unit) return;
  const source = latestPanelSource(unitId);
  el("drawerTitle").textContent = unit.display_name || unit.unit_id;
  el("drawerSubtitle").textContent = `${unit.unit_id} / ${unit.entity_ref}`;
  const modeButtons = isLive() ? "" : `
    <div class="drawerTabs">
      <button class="${state.detailMode === "view" ? "active" : ""}" type="button" data-unit-mode="view">查看</button>
      <button class="${state.detailMode === "edit" ? "active" : ""}" type="button" data-unit-mode="edit">编辑</button>
    </div>
  `;
  el("drawerContent").innerHTML = state.detailMode === "edit"
    ? `${modeButtons}${unitEditHtml(unit)}`
    : `
    ${modeButtons}
    <div class="statGrid">
      ${stat("生命值", `${valueText(unit.hp)} / ${valueText(unit.max_hp)}`)}
      ${stat("能量", `${valueText(unit.energy)} / ${valueText(unit.max_energy)}`)}
      ${stat("护盾", unit.shield)}
      ${stat("可回复生命", unit.recoverable_hp)}
      ${stat("韧性", `${valueText(unit.toughness)} / ${valueText(unit.max_toughness)}`)}
      ${stat("行动值", unit.action_value)}
      ${stat("状态数量", unit.status_count)}
      ${stat("修正数量", unit.modifier_count)}
    </div>
    ${panelDetailHtml(unit.panel || {})}
    ${panelSourceHtml(source)}
    ${rawDetails("高级调试：单位完整摘要", unit)}
  `;
  el("drawerContent").querySelectorAll("[data-unit-mode]").forEach((button) => {
    button.addEventListener("click", () => {
      state.detailMode = button.dataset.unitMode || "view";
      renderUnitDetail(unitId);
    });
  });
  const applyButton = el("applyUnitEditBtn");
  if (applyButton) {
    applyButton.addEventListener("click", () => applyUnitEdit(unitId).catch((error) => setMessage(error.message, "bad")));
  }
}

async function openEventDetail(index) {
  const event = ((state.report || {}).event_replay_view || [])[index];
  if (!event) return;
  let step = event.event_kind === "route_step"
    ? ((state.report || {}).steps || []).find((item) => item.route_index === event.route_index)
    : null;
  if (isLive() && step) {
    const query = new URLSearchParams(battleIdentity());
    step = await api(`/api/battle/steps/${step.route_index}?${query}`);
  }
  state.selectedEventIndex = index;
  state.selectedUnitId = "";
  el("drawerTitle").textContent = event.title || `第 ${index + 1} 步`;
  el("drawerSubtitle").textContent = `${event.actor_id || ""} 使用 ${event.action_id || ""}`;
  if (!step) {
    el("drawerContent").innerHTML = `
      <div class="statGrid">
        ${stat("事件类型", event.event_kind)}
        ${stat("行动者", event.actor_id)}
        ${stat("临时行为", event.temporary_until_enemy_ai ? "是" : "否")}
        ${stat("后续待接", event.todo || "无")}
        ${stat("产生变更", event.mutation_count)}
      </div>
      ${noticeRecordsHtml("过程提示", event.process_notice_records || [])}
      ${rawDetails("高级调试：事件摘要", event)}
    `;
    openDrawer();
    renderBattlefield();
    renderEventReplay();
    return;
  }
  el("drawerContent").innerHTML = `
    <div class="statGrid">
      ${stat("动作等级", event.action_level)}
      ${stat("目标", (event.target_ids || []).join(", ") || "无")}
      ${stat("伤害记录", event.damage_count)}
      ${stat("首条伤害", event.first_damage ?? "无")}
      ${stat("状态变更", event.mutation_count)}
      ${stat("真正阻塞", event.blocked_count)}
      ${stat("覆盖缺口", event.coverage_gap_count)}
      ${stat("过程提示", event.process_notice_count)}
      ${stat("来源审计", passText(step.source_audit?.ok))}
      ${stat("快照回放", passText(step.replay?.ok))}
    </div>
    ${commandDetailHtml(step.input_command || {})}
    ${damageDetailHtml(step.damage_records || [])}
    ${recordBundleHtml("状态变化", step.status_records || [])}
    ${recordBundleHtml("资源变化", step.resource_records || [])}
    ${timelineDetailHtml(step.timeline_queue_records || [])}
    ${noticeRecordsHtml("真正阻塞", step.blocked_records || [])}
    ${noticeRecordsHtml("覆盖缺口", step.coverage_gap_records || [])}
    ${noticeRecordsHtml("过程提示", step.process_notice_records || [])}
    ${auditResultHtml(step)}
    ${rawDetails(isLive() ? "结算摘要（完整证据见战斗记录）" : "高级调试：原始 transition", step.transition || {})}
  `;
  openDrawer();
  renderBattlefield();
  renderEventReplay();
}

function panelDetailHtml(panel) {
  const core = panel.core_stats || {};
  const hp = panel.hp || {};
  const energy = panel.energy || {};
  const derived = panel.derived_stats || {};
  const toughness = panel.toughness_state || {};
  const resources = panel.resources || {};
  return `
    <h3>面板数值</h3>
    <div class="statGrid">
      ${stat("生命值", `${valueText(hp.current)} / ${valueText(hp.maximum)}`)}
      ${stat("攻击力", core.attack)}
      ${stat("防御力", core.defense)}
      ${stat("速度", core.speed)}
      ${stat("能量", `${valueText(energy.current)} / ${valueText(energy.maximum)}`)}
      ${stat("韧性", `${valueText(toughness.current)} / ${valueText(toughness.maximum)}`)}
      ${stat("暴击率", derived.critical_chance)}
      ${stat("暴击伤害", derived.critical_damage)}
      ${stat("增伤", derived.damage_added_ratio)}
      ${stat("效果命中", derived.effect_hit_rate)}
      ${stat("效果抵抗", derived.effect_resistance)}
      ${stat("击破特攻", derived.break_damage_added_ratio)}
    </div>
    ${statusTableHtml(panel.status_details || [], panel.statuses || [])}
    ${modifierTableHtml(panel.modifiers || [])}
    ${kvTable("资源明细", Object.entries(resources).map(([key, value]) => [resourceLabel(key), value]))}
  `;
}

function damageDetailHtml(records) {
  if (!records.length) return "<h3>伤害审计</h3><p>暂无伤害记录</p>";
  return `
    <h3>伤害审计</h3>
    ${records.map((record) => `
      <div class="auditItem">
        <div class="eventTitle">
          <span>${escapeHtml(record.record_type || "")}</span>
          <span class="cardSmall">${escapeHtml(record.mutation_id || "过程记录")}</span>
        </div>
        <div class="statGrid">
          ${stat("最终伤害", record.final_damage ?? record.amount)}
          ${stat("公式族", record.damage_formula_family)}
          ${stat("攻击类型", record.attack_type)}
          ${stat("属性", record.element_type)}
          ${stat("目标生命", `${valueText(record.target_before_hp)} -> ${valueText(record.target_after_hp)}`)}
          ${stat("mutation", record.mutation_id || "过程记录")}
        </div>
        ${kvObjectTable("公式结果", record.formula_result || {})}
        ${kvObjectTable("缩放", record.scaling || {})}
        ${kvObjectTable("倍率", record.multipliers || {})}
        ${kvObjectTable("暴击", record.crit_resolution || {})}
        ${ledgerHtml(record.modifier_ledger || {})}
        ${kvObjectTable("数值求值", record.numeric_evaluation || {})}
        ${sourceFrameHtml(record.source_frame || {})}
        ${sourceTraceHtml("来源追踪", record.trace || {})}
      </div>
    `).join("")}
  `;
}

function unitEditHtml(unit) {
  const scenarioUnit = scenarioUnitFor(unit.unit_id) || {};
  const buildMode = scenarioUnit.build_mode || "kernel_fixture";
  if (buildMode === "assembled_character_build") {
    const build = scenarioUnit.character_build || {};
    return `
      <h3>角色构筑模式</h3>
      <p><strong>assembled_character_build</strong></p>
      <p class="mutedText">正式面板由角色构筑装配结果生成；此 JSON 工作台仅展示构筑身份，不提供面板或行迹开关编辑。</p>
      ${kvTable("构筑身份", [
        ["构筑 ID", build.build_id || "—"],
        ["角色卡", build.character_card_id || "—"],
        ["输入 fingerprint", build.input_fingerprint || "—"],
      ])}
    `;
  }
  const panel = scenarioUnit.panel || {};
  const resources = panel.resources || {};
  const flags = panel.flags || {};
  const traceNodes = traceNodesForUnit(unit);
  const enabled = new Set(asArray(flags.enabled_trace_node_ids));
  const disabled = new Set(asArray(flags.disabled_trace_node_ids));
  const field = (label, name, value, step = "1") => `
    <label class="editField">
      <span>${escapeHtml(label)}</span>
      <input data-edit-field="${escapeHtml(name)}" type="number" step="${escapeHtml(step)}" value="${escapeHtml(editValue(value))}">
    </label>
  `;
  const panelField = (label, name, value, step = "1") => `
    <label class="editField">
      <span>${escapeHtml(label)}</span>
      <input data-edit-panel="${escapeHtml(name)}" type="number" step="${escapeHtml(step)}" value="${escapeHtml(editValue(value))}">
    </label>
  `;
  const resourceField = (label, key, value, step = "0.0001") => `
    <label class="editField">
      <span>${escapeHtml(label)}</span>
      <input data-edit-resource="${escapeHtml(key)}" type="number" step="${escapeHtml(step)}" value="${escapeHtml(editValue(value))}">
    </label>
  `;
  const readonlyResourceField = (label, value) => `
    <label class="editField">
      <span>${escapeHtml(label)}</span>
      <input type="number" value="${escapeHtml(editValue(value))}" readonly>
    </label>
  `;
  return `
    <h3>单位基础</h3>
    <div class="editGrid">
      ${field("等级", "level", scenarioUnit.level ?? unit.level)}
      ${field("星魂", "eidolon_level", scenarioUnit.eidolon_level ?? 0)}
      ${field("站位", "position", scenarioUnit.position ?? unit.position)}
    </div>
    <h3>面板覆盖</h3>
    <div class="editGrid">
      ${panelField("当前生命", "hp", panel.hp ?? unit.hp)}
      ${panelField("生命上限", "max_hp", panel.max_hp ?? unit.max_hp)}
      ${panelField("攻击力", "attack", panel.attack ?? (unit.panel || {}).core_stats?.attack)}
      ${panelField("防御力", "defense", panel.defense ?? (unit.panel || {}).core_stats?.defense)}
      ${panelField("速度", "speed", panel.speed ?? (unit.panel || {}).core_stats?.speed, "0.0001")}
      ${panelField("当前能量", "energy", panel.energy ?? unit.energy, "0.0001")}
      ${panelField("能量上限", "max_energy", panel.max_energy ?? unit.max_energy, "0.0001")}
      ${panelField("当前韧性", "toughness", panel.toughness ?? unit.toughness, "0.0001")}
      ${panelField("韧性上限", "max_toughness", panel.max_toughness ?? unit.max_toughness, "0.0001")}
      ${panelField("行动值", "action_value", panel.action_value ?? unit.action_value, "0.0001")}
    </div>
    <h3>资源与抗性</h3>
    <div class="editGrid">
      ${readonlyResourceField("护盾（实例汇总，只读）", unit.shield)}
      ${resourceField("可回复生命", "recoverable_hp", resources.recoverable_hp ?? unit.recoverable_hp)}
      ${resourceField("暴击率", "critical_chance", resources.critical_chance)}
      ${resourceField("暴击伤害", "critical_damage", resources.critical_damage)}
      ${resourceField("增伤", "damage_added_ratio", resources.damage_added_ratio)}
      ${resourceField("击破特攻", "break_damage_added_ratio", resources.break_damage_added_ratio)}
      ${resourceField("效果命中", "effect_hit_rate", resources.effect_hit_rate)}
      ${resourceField("效果抵抗", "effect_resistance", resources.effect_resistance)}
      ${resourceField("击破延后", "break_delay", resources.break_delay)}
    </div>
    <div class="editGrid">
      <label class="editField wide">
        <span>弱点列表，用逗号或换行分隔</span>
        <textarea id="editWeaknesses">${escapeHtml(asArray(flags.weaknesses).join(", "))}</textarea>
      </label>
      <label class="editField wide">
        <span>初始状态，用逗号或换行分隔</span>
        <textarea id="editStatuses">${escapeHtml(asArray(panel.statuses).join(", "))}</textarea>
      </label>
    </div>
    ${traceEditHtml(traceNodes, enabled, disabled)}
    <div class="drawerActions">
      <button id="applyUnitEditBtn" type="button">应用并重新运行</button>
    </div>
  `;
}

function traceEditHtml(traceNodes, enabled, disabled) {
  if (!traceNodes.length) return "<h3>行迹</h3><p class=\"mutedText\">当前实体没有可编辑行迹节点。</p>";
  return `
    <h3>行迹</h3>
    <div class="traceGrid">
      ${traceNodes.map((node) => {
        const checked = enabled.has(node.trace_node_id) || (node.default_enabled && !disabled.has(node.trace_node_id));
        const mapped = (node.mapped_terms || []).map((term) => `${term.target_key || "属性"} ${valueText(term.value)}`).join("，");
        return `
          <label class="traceItem ${node.available ? "" : "disabledTrace"}">
            <input data-edit-trace="${escapeHtml(node.trace_node_id)}" type="checkbox" ${checked ? "checked" : ""}>
            <span>
              <strong>${escapeHtml(node.trace_id || node.trace_node_id)}</strong>
              <em>${escapeHtml(node.trace_kind || "trace")}${node.default_enabled ? " / 默认启用" : ""}</em>
              <small>${escapeHtml(mapped || node.blocked_reason || "无属性映射")}</small>
            </span>
          </label>
        `;
      }).join("")}
    </div>
  `;
}

async function applyUnitEdit(unitId) {
  const scenario = parseEditor("scenarioEditor");
  const unit = (scenario.units || []).find((item) => item && item.unit_id === unitId);
  if (!unit) throw new Error(`找不到单位：${unitId}`);
  if ((unit.build_mode || "kernel_fixture") !== "kernel_fixture") {
    throw new Error("正式角色构筑只能通过 JSON 构筑输入修改，不能写入旧面板或行迹 flags");
  }
  unit.panel = unit.panel || {};
  unit.panel.resources = unit.panel.resources || {};
  unit.panel.flags = unit.panel.flags || {};

  document.querySelectorAll("[data-edit-field]").forEach((input) => {
    const key = input.dataset.editField;
    const value = numberInputValue(input);
    if (key) unit[key] = key === "level" || key === "eidolon_level" || key === "position" ? Math.trunc(value) : value;
  });
  document.querySelectorAll("[data-edit-panel]").forEach((input) => {
    const key = input.dataset.editPanel;
    if (key) unit.panel[key] = numberInputValue(input);
  });
  document.querySelectorAll("[data-edit-resource]").forEach((input) => {
    const key = input.dataset.editResource;
    if (!key) return;
    const raw = input.value.trim();
    if (raw === "") {
      delete unit.panel.resources[key];
    } else {
      unit.panel.resources[key] = Number(raw);
    }
  });
  unit.panel.statuses = splitList(el("editStatuses") ? el("editStatuses").value : "");
  const weaknesses = splitList(el("editWeaknesses") ? el("editWeaknesses").value : "");
  if (weaknesses.length) {
    unit.panel.flags.weaknesses = weaknesses;
  } else {
    delete unit.panel.flags.weaknesses;
  }

  const traceNodes = traceNodesForUnit(findBattlefieldUnit(unitId) || {});
  const checked = new Set(
    Array.from(document.querySelectorAll("[data-edit-trace]"))
      .filter((input) => input.checked)
      .map((input) => input.dataset.editTrace)
      .filter(Boolean)
  );
  unit.panel.flags.enabled_trace_node_ids = Array.from(checked).sort();
  unit.panel.flags.disabled_trace_node_ids = traceNodes
    .filter((node) => node.default_enabled && !checked.has(node.trace_node_id))
    .map((node) => node.trace_node_id)
    .sort();

  el("scenarioEditor").value = pretty(scenario);
  state.detailMode = "view";
  await runScenario({ quiet: true });
  openUnitDetail(unitId);
  setMessage(`已应用单位编辑：${unitId}`, "ok");
}

function commandDetailHtml(command) {
  return kvTable("行动输入", [
    ["行动者", command.actor_id],
    ["动作", command.action_id],
    ["等级", command.action_level],
    ["目标", (command.target_ids || []).join(", ") || "无"],
    ["来源", command.source],
    ["队列", command.queue_name || "无"],
  ]);
}

function recordBundleHtml(title, bundles) {
  const rows = [];
  for (const bundle of bundles || []) {
    for (const record of bundle.records || []) {
      rows.push([
        record.record_type || "-",
        readableReason(record),
        record.mutation_id || "过程记录",
      ]);
    }
    for (const mutation of bundle.mutations || []) {
      rows.push([
        mutation.op || "mutation",
        (mutation.path || []).join("."),
        mutation.mutation_id || mutation.id || "-",
      ]);
    }
  }
  return simpleTable(title, ["类型", "原因/路径", "mutation"], rows, "暂无记录");
}

function timelineDetailHtml(records) {
  const rows = [];
  for (const bundle of records || []) {
    for (const record of bundle.records || []) rows.push([record.record_type || "-", readableReason(record), record.mutation_id || "过程记录"]);
    for (const mutation of bundle.mutations || []) rows.push([mutation.op || "mutation", (mutation.path || []).join("."), mutation.mutation_id || mutation.id || "-"]);
  }
  return simpleTable("行动条与队列", ["类型", "说明", "mutation"], rows, "暂无行动条或队列记录");
}

function noticeRecordsHtml(title, records) {
  if (!records || !records.length) return `<h3>${escapeHtml(title)}</h3><p class="mutedText">暂无记录</p>`;
  return `
    <h3>${escapeHtml(title)}</h3>
    <div class="noticeList">
      ${records.map((record) => `
        <div class="noticeItem ${noticeClass(record.category || title)}">
          <div class="eventTitle">
            <span>${escapeHtml(record.record_type || record.reason || "记录")}</span>
            <span class="cardSmall">${escapeHtml(record.category || title)}</span>
          </div>
          <div>${escapeHtml(record.impact || readableReason(record) || "无说明")}</div>
          <div class="cardSmall">原因：${escapeHtml(record.reason || readableReason(record) || "-")}</div>
          <div class="cardSmall">产生 mutation：${escapeHtml(record.produced_mutation ? "是" : "否")}</div>
          ${record.temporary_until_enemy_ai ? "<span class=\"pill warn\">临时行为：等待敌方 AI 接回</span>" : ""}
          ${record.path ? `<div class="cardSmall">路径：${escapeHtml(record.path)}</div>` : ""}
        </div>
      `).join("")}
    </div>
  `;
}

function auditResultHtml(step) {
  const source = step.source_audit || {};
  const replay = step.replay || {};
  const traceability = step.settlement_traceability || {};
  const contract = step.contract || {};
  return `
    <h3>审计结果</h3>
    <div class="statGrid">
      ${stat("来源审计", passText(source.ok))}
      ${stat("快照回放", passText(replay.ok))}
      ${stat("结算追踪", passText(traceability.ok))}
      ${stat("契约检查", passText(contract.ok))}
    </div>
    ${simpleTable("审计错误", ["来源", "内容"], [
      ...(source.violations || []).map((item) => ["source_audit", item]),
      ...(replay.errors || []).map((item) => ["replay", item]),
      ...(traceability.errors || []).map((item) => ["settlement", item]),
      ...(contract.errors || []).map((item) => ["contract", item]),
    ], "暂无审计错误")}
  `;
}

function panelSourceHtml(source) {
  const unit = source.scenario_unit || {};
  const combatant = source.combatant_profile || {};
  const traceTerms = source.trace_static_stat_bonus_terms || [];
  const traceBlocked = source.trace_blocked_slots || [];
  const eidolon = source.eidolon || {};
  return `
    <h3>面板来源拆解</h3>
    <div class="statGrid">
      ${stat("场景等级", unit.level)}
      ${stat("场景星魂", unit.eidolon_level)}
      ${stat("档案来源", combatant.profile_id || "无")}
      ${stat("档案覆盖", combatant.coverage_status || "无")}
      ${stat("面板覆盖项", (source.panel_overrides || []).length)}
      ${stat("行迹加成项", traceTerms.length)}
      ${stat("行迹阻塞项", traceBlocked.length)}
      ${stat("启用星魂", (eidolon.enabled_ranks || []).join(", ") || "无")}
    </div>
    ${simpleTable("面板覆盖", ["字段", "数值"], (source.panel_overrides || []).map((item) => {
      const value = item && typeof item === "object" ? item : {};
      return [value.field || value.key || compactValue(item), value.value ?? ""];
    }), "暂无面板覆盖")}
    ${simpleTable("行迹静态加成", ["属性", "类型", "数值"], traceTerms.map((item) => {
      const value = item && typeof item === "object" ? item : {};
      return [value.target_key || "-", value.application_kind || "-", value.value];
    }), "暂无行迹静态加成")}
    ${noticeRecordsHtml("行迹缺口", traceBlocked.map((item) => ({
      record_type: item.mechanism_slot_id,
      category: "覆盖缺口",
      reason: item.blocked_reason,
      impact: "该行迹槽位未产生面板变更。",
      produced_mutation: false,
    })))}
    ${sourceTraceHtml("角色档案来源", combatant.source_trace || {})}
  `;
}

function statusTableHtml(details, statuses) {
  if (details.length) {
    return simpleTable("buff/debuff/status", ["状态", "层数", "持续", "来源"], details.map((item) => [
      item.status_id || item.id || item.name || "-",
      item.stack ?? item.stacks ?? "-",
      item.duration ?? item.remaining_duration ?? "-",
      item.source_id || item.source || "-",
    ]), "暂无状态");
  }
  return simpleTable("buff/debuff/status", ["状态"], asArray(statuses).map((item) => [item]), "暂无状态");
}

function modifierTableHtml(modifiers) {
  return simpleTable("modifier", ["名称", "目标", "数值", "来源"], (modifiers || []).map((item) => [
    item.modifier_id || item.id || item.name || "-",
    item.target_key || item.stat || "-",
    item.value ?? item.ratio ?? "-",
    item.source_id || item.source || "-",
  ]), "暂无 modifier");
}

function sourceFrameHtml(sourceFrame) {
  return kvTable("来源帧", Object.entries(sourceFrame || {}).map(([key, value]) => [sourceLabel(key), compactValue(value)]));
}

function sourceTraceHtml(title, trace) {
  if (!trace || typeof trace !== "object" || !Object.keys(trace).length) return `<h3>${escapeHtml(title)}</h3><p class="mutedText">暂无来源追踪</p>`;
  const source = trace.source || trace;
  return kvTable(title, [
    ["来源路径", source.source_path],
    ["原始类型", source.raw_type],
    ["原始编号", source.raw_id],
    ["证据", compactValue(source.evidence || trace.evidence || {})],
  ]);
}

function ledgerHtml(ledger) {
  const applied = asArray(ledger.applied || ledger.applied_terms);
  const skipped = asArray(ledger.skipped || ledger.skipped_terms);
  return `
    ${simpleTable("已应用修正项", ["名称", "类型", "数值"], applied.map((item) => [
      item.modifier_id || item.name || item.term_id || item.source_id || "-",
      item.kind || item.application_kind || item.bucket || "-",
      item.value ?? item.amount ?? item.applied_value ?? "-",
    ]), "暂无已应用修正项")}
    ${simpleTable("跳过修正项", ["名称", "原因", "来源"], skipped.map((item) => [
      item.modifier_id || item.name || item.term_id || "-",
      item.reason || item.blocked_reason || "-",
      item.source || item.source_id || "-",
    ]), "暂无跳过修正项")}
  `;
}

function kvObjectTable(title, value) {
  return kvTable(title, Object.entries(value || {}).map(([key, item]) => [sourceLabel(key), compactValue(item)]));
}

function kvTable(title, rows) {
  return simpleTable(title, ["项目", "数值"], (rows || []).filter((row) => row[1] !== undefined && row[1] !== null && row[1] !== ""), "暂无数据");
}

function simpleTable(title, headers, rows, emptyMessage) {
  if (!rows || !rows.length) return `<h3>${escapeHtml(title)}</h3><p class="mutedText">${escapeHtml(emptyMessage || "暂无数据")}</p>`;
  return `
    <h3>${escapeHtml(title)}</h3>
    <div class="tableWrap">
      <table>
        <thead><tr>${headers.map((header) => `<th>${escapeHtml(header)}</th>`).join("")}</tr></thead>
        <tbody>
          ${rows.map((row) => `<tr>${row.map((cell) => `<td>${escapeHtml(compactValue(cell))}</td>`).join("")}</tr>`).join("")}
        </tbody>
      </table>
    </div>
  `;
}

function auditGroupHtml(title, records, className, emptyMessage) {
  const shown = (records || []).slice(0, 6);
  return `
    <div class="auditGroup">
      <div class="eventTitle">
        <span>${escapeHtml(title)}</span>
        <span class="pill ${escapeHtml(className)}">${escapeHtml(valueText((records || []).length))}</span>
      </div>
      ${shown.length ? shown.map((record) => `
        <div class="auditMini">
          <div>${escapeHtml(record.record_type || record.reason || "记录")}</div>
          <div class="cardSmall">${escapeHtml(record.impact || record.reason || readableReason(record) || "-")}</div>
        </div>
      `).join("") : emptyText(emptyMessage)}
    </div>
  `;
}

function auditCheckSummaryHtml() {
  if (isLive()) return "<p>点击事件记录查看该步来源、结算和快照检查；整场一致性通过下载后的回放校验。</p>";
  const rows = [];
  for (const step of ((state.report || {}).steps || [])) {
    if (!(step.source_audit || {}).ok || !(step.replay || {}).ok || !(step.settlement_traceability || {}).ok || !(step.contract || {}).ok) {
      rows.push([
        `第 ${Number(step.route_index) + 1} 步`,
        passText((step.source_audit || {}).ok),
        passText((step.replay || {}).ok),
        passText((step.settlement_traceability || {}).ok),
        passText((step.contract || {}).ok),
      ]);
    }
  }
  return simpleTable("审计失败", ["步骤", "来源", "回放", "结算", "契约"], rows, "来源审计、快照回放、结算追踪和契约检查均通过");
}

function scenarioUnitFor(unitId) {
  try {
    const scenario = parseEditor("scenarioEditor");
    return (scenario.units || []).find((unit) => unit && unit.unit_id === unitId) || null;
  } catch {
    return null;
  }
}

function traceNodesForUnit(unit) {
  const catalog = state.catalog || {};
  const byEntity = catalog.trace_nodes_by_entity || {};
  return byEntity[unit.entity_ref] || [];
}

function numberInputValue(input) {
  const raw = input.value.trim();
  if (raw === "") return 0;
  const value = Number(raw);
  if (!Number.isFinite(value)) throw new Error(`数值无效：${raw}`);
  return value;
}

function splitList(text) {
  return String(text || "")
    .split(/[\n,，]+/)
    .map((item) => item.trim())
    .filter(Boolean);
}

function asArray(value) {
  if (Array.isArray(value)) return value;
  if (value === null || value === undefined || value === "") return [];
  return [value];
}

function compactValue(value) {
  if (value === null || value === undefined || value === "") return "-";
  if (typeof value === "number") return valueText(value);
  if (typeof value === "boolean") return value ? "是" : "否";
  if (typeof value === "string") return value;
  if (Array.isArray(value)) return value.map((item) => compactValue(item)).join(", ");
  if (typeof value === "object") {
    const keys = Object.keys(value);
    return keys.slice(0, 6).map((key) => `${sourceLabel(key)}=${compactValue(value[key])}`).join("；") + (keys.length > 6 ? "；..." : "");
  }
  return String(value);
}

function readableReason(record) {
  if (!record || typeof record !== "object") return "";
  const payload = record.payload || record.payload_summary || {};
  return record.reason || payload.reason || payload.blocked_reason || record.blocked_reason || "";
}

function noticeClass(category) {
  if (category === "真正阻塞") return "bad";
  if (category === "覆盖缺口") return "warn";
  return "";
}

function resourceLabel(key) {
  const labels = {
    shield: "护盾",
    recoverable_hp: "可回复生命",
    critical_chance: "暴击率",
    critical_damage: "暴击伤害",
    damage_added_ratio: "增伤",
    break_damage_added_ratio: "击破特攻",
    effect_hit_rate: "效果命中",
    effect_resistance: "效果抵抗",
    break_delay: "击破延后",
  };
  return labels[key] || key;
}

function sourceLabel(key) {
  const labels = {
    source_path: "来源路径",
    raw_type: "原始类型",
    raw_id: "原始编号",
    evidence: "证据",
    final_damage: "最终伤害",
    amount: "数值",
    ok: "是否通过",
    value: "数值",
    expression_kind: "表达式类型",
  };
  return labels[key] || key;
}

function latestPanelSource(unitId) {
  if (isLive()) return state.report?.panel_source_breakdown?.[unitId] || {};
  const steps = (state.report && state.report.steps) || [];
  for (let index = steps.length - 1; index >= 0; index -= 1) {
    const source = steps[index].panel_source_breakdown || {};
    if (source[unitId]) return source[unitId];
  }
  return {};
}

function findBattlefieldUnit(unitId) {
  const units = (state.report && state.report.battlefield_view && state.report.battlefield_view.units) || [];
  return units.find((unit) => unit.unit_id === unitId);
}

function openDrawer() {
  el("detailDrawer").classList.add("open");
}

function closeDrawer() {
  el("detailDrawer").classList.remove("open");
}

function parseEditor(id) {
  const data = JSON.parse(el(id).value || "{}");
  if (!data || typeof data !== "object" || Array.isArray(data)) {
    throw new Error(`${editorName(id)} 的根节点必须是对象`);
  }
  return data;
}

function setMessage(text, className = "") {
  const node = el("message");
  node.textContent = text;
  node.className = `message ${className}`;
}

function pretty(value) {
  return JSON.stringify(value, null, 2);
}

function rawDetails(title, value, open = false) {
  return `
    <details class="rawDetails" ${open ? "open" : ""}>
      <summary>${escapeHtml(title)}</summary>
      <pre>${escapeHtml(pretty(value))}</pre>
    </details>
  `;
}

function stat(label, value) {
  return `
    <div class="stat">
      <div class="label">${escapeHtml(label)}</div>
      <div class="value">${escapeHtml(valueText(value))}</div>
    </div>
  `;
}

function emptyText(text) {
  return `<p class="mutedText">${escapeHtml(text)}</p>`;
}

function valueText(value) {
  if (value === null || value === undefined || value === "") return "-";
  if (typeof value === "number" && Number.isFinite(value)) {
    return Number.isInteger(value) ? String(value) : String(Number(value.toFixed(4)));
  }
  return String(value);
}

function editValue(value) {
  if (value === null || value === undefined || value === "") return "";
  if (typeof value === "number" && Number.isFinite(value)) return String(value);
  return String(value);
}

function queueLabel(item) {
  if (!item || typeof item !== "object") return "";
  return item.window_family || item.queue_name || item.priority || item.actor_id || item.owner_id || "队列项";
}

function passText(value) {
  if (value === undefined || value === null) return "未检查";
  return value ? "通过" : "失败";
}

function editorName(id) {
  const names = {
    scenarioEditor: "测试用例",
    observationsEditor: "游戏观测对照",
  };
  return names[id] || id;
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll("\"", "&quot;")
    .replaceAll("'", "&#039;");
}

el("loadCaseBtn").addEventListener("click", () => loadSelectedCase().catch((error) => setMessage(error.message, "bad")));
el("saveCaseBtn").addEventListener("click", () => saveCase().catch((error) => setMessage(error.message, "bad")));
el("runBtn").addEventListener("click", () => runScenario().catch((error) => setMessage(error.message, "bad")));
el("undoRouteBtn").addEventListener("click", () => {
  try {
    undoRouteStep();
  } catch (error) {
    setMessage(error.message, "bad");
  }
});
el("closeDrawerBtn").addEventListener("click", closeDrawer);
el("scenarioEditor").addEventListener("input", () => {
  if (!isLive()) state.report = null;
  state.selectedSkill = null;
  renderSetup();
  renderAll();
});
document.querySelectorAll("input[name=mode], #initTimeline").forEach((input) => {
  input.addEventListener("change", () => runScenario({ quiet: true }).catch((error) => setMessage(error.message, "bad")));
});
el("caseSelect").addEventListener("change", () => {
  el("caseId").value = el("caseSelect").value;
});

function isLive() { return el("battleMode").value === "live"; }

function battleIdentity() {
  return state.session ? {session_id: state.session.session_id, revision: state.session.revision} : {};
}

const observationFields = {hp: "生命", energy: "能量", toughness: "韧性", shield: "护盾"};
const observationInput = (field) => el(`observation${field[0].toUpperCase()}${field.slice(1)}`);

function observationIsCurrent() {
  return !state.observationIdentity || (state.session
    && state.observationIdentity.session_id === state.session.session_id
    && state.observationIdentity.revision === state.session.revision);
}

function renderObservations() {
  el("observationPanel").hidden = !isLive();
  const units = state.report?.battlefield_view?.units || [];
  const selected = el("observationUnit").value;
  el("observationUnit").innerHTML = '<option value="">请选择当前单位</option>' + units.map((unit) =>
    `<option value="${escapeHtml(unit.unit_id)}">${escapeHtml(unit.display_name || unit.unit_id)} · ${escapeHtml(unit.unit_id)}</option>`).join("");
  el("observationUnit").value = units.some((unit) => unit.unit_id === selected) ? selected : "";
  const current = observationIsCurrent();
  el("observationMoment").textContent = !state.session ? "开始战斗后可记录当前局面。"
    : current ? `当前战斗 · 操作 ${state.session.revision}`
      : `战斗已变化；输入仍属于操作 ${state.observationIdentity.revision}。请清空数值后按当前时刻重新填写。`;
  el("observationPanel").querySelectorAll("input, select, button").forEach((input) => { input.disabled = state.busy; });
  el("compareObservationBtn").disabled = state.busy || !state.session || !current;
  try {
    const observations = parseEditor("observationsEditor");
    if (observations.comparisons !== undefined && !Array.isArray(observations.comparisons)) throw new Error("comparisons 必须是记录数组，请检查观测 JSON。");
    const records = observations.comparisons || [];
    // Ponytail: show the latest 20 records to bound DOM size; export retains all.
    el("observationResults").innerHTML = `<p>共 ${records.length} 条，显示最近 20 条。各记录保留写入时的对照结果。</p>` + records.slice(-20).reverse().map((record) => {
      if (!record || typeof record !== "object" || !record.measurements) return emptyText("记录格式无效，请检查观测 JSON。");
      const rows = Object.entries(record.measurements).filter(([key, value]) => observationFields[key] && value && typeof value === "object");
      return `<details><summary>${escapeHtml(record.scenario_id)} · ${escapeHtml(record.unit_id)} · 操作 ${escapeHtml(record.revision)}</summary>
        <p>${escapeHtml(record.captured_at)} · 游戏版本 ${escapeHtml(record.game_version || "未填写")}</p>
        <p>${escapeHtml(record.note || "")}</p><div class="tableWrap"><table>
        <caption>${escapeHtml(record.entity_ref)} 的数值对照</caption>
        <thead><tr><th scope="col">指标</th><th scope="col">模拟值</th><th scope="col">游戏观测</th><th scope="col">差值</th></tr></thead>
        <tbody>${rows.map(([field, value]) => `<tr><th scope="row">${observationFields[field]}</th><td>${escapeHtml(value.simulated)}</td><td>${escapeHtml(value.observed)}</td><td>${escapeHtml(value.difference)}</td></tr>`).join("")}</tbody></table></div></details>`;
    }).join("");
  } catch (error) { el("observationResults").textContent = error.message; }
}

function resetObservation() {
  for (const field of Object.keys(observationFields)) observationInput(field).value = "";
  state.observationIdentity = null;
  renderObservations();
}

async function compareObservation() {
  if (state.busy || !state.session || !isLive()) return;
  const source = el("observationsEditor").value;
  try {
    const observations = parseEditor("observationsEditor");
    if (observations.comparisons !== undefined && !Array.isArray(observations.comparisons)) throw new Error("comparisons 必须是记录数组，请检查观测 JSON。");
    if (!observationIsCurrent()) throw new Error("战斗已变化，请清空数值后按当前时刻重新填写。");
    const observed = Object.fromEntries(Object.keys(observationFields).map((field) =>
      [field, observationInput(field).value.trim()]).filter(([, value]) => value !== ""));
    if (!el("observationUnit").value || !Object.keys(observed).length) throw new Error("请选择单位，并至少填写一个游戏数值。");
    const request = {...battleIdentity(), unit_id: el("observationUnit").value, observed,
      game_version: el("observationVersion").value, note: el("observationNote").value};
    state.observationIdentity = battleIdentity();
    state.busy = true;
    renderAll();
    const record = await api("/api/battle/observation", {method: "POST", body: JSON.stringify(request)});
    if (el("observationsEditor").value !== source) { setMessage("观测 JSON 在请求期间发生变化，已保留编辑；本次对照未追加，请重试。", "warn"); return; }
    observations.comparisons = [...(observations.comparisons || []), record];
    el("observationsEditor").value = pretty(observations);
    resetObservation();
    setMessage("已记录当前局面对照。请保存用例或导出观测，并下载对应战斗记录。", "ok");
  } catch (error) {
    if (error.status === 409) {
      try { acceptBattle(await api("/api/battle")); } catch { /* Retain the typed observation until a refresh succeeds. */ }
    }
    setMessage(error.message, "bad");
  } finally { state.busy = false; renderAll(); }
}

for (const field of Object.keys(observationFields)) observationInput(field).addEventListener("input", () => {
  if (!state.observationIdentity) state.observationIdentity = battleIdentity();
  renderObservations();
});
el("compareObservationBtn").addEventListener("click", compareObservation);
el("resetObservationBtn").addEventListener("click", resetObservation);
el("observationsEditor").addEventListener("input", renderObservations);
el("exportObservationsBtn").addEventListener("click", () => {
  try {
    const url = URL.createObjectURL(new Blob([pretty(parseEditor("observationsEditor"))], {type: "application/json"}));
    const link = document.createElement("a");
    link.href = url;
    link.download = "hsr-observations.json";
    link.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  } catch (error) { setMessage(error.message, "bad"); }
});

async function forkBattle() {
  if (state.busy || !state.session) return;
  const selected = el("forkChoice").value;
  const choice = (state.report?.fork_choices || []).find((item) => String(item.operation_index) === selected);
  if (!choice) { setMessage("请选择有效的历史提交。", "bad"); return; }
  return battleRequest("/api/battle/fork", {...battleIdentity(), operation_index: choice.operation_index}, "正在校验并重建所选历史局面…");
}

el("forkBattleBtn").addEventListener("click", forkBattle);

function acceptBattle(report) {
  state.session = report.session_id ? {session_id: report.session_id, revision: report.revision} : null;
  state.report = report.session_id ? report : null;
  state.selectedSkill = null;
  state.selectedEventIndex = null;
  state.selectedTargets = [];
  closeDrawer();
  renderAll();
}

async function battleRequest(path, body, message) {
  if (state.busy) return;
  state.busy = true;
  document.querySelector(".topbar").setAttribute("aria-busy", "true");
  el("runBtn").disabled = true;
  renderAll();
  setMessage(message);
  try {
    const report = await api(path, {method: "POST", body: JSON.stringify(body)});
    acceptBattle(report);
    const last = report.steps.at(-1);
    const reasons = last?.transition_outcome?.reason_codes || [];
    if (last && !last.transition_outcome.successor_eligible) {
      setMessage(`动作未提交：${reasons.join("；")}。可以更换动作或下载记录。`, "warn");
    } else if (report.decision.ready === false && !report.outcome) {
      setMessage(`推进受阻：${report.decision.blocked_reason || report.action_prompt.reason}。可下载记录保留现场。`, "warn");
    } else {
      const outcome = {victory: "战斗胜利", defeat: "战斗败北"}[report.outcome];
      setMessage(outcome ? `${outcome}。可下载记录并校验回放。` : "请选择行动者的动作；敌我双方均由你操作。", "ok");
    }
  } catch (error) {
    if (error.status === 409) acceptBattle(await api("/api/battle"));
    setMessage(error.message, "bad");
  } finally {
    state.busy = false;
    document.querySelector(".topbar").removeAttribute("aria-busy");
    el("runBtn").disabled = false;
    renderAll();
  }
}

async function startBattle() {
  const scenario = parseEditor("scenarioEditor");
  return battleRequest("/api/battle", {...battleIdentity(), scenario}, "正在加载所选规则并校验入场，首次加载需要稍候…");
}

function renderSetup() {
  try {
    const scenario = parseEditor("scenarioEditor");
    renderPartyFormation(scenario);
    const wave = scenario.battle_setup?.wave || scenario.wave_setup || {};
    el("currentStage").textContent = `当前来源：${wave.stage_ref || wave.wave_definition_ref || scenario.stage_ref || scenario.wave_definition_ref || "未选择"}；起始波次：${Number(wave.wave_index ?? scenario.wave_index ?? 0) + 1}`;
    el("setupFields").innerHTML = (scenario.units || []).filter((unit) => unit.character_build).map((unit) => `
      <fieldset data-build-unit="${escapeHtml(unit.unit_id)}">
        <legend>${escapeHtml(unit.unit_id)} · ${escapeHtml(unit.entity_ref)}</legend>
        ${characterFields(unit)}
        ${[["level", "等级"], ["promotion", "晋阶"], ["eidolon_level", "星魂"]].map(([key, label]) => `
          <label>${label}<input type="number" step="1" data-build-field="${key}" value="${escapeHtml(unit.character_build[key])}"></label>
        `).join("")}
        ${initialConditionFields(unit)}
        ${buildTraceFields(unit)}
        ${lightConeFields(unit)}
        ${relicFields(unit)}
      </fieldset>
    `).join("") || emptyText("此配置没有可编辑的角色构筑。完整配置可在下方 JSON 中查看。");
    el("setupFields").querySelectorAll("[data-build-field]").forEach((input) => input.addEventListener("change", () => {
      const draft = parseEditor("scenarioEditor");
      const unit = draft.units.find((item) => item.unit_id === input.closest("fieldset").dataset.buildUnit);
      const key = input.dataset.buildField;
      if (!input.value.trim() || !Number.isSafeInteger(Number(input.value))) {
        setMessage("构筑值需要填写整数，合法范围由内核校验。", "bad");
        renderSetup();
        return;
      }
      unit.character_build[key] = Number(input.value);
      if (key === "level" || key === "eidolon_level") unit[key] = Number(input.value);
      delete unit.character_build.input_fingerprint;
      el("scenarioEditor").value = pretty(draft);
      renderBuildPreview();
      setMessage("配置已修改，点击开始战斗后生效。当前战斗保持原构筑。", "ok");
    }));
    el("setupFields").querySelectorAll("[data-build-trace]").forEach((select) => select.addEventListener("change", () => {
      try { changeBuildTrace(select.closest("fieldset").dataset.buildUnit, select.dataset.buildTrace, select.value); }
      catch (error) { setMessage(error.message, "bad"); }
    }));
    el("setupFields").querySelectorAll("[data-apply-character]").forEach((button) => button.addEventListener("click", () => {
      const fieldset = button.closest("fieldset");
      applyCharacter(fieldset.dataset.buildUnit, fieldset.querySelector("[data-character-choice]").value);
    }));
    el("setupFields").querySelectorAll("[data-apply-initial]").forEach((button) => button.addEventListener("click", () => {
      const fieldset = button.closest("fieldset");
      const fields = Object.fromEntries(Array.from(fieldset.querySelectorAll("[data-initial-field]"),
        (input) => [input.dataset.initialField, input.value]));
      applyInitialCondition(fieldset.dataset.buildUnit, fields);
    }));
    el("setupFields").querySelectorAll("[data-apply-cone]").forEach((button) => button.addEventListener("click", () => {
      const fieldset = button.closest("fieldset");
      const fields = Object.fromEntries(Array.from(fieldset.querySelectorAll("[data-cone-field]"),
        (input) => [input.dataset.coneField, input.value]));
      applyLightCone(fieldset.dataset.buildUnit, fields);
    }));
    el("setupFields").querySelectorAll("[data-relic-template]").forEach((select) => select.addEventListener("change", () => {
      const section = select.closest("[data-relic-slot]");
      section.querySelector("[data-relic-parameters]").innerHTML = relicParameters(null, select.value);
    }));
    el("setupFields").querySelectorAll("[data-load-relic]").forEach((button) => button.addEventListener("click", () => {
      loadRelicAffixes(button.closest("[data-relic-slot]"));
    }));
    el("setupFields").querySelectorAll("[data-apply-relic]").forEach((button) => button.addEventListener("click", () => {
      const section = button.closest("[data-relic-slot]");
      const fields = Object.fromEntries(Array.from(section.querySelectorAll("[data-relic-field]"),
        (input) => [input.dataset.relicField, input.value]));
      fields.template_identity = section.querySelector("[data-relic-template]").value;
      fields.sub_affixes = Array.from(section.querySelectorAll("[data-relic-sub]"), (row) =>
        Object.fromEntries(Array.from(row.querySelectorAll("[data-sub-field]"), (input) => [input.dataset.subField, input.value])));
      applyRelic(section.closest("fieldset").dataset.buildUnit, section.dataset.relicSlot, fields);
    }));
    renderBuildPreview();
  } catch {
    el("partyFormation").textContent = "";
    el("setupFields").textContent = "配置 JSON 无法解析，请修正后再开战。";
    renderBuildPreview();
  }
}

function renderPartyFormation(scenario) {
  const party = (scenario.units || []).filter((unit) => unit.side === "ally");
  if (!party.length) { el("partyFormation").textContent = "请先载入一个角色配置，再调整队伍。"; return; }
  if (party.some((unit) => !unit.character_build || !Number.isSafeInteger(unit.position)) ||
      new Set(party.map((unit) => unit.position)).size !== party.length) {
    el("partyFormation").textContent = "我方站位缺失或重复，或包含非角色单位，请先在配置 JSON 中修正。";
    return;
  }
  party.sort((a, b) => a.position - b.position);
  el("partyFormation").innerHTML = `<p>我方站位（从左到右） · ${party.length} / 4 人</p><ol class="partyFormation">
    ${party.map((unit, index) => `<li><span>${escapeHtml(unit.unit_id)}</span>
      ${[[index - 1, "左移"], [index + 1, "右移"]].filter(([next]) => next >= 0 && next < party.length).map(([next, label]) =>
        `<button type="button" data-party-unit="${escapeHtml(unit.unit_id)}" data-party-next="${next}" aria-label="${escapeHtml(unit.unit_id)}${label}">${label}</button>`).join("")}
      ${party.length > 1 ? `<button type="button" data-remove-member="${escapeHtml(unit.unit_id)}" aria-label="移除队员 ${escapeHtml(unit.unit_id)}">移除队员</button>` : ""}
    </li>`).join("")}</ol>
    ${party.length < 4 ? state.characters?.length ? `<div class="buildTraces"><label>新增队员
      <select data-new-member>${state.characters.map((item) => `<option value="${escapeHtml(item.entity_ref)}">${escapeHtml(item.name)} · ${escapeHtml(item.entity_ref)}</option>`).join("")}</select>
      </label><button type="button" data-add-member>添加队员</button></div>` : '<p class="mutedText">加载角色目录后可添加队员。</p>' : '<p class="mutedText">队伍已满。</p>'}
    <p class="mutedText">队伍保留 1–4 人。新增队员为 1 级、零星魂、默认行迹和空装备；移除会一并删除该位构筑。调整下次开战生效。</p>`;
  el("partyFormation").querySelectorAll("[data-party-unit]").forEach((button) => button.addEventListener("click", () => {
    const order = party.map((unit) => unit.unit_id);
    const index = order.indexOf(button.dataset.partyUnit), next = Number(button.dataset.partyNext);
    [order[index], order[next]] = [order[next], order[index]];
    applyPartyOrder(order, button.dataset.partyUnit);
  }));
  el("partyFormation").querySelectorAll("[data-remove-member]").forEach((button) => button.addEventListener("click", () => {
    applyCharacter(button.dataset.removeMember, null, "remove");
  }));
  el("partyFormation").querySelectorAll("[data-add-member]").forEach((button) => button.addEventListener("click", () => {
    applyCharacter(null, el("partyFormation").querySelector("[data-new-member]").value, "add");
  }));
}

async function applyPartyOrder(unitIds, focusUnit) {
  if (state.busy) return;
  const source = el("scenarioEditor").value;
  state.busy = true;
  el("setupPanel").setAttribute("aria-busy", "true");
  renderAll();
  try {
    const result = await api("/api/battle/party-order", {method: "POST", body: JSON.stringify({
      scenario: JSON.parse(source), unit_ids: unitIds,
    })});
    if (el("scenarioEditor").value !== source) { setMessage("配置在调整期间发生变化，未替换站位，请重试。", "warn"); return; }
    el("scenarioEditor").value = pretty(result.scenario);
    renderSetup();
    setMessage("站位已写入配置，下次开战生效。", "ok");
  } catch (error) { setMessage(error.message, "bad"); }
  finally {
    state.busy = false;
    el("setupPanel").removeAttribute("aria-busy");
    renderAll();
    Array.from(el("partyFormation").querySelectorAll("[data-party-unit]"))
      .find((button) => button.dataset.partyUnit === focusUnit)?.focus();
  }
}

function initialConditionFields(unit) {
  const initial = unit.initial_condition;
  if (!initial) return "";
  return `<details class="buildTraces"><summary>初始生命值与能量</summary>
    <label>生命值方式<select data-initial-field="hp_mode">
      ${["full", "ratio", "absolute"].includes(initial.hp_mode) ? "" : `<option selected value="${escapeHtml(initial.hp_mode)}">未识别：${escapeHtml(initial.hp_mode)}</option>`}
      ${[["full", "满血"], ["ratio", "生命比例（0–1）"], ["absolute", "指定生命值"]].map(([value, label]) =>
        `<option value="${value}" ${initial.hp_mode === value ? "selected" : ""}>${label}</option>`).join("")}
    </select></label>
    <label>生命值或比例（满血时忽略）<input type="number" step="any" data-initial-field="hp_value" value="${escapeHtml(initial.hp_value ?? "")}"></label>
    ${initial.initial_energy === null ? '<p>该角色使用特殊资源，初始值由正式能力初始化。</p>' :
      `<label>初始能量<input type="number" step="any" data-initial-field="initial_energy" value="${escapeHtml(initial.initial_energy ?? "")}"></label>`}
    <button type="button" data-apply-initial>应用初始条件</button>
    <p class="mutedText">仅修改下次开战配置。生命值须大于零，生命值与普通能量上限在开战时校验。</p>
  </details>`;
}

async function applyInitialCondition(unitId, fields) {
  if (state.busy) return;
  const source = el("scenarioEditor").value;
  state.busy = true;
  el("setupPanel").setAttribute("aria-busy", "true");
  renderAll();
  try {
    const result = await api("/api/battle/initial-condition", {method: "POST", body: JSON.stringify({
      scenario: JSON.parse(source), unit_id: unitId,
      initial_condition: {hp_mode: fields.hp_mode, hp_value: fields.hp_mode === "full" ? null : fields.hp_value,
                          initial_energy: fields.initial_energy ?? null},
    })});
    if (el("scenarioEditor").value !== source) { setMessage("配置在应用期间发生变化，未替换初始条件，请重试。", "warn"); return; }
    el("scenarioEditor").value = pretty(result.scenario);
    renderSetup();
    setMessage("初始条件已写入配置。开战时按正式面板校验，当前战斗保持不变。", "ok");
  } catch (error) { setMessage(error.message, "bad"); }
  finally { state.busy = false; el("setupPanel").removeAttribute("aria-busy"); renderAll(); }
}

function buildTraceFields(unit) {
  const options = state.buildOptions?.units.find((item) => item.unit_id === unit.unit_id &&
    item.character_card_id === unit.character_build.character_card_id);
  if (!options) return "";
  const selected = unit.character_build.unlocked_trace_node_ids || [];
  const groups = new Map();
  for (const node of options.traces) {
    if (!groups.has(node.trace_id)) groups.set(node.trace_id, []);
    groups.get(node.trace_id).push(node);
  }
  const unknown = selected.filter((id) => !options.traces.some((node) => node.trace_node_id === id));
  return `<details class="buildTraces"><summary>技能等级与行迹</summary><div class="traceGrid">${Array.from(groups, ([id, nodes]) => {
    nodes.sort((a, b) => a.level - b.level);
    const initial = nodes.find((node) => node.default_unlocked);
    const explicit = nodes.filter((node) => selected.includes(node.trace_node_id));
    const choice = explicit.length > 1 ? "conflicting" : explicit[0]?.trace_node_id || "";
    return `<label>${escapeHtml(nodes[0].label)} <small class="mutedText">${escapeHtml(id)}</small>
      <select data-build-trace="${escapeHtml(id)}">
        <option value="" ${!choice ? "selected" : ""}>${initial ? `默认 · Lv.${initial.level}` : "未选择"}</option>
        ${explicit.length > 1 ? '<option value="conflicting" selected disabled>多个等级冲突，请重选</option>' : ""}
        ${nodes.map((node) => `<option value="${escapeHtml(node.trace_node_id)}" ${choice === node.trace_node_id ? "selected" : ""}
          ${node.default_unlocked || node.coverage_status !== "executable" ? "disabled" : ""}>
          Lv.${node.level}${node.default_unlocked ? "（默认）" : ""}${node.required_character_level ? ` · 角色等级 ${node.required_character_level}` : ""}${node.required_promotion ? ` · 晋阶 ${node.required_promotion}` : ""}${node.coverage_status !== "executable" ? " · 尚未支持" : ""}
        </option>`).join("")}
      </select>
      ${nodes[0].prerequisite_trace_ids.length ? `<small>前置行迹：${escapeHtml(nodes[0].prerequisite_trace_ids.join("、"))}</small>` : ""}
    </label>`;
  }).join("")}</div>${unknown.length ? `<p>配置中有未识别的已选行迹，已保留：${escapeHtml(unknown.join("、"))}</p>` : ""}</details>`;
}

function changeBuildTrace(unitId, traceId, nodeId) {
  if (state.busy) return;
  const draft = parseEditor("scenarioEditor");
  const unit = draft.units.find((item) => item.unit_id === unitId);
  const options = state.buildOptions?.units.find((item) => item.unit_id === unitId &&
    item.character_card_id === unit?.character_build?.character_card_id);
  const nodes = options?.traces.filter((node) => node.trace_id === traceId) || [];
  if (!nodes.length || nodeId && !nodes.some((node) => node.trace_node_id === nodeId &&
      !node.default_unlocked && node.coverage_status === "executable")) throw new Error("行迹选项已变化，请重新加载。");
  unit.character_build.unlocked_trace_node_ids = (unit.character_build.unlocked_trace_node_ids || [])
    .filter((id) => !nodes.some((node) => node.trace_node_id === id));
  if (nodeId) unit.character_build.unlocked_trace_node_ids.push(nodeId);
  delete unit.character_build.input_fingerprint;
  el("scenarioEditor").value = pretty(draft);
  renderBuildPreview();
  setMessage("行迹选择已写入配置。请校验构筑，或按新配置开始战斗。", "ok");
}

function contentSupportHtml(support) {
  if (!support) return "";
  const build = support.scope === "configured_builds";
  const labels = build ? {supported: "构筑校验通过", blocked: "构筑受阻", unchecked: "尚未校验"}
    : {supported: "当前可继续", blocked: "当前受阻", unchecked: "当前无待选动作"};
  const kinds = {character_build: "构筑", action_choice: "当前动作选项", decision: "战斗推进", last_submission: "最近一次提交"};
  return `<details ${support.status === "blocked" ? "open" : ""}><summary>${escapeHtml(labels[support.status] || "尚未校验")}</summary>
    <p class="mutedText">${build ? "仅表示当前角色、行迹与装备的构筑准入；入场、各技能执行、敌人和关卡仍按实际流程检查。"
      : "仅表示当前局面的合法选择及最近一次提交结果；未执行的技能和分支尚未验证。"}</p>
    ${simpleTable("检查范围与原因", ["范围", "单位", "内容", "结果", "原因"], (support.checks || []).map((check) =>
      [kinds[check.kind] || check.kind, check.unit_id, check.ref_id,
       check.status === "supported" ? "通过" : check.status === "blocked" ? "受阻" : "未检查", check.reasons.join("；")]))}
  </details>`;
}

function renderBuildPreview() {
  if (!state.buildOptions) { el("buildPreview").innerHTML = ""; return; }
  if (el("scenarioEditor").value !== state.buildPreviewSource) {
    el("buildPreview").textContent = "配置已变化，请再次校验构筑以更新面板与技能等级。";
    return;
  }
  el("buildPreview").innerHTML = contentSupportHtml(state.buildOptions.content_support) + state.buildOptions.units.map((unit) => {
    const panel = unit.base_panel;
    const reasons = [...unit.blocked_reasons, ...unit.mechanism_reasons];
    return `<h3>${escapeHtml(unit.unit_id)} · ${unit.battle_admission_status === "admitted" ? "构筑校验通过" : "构筑受阻"}</h3>
      ${panel ? `<p>生命 ${escapeHtml(panel.max_hp)} · 攻击 ${escapeHtml(panel.attack)} · 防御 ${escapeHtml(panel.defense)} · 速度 ${escapeHtml(panel.speed)}</p>` : ""}
      ${simpleTable("生效技能等级", ["技能", "基础等级", "星魂加成", "生效等级"], unit.skill_levels.map((skill) =>
        [skill.skill_id, skill.base_level, skill.eidolon_level_bonus, skill.effective_level]))}
      ${(unit.relic_stats || []).map((item) => simpleTable(`${relicSlotLabel(item.slot)}词条`, ["属性", "数值"],
        item.properties.map((property) => [relicPropertyLabel(property.property_type), property.value]))).join("")}
      ${reasons.length && !state.buildOptions.content_support ? `<p>${escapeHtml(reasons.join("；"))}</p>` : ""}`;
  }).join("");
}

function lightConeFields(unit) {
  if (!state.lightCones) return "";
  const cone = unit.character_build.equipment_build.light_cone;
  const identity = cone?.definition_key.definition_identity || "";
  const missing = identity && !state.lightCones.some((item) => item.definition_identity === identity);
  const paths = {Warrior: "毁灭", Rogue: "巡猎", Mage: "智识", Shaman: "同谐", Warlock: "虚无", Knight: "存护", Priest: "丰饶", Memory: "记忆", Elation: "欢愉"};
  return `<details class="buildTraces"><summary>光锥</summary><div class="traceGrid">
    <label>光锥选择<select data-cone-field="definition_identity">
      <option value="" ${!identity ? "selected" : ""}>不装备</option>
      ${missing ? `<option value="${escapeHtml(identity)}" selected>目录未匹配 · ${escapeHtml(identity)}</option>` : ""}
      ${state.lightCones.map((item) => `<option value="${escapeHtml(item.definition_identity)}" ${identity === item.definition_identity ? "selected" : ""}
        ${item.coverage_status !== "executable" ? "disabled" : ""}>${escapeHtml(item.name)} · ${escapeHtml(paths[item.path_type] || item.path_type)}${item.coverage_status !== "executable" ? " · 尚未支持" : ""}</option>`).join("")}
    </select></label>
    ${[["level", "等级", 1], ["promotion", "晋阶", 0], ["superimposition", "叠影", 1]].map(([key, label, initial]) => `
      <label>${label}<input type="number" step="1" data-cone-field="${key}" value="${escapeHtml(cone?.[key] ?? initial)}"></label>`).join("")}
    </div><p class="mutedText">选择后点击应用；面板和光锥效果由构筑校验决定。</p>
    <button type="button" data-apply-cone>应用光锥并校验构筑</button>
  </details>`;
}

async function applyLightCone(unitId, fields) {
  if (state.busy) return;
  const source = el("scenarioEditor").value;
  state.busy = true;
  el("setupPanel").setAttribute("aria-busy", "true");
  renderAll();
  try {
    let cone = null;
    if (fields.definition_identity) {
      cone = {definition_identity: fields.definition_identity};
      for (const key of ["level", "promotion", "superimposition"]) {
        if (!String(fields[key] ?? "").trim() || !Number.isSafeInteger(Number(fields[key]))) throw new Error("光锥等级、晋阶和叠影需要填写整数。");
        cone[key] = Number(fields[key]);
      }
    }
    setMessage("正在校验光锥构筑，请稍候…");
    const result = await api("/api/battle/light-cone", {method: "POST", body: JSON.stringify({
      scenario: JSON.parse(source), unit_id: unitId, light_cone: cone,
    })});
    if (el("scenarioEditor").value !== source) { setMessage("配置在校验期间发生变化，未应用光锥，请重试。", "warn"); return; }
    el("scenarioEditor").value = pretty(result.scenario);
    state.buildOptions = result;
    state.buildPreviewSource = el("scenarioEditor").value;
    renderSetup();
    const admitted = result.units.every((unit) => unit.battle_admission_status === "admitted");
    setMessage(admitted ? "光锥构筑已校验并写入配置，重新开战后生效。" : "光锥选择已写入配置，构筑受阻原因见下方；请调整后再开战。", admitted ? "ok" : "warn");
  } catch (error) { setMessage(error.message, "bad"); }
  finally {
    state.busy = false;
    el("setupPanel").removeAttribute("aria-busy");
    renderAll();
  }
}

async function prepareBuilds(includeEquipment = false) {
  if (state.busy) return;
  const source = el("scenarioEditor").value;
  state.busy = true;
  el("setupPanel").setAttribute("aria-busy", "true");
  renderAll();
  setMessage(includeEquipment ? "正在加载装备目录并校验构筑，首次加载需要稍候…" : "正在加载行迹选项并校验构筑，首次加载需要稍候…");
  try {
    const options = await api("/api/battle/builds", {method: "POST", body: JSON.stringify({scenario: JSON.parse(source), include_equipment: includeEquipment})});
    if (el("scenarioEditor").value !== source) { setMessage("配置在校验期间发生变化，请重新校验。", "warn"); return; }
    state.buildOptions = options;
    if (options.light_cones) state.lightCones = options.light_cones;
    if (options.relic_templates) state.relicTemplates = options.relic_templates;
    if (options.relic_slots) state.relicSlots = options.relic_slots;
    state.buildPreviewSource = source;
    renderSetup();
    const admitted = options.units.every((unit) => unit.battle_admission_status === "admitted");
    setMessage(admitted ? "构筑装配通过，可以调整技能等级与行迹。开战时还会检查被动启动、敌人和关卡。" : "构筑存在未满足条件，具体原因见下方。", admitted ? "ok" : "warn");
  } catch (error) { setMessage(error.message, "bad"); }
  finally {
    state.busy = false;
    el("setupPanel").removeAttribute("aria-busy");
    renderAll();
  }
}

el("prepareBuildsBtn").addEventListener("click", () => prepareBuilds());
el("loadLightConesBtn").addEventListener("click", () => prepareBuilds(true));
el("loadCharactersBtn").addEventListener("click", loadCharacters);
el("searchStagesBtn").addEventListener("click", searchStages);
el("applyStageBtn").addEventListener("click", applyStage);
el("stageChoice").addEventListener("change", renderAll);

async function searchStages() {
  if (state.busy) return;
  const query = el("stageSearch").value;
  state.busy = true;
  el("stagePanel").setAttribute("aria-busy", "true");
  renderAll();
  try {
    const result = await api(`/api/battle/stages?${new URLSearchParams({q: query})}`);
    if (el("stageSearch").value !== query) return;
    el("stageChoice").innerHTML = '<option value="">请选择</option>' + result.stages.map((stage) =>
      `<option value="${escapeHtml(stage.stage_id)}">${escapeHtml(stage.name)} · ${escapeHtml(stage.stage_id)} · Lv.${escapeHtml(stage.level ?? "未确定")} · ${escapeHtml(stage.wave_count)} 波</option>`).join("");
    el("stageChoice").value = "";
    el("stageSearchResult").textContent = result.total > result.stages.length
      ? `共 ${result.total} 项，仅展示前 ${result.stages.length} 项，请缩小搜索范围。`
      : `找到 ${result.total} 项来源记录。`;
  } catch (error) { setMessage(error.message, "bad"); }
  finally { state.busy = false; el("stagePanel").removeAttribute("aria-busy"); renderAll(); }
}

async function applyStage() {
  if (state.busy || !el("stageChoice").value) return;
  const source = el("scenarioEditor").value;
  const stageId = el("stageChoice").value;
  state.busy = true;
  el("stagePanel").setAttribute("aria-busy", "true");
  renderAll();
  try {
    const result = await api("/api/battle/stage", {method: "POST", body: JSON.stringify({
      scenario: JSON.parse(source), stage_id: stageId,
    })});
    if (el("scenarioEditor").value !== source) { setMessage("配置在切换期间发生变化，未替换波次，请重试。", "warn"); return; }
    el("scenarioEditor").value = pretty(result.scenario);
    state.buildOptions = null;
    state.buildPreviewSource = "";
    renderSetup();
    setMessage(`已选择 ${result.stage.name} 的 ${result.stage.wave_count} 波敌人。点击开始战斗后校验机制并生效。`, "ok");
  } catch (error) { setMessage(error.message, "bad"); }
  finally { state.busy = false; el("stagePanel").removeAttribute("aria-busy"); renderAll(); }
}

function characterFields(unit) {
  if (!state.characters) return "";
  const elements = {Physical: "物理", Fire: "火", Ice: "冰", Thunder: "雷", Wind: "风", Quantum: "量子", Imaginary: "虚数"};
  return `<div class="buildTraces"><label>角色<select data-character-choice>
    ${!state.characters.some((item) => item.entity_ref === unit.entity_ref) ? `<option selected value="${escapeHtml(unit.entity_ref)}">目录未匹配 · ${escapeHtml(unit.entity_ref)}</option>` : ""}
    ${state.characters.map((item) => `<option value="${escapeHtml(item.entity_ref)}" ${item.entity_ref === unit.entity_ref ? "selected" : ""}>${escapeHtml(item.name)} · ${escapeHtml(elements[item.element] || item.element)} · ${escapeHtml(item.entity_ref)} · 未检查</option>`).join("")}
    </select></label><button type="button" data-apply-character>切换角色并重置该位构筑</button>
    <p class="mutedText">切换后为 1 级、零星魂、默认行迹、空装备和满生命初始状态。目录收录不代表机制已可用，请随后校验构筑。</p></div>`;
}

async function loadCharacters() {
  if (state.busy) return;
  state.busy = true;
  renderAll();
  setMessage("正在读取角色目录…");
  try {
    const result = await api("/api/battle/characters");
    state.characters = result.characters;
    renderSetup();
    setMessage(`已加载 ${result.characters.length} 个角色选项。选择后请校验构筑；技能规则按所选队伍加载。`, "ok");
  } catch (error) { setMessage(error.message, "bad"); }
  finally { state.busy = false; renderAll(); }
}

async function applyCharacter(unitId, entityRef, operation = "replace") {
  if (state.busy) return;
  const source = el("scenarioEditor").value;
  state.busy = true;
  el("setupPanel").setAttribute("aria-busy", "true");
  renderAll();
  try {
    const result = await api("/api/battle/character", {method: "POST", body: JSON.stringify({
      scenario: JSON.parse(source), unit_id: unitId, entity_ref: entityRef, operation,
    })});
    if (el("scenarioEditor").value !== source) { setMessage("配置在队员调整期间发生变化，已保留当前编辑，请重试。", "warn"); return; }
    el("scenarioEditor").value = pretty(result.scenario);
    state.buildOptions = null;
    state.buildPreviewSource = "";
    renderSetup();
    setMessage(operation === "remove" ? "队员及其构筑已从配置移除，下次开战生效。"
      : operation === "add" ? "队员已添加。请调整等级、行迹和装备并校验，再开始新战斗。"
        : "该位角色与构筑已重置。请调整等级、行迹和装备并校验，再开始新战斗。", "ok");
  } catch (error) { setMessage(error.message, "bad"); }
  finally {
    state.busy = false;
    el("setupPanel").removeAttribute("aria-busy");
    renderAll();
    if (operation !== "replace") el("partyFormation").querySelectorAll("select, button")[0]?.focus();
  }
}

function relicSlotLabel(slot) {
  return {HEAD: "头部", HAND: "手部", BODY: "躯干", FOOT: "脚部", NECK: "位面球", OBJECT: "连结绳"}[slot] || slot;
}

function relicPropertyLabel(property) {
  return {HPDelta: "生命", AttackDelta: "攻击", DefenceDelta: "防御", SpeedDelta: "速度",
    HPAddedRatio: "生命（比例）", AttackAddedRatio: "攻击（比例）", DefenceAddedRatio: "防御（比例）",
    CriticalChanceBase: "暴击率", CriticalDamageBase: "暴击伤害", StatusProbabilityBase: "效果命中",
    StatusResistanceBase: "效果抵抗", BreakDamageAddedRatioBase: "击破特攻",
    HealRatioBase: "治疗量加成", SPRatioBase: "能量恢复效率", PhysicalAddedRatio: "物理伤害加成",
    FireAddedRatio: "火伤害加成", IceAddedRatio: "冰伤害加成", ThunderAddedRatio: "雷伤害加成",
    WindAddedRatio: "风伤害加成", QuantumAddedRatio: "量子伤害加成", ImaginaryAddedRatio: "虚数伤害加成"}[property] || property;
}

function relicFields(unit) {
  if (!state.relicTemplates) return "";
  const relics = unit.character_build.equipment_build.relics;
  return `<details class="buildTraces"><summary>遗器 · ${relics.length} 件</summary>
    ${state.relicSlots.map((slot) => {
      const relic = relics.find((item) => item.slot_key.definition_identity === slot);
      const identity = relic?.template_key.definition_identity || "";
      const choices = state.relicTemplates.filter((item) => item.slot === slot);
      return `<section class="relicEditor" data-relic-slot="${escapeHtml(slot)}"><h4>${escapeHtml(relicSlotLabel(slot))}</h4>
        <label>套装与稀有度<select data-relic-template>
          <option value="" ${!identity ? "selected" : ""}>不装备</option>
          ${identity && !choices.some((item) => item.definition_identity === identity) ? `<option selected value="${escapeHtml(identity)}">目录未匹配 · ${escapeHtml(identity)}</option>` : ""}
          ${choices.map((item) => `<option value="${escapeHtml(item.definition_identity)}" ${identity === item.definition_identity ? "selected" : ""}
            ${item.coverage_status !== "executable" ? "disabled" : ""}>${escapeHtml(item.name)} · ${escapeHtml(item.rarity)} 星 · ${escapeHtml(item.definition_identity)}</option>`).join("")}
        </select></label>
        <button type="button" data-load-relic>加载该遗器词条</button>
        <div data-relic-parameters>${relicParameters(relic, identity)}</div>
        <button type="button" data-apply-relic>应用此部位并校验构筑</button>
      </section>`;
    }).join("")}<p class="mutedText">选择“不装备”后应用可卸下该部位。修改需应用后才会写入配置。</p></details>`;
}

function relicParameters(relic, templateIdentity) {
  if (!templateIdentity) return "";
  const options = state.relicAffixes[templateIdentity];
  if (!options) return '<p>请先加载该遗器的可选词条。</p>';
  const select = (items, chosen, attribute) => `<select ${attribute}>
    <option value="">请选择（副词条可留空）</option>
    ${chosen && !items.some((item) => item.definition_identity === chosen) ? `<option selected value="${escapeHtml(chosen)}">未匹配 · ${escapeHtml(chosen)}</option>` : ""}
    ${items.map((item) => `<option value="${escapeHtml(item.definition_identity)}" ${chosen === item.definition_identity ? "selected" : ""}>${escapeHtml(relicPropertyLabel(item.property_type))}</option>`).join("")}
    </select>`;
  const rolls = relic?.sub_affix_rolls || [];
  return `<div class="traceGrid"><label>等级<input type="number" step="1" data-relic-field="level" value="${escapeHtml(relic?.level ?? 0)}"></label>
    <label>主词条${select(options.main_affixes, relic?.main_affix_key.definition_identity, 'data-relic-field="main_affix_identity"')}</label></div>
    ${Array.from({length: Math.max(4, rolls.length)}, (_, index) => {
      const roll = rolls[index];
      return `<div class="traceGrid" data-relic-sub><label>副词条 ${index + 1}${select(options.sub_affixes, roll?.affix_key.definition_identity, 'data-sub-field="definition_identity"')}</label>
        <label>基础份数<input type="number" step="1" data-sub-field="count" value="${escapeHtml(roll?.count ?? 1)}"></label>
        <label>累计附加档位<input type="number" step="1" data-sub-field="step" value="${escapeHtml(roll?.step ?? 0)}"></label></div>`;
    }).join("")}<p class="mutedText">副词条用基础份数与累计附加档位表示最终数值，不限制强化历程。校验后可查看实际词条数值；比例 0.1 表示 10%。</p>`;
}

async function loadRelicAffixes(section) {
  if (state.busy) return;
  const templateIdentity = section.querySelector("[data-relic-template]").value;
  if (!templateIdentity) { section.querySelector("[data-relic-parameters]").innerHTML = ""; return; }
  const source = el("scenarioEditor").value;
  state.busy = true;
  el("setupPanel").setAttribute("aria-busy", "true");
  renderAll();
  try {
    const draft = JSON.parse(source);
    if (!state.relicAffixes[templateIdentity]) {
      setMessage("正在加载所选遗器的词条，请稍候…");
      const options = await api("/api/battle/relic-affixes", {method: "POST", body: JSON.stringify({scenario: draft, template_identity: templateIdentity})});
      if (options.template_identity !== templateIdentity) throw new Error("遗器选项不匹配，请重新加载。");
      state.relicAffixes[templateIdentity] = options;
    }
    if (el("scenarioEditor").value !== source) { setMessage("配置在加载期间发生变化，请重试。", "warn"); return; }
    const unit = draft.units.find((item) => item.unit_id === section.closest("fieldset").dataset.buildUnit);
    const relic = unit.character_build.equipment_build.relics.find((item) => item.template_key.definition_identity === templateIdentity && item.slot_key.definition_identity === section.dataset.relicSlot);
    section.querySelector("[data-relic-parameters]").innerHTML = relicParameters(relic, templateIdentity);
    setMessage("可选择主副词条，应用后由内核校验。", "ok");
  } catch (error) { setMessage(error.message, "bad"); }
  finally { state.busy = false; el("setupPanel").removeAttribute("aria-busy"); renderAll(); }
}

async function applyRelic(unitId, slotIdentity, fields) {
  if (state.busy) return;
  const source = el("scenarioEditor").value;
  state.busy = true;
  el("setupPanel").setAttribute("aria-busy", "true");
  renderAll();
  try {
    const integer = (value) => {
      if (!String(value ?? "").trim() || !Number.isSafeInteger(Number(value))) throw new Error("遗器等级和副词条份数、档位需要填写整数。");
      return Number(value);
    };
    let relic = null;
    if (fields.template_identity) {
      if (!fields.main_affix_identity) throw new Error("请加载词条并选择主词条。");
      relic = {template_identity: fields.template_identity, level: integer(fields.level),
        main_affix_identity: fields.main_affix_identity,
        sub_affixes: fields.sub_affixes.filter((item) => item.definition_identity).map((item) => ({
          definition_identity: item.definition_identity, count: integer(item.count), step: integer(item.step),
        }))};
    }
    setMessage("正在校验遗器构筑，请稍候…");
    const result = await api("/api/battle/relic", {method: "POST", body: JSON.stringify({
      scenario: JSON.parse(source), unit_id: unitId, slot_identity: slotIdentity, relic,
    })});
    if (el("scenarioEditor").value !== source) { setMessage("配置在校验期间发生变化，未应用遗器，请重试。", "warn"); return; }
    el("scenarioEditor").value = pretty(result.scenario);
    state.buildOptions = result;
    state.buildPreviewSource = el("scenarioEditor").value;
    renderSetup();
    const admitted = result.units.every((unit) => unit.battle_admission_status === "admitted");
    setMessage(admitted ? "遗器构筑已校验并写入配置，重新开战后生效。" : "遗器选择已写入配置，构筑受阻原因见下方；请调整后再开战。", admitted ? "ok" : "warn");
  } catch (error) { setMessage(error.message, "bad"); }
  finally { state.busy = false; el("setupPanel").removeAttribute("aria-busy"); renderAll(); }
}

el("battleMode").addEventListener("change", async () => {
  if (state.busy) { el("battleMode").value = "live"; return; }
  try {
    state.report = null;
    state.selectedSkill = null;
    await loadCases();
    if (isLive()) acceptBattle(await api("/api/battle"));
    renderAll();
  } catch (error) { setMessage(error.message, "bad"); }
});
el("refreshBattleBtn").addEventListener("click", async () => {
  if (state.busy) return;
  try {
    el("battleMode").value = "live";
    acceptBattle(await api("/api/battle"));
    setMessage(state.session ? "已刷新当前战斗。" : "没有正在进行的战斗，请载入场景并开始。", "ok");
  } catch (error) { setMessage(error.message, "bad"); }
});
el("downloadBattleBtn").addEventListener("click", async () => {
  try {
    const response = await fetch(`/api/battle/archive?${new URLSearchParams(battleIdentity())}`);
    if (!response.ok) throw new Error((await response.json()).error);
    const url = URL.createObjectURL(await response.blob());
    const link = document.createElement("a");
    link.href = url;
    link.download = `hsr-battle-${state.session.session_id}.json.gz`;
    link.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  } catch (error) { setMessage(error.message, "bad"); }
});
el("replayBattleBtn").addEventListener("click", () => el("replayFile").click());
el("resumeBattleBtn").addEventListener("click", () => el("resumeFile").click());
el("replayFile").addEventListener("change", () => importBattleArchive(el("replayFile").files[0], false));
el("resumeFile").addEventListener("change", () => importBattleArchive(el("resumeFile").files[0], true));

async function importBattleArchive(file, resume) {
  if (!file || state.busy) return;
  const identity = battleIdentity();
  state.busy = true;
  document.querySelector(".topbar").setAttribute("aria-busy", "true");
  el("runBtn").disabled = true;
  renderAll();
  setMessage(resume ? "正在校验归档并恢复战斗，请稍候…" : "正在独立重建并逐步校验回放，当前战斗保持不变…");
  try {
    const text = await readBattleArchive(file);
    const body = resume ? JSON.stringify({...identity, archive: JSON.parse(text)}) : text;
    const report = await api(`/api/battle/${resume ? "resume" : "replay"}`, {method: "POST", body});
    if (resume) {
      el("battleMode").value = "live";
      el("scenarioEditor").value = pretty(report.scenario);
      renderSetup();
      acceptBattle(report);
      const outcome = {victory: "胜利", defeat: "败北"}[report.outcome];
      if (outcome) setMessage(`归档已恢复，战斗已${outcome}。可查看战场或下载记录。`, "ok");
      else if (!report.decision.ready) setMessage(`归档已恢复，推进受阻：${report.decision.blocked_reason}。可下载记录保留现场。`, "warn");
      else setMessage("归档已恢复，请选择动作继续战斗。", "ok");
    } else {
      setMessage(report.ok ? `回放通过：${report.step_count} 步，零差异。` : `回放失败：${report.errors.join("；")}`, report.ok ? "ok" : "bad");
    }
  } catch (error) {
    if (error.status === 409) {
      try { acceptBattle(await api("/api/battle")); } catch { /* Keep the last visible battle until a refresh succeeds. */ }
    }
    setMessage(error.message, "bad");
  } finally {
    state.busy = false;
    document.querySelector(".topbar").removeAttribute("aria-busy");
    el("runBtn").disabled = false;
    el("replayFile").value = el("resumeFile").value = "";
    renderAll();
  }
}

async function readBattleArchive(file) {
  let stream = file.stream();
  if (file.name.toLowerCase().endsWith(".gz")) {
    if (typeof DecompressionStream === "undefined") throw new Error("当前浏览器无法解压，请先将归档解压为 JSON 文件再载入。");
    stream = stream.pipeThrough(new DecompressionStream("gzip"));
  }
  const reader = stream.getReader();
  const chunks = [];
  let size = 0;
  try {
    while (true) {
      const {done, value} = await reader.read();
      if (done) break;
      size += value.byteLength;
      if (size > 9_900_000) throw new Error("归档解压后超过网页载入上限（约 10 MB），请使用 CLI 恢复。");
      chunks.push(value);
    }
  } finally { await reader.cancel(); }
  return new Response(new Blob(chunks)).text();
}

init();
