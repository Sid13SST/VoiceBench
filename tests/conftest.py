import json

import pytest


def make_scenario(**overrides):
    base = {
        "id": "v1-001",
        "version": "v1",
        "language": "en",
        "domain": "banking",
        "condition": "clean",
        "reference": "please send five thousand rupees to rahul",
        "expected_intent": "transfer_money",
        "expected_slots": {"amount": "5000", "recipient": "rahul"},
    }
    base.update(overrides)
    return base


@pytest.fixture
def scenario_dict():
    return make_scenario()


@pytest.fixture
def write_jsonl(tmp_path):
    def _write(rows, name="scenarios.jsonl"):
        path = tmp_path / name
        lines = [r if isinstance(r, str) else json.dumps(r, ensure_ascii=False) for r in rows]
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return path

    return _write
