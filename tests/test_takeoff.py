"""積算基準の規約。**数字を直したら落ちる**ように書く。

見積りの数量は後から検算されるので、規約が黙って変わるのが一番困る。
"""
from __future__ import annotations

from decimal import Decimal

import pytest

from takeoff import measures, rules, takeoff

from .conftest import EXAMPLES

D = Decimal

#: 規約を検算するための固定の実測。**見本とは切り離す。**
#: 見本は作り直されるが、規約は変わらない
FIXED = {
    "schema_version": "mdr-measures-1", "source": "test",
    "plan_id": "t1", "name": "検算用",
    "rooms": [{
        "id": "r1", "name": "居室",
        "floor_area": 20, "ceiling_area": 20,
        "perimeter": 18000, "height": 2400, "wall_area": 43.2,
        "openings": [
            # 掃き出し窓 1.8 × 2.0 = 3.6 ㎡（床まで届く）
            {"id": "a", "kind": "slidingDouble", "width": 1800, "height": 2000, "sill": 0},
            # 腰窓 1.6 × 1.1 = 1.76 ㎡（床まで届かない）
            {"id": "b", "kind": "window", "width": 1600, "height": 1100, "sill": 800},
            # 小窓 0.6 × 0.6 = 0.36 ㎡（0.5 ㎡以下）
            {"id": "c", "kind": "window", "width": 600, "height": 600, "sill": 1200},
        ],
        "furniture": [{"code": "sofa", "label": "ソファ", "count": 2}],
        "basis": {},
    }],
    "basis": {},
}

RULES = '''
standard = "検算用"
[[finish]]
rooms = ["居室"]
floor = "FL"
ceiling = "CE"
wall = "WA"
baseboard = "BB"
cornice = "CN"
strip = "ST"
[fittings]
slidingDouble = "DR"
window = "WD"
[furniture]
sofa = "SF"
'''


@pytest.fixture(scope="module")
def room():
    return measures.parse(FIXED).rooms[0]


@pytest.fixture(scope="module")
def built():
    import tomllib
    return takeoff.build(measures.parse(FIXED), rules.parse(tomllib.loads(RULES)))


def qty_of(result, code: str) -> Decimal:
    return next(i.qty for i in result.items if i.code == code)


# --- 開口の欠除 ---------------------------------------------------------

def test_開口は_1_箇所_0_5_平米以下なら差し引かない(room):
    # 掃き出し 3.6 と腰窓 1.76 は引く。小窓 0.36 は引かない
    # 43.2 − 3.6 − 1.76 = 37.84
    assert takeoff.deducted_wall(room, D("0.5")) == D("37.84")


def test_閾値を下げると小窓も引かれる(room):
    # 37.84 − 0.36 = 37.48
    assert takeoff.deducted_wall(room, D("0.1")) == D("37.48")


def test_開口が壁を超えても負にしない(room):
    assert takeoff.deducted_wall(room, D("0")) >= 0


# --- 巾木と回縁 ---------------------------------------------------------

def test_巾木は床まで届く建具の幅だけを引く(room):
    # 18000 − 1800（掃き出しのみ）= 16200mm = 16.2m
    assert takeoff.baseboard_length(room) == D("16.2")


def test_腰窓は巾木から引かない(room):
    # 腰窓 1600 と小窓 600 を引いたら 14.0 になってしまう
    assert takeoff.baseboard_length(room) != D("14")


def test_回縁は周長そのまま(room):
    # 建具は天井まで届かないので引かない
    assert takeoff.cornice_length(room) == D("18")


def test_巾木による壁の欠除は無いものとする(room, built):
    # 基準は「巾木・回縁等による仕上げの欠除は、幅又は高さを問わず無いものとする」
    # 壁面積から巾木の高さを引いていないことを固定する
    assert qty_of(built, "WA") == D("37.84")


# --- 面ごとの数量 -------------------------------------------------------

def test_床と天井は実測をそのまま使う(built):
    assert qty_of(built, "FL") == D("20")
    assert qty_of(built, "CE") == D("20")


