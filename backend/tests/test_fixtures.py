"""Parsers must keep working on real Qloo responses captured by scripts/probe_qloo.py."""
import json
from pathlib import Path

import pytest

from app import qloo as Q

FIX = Path(__file__).parent / "fixtures"
CASES = [("tag_search", Q.parse_tag_search), ("search", Q.parse_search), ("heatmap", Q.parse_heatmap),
         ("area_tags", Q.parse_area_tags), ("area_place", Q.parse_entities)]


@pytest.mark.parametrize("name,parser", CASES)
def test_parser_on_real_response(name, parser):
    f = FIX / f"{name}.json"
    if not f.exists():
        pytest.skip(f"run scripts/probe_qloo.py to capture {name}")
    parsed = parser(json.loads(f.read_text()))
    assert parsed, f"{name} parsed to an empty list"
    assert all(p.get("id") or "affinity" in p for p in parsed)
