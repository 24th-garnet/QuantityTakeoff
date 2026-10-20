"""面を個体で受ける。**壁 1 枚ずつに別の仕上げを当てられる。**

室の合計（`wall_area`）だけでは 4 面に別々の壁紙が貼れない。面が id を持って
並んでいれば、面ごとに 1 行を立てられる。

**足し合わせると室ごとの答えに戻ること**を固定する。ここが割れると、面ごとに
拾うか室ごとに拾うかで金額が変わり、**どちらが本当か説明できなくなる**。

壁は面積ではなく長さと高さで受ける。開口を引くのは積算基準の規約（1 か所
`min_opening` ㎡以下は引かない）で、**上流が先に引いてはいけない**。
"""
from __future__ import annotations

import tomllib
from decimal import Decimal

import pytest

from takeoff import measures, rules, takeoff

from .test_takeoff import FIXED, RULES

D = Decimal

#: 検算用の 4 面。周長 18m・壁高 2.4m の室を 4 枚に割る。
#: 掃き出し窓（3.6 ㎡）は w0 に、腰窓（1.76 ㎡）は w1 に、小窓（0.36 ㎡）は w2 に。
FACES = [
    {"id": "w0", "kind": "wall", "length": 5000, "height": 2400, "openings": ["a"]},
    {"id": "w1", "kind": "wall", "length": 4000, "height": 2400, "openings": ["b"]},
    {"id": "w2", "kind": "wall", "length": 5000, "height": 2400, "openings": ["c"]},
    {"id": "w3", "kind": "wall", "length": 4000, "height": 2400, "openings": []},
    {"id": "__floor__", "kind": "floor", "area": 20},
    {"id": "__ceiling__", "kind": "ceiling", "area": 20},
]


def doc(faces=FACES, **room) -> dict:
    r = {**FIXED["rooms"][0], "surfaces": faces, **room}
    return {**FIXED, "rooms": [r]}


def built(faces=FACES, rule_text=RULES, **room):
    return takeoff.build(measures.parse(doc(faces, **room)),
                         rules.parse(tomllib.loads(rule_text)))


def walls(result) -> list:
    return [i for i in result.items if i.kind == "wall"]


# --- 面ごとに拾える ----------------------------------------------------------

def test_壁は面ごとに1行():
    got = walls(built())
    assert [i.note for i in got] == [
        "居室 w0 壁面積。開口 1 箇所を差し引き",
        "居室 w1 壁面積。開口 1 箇所を差し引き",
        "居室 w2 壁面積。差し引く開口なし",     # 小窓 0.36 ㎡ は引かない
        "居室 w3 壁面積。差し引く開口なし",
    ]


def test_面ごとに別の仕上げを当てられる():
    """**これが面を個体にした理由。**"""
    faces = [{**f, "finish": "ERABI"} if f["id"] == "w0" else f for f in FACES]
    got = {i.note.split()[1]: i.code for i in walls(built(faces))}
    assert got["w0"] == "ERABI"
    assert got["w1"] == got["w2"] == got["w3"] == "WA"   # 選んでいない面は規則のまま


def test_その面に属する開口だけを引く():
    """室の合計から引くのと違い、**どの建具がどの壁に付いているか**で引ける。"""
    got = {i.note.split()[1]: i.qty for i in walls(built())}
    assert got["w0"] == D("8.4")      # 5.0×2.4 = 12.0 − 3.6（掃き出し窓）
    assert got["w1"] == D("7.84")     # 4.0×2.4 =  9.6 − 1.76（腰窓）
    assert got["w2"] == D("12")       # 5.0×2.4 = 12.0 − 0（小窓は 0.5 ㎡以下）
    assert got["w3"] == D("9.6")      # 4.0×2.4 =  9.6


def test_足すと室ごとの答えに戻る():
    """**面ごとと室ごとで金額が変わってはいけない。**"""
    per_face = sum((i.qty for i in walls(built())), D(0))
    whole = next(i.qty for i in walls(built(faces=[])))
    assert per_face == whole


def test_床と天井も面で来る():
    got = {i.kind: i.qty for i in built().items if i.kind in ("floor", "ceiling")}
    assert got["floor"] == D("20") and got["ceiling"] == D("20")


def test_巾木と回縁は面から導くので室ごとのまま():
    """**クリックできる面ではない。** 周長から引くので 1 行で足りる。"""
    got = [i for i in built().items if i.kind in ("baseboard", "cornice")]
    assert [i.note for i in got] == ["居室 内法周長 − 床まで届く建具 1 箇所",
                                     "居室 内法周長"]


def test_面が無ければ従来どおり():
    """**後方互換。** 上流が面を分けて出せないなら室の合計で拾う。"""
    a, b = built(faces=[]), takeoff.build(measures.parse(FIXED),
                                          rules.parse(tomllib.loads(RULES)))
    assert [(i.code, i.qty, i.note) for i in a.items] == \
           [(i.code, i.qty, i.note) for i in b.items]


def test_面の根拠は弱いほうが勝つ():
    faces = [{**f, "basis": "外接"} if f["id"] == "w0" else f for f in FACES]
    got = {i.note.split()[1]: i.basis for i in walls(built(faces))}
    assert got["w0"] == "外接"
    assert got["w1"] == "実測"


# --- 断り方 ------------------------------------------------------------------

def test_知らない面の種類は断る():
    with pytest.raises(measures.MeasureError) as e:
        measures.parse(doc([{"id": "x", "kind": "巾木"}]))
    assert "知らない面の種類" in str(e.value)


def test_室に無い開口を指したら断る():
    """**黙って無視しない。** 指し先が無ければ、その壁は引かれずに過大になる。"""
    with pytest.raises(measures.MeasureError) as e:
        measures.parse(doc([{"id": "w0", "kind": "wall", "length": 1000,
                             "height": 2400, "openings": ["zzz"]}]))
    assert "開口 zzz が室の openings に無い" in str(e.value)


def test_識別子の無い面は断る():
    with pytest.raises(measures.MeasureError) as e:
        measures.parse(doc([{"kind": "wall", "length": 1000, "height": 2400}]))
    assert "id が空" in str(e.value)


def test_面の重複は断る():
    f = {"id": "w0", "kind": "wall", "length": 1000, "height": 2400}
    with pytest.raises(measures.MeasureError) as e:
        measures.parse(doc([f, dict(f)]))
    assert "面 w0 が重複している" in str(e.value)


def test_寸法が0の壁は断る():
    """数量の出ない面を黙って並べない。"""
    with pytest.raises(measures.MeasureError) as e:
        measures.parse(doc([{"id": "w0", "kind": "wall",
                             "length": 0, "height": 2400}]))
    assert "長さか高さが 0" in str(e.value)


def test_床が2枚あったら断る():
    f = {"kind": "floor", "area": 10}
    with pytest.raises(measures.MeasureError) as e:
        measures.parse(doc([{**f, "id": "a"}, {**f, "id": "b"}]))
    assert "floor の面が 2 枚ある" in str(e.value)


def test_開口の実体は室に1つだけ():
    """**面にも実体を持たせると建具の員数が倍になる。** 面が持つのは id だけ。"""
    got = [i for i in built().items if i.kind == "建具"]
    assert sum(int(i.qty) for i in got) == 3        # 掃き出し窓・腰窓・小窓
