import json
from pathlib import Path

import pytest

from rebuilt.genome.io import load, parse
from rebuilt.model.compile import compile_genome

ROOT = Path(__file__).resolve().parents[1]
HOUSE = ROOT / "examples/fictional_house/fictional_house.genome.json"
EVIDENCE = ROOT / "examples/fictional_house/evidence"


@pytest.fixture(scope="session")
def raw():
    return json.loads(HOUSE.read_text())


@pytest.fixture(scope="session")
def genome():
    g, issues = load(HOUSE)
    assert g is not None, issues.items
    return g


@pytest.fixture(scope="session")
def model(genome):
    return compile_genome(genome)


def variant(raw, mutate):
    import copy

    d = copy.deepcopy(raw)
    mutate(d)
    return parse(d)
