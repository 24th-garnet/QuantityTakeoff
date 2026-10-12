"""実測 JSON の読み込み。**上流との契約を直したら落ちる**ように書く。"""
from __future__ import annotations

import json
from decimal import Decimal

import pytest

from takeoff import measures
from takeoff.measures import MeasureError

from .conftest import EXAMPLES

D = Decimal


def room(**kw) -> dict:
    base = dict(id="r1", name="居室", floor_area=10, ceiling_area=10,
                perimeter=13000, height=2400, wall_area=31.2,
                openings=[], furniture=[], basis={})
    return base | kw


def doc(**kw) -> dict:
    base = {"schema_version": measures.SCHEMA, "source": "test",
            "plan_id": "p1", "name": "n", "rooms": [room()]}
    return base | kw


def test_両方の見本が読める():
    for f in ("minicad", "scan"):
        m = measures.load(EXAMPLES / f"{f}.measures.json")
        assert m.rooms


def test_知らない版は断る():
    with pytest.raises(MeasureError, match="知らない版"):
        measures.parse(doc(schema_version="mdr-measures-9"))


def test_小数が_float_を通らずに読める():
    m = measures.load(EXAMPLES / "minicad.measures.json")
    assert m.rooms[0].floor_area == D("19.42")
    assert str(m.rooms[0].floor_area) == "19.42"


def test_開口の面積を出す():
    # 1690 × 1170 mm = 1.9773 m2
    o = measures.parse(doc(rooms=[room(openings=[
        {"id": "o1", "kind": "window", "width": 1690, "height": 1170, "sill": 800}
    ])])).rooms[0].openings[0]
    assert o.area == D("1.977300")


def test_床まで届く建具だけが_to_floor():
    r = measures.parse(doc(rooms=[room(openings=[
        {"id": "a", "kind": "door", "width": 800, "height": 2000, "sill": 0},
        {"id": "b", "kind": "window", "width": 1690, "height": 1170, "sill": 800},
    ])])).rooms[0]
    assert [o.to_floor for o in r.openings] == [True, False]


def test_部屋を分けられない上流は未計測と名乗る():
    # 語彙を増やさない。「部屋という概念が上流に無い」は未計測そのもの
    m = measures.load(EXAMPLES / "scan.measures.json")
    assert m.basis["partition"] == "未計測"
    assert m.split is False


def test_分けられる上流は分割済み():
    assert measures.load(EXAMPLES / "minicad.measures.json").split is True


def test_仮定を部屋の分まで集めて運ぶ():
    m = measures.load(EXAMPLES / "scan.measures.json")
    keys = [k for k, _, _ in m.assumptions]
    assert "partition" in keys
    assert any(k.endswith("wall_area") for k in keys)   # 部屋ごとの根拠も集める


def test_知らない根拠は断る():
    with pytest.raises(MeasureError, match="知らない根拠"):
        measures.parse(doc(rooms=[room(basis={"area": "だいたい"})]))


def test_根拠の無い欄は実測と読む():
    r = measures.parse(doc(rooms=[room(basis={"height": "既定"})])).rooms[0]
    assert r.basis_of("area") == "実測"
    assert r.basis_of("area", "height") == "既定"      # 一番弱いものが勝つ


def test_高さが_0_なら断る():
    with pytest.raises(MeasureError, match="height が 0"):
        measures.parse(doc(rooms=[room(height=0)]))


def test_負の面積は断る():
    with pytest.raises(MeasureError, match="負の値"):
        measures.parse(doc(rooms=[room(floor_area=-1)]))


def test_部屋が空なら断る():
    with pytest.raises(MeasureError, match="rooms が空"):
        measures.parse(doc(rooms=[]))


def test_不備は全部ためてから投げる():
    with pytest.raises(MeasureError) as e:
        measures.parse(doc(rooms=[room(id="", floor_area=-1, height=0)]))
    assert len(e.value.reasons) == 3


def test_家具の員数は_1_以上():
    with pytest.raises(MeasureError, match="1 以上"):
        measures.parse(doc(rooms=[room(furniture=[{"code": "sofa", "count": 0}])]))
