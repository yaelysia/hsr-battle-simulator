"""Manually registered lifecycle rules from the pinned skill descriptions.

L0 content registration only: no runtime reads or interprets TextMap. The four
skills explicitly retire the companion on its creator's confirmed defeat; the
last also names the selected bondmate. Watching both roles is idempotent when
they identify the same unit. No default is inferred for passive form timers.
"""
from ..ir_types import IRSource


_TEXT_KEYS = {
    'battle_event:11203': '5744414498088641135',
    'battle_event:11216': '7118445344770551617',
    'battle_event:11222': '18297897681472862996',
    'battle_event:11414': '18015099429909317122',
}


def registered_battle_event_lifecycle(entity_ref: str) -> dict:
    key = _TEXT_KEYS.get(entity_ref)
    if key is None:
        return {}
    source = IRSource('TextMap/TextMapCHS.json', 'TextMapEntry', key, {
        'json_path': '$.' + key,
        'registration': 'manually_registered_skill_lifecycle',
        'version': 'pinned_tbgd_14c1d18f91a8101d610e6c523447a7517de3fae1',
        'condition': 'creator or current bound companion holder is confirmed defeated or removed; not limbo',
        'conclusion': 'owned action companion disappears; origin and current holder remain separate roles',
    })
    return {
        'admission_status': 'executable',
        'retire_on_terminal_dependency': ['creation_source_unit_id', 'owner_id'],
        'source': source.to_json(),
    }
