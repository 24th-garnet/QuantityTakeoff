"""見積モジュールまで通ること。**契約が合っていなければ落ちる。**

`InteriorEstimation` が隣に無ければ飛ばす。片方だけ clone した環境でも
テストが落ちないようにする。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from takeoff import measures, report, rules, takeoff

from .conftest import EXAMPLES, ROOT

EST = ROOT.parent / "InteriorEstimation"
pytestmark = pytest.mark.skipif(not (EST / "estimate").is_dir(),
                                reason="InteriorEstimation が隣に無い")


@pytest.fixture(scope="module")
def estimate_mod():
    if str(EST) not in sys.path:
        sys.path.insert(0, str(EST))
    from estimate import breakdown, price, quantity
    return breakdown, price, quantity


def quantities(tmp_path: Path) -> Path:
    r = takeoff.build(measures.load(EXAMPLES / "minicad.measures.json"),
                      rules.load(EXAMPLES / "rules.toml"))
    p = tmp_path / "q.json"
    p.write_text(report.quantities_json(r), encoding="utf-8")
    return p


def test_拾った数量リストを見積が読める(tmp_path, estimate_mod):
    _, _, quantity = estimate_mod
    sheet = quantity.load(quantities(tmp_path))
    assert len(sheet.lines) >= 15


def test_拾った品目がすべて見本の単価表に当たる(tmp_path, estimate_mod):
    breakdown, price, quantity = estimate_mod
    book = price.load(EST / "examples/prices.csv", EST / "examples/trades.csv")
    est = breakdown.build(quantity.load(quantities(tmp_path)), book)
    assert est.complete is True, [u.code for u in est.unknown]


def test_数量が_float_を通らずに渡る(tmp_path, estimate_mod):
    _, _, quantity = estimate_mod
    sheet = quantity.load(quantities(tmp_path))
    floor = next(l for l in sheet.lines if l.code == "FL-2000")
    assert str(floor.qty) == "19.42"


def test_見積の合計が行の和と一致する(tmp_path, estimate_mod):
    breakdown, price, quantity = estimate_mod
    book = price.load(EST / "examples/prices.csv", EST / "examples/trades.csv")
    est = breakdown.build(quantity.load(quantities(tmp_path)), book)
    assert est.amount == sum((r.amount for r in est.rows), type(est.amount)(0))
