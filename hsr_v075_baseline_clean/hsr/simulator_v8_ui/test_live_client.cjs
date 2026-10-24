// Run with: node hsr_v075_baseline_clean/hsr/simulator_v8_ui/test_live_client.cjs
// Client control flow only; the Python source integration covers real combat.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');

const nodes = new Map();
function node(id) {
  if (!nodes.has(id)) nodes.set(id, {
    value: id === 'battleMode' ? 'live' : '', innerHTML: '', textContent: '', disabled: false,
    classList: {add() {}, remove() {}},
    listeners: {}, addEventListener(event, callback) { this.listeners[event] = callback; }, setAttribute() {}, removeAttribute() {},
    querySelectorAll() { return []; }, appendChild() {},
  });
  return nodes.get(id);
}
const calls = [];
let respond;
const context = vm.createContext({
  document: {getElementById: node, querySelector: node, querySelectorAll: () => [], createElement: node},
  fetch: async (url, options = {}) => {
    calls.push({url, options});
    return respond(url, options);
  },
  URLSearchParams, Response, Blob, ReadableStream, DecompressionStream, setTimeout, clearTimeout,
});
const source = fs.readFileSync(path.join(__dirname, 'static/app.js'), 'utf8');
vm.runInContext(source.replace(/\ninit\(\);\s*$/, '\n'), context);
const state = vm.runInContext('state', context);
const ok = (data) => ({ok: true, json: async () => data});
const view = {
  session_id: 'battle', revision: 2, decision: {token: {decision_id: 'decision'}},
  validation: {ok: true}, steps: [], action_prompt: {slots: []},
};

