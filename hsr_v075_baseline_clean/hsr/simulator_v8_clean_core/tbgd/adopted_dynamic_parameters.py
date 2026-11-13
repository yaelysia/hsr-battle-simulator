"""Explicit numeric declarations taken from skill text, not missing-slot guesses.

Fixed 14c1d18f: 800704 says each 10 recovered energy grants 1% Mem charge;
1800703 says 100% charge grants immediate action. Native BattleCry/Skill writes
multiply the stated percentage by 100, so the store uses percentage points.
The native expressions read the per-step coefficient through hash 1776456860
and the cap through 1283247492, without declaring their values in the config.
"""


def adopt_charge_parameters(bindings, config_path):
    avatar = config_path == 'Config/ConfigCharacter/Avatar/Avatar_PlayerBoy_30_Config.json'
    servant = config_path == 'Config/ConfigCharacter/Servant/Servant_PlayerBoyServant_30_Config.json'
    if not (avatar or servant):
        return bindings
    values = {'1776456860': 1.0, **({'1283247492': 100.0} if servant else {})}
    by_hash = dict(bindings.get('by_hash', {}))
    for key, value in values.items():
        by_hash[key] = {**by_hash.get(key, {}), 'hash': key,
            'read_info': {'Type': 'None', 'Index': 0}, 'initial_value': value,
            'source_path': 'adopted:800704-and-1800703-skill-text',
            'value_basis': '1% per 10 energy; full charge 100%; native unit is percentage points',
            'version': 'TBGD 14c1d18f'}
    return {**bindings, 'by_hash': by_hash}
