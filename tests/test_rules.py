"""拾い方の設定。"""
from __future__ import annotations

from decimal import Decimal

import pytest

from takeoff import rules
from takeoff.rules import RuleError

from .conftest import EXAMPLES


def toml(body: str) -> dict:
    import tomllib
    return tomllib.loads(body)


BASE = '''
standard = "基準 X"
[[finish]]
rooms = ["居室"]
floor = "FL-1"
'''


def test_見本の設定が読める():
    r = rules.load(EXAMPLES / "rules.toml")
    assert r.standard
    assert r.min_opening == Decimal("0.5")
    assert len(r.finishes) == 2


def test_基準の版が空なら断る():
    # 後から根拠をたどれないと検算できない
    with pytest.raises(RuleError, match="standard"):
        rules.parse(toml('[[finish]]\nrooms=["居室"]\nfloor="FL-1"\n'))


def test_欠除の閾値の既定は_0_5():
    assert rules.parse(toml(BASE)).min_opening == rules.DEFAULT_MIN_OPENING


def test_欠除の閾値を変えられる():
    # 現場で加工できないものは 0.1 ㎡という運用がある
    r = rules.parse(toml(BASE + '\n[deduct]\nmin_opening_area = 0.1\n'))
    assert r.min_opening == Decimal("0.1")


def test_部屋名は部分一致で当たる():
    r = rules.parse(toml(BASE))
    assert r.finish_for("洋室 居室").codes["floor"] == "FL-1"
    assert r.finish_for("浴室") is None


def test_先に書いた仕上げが勝つ():
    r = rules.parse(toml('standard="X"\n'
                         '[[finish]]\nrooms=["室"]\nfloor="A"\n'
                         '[[finish]]\nrooms=["居室"]\nfloor="B"\n'))
    assert r.finish_for("居室").codes["floor"] == "A"


def test_知らない面は断る():
    with pytest.raises(RuleError, match="知らない面"):
        rules.parse(toml('standard="X"\n[[finish]]\nrooms=["a"]\nroof="R"\n'))


def test_部屋名が空なら断る():
    with pytest.raises(RuleError, match="パターンが空"):
        rules.parse(toml('standard="X"\n[[finish]]\nrooms=[]\nfloor="A"\n'))


def test_仕上げが_1_つも無ければ断る():
    with pytest.raises(RuleError, match="finish"):
        rules.parse(toml('standard="X"\n'))


def test_空文字だけの仕上げは断る():
    with pytest.raises(RuleError, match="1 つも無い"):
        rules.parse(toml('standard="X"\n[[finish]]\nrooms=["a"]\nfloor=""\n'))


def test_面の単位は_1_箇所で決まる():
    # 単価表の単位と合っている必要があるので、出どころを 1 つにする
    units = {k: u for k, _, u in rules.SURFACES}
    assert units["floor"] == "㎡" and units["baseboard"] == "m"
