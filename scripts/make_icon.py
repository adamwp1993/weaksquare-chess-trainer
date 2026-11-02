"""Build the app icon, assets/icon/weaksquare.ico, from assets/icon/weaksquare.svg (NFR-8a).

    uv run python scripts/make_icon.py           # rebuild the .ico (commit it with the SVG)
    uv run python scripts/make_icon.py --check   # exit 1 if the committed .ico doesn't match the SVG

Renders the SVG with Playwright's Chromium (already a dev dependency) at every size Windows uses, and
packs the PNGs into one .ico with the standard library, so neither setup.py nor the app needs image
tools. Windows Vista and later read PNG entries at every size.
"""

from __future__ import annotations

import argparse
import struct
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SVG = ROOT / "assets" / "icon" / "weaksquare.svg"
ICO = ROOT / "assets" / "icon" / "weaksquare.ico"
SIZES = (16, 20, 24, 32, 40, 48, 64, 128, 256)


def render_pngs(svg: str) -> dict[int, bytes]:
    from playwright.sync_api import sync_playwright

    out: dict[int, bytes] = {}
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        try:
            for size in SIZES:
                page = browser.new_page(viewport={"width": size, "height": size}, device_scale_factor=1)
                html = (
                    "<html><body style='margin:0;background:transparent'>"
                    f"<img src='data:image/svg+xml;utf8,{_escape(svg)}' width='{size}' height='{size}' "
                    "style='display:block'></body></html>"
                )
                page.set_content(html)
                page.wait_for_load_state("load")
                out[size] = page.screenshot(omit_background=True, clip={"x": 0, "y": 0, "width": size, "height": size})
                page.close()
        finally:
            browser.close()
    return out


def _escape(svg: str) -> str:
    return svg.replace("%", "%25").replace("#", "%23").replace("'", "%27").replace("\n", " ")


def pack_ico(pngs: dict[int, bytes]) -> bytes:
    """ICONDIR, then one 16-byte ICONDIRENTRY per image, then the PNG data (sizes ascending)."""
    sizes = sorted(pngs)
    header = struct.pack("<HHH", 0, 1, len(sizes))
    offset = len(header) + 16 * len(sizes)
    entries, data = b"", b""
    for size in sizes:
        png = pngs[size]
        dim = 0 if size >= 256 else size  # 0 means 256 in the ICO format
        entries += struct.pack("<BBBBHHII", dim, dim, 0, 0, 1, 32, len(png), offset)
        offset += len(png)
        data += png
    return header + entries + data


def read_ico_sizes(ico: bytes) -> list[int]:
    """The image sizes listed in an .ico (used by the tests)."""
    reserved, kind, count = struct.unpack_from("<HHH", ico, 0)
    if reserved != 0 or kind != 1:
        raise ValueError("not an .ico file")
    sizes = []
    for i in range(count):
        width = struct.unpack_from("<B", ico, 6 + 16 * i)[0]
        sizes.append(width or 256)
    return sizes


def build() -> bytes:
    return pack_ico(render_pngs(SVG.read_text(encoding="utf-8")))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--check", action="store_true", help="compare with the committed .ico instead of writing it")
    args = ap.parse_args()
    ico = build()
    if args.check:
        if not ICO.is_file() or ICO.read_bytes() != ico:
            print(f"{ICO.relative_to(ROOT)} doesn't match the SVG. Run: uv run python scripts/make_icon.py")
            return 1
        print("icon is up to date")
        return 0
    ICO.write_bytes(ico)
    print(f"wrote {ICO.relative_to(ROOT)} ({len(ico):,} bytes, sizes {', '.join(map(str, SIZES))})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
