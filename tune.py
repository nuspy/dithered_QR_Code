"""Esplora il compromesso fra leggibilita' del codice e fedelta' dell'immagine.

Ogni parametro che rende il QR piu' robusto toglie qualcosa alla foto. Invece di
sceglierli a occhio, qui si genera una griglia di varianti e si misurano
entrambe le grandezze, cosi' il compromesso e' un dato e non un'impressione.

    python tune.py "testo" foto.jpg --grid margin=0,0.04,0.08,0.14
"""

from __future__ import annotations

import argparse
import itertools
from dataclasses import replace
from pathlib import Path

from dithered_qr import Settings, generate
from verify import check

NUMERIC = {"margin", "blend", "sacrifice", "center_pull", "contrast", "clahe", "sharpen", "gamma"}
INTEGER = {"scale", "core", "passes", "min_version", "border"}


def parse_grid(specs: list[str]) -> dict[str, list]:
    grid: dict[str, list] = {}
    for spec in specs:
        name, _, values = spec.partition("=")
        name = name.strip()
        if not values:
            raise SystemExit(f"griglia non valida: {spec!r} (atteso nome=v1,v2,...)")
        if name in INTEGER:
            grid[name] = [int(v) for v in values.split(",")]
        elif name in NUMERIC:
            grid[name] = [float(v) for v in values.split(",")]
        else:
            grid[name] = values.split(",")
    return grid


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("text")
    p.add_argument("image", type=Path)
    p.add_argument("--grid", nargs="+", required=True, metavar="NOME=V1,V2",
                   help="parametri da variare, es. margin=0,0.05,0.1 scale=9,13")
    p.add_argument("--out-dir", type=Path, help="salva un PNG per combinazione")
    args = p.parse_args(argv)

    grid = parse_grid(args.grid)
    names = list(grid)
    combos = list(itertools.product(*(grid[n] for n in names)))

    if args.out_dir:
        args.out_dir.mkdir(parents=True, exist_ok=True)

    print("{:<40} {:>12} {:>9} {:>9}".format("combinazione", "leggibilita'", "fedelta'", "corretti"))
    print("-" * 73)
    rows = []
    for combo in combos:
        cfg = replace(Settings(), **dict(zip(names, combo)))
        result = generate(args.text, args.image, cfg)
        report = check(result.image, args.text, result.modules)
        label = " ".join(f"{n}={v}" for n, v in zip(names, combo))
        print(f"{label:<40} {report.score:>11.0%} {result.fidelity:>9.3f} {result.corrected:>9}")
        rows.append((label, report.score, result.fidelity))
        if args.out_dir:
            safe = label.replace("=", "").replace(" ", "_").replace(".", "")
            result.image.save(args.out_dir / f"{safe}.png")

    perfect = [r for r in rows if r[1] >= 1.0]
    if perfect:
        best = max(perfect, key=lambda r: r[2])
        print(f"\nmiglior fedelta' fra le combinazioni pienamente leggibili: {best[0]} "
              f"(fedelta' {best[2]:.3f})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
