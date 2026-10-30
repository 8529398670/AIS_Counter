"""Build tests/matlab/build/ais_auto_headless.m from original-code/ais_auto.m.

The patch is mechanical and minimal so the analysis logic stays byte-identical
to the original: only the interactive calls (zoom/pause, ginput, clipboard) and
the _xy.txt destination change, plus a few lines that save intermediates for
the parity tests. Every replacement must match exactly once, so a change to the
original fails loudly here instead of silently producing a different harness.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "original-code" / "ais_auto.m"
OUT = ROOT / "tests" / "matlab" / "build" / "ais_auto_headless.m"

# Variables too big (or useless) to dump on every click.
SKIP = "pic|Ch|Chais|Chais_smooth|D|ais_Ch|ais_opened|ais_closed|L|L_bw|dist|ind_dist|dist_skel|ind_dist_skel|Ch1_pic|temp|d|ais_CC|ais_trace|SEo|SEc"
SAVE = "save(getappdata(0,'ais_dump_%s'),'-v7','-regexp','^(?!(" + SKIP + ")$).');"

PATCHES = [
    ("function [out] = ais_auto(cell,threshold,smooth,chosen)",
     "function [out] = ais_auto_headless(cell,threshold,smooth,chosen)"),
    ("    zoom ON;pause;zoom OFF;\n", ""),
    ("    [Xcell,Ycell]=ginput(1);", "    [Xcell,Ycell]=next_click();"),
    ("    ais_select=(L==I);",
     "    ais_select=(L==I); dbg_sel{loop+1}=ais_select; dbg_th(loop+1)=threshold; dbg_click(loop+1,:)=[Xcell Ycell]; dbg_I(loop+1)=I;"),
    ("Yais=YaisL{longline};\n", "Yais=YaisL{longline};\n" + SAVE % "trace" + "\n"),
    ("[~,~,S]=ginput(1);", "S='y';"),
    ("savexy = [cell '_xy.txt'];", "savexy = [getappdata(0,'ais_xy_prefix') '_xy.txt'];"),
    ("clipboard('copy',num2str(lngth,6));", "lngth_str=num2str(lngth,6); " + SAVE % "final"),
]

COUNTS = {"savexy = [cell '_xy.txt'];": 2}


def main() -> int:
    text = SRC.read_text()
    for old, new in PATCHES:
        n = text.count(old)
        want = COUNTS.get(old, 1)
        if n != want:
            print(f"patch anchor found {n}x (want {want}): {old!r}", file=sys.stderr)
            return 1
        text = text.replace(old, new)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(text)
    print(OUT)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
