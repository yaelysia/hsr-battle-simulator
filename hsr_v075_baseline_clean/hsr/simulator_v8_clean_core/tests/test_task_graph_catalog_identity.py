"""The task graph catalog identity keeps the exact byte stream after chunking.

The catalog digest is produced member by member so one large catalog never becomes a
single string. The same valid input must produce byte-identical hash input and catalog
id; the formal catalog fixture check at
tests/test_p9_a2_p3_wait_anim_state_process_only_barrier_retirement.py keeps the
end-to-end catalog id comparison.
"""
from __future__ import annotations

import json
from hashlib import sha256

import pytest

from hsr.simulator_v8_clean_core.rules.task_graph import _catalog_identity_digest


class _Item:
    def __init__(self, payload: object):
        self.payload = payload

    def to_json(self) -> object:
        return self.payload


def _complete_json_digest(identity: dict[str, object]) -> str:
    encoded = json.dumps(
        identity,
        sort_keys=True,
        separators=(",", ":"),
        default=lambda item: item.to_json(),
    )
    return sha256(encoded.encode("utf-8")).hexdigest()


@pytest.mark.parametrize(
    "identity",
    (
        {},
        {"z": [], "a": (), "中文": [True, 1, 1.0, None, -0.0, '"\\\n中文']},
        {"rows": [_Item({"z": [1.25e-30, {"b": "值", "a": False}]})], "flag": True},
        {
            "mixed": (_Item([1, 2]), {"nested": [None, ""]}),
            "large": [f"member:{index}" for index in range(256)],
        },
    ),
)
def test_catalog_identity_digest_matches_the_complete_json(identity):
    assert _catalog_identity_digest(identity) == _complete_json_digest(identity)
