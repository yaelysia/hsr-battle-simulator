const state = {
  cases: [],
  catalog: null,
  report: null,
  selectedSkill: null,
  selectedUnitId: "",
  selectedEventIndex: null,
  detailMode: "view",
};

const el = (id) => document.getElementById(id);

async function api(path, options = {}) {
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  const data = await response.json();
  if (!response.ok) {
    throw new Error(data.error || response.statusText);
  }
  return data;
}

async function init() {
  try {
    const health = await api("/api/health");
    el("health").textContent = health.ok ? "已连接" : "未就绪";
    state.catalog = await api("/api/catalog");
    await loadCases();
    if (state.cases.length) {
      el("caseSelect").value = state.cases[0].case_id;
      el("caseId").value = state.cases[0].case_id;
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
  state.cases = data.cases || [];
  const select = el("caseSelect");
  select.innerHTML = "";
  for (const item of state.cases) {
    const option = document.createElement("option");
    option.value = item.case_id;
    option.textContent = `${item.case_id} (${item.route_count || 0})`;
    select.appendChild(option);
  }
}

async function loadSelectedCase() {
  const caseId = el("caseSelect").value || el("caseId").value;
  if (!caseId) return;
  const scenario = await api(`/api/cases/${encodeURIComponent(caseId)}`);
  const observations = await api(`/api/observations/${encodeURIComponent(caseId)}`);
  el("caseId").value = caseId;
  el("scenarioEditor").value = pretty(scenario);
  el("observationsEditor").value = pretty(observations);
  state.selectedSkill = null;
  state.selectedUnitId = "";
  state.selectedEventIndex = null;
  state.detailMode = "view";
  setMessage(`已加载用例：${caseId}`, "ok");
  await runScenario({ quiet: true });
}

async function saveCase() {
  const caseId = el("caseId").value.trim();
  if (!caseId) throw new Error("需要填写用例编号");
  const scenario = parseEditor("scenarioEditor");
  const observations = parseEditor("observationsEditor");
  await api(`/api/cases/${encodeURIComponent(caseId)}`, {
    method: "PUT",
    body: JSON.stringify(scenario),
  });
  await api(`/api/observations/${encodeURIComponent(caseId)}`, {
    method: "PUT",
    body: JSON.stringify(observations),
  });
  await loadCases();
  el("caseSelect").value = caseId;
  setMessage(`已保存用例：${caseId}`, "ok");
}

async function runScenario({ quiet = false } = {}) {
  const scenario = parseEditor("scenarioEditor");
  const observations = parseEditor("observationsEditor");
  const mode = document.querySelector("input[name=mode]:checked").value;
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
        auto_skip_enemy_turns: true,
        max_auto_skip_turns: 20,
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
    card.addEventListener("click", () => handleUnitClick(card.dataset.unitId));
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
        <span class="mutedText">加载用例后自动运行</span>
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
    <div class="skillButtons">
      ${slots.map((slot) => skillButton(slot, selected)).join("")}
    </div>
    ${prompt.reason ? `<p>${escapeHtml(prompt.reason)}</p>` : ""}
    ${selected ? `<div class="targetHint">已选择 ${escapeHtml(selected.display_label || selected.label)}，请点击目标卡片。</div>` : ""}
  `;
  el("actionPrompt").querySelectorAll("[data-skill-slot]").forEach((button) => {
    button.addEventListener("click", () => selectSkill(button.dataset.skillSlot).catch((error) => setMessage(error.message, "bad")));
  });
}

function skillButton(slot, selected) {
  const disabled = !slot.available;
  const isSelected = selected && selected.slot === slot.slot;
  const label = slot.display_label || slot.label || slot.slot;
  const reason = slot.blocked_reason || "未接通";
  return `
    <button
      class="skillButton ${isSelected ? "active" : ""}"
      type="button"
      data-skill-slot="${escapeHtml(slot.slot)}"
      ${disabled ? "disabled" : ""}
      title="${escapeHtml(disabled ? reason : `${slot.action_ref} 等级 ${slot.action_level}`)}"
    >
      ${escapeHtml(label)}${disabled ? "：未接通" : ""}
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
  const route = scenario.route || [];
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
  el("eventReplay").innerHTML = events.map((event, index) => `
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
  `).join("") || emptyText("暂无事件");
  el("eventReplay").querySelectorAll("[data-event-index]").forEach((button) => {
    button.addEventListener("click", () => openEventDetail(Number(button.dataset.eventIndex)));
  });
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
  const blocked = (state.report.blocked_records || []).length;
  const gaps = (state.report.coverage_gap_records || []).length;
  const skips = (state.report.auto_skip_records || []).length;
  el("runState").textContent = `${ok ? "通过" : "阻塞"}，${steps.length} 步，阻塞 ${blocked}，缺口 ${gaps}，跳过敌方 ${skips}`;
}

async function selectSkill(slotName) {
  const prompt = (state.report && state.report.action_prompt) || {};
  const slot = (prompt.slots || []).find((item) => item.slot === slotName);
  if (!slot || !slot.available) {
    setMessage(slot ? slot.blocked_reason || "动作槽位未接通" : "找不到动作槽位", "warn");
    return;
  }
  const selectableTargets = (prompt.targets || []).filter((item) => item.selection_kind !== "auto");
  const autoTargetIds = Array.isArray(slot.auto_target_ids) ? slot.auto_target_ids.filter(Boolean) : [];
  if (autoTargetIds.length && selectableTargets.length === 0) {
    await appendRouteStepWithTargets(slot, autoTargetIds, "自动目标组");
    return;
  }
  state.selectedSkill = slot;
  setMessage(`已选择 ${slot.display_label || slot.label}，请选择目标`, "ok");
  renderActionPrompt();
  renderBattlefield();
}

async function handleUnitClick(unitId) {
  const unit = findBattlefieldUnit(unitId);
  if (!unit) return;
  if (state.selectedSkill) {
    if (!isPromptTarget(unit.unit_id)) {
      setMessage("当前单位不是这个动作的合法候选目标", "warn");
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
  const prompt = (state.report && state.report.action_prompt) || {};
  if (!prompt.current_unit_id || !slot.action_ref || !slot.action_level) {
    setMessage("动作槽位未接通，未生成路线", "warn");
    return;
  }
  const scenario = parseEditor("scenarioEditor");
  scenario.route = Array.isArray(scenario.route) ? scenario.route : [];
  scenario.route.push({
    actor_id: prompt.current_unit_id,
    action_ref: slot.action_ref,
    action_level: Number(slot.action_level),
    target_ids: targetIds,
    source: "manual",
    metadata: {},
  });
  el("scenarioEditor").value = pretty(scenario);
  state.selectedSkill = null;
  setMessage(`已追加路线：${prompt.current_unit_name} 使用 ${slot.display_label || slot.label} -> ${targetLabel}`, "ok");
  await runScenario({ quiet: true });
}

function isPromptTarget(unitId) {
  const prompt = (state.report && state.report.action_prompt) || {};
  return (prompt.targets || []).some((item) => item.unit_id === unitId && item.selection_kind !== "auto");
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
  const modeButtons = `
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

function openEventDetail(index) {
  const event = ((state.report || {}).event_replay_view || [])[index];
  if (!event) return;
  const step = event.event_kind === "route_step"
    ? ((state.report || {}).steps || []).find((item) => item.route_index === event.route_index)
    : null;
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
      ${stat("来源审计", passText(event.source_audit_ok))}
      ${stat("快照回放", passText(event.replay_ok))}
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
    ${rawDetails("高级调试：原始 transition", step.transition || {})}
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
      item.modifier_id || item.name || item.term_id || "-",
      item.kind || item.application_kind || "-",
      item.value ?? item.amount ?? "-",
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
  state.report = null;
  state.selectedSkill = null;
  renderAll();
});
document.querySelectorAll("input[name=mode], #initTimeline").forEach((input) => {
  input.addEventListener("change", () => runScenario({ quiet: true }).catch((error) => setMessage(error.message, "bad")));
});
el("caseSelect").addEventListener("change", () => {
  el("caseId").value = el("caseSelect").value;
});

init();
