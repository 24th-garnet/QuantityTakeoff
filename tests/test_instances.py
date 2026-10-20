"""置いてあるものを 1 個ずつ受ける。**椅子 4 脚を別々に扱える。**

`furniture` が `{"code": "chair", "count": 4}` と種別で数えるのに対し、
`instances` は 1 個ずつ識別子を持つ。4 脚のうち 1 脚だけ別の品目にできるのは、
個体が並んでいるときだけ。

**置換したアセットが種別より勝つ。** 3D の上で人がカタログから選んだものが、
「ソファという種別」より具体的だから。対応表そのものは拾い側に無い——単価も
品目も見積り側の持ち物なので、`(source, id)` を引く呼び出しを受け取るだけ。
"""
from __future__ import annotations

import tomllib
from decimal import Decimal

import pytest

from takeoff import measures, rules, takeoff

from .test_takeoff import FIXED, RULES

D = Decimal

CHAIRS = [
    {"id": "c1", "category": "chair", "label": "椅子"},
    {"id": "c2", "category": "chair", "label": "椅子"},
]


def doc(instances, **room) -> dict:
    r = {**FIXED["rooms"][0], "instances": instances, **room}
    return {**FIXED, "rooms": [r]}


def built(instances, resolve=None, rule_text=RULES, **room):
    return takeoff.build(measures.parse(doc(instances, **room)),
                         rules.parse(tomllib.loads(rule_text)), resolve)


def things(result) -> list[tuple[str, str]]:
    """(品目コード, どの個体から来たか)。"""
    return [(i.code, i.ref) for i in result.items if i.kind == "家具"]


# --- 1 個ずつ ----------------------------------------------------------------

def test_同じ種別でも1個ずつ行が立つ():
    got = things(built(CHAIRS, rule_text=RULES.replace("sofa = \"SF\"",
                                                       "chair = \"CH\"")))
    assert got == [("CH", "c1"), ("CH", "c2")]
    assert all(i.qty == D(1) for i in built(CHAIRS, rule_text=RULES.replace(
        "sofa = \"SF\"", "chair = \"CH\"")).items if i.kind == "家具")


def test_1脚だけ別の品目にできる():
    """**これが個体にした理由。**"""
    picked = [CHAIRS[0], {**CHAIRS[1], "item": "ERABI"}]
    got = things(built(picked, rule_text=RULES.replace('sofa = "SF"',
                                                       'chair = "CH"')))
    assert got == [("CH", "c1"), ("ERABI", "c2")]


def test_個体が無ければ種別で畳んだまま():
    """**後方互換。** 上流が員数を分けて出せないなら従来どおり。"""
    a = takeoff.build(measures.parse(FIXED), rules.parse(tomllib.loads(RULES)))
    assert [(i.code, i.qty) for i in a.items if i.kind == "家具"] == [("SF", D(2))]


# --- 置換アセット ------------------------------------------------------------

def test_置換したアセットが品目を決める():
    one = [{"id": "x", "category": "chair", "label": "椅子",
            "asset": {"source": "abo", "id": "B071FMSY5S"}}]
    got = built(one, lambda s, a: "ERABI" if (s, a) == ("abo", "B071FMSY5S") else None)
    assert things(got) == [("ERABI", "x")]


def test_置換が種別の規則より勝つ():
    """**人が 3D の上で選んだものが、種別より具体的。**"""
    one = [{"id": "x", "category": "sofa", "label": "ソファ",
            "asset": {"source": "abo", "id": "B0"}}]
    got = built(one, lambda s, a: "ERABI")
    assert things(got) == [("ERABI", "x")]       # 規則の SF ではない


def test_規則に無い種別でも置換してあれば拾える():
    """`[furniture]` に bed が無くても、カタログから選んであれば拾う。"""
    one = [{"id": "x", "category": "bed", "label": "ベッド",
            "asset": {"source": "abo", "id": "B0"}}]
    got = built(one, lambda s, a: "BED-01")
    assert things(got) == [("BED-01", "x")]
    assert not got.unassigned


def test_対応表に無いアセットは報告に出る():
    """**黙って種別に落とさない。** 書き忘れが見積書から消える。"""
    one = [{"id": "x", "category": "sofa", "label": "ソファ",
            "asset": {"source": "abo", "id": "B0"}}]
    got = built(one, lambda s, a: None)
    assert things(got) == []
    assert [u.kind for u in got.unassigned] == ["置換"]
    assert "abo/B0" in got.unassigned[0].detail
    assert "ソファ" in got.unassigned[0].detail


def test_入れないと決めたものは黙って飛ばす():
    """空文字は人が決めた印。**報告に出し続けると誰も見なくなる。**"""
    one = [{"id": "x", "category": "sofa", "asset": {"source": "a", "id": "b"}}]
    got = built(one, lambda s, a: "")
    assert things(got) == [] and not got.unassigned


def test_直に指した品目が置換より勝つ():
    one = [{"id": "x", "category": "sofa", "item": "CHOKUSETSU",
            "asset": {"source": "abo", "id": "B0"}}]
    assert things(built(one, lambda s, a: "ASSET")) == [("CHOKUSETSU", "x")]


# --- 断り方 ------------------------------------------------------------------

def test_識別子の無い個体は断る():
    with pytest.raises(measures.MeasureError) as e:
        measures.parse(doc([{"category": "chair"}]))
    assert "id が空" in str(e.value)


def test_識別子の重複は断る():
    with pytest.raises(measures.MeasureError) as e:
        measures.parse(doc([{"id": "a", "category": "c"},
                            {"id": "a", "category": "c"}]))
    assert "a が重複している" in str(e.value)


def test_出どころの無いアセットは断る():
    """**bare な id は識別にならない。** ASIN とファイル名では空間が違う。"""
    with pytest.raises(measures.MeasureError) as e:
        measures.parse(doc([{"id": "x", "category": "c",
                             "asset": {"id": "B0"}}]))
    assert "source と id の両方が要る" in str(e.value)


def test_寸法は値段を決めない():
    """運ぶが、品目は決めない。**見積書に添えるだけ。**"""
    one = [{"id": "x", "category": "sofa", "extent": [1800, 760, 880]}]
    r = measures.parse(doc(one)).rooms[0].instances[0]
    assert r.extent == (D(1800), D(760), D(880))
    assert things(built(one)) == [("SF", "x")]   # 種別の規則で決まっている
