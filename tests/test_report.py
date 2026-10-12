"""書き出し。**受け手が食える形であること**を固定する。"""
from __future__ import annotations

import json
from decimal import Decimal

from takeoff import measures, report, rules, takeoff

from .conftest import EXAMPLES


def built(name: str = "minicad"):
    return takeoff.build(measures.load(EXAMPLES / f"{name}.measures.json"),
                         rules.load(EXAMPLES / "rules.toml"))


def test_全角を_2_で数える():
    assert report.width("洗面脱衣") == 8
    assert report.width("FL-2000") == 7


def test_表の列幅がそろう():
    lines = report.text(built()).splitlines()
    body = [l for l in lines if l.startswith(("居室", "洗面脱衣"))]
    assert len(body) >= 10
    assert len({report.width(l) for l in body}) == 1


def test_数量は末尾の_0_を落とすが指数にしない():
    assert report.num(Decimal("19.420")) == "19.42"
    assert report.num(Decimal("1000")) == "1000"


def test_部屋を分けられない上流はそう断る():
    assert "部屋を分けていない" in report.text(built("scan"))
    assert "部屋を分けていない" not in report.text(built())


def test_仮定を表に出す():
    out = report.text(built("scan"))
    assert "RoomPlan は壁厚を返さない" in out
    assert "仮定に頼った数量" in out


def test_実測でない根拠は注記に添える():
    d = report.quantities(built("scan"))
    wall = next(i for i in d["items"] if i["code"] == "WC-1000")
    assert "（根拠 既定）" in wall["note"]


def test_実測なら注記に根拠を書かない():
    d = report.quantities(built())
    floor = next(i for i in d["items"] if i["code"] == "FL-2000")
    assert "根拠" not in floor["note"]


def test_数量リストは数量を文字列で出す():
    # 受け手は Decimal で読み直す。JSON の数にすると float を経由した読み手が濁らせる
    d = report.quantities(built())
    assert d["items"][0]["qty"] == "19.42"
    assert isinstance(d["items"][0]["qty"], str)


def test_数量リストに出どころが入る():
    d = report.quantities(built())
    assert any("居室 床面積" == i["note"] for i in d["items"])


def test_同じ品目コードが_2_行あっても合算しない():
    # 「居室の壁」と「洗面脱衣の壁」は同じクロスでも別の行として見せたい
    d = report.quantities(built())
    walls = [i for i in d["items"] if i["code"] == "WC-1000"]
    assert len(walls) >= 2


def test_頭書きは渡されたときだけ入る():
    assert "estimate" not in report.quantities(built())
    d = report.quantities(built(), number="X-1", issued="2026-10-13")
    assert d["estimate"] == {"number": "X-1", "issued": "2026-10-13"}


def test_数量リストが_json_にできる():
    json.loads(report.quantities_json(built()))