def test_撤去は壁と天井の既存仕上げ(built):
    # 37.84 + 20 = 57.84
    assert qty_of(built, "ST") == D("57.84")


def test_長さの数量は_m_で出す(built):
    item = next(i for i in built.items if i.code == "BB")
    assert item.unit == "m" and item.qty == D("16.2")


def test_面積の数量は_平米_で出す(built):
    assert next(i for i in built.items if i.code == "FL").unit == "㎡"


# --- 員数 ---------------------------------------------------------------

def test_建具は種別ごとに数える(built):
    assert qty_of(built, "DR") == D("1")
    assert qty_of(built, "WD") == D("2")      # 腰窓と小窓


def test_家具の員数をそのまま運ぶ(built):
    assert qty_of(built, "SF") == D("2")


# --- 当たらなかったもの -------------------------------------------------

def test_仕上げの当たらない部屋を数えて見せる():
    import tomllib
    m = measures.parse(FIXED | {"rooms": [FIXED["rooms"][0] | {"name": "書庫"}]})
    r = takeoff.build(m, rules.parse(tomllib.loads(RULES)))
    assert [u.kind for u in r.unassigned] == ["仕上げ"]
    assert r.complete is False


def test_品目コードの無い建具を数えて見せる():
    import tomllib
    r = takeoff.build(measures.parse(FIXED),
                      rules.parse(tomllib.loads(RULES.replace('window = "WD"\n', ''))))
    assert any(u.kind == "建具" for u in r.unassigned)


def test_空文字は拾わないという判断なので報告しない():
    # 「まだ見ていない」と「この部屋にその面は無い」を分ける
    import tomllib
    r = takeoff.build(measures.parse(FIXED),
                      rules.parse(tomllib.loads(RULES.replace('window = "WD"', 'window = ""'))))
    assert not any(u.kind == "建具" for u in r.unassigned)
    assert not any(i.code == "WD" for i in r.items)


def test_全部当たれば_complete(built):
    assert built.complete is True


# --- 仮定の報告 ---------------------------------------------------------

def test_上流の仮定を運ぶ():
    m = measures.load(EXAMPLES / "scan.measures.json")
    r = takeoff.build(m, rules.load(EXAMPLES / "rules.toml"))
    assert [k for k, _, _ in r.assumptions]
    assert r.split is False


def test_仮定の無い上流では何も言わない(built):
    assert built.assumptions == () and built.weak_items == ()


def test_数量の根拠は使った入力の一番弱いもの():
    # 壁は wall_area・height・openings を使う。height が既定なら壁の根拠も既定
    m = measures.parse(FIXED | {"rooms": [FIXED["rooms"][0] | {"basis": {"height": "既定"}}]})
    import tomllib
    r = takeoff.build(m, rules.parse(tomllib.loads(RULES)))
    assert next(i for i in r.items if i.code == "WA").basis == "既定"
    assert next(i for i in r.items if i.code == "FL").basis == "実測"


def test_必ず過大になる根拠を別枠で数える():
    m = measures.parse(FIXED | {"rooms": [FIXED["rooms"][0] | {"basis": {"area": "外接"}}]})
    import tomllib
    r = takeoff.build(m, rules.parse(tomllib.loads(RULES)))
    assert [i.code for i in r.overstated] == ["FL", "CE", "ST"]


def test_数量は第_3_位を四捨五入する():
    # 切り上げない（過大な見積りは説明できない）、切り捨てない（材料が足りなくなる）
    assert takeoff.round_qty(Decimal("19.4349")) == Decimal("19.43")
    assert takeoff.round_qty(Decimal("19.4350")) == Decimal("19.44")


def test_拾って_0_だった面は落として数える():
    # 「拾い忘れ」と区別する
    import tomllib
    m = measures.parse(FIXED | {"rooms": [FIXED["rooms"][0] | {"ceiling_area": 0}]})
    r = takeoff.build(m, rules.parse(tomllib.loads(RULES)))
    assert [d.kind for d in r.dropped] == ["天井"]
    assert not any(i.code == "CE" for i in r.items)


def test_拠った基準を結果に残す(built):
    assert built.standard == "検算用"
