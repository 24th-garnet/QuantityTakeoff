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
from .rules import SURFACES

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


#: 面として個体で受けられる種類。**人が 3D の上でつつけるものだけ。**
#: 巾木・回縁・撤去は面から導く量で、クリックできる面ではないので室ごとのまま。
SURFACE_KINDS = ("wall", "floor", "ceiling")


@dataclass(frozen=True)
class Surface:
    """面 1 つ。**壁 1 枚、床、天井。**

    室の合計（`wall_area`）だけでは 4 面に別々の壁紙が貼れない。面が
    **個体として id を持つ**ことが、面ごとに仕上げを選べることの全て。

    **壁は面積を持たない。** 長さと高さと、その面に属する開口の id を持つ。
    「1 か所いくつ以下を引かないか」は積算基準の規約（`deducted_wall` の
    `min_opening`）で、幾何を知っている上流の持ち物ではない。上流が先に
    引くと規約が幾何の側に漏れる。

    床と天井が `area` を持つのは、引くものが無く、面積が上流の実測そのものだから。
    """

    id: str
    kind: str
    #: 上流で選んだ品目コード。**空文字は「この面は拾わない」と人が判断した印**
    finish: str = ""
    #: 壁の長さ（mm）
    length: Decimal = Decimal(0)
    #: 壁の高さ（mm）
    height: Decimal = Decimal(0)
    #: 床・天井の面積（㎡）
    area: Decimal = Decimal(0)
    #: この面に属する開口の id。実体は `Room.openings` にある
    openings: tuple[str, ...] = ()
    #: この面の量の根拠
    basis: str = basis_mod.MEASURED

    @property
    def gross(self) -> Decimal:
        """開口を抜く前の見付面積（㎡）。"""
        if self.kind == "wall":
            return self.length * self.height / Decimal(1_000_000)
        return self.area


@dataclass(frozen=True)
class Furniture:
    """家具 1 種。

    `item` は**上流で選んだ品目**。3D の上でそのオブジェクトに品目を割り当てた
    なら、種別（`sofa`）から規則で引くのではなく、選んだものがそのまま来る。
    空なら `[furniture]` の規則で引く。
    """

    code: str
    label: str
    count: int
    #: 上流で選んだ品目コード。**空なら規則で引く**
    item: str = ""