const deadline = setTimeout(() => {
  console.error('live client check did not finish');
  process.exitCode = 1;
}, 5000);
(async () => {
  respond = async (url) => {
    if (url === '/api/health') return ok({ok: true});
    if (url === '/api/battle/examples') return ok({examples: []});
    if (url === '/api/cases') return ok({cases: []});
    if (url === '/api/battle') return ok({session_id: null});
    throw new Error(`unexpected initial request ${url}`);
  };
  await context.init();
  assert.equal(calls.some((call) => call.url === '/api/catalog' || call.options.method === 'POST'), false);

  context.acceptBattle(view);
  const template = {actor_id: 'ally', action_id: 'control:ultimate', action_level: 1,
                    source: 'queue', queue_name: 'ultimate', metadata: {kind: 'request', token: 'original'}};
  const slot = {command_template: template, actor_id: 'ally', action_ref: template.action_id, action_level: 1};
  respond = async () => ok({...view, revision: 4});
  await context.appendRouteStepWithTargets(slot, ['enemy'], 'enemy');
  const submitted = JSON.parse(calls.at(-1).options.body);
  assert.deepEqual(submitted, {session_id: 'battle', revision: 2, decision_id: 'decision',
                              command: {...template, target_ids: ['enemy']}});
  assert.equal(state.session.revision, 4);
  assert.equal(state.busy, false);

  // A double click cannot send another command while the first request is pending.
  let finish;
  respond = () => new Promise((resolve) => { finish = resolve; });
  const pending = context.appendRouteStepWithTargets(slot, [], '');
  const count = calls.length;
  await context.appendRouteStepWithTargets(slot, [], '');
  assert.equal(calls.length, count);
  finish(ok({...view, revision: 6}));
  await pending;

  // Stale pages refresh; their rejected command is never retried automatically.
  // The draft belongs to saved-A while the refreshed battle belongs to saved-B;
  // refreshing the battle must not rename the retained draft's save target.
  state.cases = [{case_id: 'saved-A', scenario_id: 'scenario-A'},
                 {case_id: 'saved-B', scenario_id: 'scenario-B'}];
  node('caseSelect').value = 'saved-A';
  node('caseId').value = 'saved-A';
  const draftA = JSON.stringify({scenario_id: 'scenario-A', units: []});
  node('scenarioEditor').value = draftA;
  respond = async (url) => url.endsWith('/submit')
    ? {ok: false, status: 409, json: async () => ({error: 'stale'})}
    : ok({...view, revision: 8, scenario_id: 'scenario-B', scenario: {scenario_id: 'scenario-B', units: []}});
  await context.appendRouteStepWithTargets(slot, [], '');
  assert.equal(calls.at(-1).url, '/api/battle');
  assert.equal(state.session.revision, 8);
  assert.equal(state.report.scenario_id, 'scenario-B');
  assert.equal(node('caseId').value, 'saved-A');
  assert.equal(node('caseSelect').value, 'saved-A');
  assert.equal(node('scenarioEditor').value, draftA);
  assert.equal(state.busy, false);
  assert.equal(node('message').textContent, 'stale');

  // A malformed HTTP 200 body is a failed request, not a successful battle report.
  respond = async () => ({ok: true, status: 200, json: async () => { throw new SyntaxError('HTML body'); }});
  const malformedSuccessCalls = calls.length;
  await context.battleRequest('/api/battle/submit', {}, 'malformed success');
  assert.equal(calls.length, malformedSuccessCalls + 1); // Neither refresh nor retry.
  assert.equal(state.session.session_id, 'battle');
  assert.equal(state.session.revision, 8);
  assert.equal(state.report.session_id, 'battle');
  assert.equal(node('caseId').value, 'saved-A');
  assert.equal(node('scenarioEditor').value, draftA);
  assert.match(node('message').textContent, /无法解析.*HTTP 200/);
  assert.equal(state.busy, false);

  // A malformed 409 body still carries the conflict status: refresh once, never retry.
  respond = async (url) => url.endsWith('/submit')
    ? {ok: false, status: 409, json: async () => { throw new SyntaxError('HTML conflict'); }}
    : ok({...view, revision: 8, scenario_id: 'scenario-B', scenario: {scenario_id: 'scenario-B', units: []}});
  const malformedConflictCalls = calls.length;
  await context.battleRequest('/api/battle/submit', {}, 'malformed conflict');
  assert.equal(calls.length, malformedConflictCalls + 2);
  assert.equal(calls.at(-2).url, '/api/battle/submit');
  assert.equal(calls.at(-1).url, '/api/battle');
  assert.equal(state.session.revision, 8);
  assert.equal(state.report.scenario_id, 'scenario-B');
  assert.equal(node('caseId').value, 'saved-A');
  assert.equal(node('caseSelect').value, 'saved-A');
  assert.equal(node('scenarioEditor').value, draftA);
  assert.match(node('message').textContent, /战斗已更新或页面已过期.*409/);
  assert.equal(state.busy, false);

  // A failed refresh must not replace the 409 conflict message or the last visible battle.
  respond = async (url) => url.endsWith('/submit')
    ? {ok: false, status: 409, json: async () => ({error: 'stale again'})}
    : {ok: false, status: 500, json: async () => ({error: 'refresh failed'})};
  await context.battleRequest('/api/battle/submit', {}, 'conflict then refresh failure');
  assert.equal(node('message').textContent, 'stale again');
  assert.equal(state.session.revision, 8);
  assert.equal(state.report.scenario_id, 'scenario-B');
  assert.equal(state.busy, false);

  // Saved copies may share one scenario_id; with no unique match, keep the draft target.
  state.cases = [{case_id: 'saved-A', scenario_id: 'scenario-A'},
                 {case_id: 'copy-A', scenario_id: 'scenario-A'},
                 {case_id: 'saved-B', scenario_id: 'scenario-B'}];
  node('caseSelect').value = 'saved-B';
  node('caseId').value = 'saved-B';
  context.syncCaseIdentity('scenario-A');
  assert.equal(node('caseSelect').value, 'saved-B');
  assert.equal(node('caseId').value, 'saved-B');

  // A rejected startup must not erase the last usable battle from the screen.
  respond = async () => ({ok: false, status: 400, json: async () => ({error: 'blocked build'})});
  await context.battleRequest('/api/battle', {}, 'starting');
  assert.equal(state.session.revision, 8);
  assert.equal(node('message').textContent, 'blocked build');
  assert.equal(context.passText(undefined), '未检查');

  // The archive's number spelling must reach the server unchanged: JSON.parse/stringify
  // would rewrite 1.0 as 1 and make a restored session fail its initial-snapshot check.
  const archiveText = '{"format":"test","value":1.0}';
  const file = {name: 'battle.json', stream: () => new Blob([archiveText]).stream()};
  state.cases = [{case_id: 'example:restored', scenario: {scenario_id: 'restored-scenario'}}];
  const restored = {...view, session_id: 'restored', revision: 11, restored_operation_count: 10,
                    scenario_id: 'restored-scenario', scenario: {units: []},
                    decision: {ready: true, token: {decision_id: 'next'}}};
  respond = async () => ok(restored);
  await context.importBattleArchive(file, true);
  assert.equal(calls.at(-1).url, '/api/battle/resume');
  assert.deepEqual(JSON.parse(calls.at(-1).options.body), {
    session_id: 'battle', revision: 8, archive_text: archiveText,
  });
  assert.equal('archive' in JSON.parse(calls.at(-1).options.body), false);
  assert.equal(state.session.session_id, 'restored');
  assert.equal(node('battleMode').value, 'live');
  assert.equal(node('caseSelect').value, 'example:restored');
  assert.equal(node('caseId').value, 'restored');
  assert.match(node('eventReplay').innerHTML, /恢复前的完整历史/);
  assert.equal(state.busy, false);

  let importStarted;
  const fetching = new Promise((resolve) => { importStarted = resolve; });
  respond = () => new Promise((resolve) => { finish = resolve; importStarted(); });
  const importing = context.importBattleArchive(file, true);
  await fetching;
  const importCount = calls.length;
  await context.importBattleArchive(file, true);
  assert.equal(calls.length, importCount);
  finish({ok: false, status: 400, json: async () => ({error: 'archive invalid'})});
  await importing;
  assert.equal(state.session.session_id, 'restored');
  assert.equal(node('message').textContent, 'archive invalid');
  assert.equal(state.busy, false);

  await assert.rejects(context.readBattleArchive({name: 'huge.json', stream: () => new ReadableStream({
    start(controller) { controller.enqueue(new Uint8Array(9_900_001)); controller.close(); },
  })}), /10 MB/);
  await assert.rejects(context.readBattleArchive({name: 'battle.gz', stream: () => file.stream()}), /归档解压失败/);

  // Formal trace selection replaces one logical trace level, preserving all others.
  const build = {character_card_id: 'card', input_fingerprint: 'old', level: 80,
                 promotion: 6, eidolon_level: 0, unlocked_trace_node_ids: ['other', 'unknown']};
  node('scenarioEditor').value = JSON.stringify({units: [{unit_id: 'ally', character_build: build}]});
  const trace = {trace_id: 'skill', label: '战技', required_promotion: 1, required_character_level: 20,
                 prerequisite_trace_ids: [], coverage_status: 'executable'};
  const buildOptions = {units: [{unit_id: 'ally', character_card_id: 'card', battle_admission_status: 'admitted',
    traces: [{...trace, trace_node_id: 'base', level: 1, default_unlocked: true},
             {...trace, trace_node_id: 'upgrade2', level: 2}, {...trace, trace_node_id: 'upgrade3', level: 3}],
    blocked_reasons: [], mechanism_reasons: [], skill_levels: [], base_panel: null}]};
  respond = async () => ok(buildOptions);
  await context.prepareBuilds();
  assert.equal(calls.at(-1).url, '/api/battle/builds');
  assert.equal(state.session.session_id, 'restored');
  assert.match(node('setupFields').innerHTML, /战技/);
  assert.match(node('setupFields').innerHTML, /未识别/);
  context.changeBuildTrace('ally', 'skill', 'upgrade2');
  context.changeBuildTrace('ally', 'skill', 'upgrade3');
  let edited = JSON.parse(node('scenarioEditor').value).units[0].character_build;
  assert.deepEqual(edited.unlocked_trace_node_ids, ['other', 'unknown', 'upgrade3']);
  assert.equal('input_fingerprint' in edited, false);
  assert.match(node('buildPreview').textContent, /配置已变化/);
  assert.throws(() => context.changeBuildTrace('ally', 'skill', 'foreign'), /选项已变化/);
  context.changeBuildTrace('ally', 'skill', '');
  assert.deepEqual(JSON.parse(node('scenarioEditor').value).units[0].character_build.unlocked_trace_node_ids,
                   ['other', 'unknown']);
  respond = () => new Promise((resolve) => { finish = resolve; });
  const preparing = context.prepareBuilds();
  node('scenarioEditor').value = '{"units":[]}';
  finish(ok({units: []}));
  await preparing;
  assert.equal(state.buildOptions.units.length, 1);
  assert.match(node('message').textContent, /校验期间发生变化/);
  assert.equal(state.busy, false);

  const equipmentScenario = {units: [{unit_id: 'ally', character_build: {
    ...build, equipment_build: {light_cone: null, relics: [{instance_id: 'kept'}]},
  }}]};
  node('scenarioEditor').value = JSON.stringify(equipmentScenario);
  respond = async () => ok({...buildOptions, light_cones: [{definition_identity: 'cone', name: '<火焰>',
    path_type: 'Warrior', coverage_status: 'executable'}]});
  await context.prepareBuilds(true);
  assert.equal(JSON.parse(calls.at(-1).options.body).include_equipment, true);
  assert.match(node('setupFields').innerHTML, /&lt;火焰&gt;/);
  assert.doesNotMatch(node('setupFields').innerHTML, /<火焰>/);
  const serverScenario = structuredClone(equipmentScenario);
  serverScenario.units[0].character_build.input_fingerprint = 'server-calculated';
  serverScenario.units[0].character_build.equipment_build.light_cone = {
    definition_key: {definition_identity: 'cone'}, level: 20, promotion: 1, superimposition: 2,
  };
  respond = async () => ok({...buildOptions, scenario: serverScenario});
  await context.applyLightCone('ally', {definition_identity: 'cone', level: '20', promotion: '1', superimposition: '2'});
  assert.equal(calls.at(-1).url, '/api/battle/light-cone');
  assert.deepEqual(JSON.parse(calls.at(-1).options.body).light_cone,
                   {definition_identity: 'cone', level: 20, promotion: 1, superimposition: 2});
  assert.deepEqual(JSON.parse(node('scenarioEditor').value), serverScenario);
  assert.equal(state.session.session_id, 'restored');
  const coneCalls = calls.length;
  await context.applyLightCone('ally', {definition_identity: 'cone', level: '', promotion: '1', superimposition: '2'});
  assert.equal(calls.length, coneCalls);
  assert.match(node('message').textContent, /填写整数/);
  assert.equal(state.busy, false);
  respond = async () => ({ok: false, status: 400, json: async () => ({error: 'invalid equipment'})});
  await context.applyLightCone('ally', {definition_identity: ''});
  assert.equal(JSON.parse(calls.at(-1).options.body).light_cone, null);
  assert.deepEqual(JSON.parse(node('scenarioEditor').value), serverScenario);

  const relic = {instance_id: 'foot', slot_key: {definition_identity: 'FOOT'},
    template_key: {definition_identity: 'template'}, level: 15,
    main_affix_key: {definition_identity: 'speed'}, sub_affix_rolls: [
      {affix_key: {definition_identity: 'unknown-affix'}, count: 2, step: 1},
    ]};
  serverScenario.units[0].character_build.equipment_build.relics = [relic];
  node('scenarioEditor').value = JSON.stringify(serverScenario);
  state.relicSlots = ['FOOT'];
  state.relicTemplates = [{definition_identity: 'template', name: '<仙舟>', slot: 'FOOT',
    rarity: 5, coverage_status: 'executable'}];
  const parameters = {innerHTML: ''};
  const section = {
    dataset: {relicSlot: 'FOOT'}, closest: () => ({dataset: {buildUnit: 'ally'}}),
    querySelector: (selector) => selector === '[data-relic-template]' ? {value: 'template'} : parameters,
  };
  const relicOptions = {template_identity: 'template', main_affixes: [{definition_identity: 'speed', property_type: 'SpeedDelta'}],
    sub_affixes: [{definition_identity: 'atk', property_type: 'AttackDelta'}]};
  respond = async () => ok(relicOptions);
  await context.loadRelicAffixes(section);
  assert.equal(calls.at(-1).url, '/api/battle/relic-affixes');
  assert.match(parameters.innerHTML, /未匹配 · unknown-affix/);
  const affixCalls = calls.length;
  await context.loadRelicAffixes(section);
  assert.equal(calls.length, affixCalls); // Read-only template choices are reused.
  context.renderSetup();
  assert.match(node('setupFields').innerHTML, /&lt;仙舟&gt;/);
  const relicDraft = structuredClone(serverScenario);
  relicDraft.units[0].character_build.input_fingerprint = 'relic-server-calculated';
  respond = async () => ok({...buildOptions, scenario: relicDraft});
  await context.applyRelic('ally', 'FOOT', {template_identity: 'template', main_affix_identity: 'speed', level: '15',
    sub_affixes: [{definition_identity: 'atk', count: '2', step: '1'}, {definition_identity: '', count: '', step: ''}]});
  assert.equal(calls.at(-1).url, '/api/battle/relic');
  assert.deepEqual(JSON.parse(calls.at(-1).options.body).relic, {
    template_identity: 'template', main_affix_identity: 'speed', level: 15,
    sub_affixes: [{definition_identity: 'atk', count: 2, step: 1}],
  });
  assert.deepEqual(JSON.parse(node('scenarioEditor').value), relicDraft);
  assert.equal(state.session.session_id, 'restored');
  const relicCalls = calls.length;
  await context.applyRelic('ally', 'FOOT', {template_identity: 'template', main_affix_identity: 'speed', level: ''});
  assert.equal(calls.length, relicCalls);
  assert.match(node('message').textContent, /填写整数/);
  respond = () => new Promise((resolve) => { finish = resolve; });
  const applying = context.applyRelic('ally', 'FOOT', {template_identity: ''});
  assert.equal(JSON.parse(calls.at(-1).options.body).relic, null);
  node('scenarioEditor').value = '{"units":[]}';
  finish(ok({...buildOptions, scenario: relicDraft}));
  await applying;
  assert.equal(node('scenarioEditor').value, '{"units":[]}');
  assert.match(node('message').textContent, /校验期间发生变化/);
  assert.equal(state.busy, false);

  const characters = [{entity_ref: 'avatar:test', character_card_id: 'new-card', name: '<测试角色>', element: 'Wind', coverage_status: 'discovered_only'}];
  respond = async () => ok({characters});
  node('scenarioEditor').value = JSON.stringify(serverScenario);
  await context.loadCharacters();
  assert.equal(calls.at(-1).url, '/api/battle/characters');
  assert.match(node('setupFields').innerHTML, /&lt;测试角色&gt;/);
  const switched = structuredClone(serverScenario);
  switched.units[0].entity_ref = 'avatar:test';
  switched.units[0].character_build.character_card_id = 'new-card';
  respond = async () => ok({scenario: switched});
  await context.applyCharacter('ally', 'avatar:test');
  assert.equal(calls.at(-1).url, '/api/battle/character');
  assert.deepEqual(JSON.parse(calls.at(-1).options.body).entity_ref, 'avatar:test');
  assert.deepEqual(JSON.parse(node('scenarioEditor').value), switched);
  assert.equal(state.buildOptions, null);
  assert.equal(state.session.session_id, 'restored');
  respond = async () => ({ok: false, status: 400, json: async () => ({error: 'character blocked'})});
  await context.applyCharacter('ally', 'unknown');
  assert.deepEqual(JSON.parse(node('scenarioEditor').value), switched);

  const initialDraft = structuredClone(switched);
  initialDraft.units[0].initial_condition = {hp_mode: 'ratio', hp_value: '0.5', initial_energy: '30'};
  respond = () => new Promise((resolve) => { finish = resolve; });
  const settingInitial = context.applyInitialCondition('ally', {hp_mode: 'ratio', hp_value: '0.500', initial_energy: '30.00'});
  const initialCalls = calls.length;
  await context.applyInitialCondition('ally', {hp_mode: 'full', initial_energy: '0'});
  assert.equal(calls.length, initialCalls);
  assert.equal(calls.at(-1).url, '/api/battle/initial-condition');
  assert.deepEqual(JSON.parse(calls.at(-1).options.body).initial_condition,
                   {hp_mode: 'ratio', hp_value: '0.500', initial_energy: '30.00'});
  finish(ok({scenario: initialDraft}));
  await settingInitial;
  assert.deepEqual(JSON.parse(node('scenarioEditor').value), initialDraft);
  assert.match(node('setupFields').innerHTML, /初始生命值与能量/);
  assert.equal(state.session.session_id, 'restored');
  respond = async () => ({ok: false, status: 400, json: async () => ({error: 'initial condition rejected'})});
  await context.applyInitialCondition('ally', {hp_mode: 'ratio', hp_value: '2', initial_energy: '0'});
  assert.deepEqual(JSON.parse(node('scenarioEditor').value), initialDraft);
  respond = () => new Promise((resolve) => { finish = resolve; });
  const initialChanged = context.applyInitialCondition('ally', {hp_mode: 'absolute', hp_value: '100', initial_energy: '30'});
  node('scenarioEditor').value = JSON.stringify(switched);
  finish(ok({scenario: initialDraft}));
  await initialChanged;
  assert.deepEqual(JSON.parse(node('scenarioEditor').value), switched);
  assert.equal(state.busy, false);

  const partyDraft = structuredClone(switched);
  partyDraft.units[0].side = 'ally';
  partyDraft.units[0].position = 0;
  partyDraft.units.push({...structuredClone(partyDraft.units[0]), unit_id: '<second>', position: 1});
  node('scenarioEditor').value = JSON.stringify(partyDraft);
  context.renderSetup();
  assert.match(node('partyFormation').innerHTML, /从左到右/);
  assert.match(node('partyFormation').innerHTML, /&lt;second&gt;/);
  const reordered = structuredClone(partyDraft);
  reordered.units[0].position = 1;
  reordered.units[1].position = 0;
  respond = () => new Promise((resolve) => { finish = resolve; });
  const moving = context.applyPartyOrder(['<second>', 'ally']);
  const movingCalls = calls.length;
  await context.applyPartyOrder(['ally', '<second>']);
  assert.equal(calls.length, movingCalls);
  assert.equal(calls.at(-1).url, '/api/battle/party-order');
  assert.deepEqual(JSON.parse(calls.at(-1).options.body), {scenario: partyDraft, unit_ids: ['<second>', 'ally']});
  finish(ok({scenario: reordered}));
  await moving;
  assert.deepEqual(JSON.parse(node('scenarioEditor').value), reordered);
  assert.equal(state.session.session_id, 'restored');
  assert.equal(state.busy, false);
  respond = async () => ({ok: false, status: 400, json: async () => ({error: 'invalid order'})});
  await context.applyPartyOrder(['ally']);
  assert.deepEqual(JSON.parse(node('scenarioEditor').value), reordered);
  respond = () => new Promise((resolve) => { finish = resolve; });
  const changedOrder = context.applyPartyOrder(['ally', '<second>']);
  node('scenarioEditor').value = JSON.stringify(switched);
  finish(ok({scenario: partyDraft}));
  await changedOrder;
  assert.deepEqual(JSON.parse(node('scenarioEditor').value), switched);
  assert.match(node('message').textContent, /调整期间发生变化/);
  assert.equal(state.busy, false);

  // Party changes replace only the draft; stale responses cannot erase typing.
  const singleMember = structuredClone(partyDraft);
  singleMember.units.pop();
  node('scenarioEditor').value = JSON.stringify(singleMember);
  context.renderSetup();
  assert.match(node('partyFormation').innerHTML, /data-add-member/);
  assert.doesNotMatch(node('partyFormation').innerHTML, /data-remove-member/);
  respond = async () => ok({scenario: partyDraft});
  await context.applyCharacter(null, 'avatar:test', 'add');
  assert.equal(JSON.parse(calls.at(-1).options.body).operation, 'add');
  assert.deepEqual(JSON.parse(node('scenarioEditor').value), partyDraft);
  assert.match(node('partyFormation').innerHTML, /data-remove-member/);
  respond = async () => ok({scenario: singleMember});
  await context.applyCharacter('<second>', null, 'remove');
  assert.equal(JSON.parse(calls.at(-1).options.body).operation, 'remove');
  assert.deepEqual(JSON.parse(node('scenarioEditor').value), singleMember);
  assert.equal(state.session.session_id, 'restored');
  respond = () => new Promise((resolve) => { finish = resolve; });
  const adding = context.applyCharacter(null, 'avatar:test', 'add');
  node('scenarioEditor').value = JSON.stringify(partyDraft);
  finish(ok({scenario: singleMember}));
  await adding;
  assert.deepEqual(JSON.parse(node('scenarioEditor').value), partyDraft);
  assert.match(node('message').textContent, /保留当前编辑/);
  assert.equal(state.busy, false);

  node('stageSearch').value = '关卡 201';
  const stages = [{stage_id: '201010110', name: '<测试关卡>', level: 10, wave_count: 2}];
  respond = async () => ok({stages, total: 120});
  await context.searchStages();
  assert.equal(calls.at(-1).url, '/api/battle/stages?q=%E5%85%B3%E5%8D%A1+201');
  assert.match(node('stageChoice').innerHTML, /&lt;测试关卡&gt;/);
  assert.match(node('stageSearchResult').textContent, /120.*1/);
  node('stageChoice').value = '201010110';
  const stageScenario = {...switched, stage_ref: '201010110'};
  respond = () => new Promise((resolve) => { finish = resolve; });
  const staging = context.applyStage();
  const stageCalls = calls.length;
  await context.applyStage();
  assert.equal(calls.length, stageCalls);
  assert.equal(calls.at(-1).url, '/api/battle/stage');
  assert.equal(JSON.parse(calls.at(-1).options.body).stage_id, '201010110');
  finish(ok({scenario: stageScenario, stage: stages[0]}));
  await staging;
  assert.deepEqual(JSON.parse(node('scenarioEditor').value), stageScenario);
  assert.equal(state.session.session_id, 'restored');
  respond = async () => ({ok: false, status: 400, json: async () => ({error: 'stage blocked'})});
  await context.applyStage();
  assert.deepEqual(JSON.parse(node('scenarioEditor').value), stageScenario);
  respond = () => new Promise((resolve) => { finish = resolve; });
  const stageChanged = context.applyStage();
  node('scenarioEditor').value = JSON.stringify(switched);
  finish(ok({scenario: stageScenario, stage: stages[0]}));
  await stageChanged;
  assert.deepEqual(JSON.parse(node('scenarioEditor').value), switched);
  assert.equal(state.busy, false);

  node('caseSelect').value = 'example:demo';
  node('caseSelect').listeners.change();
  assert.equal(node('caseId').value, 'demo');
  node('caseSelect').value = 'custom';
  respond = (url) => url === '/api/cases/custom' ? new Promise((resolve) => { finish = resolve; }) : ok({});
  const loading = context.loadSelectedCase();
  const loadingCalls = calls.length;
  await context.loadSelectedCase();
  assert.equal(calls.length, loadingCalls);
  node('scenarioEditor').value = '{"units":[],"changed":true}';
  finish(ok(switched));
  await loading;
  assert.equal(node('scenarioEditor').value, '{"units":[],"changed":true}');
  assert.match(node('message').textContent, /已保留当前编辑/);
  assert.equal(state.busy, false);

  node('caseId').value = 'custom';
  node('observationsEditor').value = '{}';
  respond = (url) => url === '/api/cases/custom' ? new Promise((resolve) => { finish = resolve; }) : ok({cases: []});
  const saving = context.saveCase();
  const savingCalls = calls.length;
  await context.saveCase();
  assert.equal(calls.length, savingCalls);
  node('scenarioEditor').value = '{"units":[],"changed":"after-save"}';
  finish(ok({ok: true}));
  await saving;
  assert.match(node('message').textContent, /之后的编辑尚未保存/);
  respond = async (url) => url.startsWith('/api/observations/')
    ? {ok: false, status: 400, json: async () => ({error: 'disk full'})} : ok({});
  await assert.rejects(context.saveCase(), /配置已保存，但观测记录保存失败/);
  assert.equal(state.busy, false);

  context.acceptBattle({...restored, fork_choices: [{operation_index: 2, actor_id: 'ally', action_id: 'skill', target_ids: ['enemy']}]});
  node('forkChoice').value = '2';
  respond = async () => ({ok: false, status: 400, json: async () => ({error: 'history mismatch'})});
  await context.forkBattle();
  assert.equal(calls.at(-1).url, '/api/battle/fork');
  assert.deepEqual(JSON.parse(calls.at(-1).options.body), {session_id: 'restored', revision: 11, operation_index: 2});
  assert.equal(state.session.session_id, 'restored');
  respond = () => new Promise((resolve) => { finish = resolve; });
  const forking = context.forkBattle();
  const forkCalls = calls.length;
  await context.forkBattle();
  assert.equal(calls.length, forkCalls);
  finish(ok({...restored, session_id: 'branched', revision: 3, restored_operation_count: 2, fork_choices: []}));
  await forking;
  assert.equal(state.session.session_id, 'branched');
  assert.equal(state.report.restored_operation_count, 2);
  assert.equal(state.busy, false);
  await context.forkBattle();
  assert.equal(calls.length, forkCalls);
  assert.match(node('message').textContent, /有效的历史提交/);

  // Observations belong to the displayed committed moment, without submitting actions.
  const observationView = {...restored, battlefield_view: {units: [{unit_id: 'ally', display_name: '<hero>'}]}};
  context.acceptBattle(observationView);
  context.resetObservation();
  node('observationUnit').value = 'ally';
  node('observationHp').value = '10.20';
  node('observationEnergy').value = '0';
  node('observationVersion').value = 'game-version';
  node('observationNote').value = '<video> 00:10';
  node('observationsEditor').value = '{"existing":{"keep":true}}';
  node('observationHp').listeners.input();
  const observation = {unit_id: 'ally', entity_ref: 'avatar:example', scenario_id: 'scenario', revision: 11,
    captured_at: 'now', game_version: 'game-version', note: '<video> 00:10',
    measurements: {hp: {simulated: '10.1', observed: '10.20', difference: '0.10'}}};
  respond = () => new Promise((resolve) => { finish = resolve; });
  const recording = context.compareObservation();
  const recordingCalls = calls.length;
  await context.compareObservation();
  assert.equal(calls.length, recordingCalls);
  assert.equal(calls.at(-1).url, '/api/battle/observation');
  assert.deepEqual(JSON.parse(calls.at(-1).options.body), {
    session_id: 'restored', revision: 11, unit_id: 'ally', observed: {hp: '10.20', energy: '0'},
    game_version: 'game-version', note: '<video> 00:10',
  });
  finish(ok(observation));
  await recording;
  assert.deepEqual(JSON.parse(node('observationsEditor').value), {existing: {keep: true}, comparisons: [observation]});
  assert.equal(state.session.revision, 11);
  assert.equal(node('observationHp').value, '');
  assert.match(node('observationResults').innerHTML, /&lt;video&gt;/);
  assert.match(node('observationUnit').innerHTML, /&lt;hero&gt;/);

  // Keep user edits made while the comparison request is pending.
  node('observationHp').value = '12';
  const recordingEdited = context.compareObservation();
  node('observationsEditor').value = '{"edited":true}';
  finish(ok(observation));
  await recordingEdited;
  assert.equal(node('observationsEditor').value, '{"edited":true}');
  assert.equal(node('observationHp').value, '12');
  assert.match(node('message').textContent, /本次对照未追加/);

  respond = async () => ({ok: false, status: 400, json: async () => ({error: 'invalid observation'})});
  await context.compareObservation();
  assert.equal(node('observationsEditor').value, '{"edited":true}');
  assert.equal(state.busy, false);
  respond = async (url) => url.endsWith('/observation')
    ? {ok: false, status: 409, json: async () => ({error: 'stale observation'})}
    : ok({...observationView, revision: 12});
  const staleObservationCalls = calls.length;
  await context.compareObservation();
  assert.equal(calls.length, staleObservationCalls + 2);
  assert.equal(state.session.revision, 12);
  assert.equal(node('observationHp').value, '12');
  assert.equal(node('compareObservationBtn').disabled, true);
  await context.compareObservation();
  assert.equal(calls.length, staleObservationCalls + 2);
  assert.match(node('message').textContent, /按当前时刻重新填写/);
  context.resetObservation();
  assert.equal(node('compareObservationBtn').disabled, false);
  node('observationHp').value = '4';
  node('observationHp').listeners.input();
  context.acceptBattle({...observationView, revision: 13});
  assert.equal(node('compareObservationBtn').disabled, true);

  context.resetObservation();
  node('observationHp').value = '4';
  node('observationsEditor').value = '{"comparisons":{"old":"format"}}';
  await context.compareObservation();
  assert.match(node('message').textContent, /必须是记录数组/);
  assert.equal(calls.length, staleObservationCalls + 2);

  // Multi-target selection is capped by the kernel query and stays visible on the battlefield.
  const multiSlot = {slot: 'multi', label: '多目标', display_label: '多目标', actor_id: 'ally', action_ref: 'skill',
    action_level: 1, available: true, target_query: {selection_mode: 'explicit', selection_min: 1, selection_max: 2,
    candidate_ids: ['enemy-a', 'enemy-b', 'enemy-c']}};
  const multiUnits = [
    {unit_id: 'enemy-a', display_name: 'A', side: 'enemy'},
    {unit_id: 'enemy-b', display_name: 'B', side: 'enemy'},
    {unit_id: 'enemy-c', display_name: 'C', side: 'enemy'},
  ];
  state.report = {...view, battlefield_view: {units: multiUnits, enemy_units: multiUnits},
    action_prompt: {slots: [multiSlot]}, decision: {ready: true, token: {decision_id: 'multi'}}, steps: []};
  state.busy = false;
  // An unselected skill is a boolean accessibility state, not the string "null".
  const unselectedSkill = context.skillButton({available: true, slot: 'basic', action_ref: 'example'}, null);
  assert.match(unselectedSkill, /aria-pressed="false"/);
  assert.doesNotMatch(unselectedSkill, /aria-pressed="null"/);
  await context.selectSkill('multi');
  await context.handleUnitClick('enemy-a');
  await context.handleUnitClick('enemy-b');
  assert.deepEqual(Array.from(state.selectedTargets), ['enemy-a', 'enemy-b']);
  assert.match(node('enemyRow').innerHTML, /aria-pressed="true"/);
  assert.match(node('enemyRow').innerHTML, /class="unitCard enemy  targetable selected"/);
  await context.handleUnitClick('enemy-c');
  assert.deepEqual(Array.from(state.selectedTargets), ['enemy-a', 'enemy-b']);
  assert.match(node('message').textContent, /最多选择 2/);
  await context.handleUnitClick('enemy-a');
  assert.deepEqual(Array.from(state.selectedTargets), ['enemy-b']);

  // The retained route entry must carry the same queue/control metadata too.
  node('battleMode').value = 'route';
  node('scenarioEditor').value = JSON.stringify({route: []});
  context.runScenario = async () => {};
  await context.appendRouteStepWithTargets(slot, ['enemy'], 'enemy');
  const route = JSON.parse(node('scenarioEditor').value).route;
  const {action_id, ...rest} = template;
  assert.deepEqual(route, [{...rest, action_ref: action_id, target_ids: ['enemy']}]);
  console.log('live client checks passed');
})().catch((error) => { console.error(error); process.exitCode = 1; }).finally(() => clearTimeout(deadline));
