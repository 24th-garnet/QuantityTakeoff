"""実測 × 拾い方 → 数量。**純関数だけ。ファイルも時刻も見ない。**

幾何は計算しない。上流が解決した面積・周長・正味壁長を受け取り、
**積算基準の規約を当てる**ところだけを持つ。

## 規約（公共建築数量積算基準）

| | |
|---|---|
| 開口の欠除 | **1 か所 `min_opening` ㎡以下は差し引かない。** 既定 0.5 ㎡ |
| 巾木・回縁による壁の欠除 | **幅・高さを問わず無いものとする。** 壁面積から巾木の高さを引かない |
| 巾木の長さ | 周長から**床まで届く建具の幅だけ**を引く。腰窓は引かない |
| 回縁の長さ | 周長そのまま。**建具は天井まで届かない** |

基準は版で記述が変わるので、**拠った版を設定に書かせ、結果にも残す**。単価表に
`source` と `as_of` を持たせたのと同じ理由で、後から根拠をたどれないと検算できない。

## ロス率は見ない

切り代・張り代は**単価表の `loss` 列が持っている**。拾いで割増すと二重に掛かる。
ここが出すのは**設計図書の数量**であって、発注数量ではない。

## 単位

面積は ㎡、長さは m、員数は個。**実測 JSON は長さを mm で持つので、長さの数量は
1000 で割る。** どの面がどの単位かは `rules.SURFACES` が唯一の出どころ。
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from . import basis as basis_mod
from .measures import Measures, Room
from .rules import SURFACES, Finish, Rules

MM_PER_M = Decimal(1000)
ZERO = Decimal(0)

#: 数量の桁。**第 3 位を四捨五入する**（積算の慣習）。
#:
#: 切り上げない（過大な見積りは説明できない）。切り捨てない（材料が足りなくなる）。
#: `money.to_yen` が切り捨てなのは**金額**の規約で、数量とは別のもの。
PLACES = Decimal("0.01")


def round_qty(value: Decimal) -> Decimal:
    """数量を丸める。**丸めるのは拾い側。**

    見積側は単位を単価表から知るが、**拾い側は自分が面を拾ったか長さを拾ったか
    員数を拾ったかを知っている**。丸め方はその種類で決まるので、知っている側が丸める。
    """
    return value.quantize(PLACES)


@dataclass(frozen=True)
class Item:
    """拾った 1 行。"""

    code: str
    qty: Decimal
    unit: str
    #: どの部屋のどの面から来たか。**見積書の note にそのまま出る**
    note: str
    room: str
    kind: str
    #: この数量の根拠。**使った入力のうち一番弱いもの**
    basis: str = basis_mod.MEASURED

    @property
    def empty(self) -> bool:
        return self.qty <= 0


@dataclass(frozen=True)
class Unassigned:
    """仕上げの当たらなかった面、または品目コードの無い建具・家具。

    **落とさずに残す。** 黙って落とすと、拾えなかったのか拾って 0 だったのかが
    区別できず、見積りが静かに足りなくなる。
    """

    room: str
    kind: str
    detail: str


@dataclass(frozen=True)
class Result:
    """1 件分の拾い出し。"""

    plan_id: str
    name: str
    standard: str
    items: tuple[Item, ...]
    unassigned: tuple[Unassigned, ...]
    #: 上流が自己申告した仮定。(量, 根拠, 言い換え)
    assumptions: tuple[tuple[str, str, str], ...]
    #: 部屋が分かれているか
    split: bool
    #: 数量が 0 になって落とした面
    dropped: tuple[Unassigned, ...] = ()

    @property
    def complete(self) -> bool:
        return not self.unassigned

    @property
    def weak_items(self) -> tuple[Item, ...]:
        """実測でない根拠に乗った数量。"""
        return tuple(i for i in self.items if basis_mod.weak(i.basis))

    @property
    def overstated(self) -> tuple[Item, ...]:
        """必ず過大になる根拠に乗った数量。**1 行でもあれば見積りが過大。**"""
        return tuple(i for i in self.items if basis_mod.overstates(i.basis))


def deducted_wall(room: Room, min_opening: Decimal) -> Decimal:
    """開口を差し引いた壁の仕上げ面積（㎡）。

    **1 か所 `min_opening` ㎡以下は差し引かない。** 小さい開口まで引くと、拾いの手間に
    見合わないうえ、現場では結局その周りも張るため。
    """
    cut = sum((o.area for o in room.openings if o.area > min_opening), ZERO)
    return max(room.wall_area - cut, ZERO)


def baseboard_length(room: Room) -> Decimal:
    """巾木の長さ（m）。

    周長から**床まで届く建具の幅だけ**を引く。腰窓は巾木が回るので引かない。
    """
    cut = sum((o.width for o in room.openings if o.to_floor), ZERO)
    return max(room.perimeter - cut, ZERO) / MM_PER_M


def cornice_length(room: Room) -> Decimal:
    """回縁の長さ（m）。**建具は天井まで届かないので引かない。**"""
    return room.perimeter / MM_PER_M


def surface_qty(room: Room, kind: str, min_opening: Decimal) -> tuple[Decimal, str]:
    """面の種類ごとの数量と、その根拠の文。"""
    if kind == "floor":
        return room.floor_area, "床面積"
    if kind == "ceiling":
        return room.ceiling_area, "天井面積"
    if kind == "wall":
        wall = deducted_wall(room, min_opening)
        cut = [o for o in room.openings if o.area > min_opening]
        note = f"壁面積。開口 {len(cut)} 箇所を差し引き" if cut else "壁面積。差し引く開口なし"
        return wall, note
    if kind == "baseboard":
        n = sum(1 for o in room.openings if o.to_floor)
        return baseboard_length(room), f"内法周長 − 床まで届く建具 {n} 箇所"
    if kind == "cornice":
        return cornice_length(room), "内法周長"
    if kind == "strip":
        # 既存仕上げの撤去は、壁と天井に張ってあったものを剥がす
        return deducted_wall(room, min_opening) + room.ceiling_area, "壁・天井の既存仕上げ"
    raise ValueError(f"知らない面: {kind}")


def _unit(kind: str) -> str:
    for key, _, unit in SURFACES:
        if key == kind:
            return unit
    raise ValueError(f"知らない面: {kind}")


def _label(kind: str) -> str:
    for key, label, _ in SURFACES:
        if key == kind:
            return label
    return kind


#: 面の種類ごとに、根拠を引く量の鍵
NEEDS = {
    "floor": ("area",),
    "ceiling": ("area",),
    "wall": ("wall_area", "height", "openings"),
    "baseboard": ("perimeter", "openings"),
    "cornice": ("perimeter",),
    "strip": ("wall_area", "height", "area", "openings"),
}


def face_qty(room: Room, face, min_opening: Decimal) -> tuple[Decimal, str]:
    """面 1 枚の数量と、その根拠の文。**その面に属する開口だけを引く。**

    室の合計から引くのと違い、どの開口がどの壁に付いているかを面が知って
    いるので、**壁ごとに正しく引ける**。
    """
    if face.kind != "wall":
        return face.gross, f"{'床' if face.kind == 'floor' else '天井'}面積"
    holes = [o for o in (room.opening(i) for i in face.openings) if o]
    cut = [o for o in holes if o.area > min_opening]
    qty = max(face.gross - sum((o.area for o in cut), ZERO), ZERO)
    note = (f"{face.id} 壁面積。開口 {len(cut)} 箇所を差し引き" if cut
            else f"{face.id} 壁面積。差し引く開口なし")
    return qty, note


def face_items(room: Room, codes: dict[str, str], rules: Rules,
               dropped: list[Unassigned]) -> list[Item]:
    """面ごとに 1 行ずつ。**面が個体で来ているときだけ。**

    壁 4 面に別々の壁紙を貼れるのはここ。面が選んでいなければ、室ごとの
    選択（`codes`）に落ちる。
    """
    out: list[Item] = []
    where = room.name or room.id
    for face in room.surfaces:
        code = face.finish if face.finish else codes.get(face.kind, "")
        if not code:
            continue        # 書いていない or 空文字。どちらも行は作らない
        qty, note = face_qty(room, face, rules.min_opening)
        qty = round_qty(qty)
        if qty <= 0:
            dropped.append(Unassigned(where, _label(face.kind), "拾って 0 だった"))
            continue
        b = basis_mod.weakest((face.basis, room.basis_of(*NEEDS[face.kind])))
        out.append(Item(code, qty, _unit(face.kind),
                        f"{where} {note}".strip(), where, face.kind, b))
    return out


def room_items(room: Room, finish: Finish | None, rules: Rules,
               dropped: list[Unassigned]) -> list[Item]:
    """1 部屋ぶんの面の数量。**選んであれば規則より選択を使う。**

    面が個体で来ていれば面ごとに、来ていなければ室の合計から 1 行で拾う。
    巾木・回縁・撤去は**面から導く量**なので、どちらの場合も室ごとに 1 行。
    """
    out: list[Item] = []
    where = room.name or room.id
    codes = dict(finish.codes if finish else {})
    codes.update(room.finish)   # 上流で選んだものが勝つ

    faced = {f.kind for f in room.surfaces}
    if room.surfaces:
        out += face_items(room, codes, rules, dropped)

    for kind, label, _ in SURFACES:
        if kind in faced:
            continue        # 面ごとに拾い済み
        code = codes.get(kind, "")
        if not code:
            continue        # 書いていない or 空文字。どちらも行は作らない
        qty, note = surface_qty(room, kind, rules.min_opening)
        qty = round_qty(qty)
        if qty <= 0:
            # 「拾い忘れ」と「拾って 0 だった」を分ける
            dropped.append(Unassigned(where, label, "拾って 0 だった"))
            continue
        b = room.basis_of(*NEEDS[kind])
        out.append(Item(code, qty, _unit(kind),
                        f"{where} {note}".strip(), where, kind, b))
    return out


def build(measures: Measures, rules: Rules) -> Result:
    """実測と拾い方から数量を組む。

    **仕上げの当たらない部屋も、品目コードの無い建具・家具も、落とさずに数える。**
    """
    items: list[Item] = []
    unassigned: list[Unassigned] = []
    dropped: list[Unassigned] = []

    for room in measures.rooms:
        where = room.name or room.id
        finish = rules.finish_for(room.name)
        if finish is None and not room.finish:
            unassigned.append(Unassigned(where, "仕上げ",
                                         "部屋名に当たる [[finish]] が無い"))
        else:
            items += room_items(room, finish, rules, dropped)
            decided = set(finish.codes if finish else ()) | set(room.finish)
            for kind, _, _ in SURFACES:
                # 空文字は「この部屋にその面は無い」と人が判断した印。報告しない
                if kind not in decided:
                    unassigned.append(Unassigned(where, _label(kind), "品目コードが無い"))

        items += _fittings(room, rules, unassigned, where)
        items += _furniture(room, rules, unassigned, where)

    return Result(measures.plan_id, measures.name, rules.standard,
                  tuple(items), tuple(unassigned), measures.assumptions,
                  measures.split, tuple(dropped))


def _fittings(room: Room, rules: Rules, unassigned: list[Unassigned],
              where: str) -> list[Item]:
    """建具の員数。**同じ種別は 1 行にまとめる。**"""
    counts: dict[str, int] = {}
    for o in room.openings:
        counts[o.kind] = counts.get(o.kind, 0) + 1

    out: list[Item] = []
    for kind, n in counts.items():
        if kind not in rules.fittings:
            unassigned.append(Unassigned(where, "建具", f"{kind} に品目コードが無い"))
            continue
        code = rules.fittings[kind]
        if not code:
            continue        # 空文字は「拾うものが無い」と人が判断した印
        out.append(Item(code, Decimal(n), "箇所", f"{where} {kind}", where, "建具",
                        room.basis_of("openings")))
    return out


def _furniture(room: Room, rules: Rules, unassigned: list[Unassigned],
               where: str) -> list[Item]:
    out: list[Item] = []
    for f in room.furniture:
        if f.item:
            code = f.item   # 3D の上でそのオブジェクトに割り当てた品目
        elif f.code in rules.furniture:
            code = rules.furniture[f.code]
        else:
            unassigned.append(Unassigned(where, "家具", f"{f.code} に品目コードが無い"))
            continue
        if not code:
            continue        # 設備工事など、内装の数量に入れないもの
        out.append(Item(code, Decimal(f.count), "個", f"{where} {f.label}",
                        where, "家具", room.basis_of("furniture")))
    return out