@dataclass(frozen=True)
class Instance:
    """置いてあるもの 1 個。**種別で畳まない。**

    `Furniture` が `{"code": "chair", "count": 4}` と種別で数えるのに対し、
    こちらは 1 個ずつ識別子を持つ。椅子 4 脚のうち 1 脚だけ別の品目に
    できるのは、個体が並んでいるときだけ。

    `asset` は 3D の上で置き換えたカタログのアセット。**どのカタログの id かを
    `source` で名乗る**——ASIN とファイル名では識別空間が違い、bare な id は
    カタログ源が増えれば衝突する。

    `item` は品目コードを直に指したとき。`asset` → 対応表 → 品目、という順で
    引くのが本筋だが、対応表を持たない呼び手のために残してある。
    """

    id: str
    category: str
    label: str = ""
    item: str = ""
    #: `(source, id)`。空なら置換していない
    asset: tuple[str, str] | None = None
    #: 幅・高さ・奥行（mm）。**値段は決めない。**見積書に添えるだけ
    extent: tuple[Decimal, ...] = ()
    basis: str = basis_mod.MEASURED


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
    #: 置いてあるものの個体。**空なら `furniture` の種別集計で拾う**（従来どおり）。
    instances: tuple[Instance, ...] = ()
    #: 面の個体。**空なら室の合計で拾う**（従来どおり）。
    #:
    #: 壁 1 枚ずつに別の仕上げを当てられるのは、ここに面が並んでいるときだけ。
    #: 上流が面を分けて出せないなら、室の合計から 1 行で拾う。
    surfaces: tuple[Surface, ...] = ()
    #: 面の種類 → 上流で選んだ品目コード。**`[[finish]]` の規則より優先する。**
    #:
    #: 規則は「居室の壁は量産クロス」という**部屋の種別ごとの決め打ち**で、
    #: 3D の上で面を選んで壁紙を決めたときに、その選択を書き留める先が無い。
    #: ここに書いてあれば、部屋名が規則に当たるかどうかに関わらずそれを使う。
    #:
    #: 空文字の意味は `Finish.codes` と同じ——**「この面は拾わない」と人が
    #: 判断した印**で、書いていない（＝まだ選んでいない）とは別。
    finish: dict[str, str] = field(default_factory=dict)
    #: 量ごとの根拠。語彙は `basis.STRENGTH`。**欄が無ければ実測**
    basis: dict[str, str] = field(default_factory=dict)
    #: 根拠の言い換え（自由記述）
    basis_note: dict[str, str] = field(default_factory=dict)

    def basis_of(self, *keys: str) -> str:
        """その量を作るのに使った根拠のうち、**一番弱いもの**。"""
        return basis_mod.weakest(self.basis.get(k, basis_mod.MEASURED) for k in keys)

    def opening(self, oid: str) -> Opening | None:
        """id で開口を引く。**実体は室に 1 つだけ置く。**

        面にも開口の実体を持たせると、同じ建具が 2 箇所から数えられて員数が
        倍になる。面が持つのは id だけ。
        """
        return next((o for o in self.openings if o.id == oid), None)

    def faces(self, kind: str) -> tuple[Surface, ...]:
        """その種類の面。"""
        return tuple(f for f in self.surfaces if f.kind == kind)


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
        furniture.append(Furniture(code, str(f.get("label") or code).strip(),
                                   count, str(f.get("item") or "").strip()))

    instances = _instances(raw, at, reasons)
    surfaces = _surfaces(raw, at, reasons, {o.id for o in openings})
    finish = _finish(raw, at, reasons)
    b = _basis(raw, at, reasons)
    note = raw.get("basis_note") or {}
    if not isinstance(note, dict):
        reasons.append(f"{at}.basis_note: 辞書ではない")
        note = {}

    return Room(rid, name, nums["floor_area"], nums["ceiling_area"],
                nums["perimeter"], nums["height"], nums["wall_area"],
                tuple(openings), tuple(furniture), tuple(instances),
                tuple(surfaces), finish, b,
                {str(k): str(v) for k, v in note.items()})


def _instances(raw: dict, at: str, reasons: list[str]) -> list[Instance]:
    """置いてあるものを 1 個ずつ読む。**識別子が無ければ個体にならない。**"""
    got = raw.get("instances")
    if got is None:
        return []
    if not isinstance(got, list):
        reasons.append(f"{at}.instances: 並びではない")
        return []

    out: list[Instance] = []
    seen: set[str] = set()
    for m, o in enumerate(got):
        oat = f"{at}.instances[{m}]"
        if not isinstance(o, dict):
            reasons.append(f"{oat}: 辞書ではない")
            continue
        oid = str(o.get("id") or "").strip()
        if not oid:
            reasons.append(f"{oat}: id が空。品目を当てる先が決まらない")
            continue
        if oid in seen:
            reasons.append(f"{oat}: {oid} が重複している")
            continue
        seen.add(oid)

        asset = None
        raw_asset = o.get("asset")
        if raw_asset is not None:
            if not isinstance(raw_asset, dict):
                reasons.append(f"{oat}.asset: 辞書ではない")
            else:
                src = str(raw_asset.get("source") or "").strip()
                aid = str(raw_asset.get("id") or "").strip()
                if not src or not aid:
                    reasons.append(f"{oat}.asset: source と id の両方が要る。"
                                   f"どのカタログの id か決まらない")
                else:
                    asset = (src, aid)

        b = str(o.get("basis") or basis_mod.MEASURED).strip()
        if not basis_mod.known(b):
            reasons.append(f"{oat}.basis: 知らない根拠 ({b!r})")
            b = basis_mod.MEASURED

        extent = tuple(_positive(v, field_=f"{oat}.extent[{k}]", reasons=reasons)
                       for k, v in enumerate(o.get("extent") or ()))
        out.append(Instance(oid, str(o.get("category") or "").strip(),
                            str(o.get("label") or "").strip(),
                            str(o.get("item") or "").strip(),
                            asset, extent, b))
    return out


