"""拾った数量を、人が読む形と InterierEstimation が食う形に落とす。

**端末の表は全角を 2 で数える。** 部屋名と面の名前が日本語なので、文字数で揃えると列が
必ずずれる。

数量リストでは**数量を文字列で出す。** 受け手（`InterierEstimation`）は `Decimal` で
読み直すので、JSON の数にすると float を経由した読み手が末尾を濁らせる。
"""
from __future__ import annotations

import json
import unicodedata
from decimal import Decimal

from .takeoff import Result

COLUMNS = (("部屋", 14, False), ("面", 8, False), ("品目", 12, False),
           ("数量", 12, True), ("単位", 5, False))
TOTAL_WIDTH = sum(n for _, n, _ in COLUMNS) + len(COLUMNS) - 1


def width(s: str) -> int:
    return sum(2 if unicodedata.east_asian_width(c) in "WF" else 1 for c in s)


def pad(s: str, n: int, *, right: bool = False) -> str:
    while width(s) > n:
        s = s[:-1]
    fill = " " * max(0, n - width(s))
    return fill + s if right else s + fill


def num(d: Decimal, places: int = 3) -> str:
    """**末尾の 0 を落とすが、指数にはしない。**"""
    s = format(d.quantize(Decimal(1).scaleb(-places)), "f")
    if "." in s:
        s = s.rstrip("0").rstrip(".")
    return s or "0"


def text(result: Result) -> str:
    out = [result.name or result.plan_id or "数量", f"基準 {result.standard}"]
    if not result.split:
        out.append("※ 上流が部屋を分けていない。撮影範囲全体を 1 室として拾っている")
    out.append("")
    out.append(" ".join(pad(c, n, right=r) for c, (_, n, r) in
                        zip([c for c, _, _ in COLUMNS], COLUMNS)))
    out.append("=" * TOTAL_WIDTH)

    for i in result.items:
        out.append(" ".join([pad(i.room, 14), pad(_kind(i.kind), 8), pad(i.code, 12),
                             pad(num(i.qty), 12, right=True), pad(i.unit, 5)]))
    out.append("-" * TOTAL_WIDTH)
    out.append(f"{len(result.items)} 行")

    if result.overstated:
        out.append("")
        out.append(f"必ず過大になる根拠に乗った数量が {len(result.overstated)} 行ある。"
                   "**この見積りは過大。**")
        for i in result.overstated:
            out.append(f"  {pad(i.code, 12)}{i.note}")

    weak = result.weak_items
    if weak:
        out.append("")
        tally: dict[str, int] = {}
        for i in weak:
            tally[i.basis] = tally.get(i.basis, 0) + 1
        out.append(f"仮定に頼った数量が {len(weak)} 行ある。")
        out.append("  " + " / ".join(f"{k} {v} 行" for k, v in tally.items()))

    if result.assumptions:
        out.append("")
        out.append("上流が仮定に頼っている点")
        keyw = max((width(k) for k, _, _ in result.assumptions), default=8) + 2
        for key, value, note in result.assumptions:
            out.append(f"  {pad(key, keyw)}{pad(value, 7)}{note}")

    if result.dropped:
        out.append("")
        out.append(f"拾って 0 だった面が {len(result.dropped)} 件ある。"
                   "（拾い忘れとは別）")
        for d in result.dropped:
            out.append(f"  {pad(d.room, 14)}{d.kind}")

    if result.unassigned:
        out.append("")
        out.append(f"品目コードの当たらなかったものが {len(result.unassigned)} 件ある。"
                   "その分だけ数量が足りない。")
        for u in result.unassigned[:12]:
            out.append(f"  {pad(u.room, 14)}{pad(u.kind, 8)}{u.detail}")
        if len(result.unassigned) > 12:
            out.append(f"  ほか {len(result.unassigned) - 12} 件")
    return "\n".join(out)


def _kind(kind: str) -> str:
    from .rules import SURFACES
    for key, label, _ in SURFACES:
        if key == kind:
            return label
    return kind


def quantities(result: Result, *, number: str = "", issued: str = "",
               client: str = "", subject: str = "") -> dict:
    """`InterierEstimation` が食う数量リスト。

    **同じ品目コードが 2 行あっても合算しない。** 「居室の壁」と「洗面脱衣の壁」は
    同じクロスでも別の行として見せたい。合算すると見積書から現場が消える——
    受け手が持っているのと同じ判断。
    """
    doc: dict = {
        "scan_id": result.plan_id,
        "name": result.name,
        "items": [{"code": i.code, "qty": num(i.qty), "note": _note(i)}
                  for i in result.items],
    }
    est = {k: v for k, v in (("number", number), ("issued", issued),
                             ("client", client), ("subject", subject)) if v}
    if est:
        doc["estimate"] = est
    return doc


def _note(item) -> str:
    """見積書の `└` 行に出る注記。**根拠が実測でなければ添える。**"""
    from . import basis
    if basis.weak(item.basis):
        return f"{item.note}（根拠 {item.basis}）"
    return item.note


def quantities_json(result: Result, **kw) -> str:
    return json.dumps(quantities(result, **kw), ensure_ascii=False, indent=2) + "\n"
