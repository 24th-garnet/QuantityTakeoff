"""上流で選んだ仕上げ。**規則より選択が勝つ。**

`[[finish]]` は「居室の壁は量産クロス」という**部屋の種別ごとの決め打ち**で、
3D の上で面を選んで壁紙を決めたときに、その選択を書き留める先が無かった。
`rooms[].finish` と `rooms[].furniture[].item` がその先になる。

**拾い方は変わらない。** 面積も員数もこれまで通りで、変わるのはどの品目コードを
付けるかだけ。ここで数量が動いたら、選択が拾い方に漏れている。
"""
from __future__ import annotations

import tomllib
from decimal import Decimal

import pytest

from takeoff import measures, rules, takeoff

from .test_takeoff import FIXED, RULES

D = Decimal


def built(room_extra: dict | None = None, rule_text: str = RULES):
    doc = {**FIXED, "rooms": [{**FIXED["rooms"][0], **(room_extra or {})}]}
    return takeoff.build(measures.parse(doc), rules.parse(tomllib.loads(rule_text)))


def codes(result) -> dict[str, str]:
    """面の種類 → 付いた品目コード。"""
    return {i.kind: i.code for i in result.items}


def qty(result, kind: str) -> Decimal:
    return next(i.qty for i in result.items if i.kind == kind)


# --- 面 ----------------------------------------------------------------------

def test_選んだ仕上げが規則に勝つ():
    got = built({"finish": {"wall": "ERABI"}})
    assert codes(got)["wall"] == "ERABI"
    assert codes(got)["ceiling"] == "CE"      # 選んでいない面は規則のまま


def test_選んでも数量は変わらない():
    """**選択は品目コードだけを決める。** 面積に触れたら拾い方が漏れている。"""
    before, after = built(), built({"finish": {"wall": "ERABI"}})
    assert qty(after, "wall") == qty(before, "wall")
    assert qty(after, "floor") == qty(before, "floor")


def test_空文字は拾わない印():
    """規則が品目を持っていても、選んで外せる。"""
    got = built({"finish": {"cornice": ""}})
    assert "cornice" not in codes(got)
    # 「拾わなかった」ことは報告に残さない——人が決めた印なので
    assert not any(u.kind == "回縁" for u in got.unassigned)


def test_規則に当たらない部屋でも選べば拾える():
    """**部屋名が当たらなくても止まらない。**

    スキャンは部屋名を持たないことがある。名前が合わないというだけで
    何も拾えないのでは、3D の上で選んだ意味が無い。
    """
    got = built({"name": "名無し", "finish": {"wall": "WA", "floor": "FL"}})
    assert codes(got)["wall"] == "WA"
    assert not any(u.kind == "仕上げ" for u in got.unassigned)


def test_規則にも選択にも無い面は報告に出る():
    got = built({"name": "名無し", "finish": {"wall": "WA"}})
    assert {u.kind for u in got.unassigned} >= {"床", "天井", "巾木"}


def test_知らない面の名前は断る():
    """**黙って無視しない。** 選んだのに反映されないのが一番気付きにくい。"""
    with pytest.raises(measures.MeasureError) as e:
        measures.parse({**FIXED,
                        "rooms": [{**FIXED["rooms"][0], "finish": {"wal": "WA"}}]})
    assert "知らない面" in str(e.value)


def test_finishが辞書でなければ断る():
    with pytest.raises(measures.MeasureError):
        measures.parse({**FIXED, "rooms": [{**FIXED["rooms"][0], "finish": "WA"}]})


# --- 置いてあるもの ----------------------------------------------------------

def test_選んだ品目が家具の規則に勝つ():
    room = {**FIXED["rooms"][0],
            "furniture": [{"code": "sofa", "label": "ソファ", "count": 2,
                           "item": "ERABI-SOFA"}]}
    got = takeoff.build(measures.parse({**FIXED, "rooms": [room]}),
                        rules.parse(tomllib.loads(RULES)))
    furn = [i for i in got.items if i.kind == "家具"]
    assert [i.code for i in furn] == ["ERABI-SOFA"]
    assert furn[0].qty == 2        # 員数は変わらない


def test_規則に無い種別でも選べば拾える():
    """`[furniture]` に `bed` が無くても、選んだなら拾う。"""
    room = {**FIXED["rooms"][0],
            "furniture": [{"code": "bed", "label": "ベッド", "count": 1,
                           "item": "BED-01"}]}
    got = takeoff.build(measures.parse({**FIXED, "rooms": [room]}),
                        rules.parse(tomllib.loads(RULES)))
    assert [i.code for i in got.items if i.kind == "家具"] == ["BED-01"]
    assert not any(u.kind == "家具" for u in got.unassigned)


def test_選ばなければ規則のまま():
    got = built()
    assert [i.code for i in got.items if i.kind == "家具"] == ["SF"]


def test_選択が無いときの振る舞いは変わらない():
    """**既存の見本が同じ数量を出す。** 載せ替えで静かに変わるのが一番困る。"""
    a = built()
    b = built({"finish": {}})
    assert [(i.code, i.qty, i.kind) for i in a.items] == \
           [(i.code, i.qty, i.kind) for i in b.items]