def _surfaces(raw: dict, at: str, reasons: list[str],
              known: set[str]) -> list[Surface]:
    """面の個体を読む。**知らない種類と、知らない開口は断る。**

    黙って読み飛ばすと、選んだ面が 1 つ消えたまま金額が出る。欠けた面は
    見積書からは見えない——**出せない状態を黙って出さない**ための検査。
    """
    got = raw.get("surfaces")
    if got is None:
        return []
    if not isinstance(got, list):
        reasons.append(f"{at}.surfaces: 並びではない")
        return []

    out: list[Surface] = []
    seen: set[str] = set()
    for m, f in enumerate(got):
        fat = f"{at}.surfaces[{m}]"
        if not isinstance(f, dict):
            reasons.append(f"{fat}: 辞書ではない")
            continue
        fid = str(f.get("id") or "").strip()
        if not fid:
            reasons.append(f"{fat}: id が空。仕上げを当てる先が決まらない")
            continue
        if fid in seen:
            reasons.append(f"{fat}: 面 {fid} が重複している")
            continue
        seen.add(fid)

        kind = str(f.get("kind") or "").strip()
        if kind not in SURFACE_KINDS:
            reasons.append(f"{fat}: 知らない面の種類 ({kind!r})。"
                           f"使えるのは {'・'.join(SURFACE_KINDS)}")
            continue

        oids: list[str] = []
        for oid in f.get("openings") or ():
            oid = str(oid).strip()
            if oid not in known:
                reasons.append(f"{fat}: 開口 {oid} が室の openings に無い")
                continue
            oids.append(oid)

        b = str(f.get("basis") or basis_mod.MEASURED).strip()
        if not basis_mod.known(b):
            reasons.append(f"{fat}.basis: 知らない根拠 ({b!r})")
            b = basis_mod.MEASURED

        out.append(Surface(
            fid, kind, str(f.get("finish") or "").strip(),
            _positive(f.get("length", 0), field_=f"{fat}.length", reasons=reasons),
            _positive(f.get("height", 0), field_=f"{fat}.height", reasons=reasons),
            _positive(f.get("area", 0), field_=f"{fat}.area", reasons=reasons),
            tuple(oids), b))

    _check_faces(out, at, reasons)
    return out


def _check_faces(faces: list[Surface], at: str, reasons: list[str]) -> None:
    """面として成り立っているか。**0 の面は数量が出ない。**"""
    for f in faces:
        if f.kind == "wall" and (f.length <= 0 or f.height <= 0):
            reasons.append(f"{at}: 壁 {f.id} の長さか高さが 0。数量が出ない")
        if f.kind in ("floor", "ceiling") and f.area <= 0:
            reasons.append(f"{at}: {f.kind} {f.id} の面積が 0。数量が出ない")
    for kind in ("floor", "ceiling"):
        n = sum(1 for f in faces if f.kind == kind)
        if n > 1:
            reasons.append(f"{at}: {kind} の面が {n} 枚ある。"
                           f"室に 1 枚だけ置く")


def _finish(raw: dict, at: str, reasons: list[str]) -> dict[str, str]:
    """上流で選んだ仕上げ。**知らない面の名前は断る。**

    `basis` と同じ扱い。表記ゆれを黙って通すと、`wal` と書いた選択が黙って
    無視されて規則の値が出る——**選んだのに反映されない**という、画面の上で
    一番気付きにくい壊れ方になる。
    """
    got = raw.get("finish") or {}
    if not isinstance(got, dict):
        reasons.append(f"{at}.finish: 辞書ではない")
        return {}
    known = {k for k, _, _ in SURFACES}
    out: dict[str, str] = {}
    for k, v in got.items():
        key = str(k).strip()
        if key not in known:
            reasons.append(f"{at}.finish: 知らない面 ({key!r})。"
                           f"使えるのは {'・'.join(sorted(known))}")
            continue
        out[key] = str(v or "").strip()
    return out


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
