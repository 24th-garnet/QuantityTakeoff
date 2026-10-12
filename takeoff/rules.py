"""拾い方の設定。**品目コードはリポジトリに持たない。**

どの面にどの仕上げが来るかは案件ごとに違い、品目コードは会社ごとの単価表に紐づく。
単価をリポジトリに持たないのと同じ理由で、手元の TOML を指して使う（`.gitignore` 済み）。

**推定しない。** 「洗面脱衣だからクッションフロアだろう」とこちらが決めると、外れたときに
見積書のどこが間違っているのか分からなくなる。**部屋名のパターンと品目コードの対応は、
人が書く。**

読み込みは `tomllib`（Python 3.11 の標準ライブラリ）。外部依存を増やさない。
"""
from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from pathlib import Path

#: 開口の欠除の既定。公共建築数量積算基準は **1 か所 0.5 ㎡以下は欠除しない**。
#: 現場で加工できないものは 0.1 ㎡という運用もあるので、設定で変えられるようにする
DEFAULT_MIN_OPENING = Decimal("0.5")

#: 面の種類と、その数量の単位。**単位はここで決まる**（単価表の単位と合っている必要がある）
SURFACES = (("floor", "床", "㎡"), ("ceiling", "天井", "㎡"), ("wall", "壁", "㎡"),
            ("baseboard", "巾木", "m"), ("cornice", "回縁", "m"),
            ("strip", "撤去", "㎡"))


class RuleError(ValueError):
    """設定が読めない。**理由を全部ためてから投げる。**"""

    def __init__(self, reasons: list[str]) -> None:
        super().__init__("\n".join(reasons))
        self.reasons = reasons


@dataclass(frozen=True)
class Finish:
    """部屋名のパターンに当たる仕上げの組。"""

    #: 部屋名に**含まれていれば**当たる語の列
    rooms: tuple[str, ...]
    #: 面の種類 → 品目コード。
    #:
    #: **3 つの状態を分ける。** 値があれば拾う、**空文字なら「この部屋にその面は無い」と
    #: 人が判断した**、書いていなければ「まだ誰も見ていない」。空文字を許さないと、
    #: 巾木の無い部屋がいつまでも「品目コードが無い」と報告に出続けて、誰も直さなくなる
    #: （単価表の `対象外` と同じ考え方）。
    codes: dict[str, str] = field(default_factory=dict)

    def matches(self, name: str) -> bool:
        return any(p in name for p in self.rooms)


@dataclass(frozen=True)
class Rules:
    """拾い方の設定ひとそろい。"""

    #: 拠った基準の版。**後から根拠をたどれないと検算できない**
    standard: str
    #: 欠除しない開口の上限（㎡）
    min_opening: Decimal
    finishes: tuple[Finish, ...]
    #: 建具の種別 → 品目コード
    fittings: dict[str, str]
    #: 家具の識別子 → 品目コード
    furniture: dict[str, str]

    def finish_for(self, room_name: str) -> Finish | None:
        """部屋名に当たる仕上げ。**先に書いたものが勝つ。**

        正規表現にしない。パターンが読めなくなったとき、どの部屋がどれに当たるのかを
        人が目で追えなくなる。
        """
        for f in self.finishes:
            if f.matches(room_name):
                return f
        return None


def _dec(value: object, *, field_: str, reasons: list[str]) -> Decimal:
    try:
        return Decimal(str(value).strip())
    except (InvalidOperation, ArithmeticError):
        reasons.append(f"{field_}: 数として読めない ({value!r})")
        return Decimal(0)


def parse(data: dict, *, where: str = "設定") -> Rules:
    reasons: list[str] = []

    standard = str(data.get("standard") or "").strip()
    if not standard:
        reasons.append(f"{where}: standard が空。どの積算基準に拠ったかを書く")

    deduct = data.get("deduct") or {}
    if not isinstance(deduct, dict):
        reasons.append(f"{where}.deduct: 表ではない")
        deduct = {}
    min_opening = (_dec(deduct["min_opening_area"], field_=f"{where}.deduct.min_opening_area",
                        reasons=reasons)
                   if "min_opening_area" in deduct else DEFAULT_MIN_OPENING)
    if min_opening < 0:
        reasons.append(f"{where}.deduct.min_opening_area: 負にできない ({min_opening})")

    known = {k for k, _, _ in SURFACES}
    finishes: list[Finish] = []
    raw_finishes = data.get("finish") or []
    if not isinstance(raw_finishes, list):
        reasons.append(f"{where}.finish: [[finish]] の並びではない")
        raw_finishes = []
    for n, raw in enumerate(raw_finishes, start=1):
        at = f"{where}.finish[{n - 1}]"
        if not isinstance(raw, dict):
            reasons.append(f"{at}: 表ではない")
            continue
        rooms = raw.get("rooms")
        if not isinstance(rooms, list) or not rooms:
            reasons.append(f"{at}.rooms: 部屋名のパターンが空")
            continue
        codes = {}
        for key, value in raw.items():
            if key == "rooms":
                continue
            if key not in known:
                reasons.append(f"{at}: 知らない面 {key}。"
                               f"{' / '.join(sorted(known))} のどれか")
                continue
            codes[key] = str(value).strip()
        if not any(codes.values()):
            reasons.append(f"{at}: 品目コードが 1 つも無い。"
                           "すべて空文字なら、この [[finish]] は何も拾わない")
            continue
        finishes.append(Finish(tuple(str(r) for r in rooms), codes))

    if not finishes:
        reasons.append(f"{where}: [[finish]] が 1 つも無い。仕上げを当てられない")

    fittings = _codes(data.get("fittings"), f"{where}.fittings", reasons)
    furniture = _codes(data.get("furniture"), f"{where}.furniture", reasons)

    if reasons:
        raise RuleError(reasons)
    return Rules(standard, min_opening, tuple(finishes), fittings, furniture)


def _codes(raw: object, at: str, reasons: list[str]) -> dict[str, str]:
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        reasons.append(f"{at}: 表ではない")
        return {}
    return {str(k): str(v).strip() for k, v in raw.items()}


def load(path: Path) -> Rules:
    try:
        with path.open("rb") as fh:
            data = tomllib.load(fh)
    except FileNotFoundError:
        raise RuleError([f"設定が無い: {path}"]) from None
    except tomllib.TOMLDecodeError as e:
        raise RuleError([f"{path.name}: TOML として読めない ({e})"]) from None
    return parse(data, where=path.name)
