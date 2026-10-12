"""実測 JSON の読み込みと検証。

上流（CAD・スキャン）との**唯一の契約**。形式は [docs/measures.md](../docs/measures.md)。

**単位は長さが mm、面積が ㎡。** 設計図書の慣習に合わせ、変換は上流の責任にする。

**`basis` がこの形式の中心。** 同じ壁面積でも、実測の壁厚から出した値と仮定した壁厚から
出した値は信じてよい度合いが違う。CaptureVisualizer が既に `area_source` で面積の出どころを
自己申告しているので、その思想を形式全体に広げてある。

**値そのものは素のまま書き、仮定した値だけを `basis` で名指しする。** 欄が無ければ実測。
語彙は [basis](basis.py) が固定し、自由記述は `basis_note` に分ける。
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from pathlib import Path

from . import basis as basis_mod

SCHEMA = "mdr-measures-1"


class MeasureError(ValueError):
    """実測 JSON が読めない。**理由を全部ためてから投げる。**

    1 つ直すたびに次の 1 つが出るのでは、上流を直す側が何度も往復する。
    """

    def __init__(self, reasons: list[str]) -> None:
        super().__init__("\n".join(reasons))
        self.reasons = reasons


@dataclass(frozen=True)
class Opening:
    """開口 1 つ。

    **`sill`（床からの下端）が巾木を引くかどうかを決める。** 床まで届く建具は周長から
    引き、腰窓は引かない。`kind` は上流の語彙をそのまま運ぶ——拾い側は `sill` と寸法しか
    見ないので、CAD の 10 種とスキャンの 3 種が混在しても困らない。
    """

    id: str
    kind: str
    #: mm
    width: Decimal
    #: mm
    height: Decimal
    #: 床からの下端（mm）
    sill: Decimal

    @property
    def area(self) -> Decimal:
        """㎡。"""
        return self.width * self.height / Decimal(1_000_000)

    @property
    def to_floor(self) -> bool:
        """床まで届くか。巾木を引くかの判定。"""
        return self.sill == 0


@dataclass(frozen=True)
class Furniture:
    """家具 1 種。"""

    code: str
    label: str
    count: int


@dataclass(frozen=True)
class Room:
    """部屋 1 つ。**面積と長さは上流が解決済み。**"""

    id: str
    name: str
    #: ㎡
    floor_area: Decimal
    ceiling_area: Decimal
    #: 内法の周長（mm）
    perimeter: Decimal
    #: 壁高（mm）
    height: Decimal
    #: 開口を抜く前の壁の見付面積（㎡）
    wall_area: Decimal
    openings: tuple[Opening, ...] = ()
    furniture: tuple[Furniture, ...] = ()
    #: 量ごとの根拠。語彙は `basis.STRENGTH`。**欄が無ければ実測**
    basis: dict[str, str] = field(default_factory=dict)
    #: 根拠の言い換え（自由記述）
    basis_note: dict[str, str] = field(default_factory=dict)

    def basis_of(self, *keys: str) -> str:
        """その量を作るのに使った根拠のうち、**一番弱いもの**。"""
        return basis_mod.weakest(self.basis.get(k, basis_mod.MEASURED) for k in keys)


@dataclass(frozen=True)
class Measures:
    """1 件分の実測。"""

    source: str
    plan_id: str
    name: str
    rooms: tuple[Room, ...]
    #: シート全体の根拠。`partition` / `openings` / `holes` / `swing` など
    basis: dict[str, str] = field(default_factory=dict)
    basis_note: dict[str, str] = field(default_factory=dict)

    @property
    def split(self) -> bool:
        """部屋が分かれているか。

        **語彙を増やさない。**「部屋という概念が上流に無い」は `未計測` そのもの。
        `未分割` のような専用の語を足すと、根拠の軸が 2 本になって合成できなくなる。
        """
        return self.basis.get("partition", basis_mod.MEASURED) not in basis_mod.MISSING

    @property
    def assumptions(self) -> tuple[tuple[str, str, str], ...]:
        """仮定に頼っている点。(量, 根拠, 言い換え)。

        **部屋ごとの根拠も集める。** シート全体の申告だけでは、どの部屋の
        どの数量が仮定に乗っているのかが分からない。
        """
        out: list[tuple[str, str, str]] = []
        for key, value in self.basis.items():
            if basis_mod.weak(value):
                out.append((key, value, self.basis_note.get(key, "")))
        for room in self.rooms:
            where = room.name or room.id
            for key, value in room.basis.items():
                if basis_mod.weak(value):
                    out.append((f"{where} {key}", value,
                                room.basis_note.get(key, "")))
        return tuple(out)


def _dec(value: object, *, field_: str, reasons: list[str]) -> Decimal:
    """**float を文字列経由で畳む。** JSON は `parse_float=Decimal` で読むので
    通常は来ないが、ここは外から呼ばれる入口なので受けたものを必ず畳む。
    """
    if isinstance(value, Decimal):
        return value
    if value is None or isinstance(value, bool):
        reasons.append(f"{field_}: 数ではない ({value!r})")
        return Decimal(0)
    try:
        return Decimal(str(value).strip())
    except (InvalidOperation, ArithmeticError):
        reasons.append(f"{field_}: 数として読めない ({value!r})")
        return Decimal(0)


def _positive(value: object, *, field_: str, reasons: list[str],
              allow_zero: bool = True) -> Decimal:
    d = _dec(value, field_=field_, reasons=reasons)
    if d < 0 or (d == 0 and not allow_zero):
        reasons.append(f"{field_}: 負の値は置けない ({d})")
    return d


def parse(data: object, *, where: str = "実測") -> Measures:
    """読み込み済みの JSON から組む。"""
    reasons: list[str] = []
    if not isinstance(data, dict):
        raise MeasureError([f"{where}: 一番外が辞書ではない"])

    version = data.get("schema_version")
    if version != SCHEMA:
        raise MeasureError([f"{where}: 知らない版 {version!r}（{SCHEMA} が要る）"])

    raw_rooms = data.get("rooms")
    if not isinstance(raw_rooms, list) or not raw_rooms:
        raise MeasureError([f"{where}: rooms が空か配列ではない"])

    rooms: list[Room] = []
    for n, raw in enumerate(raw_rooms, start=1):
        at = f"{where} rooms[{n - 1}]"
        if not isinstance(raw, dict):
            reasons.append(f"{at}: 辞書ではない")
            continue
        rooms.append(_room(raw, at, reasons))

    if reasons:
        raise MeasureError(reasons)

    sheet_note = data.get("basis_note") or {}
    if not isinstance(sheet_note, dict):
        reasons.append(f"{where}.basis_note: 辞書ではない")
        sheet_note = {}
    sheet_basis = _basis(data, where, reasons)
    if reasons:
        raise MeasureError(reasons)

    return Measures(
        str(data.get("source") or "").strip(),
        str(data.get("plan_id") or "").strip(),
        str(data.get("name") or "").strip(),
        tuple(rooms), sheet_basis,
        {str(k): str(v) for k, v in sheet_note.items()},
    )


def _room(raw: dict, at: str, reasons: list[str]) -> Room:
    name = str(raw.get("name") or "").strip()
    rid = str(raw.get("id") or "").strip()
    if not rid:
        reasons.append(f"{at}: id が空。数量の出どころを辿れない")

    nums = {k: _positive(raw.get(k, 0), field_=f"{at}.{k}", reasons=reasons)
            for k in ("floor_area", "ceiling_area", "perimeter", "height", "wall_area")}
    if nums["height"] == 0:
        reasons.append(f"{at}.height が 0。壁の数量が出せない")

    openings: list[Opening] = []
    for m, o in enumerate(raw.get("openings") or (), start=1):
        oat = f"{at}.openings[{m - 1}]"
        if not isinstance(o, dict):
            reasons.append(f"{oat}: 辞書ではない")
            continue
        openings.append(Opening(
            str(o.get("id") or f"o{m}"), str(o.get("kind") or "").strip(),
            _positive(o.get("width", 0), field_=f"{oat}.width", reasons=reasons),
            _positive(o.get("height", 0), field_=f"{oat}.height", reasons=reasons),
            _positive(o.get("sill", 0), field_=f"{oat}.sill", reasons=reasons)))

    furniture: list[Furniture] = []
    for m, f in enumerate(raw.get("furniture") or (), start=1):
        fat = f"{at}.furniture[{m - 1}]"
        if not isinstance(f, dict):
            reasons.append(f"{fat}: 辞書ではない")
            continue
        code = str(f.get("code") or "").strip()
        if not code:
            reasons.append(f"{fat}: code が空")
            continue
        try:
            count = int(f.get("count", 1))
        except (TypeError, ValueError):
            reasons.append(f"{fat}.count が整数ではない ({f.get('count')!r})")
            continue
        if count < 1:
            reasons.append(f"{fat}.count は 1 以上 ({count})")
            continue
        furniture.append(Furniture(code, str(f.get("label") or code).strip(), count))

    b = _basis(raw, at, reasons)
    note = raw.get("basis_note") or {}
    if not isinstance(note, dict):
        reasons.append(f"{at}.basis_note: 辞書ではない")
        note = {}

    return Room(rid, name, nums["floor_area"], nums["ceiling_area"],
                nums["perimeter"], nums["height"], nums["wall_area"],
                tuple(openings), tuple(furniture), b,
                {str(k): str(v) for k, v in note.items()})


def _basis(raw: dict, at: str, reasons: list[str]) -> dict[str, str]:
    """根拠の語彙を検証する。**知らない語は断る。**

    表記ゆれを黙って通すと、その数量が何に基づくのか決まらない。
    """
    got = raw.get("basis") or {}
    if not isinstance(got, dict):
        reasons.append(f"{at}.basis: 辞書ではない")
        return {}
    out = {}
    for k, v in got.items():
        value = str(v).strip()
        if not basis_mod.known(value):
            reasons.append(f"{at}.basis.{k}: 知らない根拠 {value} は "
                           f"{' / '.join(basis_mod.STRENGTH)} のどれでもない")
            continue
        out[str(k)] = value
    return out


def load(path: Path) -> Measures:
    """**float を通さずに読む。**"""
    try:
        with path.open(encoding="utf-8") as fh:
            data = json.load(fh, parse_float=Decimal, parse_int=Decimal)
    except FileNotFoundError:
        raise MeasureError([f"実測 JSON が無い: {path}"]) from None
    except json.JSONDecodeError as e:
        raise MeasureError([f"{path.name}: JSON として読めない ({e})"]) from None
    return parse(data, where=path.name)
