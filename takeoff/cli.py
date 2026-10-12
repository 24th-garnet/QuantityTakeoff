"""コマンド。

```bash
uv run takeoff run measures.json --rules rules.toml       # 端末に表で
uv run takeoff run measures.json --rules rules.toml -o quantities.json
uv run takeoff check measures.json --rules rules.toml     # 当たり外れだけ
```
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import measures, report, rules, takeoff

DEFAULT_RULES = Path("rules.toml")


def _build(args: argparse.Namespace) -> takeoff.Result:
    return takeoff.build(measures.load(args.measures), rules.load(args.rules))


def _run(args: argparse.Namespace) -> int:
    result = _build(args)
    out = (report.quantities_json(result) if args.format == "json"
           else report.text(result) + "\n")
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(out, encoding="utf-8")
        print(f"書き出した: {args.out}", file=sys.stderr)
    else:
        sys.stdout.write(out)

    if args.strict and not result.complete:
        print(f"品目コードの当たらないものが {len(result.unassigned)} 件あるので失敗にする",
              file=sys.stderr)
        return 1
    return 0


def _check(args: argparse.Namespace) -> int:
    result = _build(args)
    print(f"{len(result.items)} 行を拾った。"
          f"当たらなかったもの {len(result.unassigned)} 件")
    for u in result.unassigned:
        print(f"  {report.pad(u.room, 14)}{report.pad(u.kind, 8)}{u.detail}")
    if result.assumptions:
        print("\n上流の仮定")
        for a in result.assumptions:
            print(f"  {a}")
    return 1 if result.unassigned else 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="takeoff",
                                description="実測から内装の数量を拾う")
    sub = p.add_subparsers(dest="cmd", required=True)

    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("measures", type=Path, help="実測 JSON")
    common.add_argument("--rules", type=Path, default=DEFAULT_RULES,
                        help="拾い方の設定 TOML（既定 rules.toml）")

    r = sub.add_parser("run", help="数量を拾う", parents=[common])
    r.add_argument("--format", choices=("text", "json"), default="text")
    r.add_argument("-o", "--out", type=Path)
    r.add_argument("--strict", action="store_true",
                   help="品目コードの当たらないものがあれば失敗にする")
    r.set_defaults(fn=_run)

    c = sub.add_parser("check", help="当たり外れだけを見る", parents=[common])
    c.set_defaults(fn=_check)

    args = p.parse_args(argv)
    try:
        return args.fn(args)
    except (measures.MeasureError, rules.RuleError) as e:
        print(str(e), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
