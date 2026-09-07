"""Generate the deterministic demo fixture project for the test suite.

Outputs into mcp/tests/fixtures/demo:
    demo.kicad_pro, demo.kicad_sch, sub/power.kicad_sch, demo.kicad_pcb,
    fixture.kicad_sym, sym-lib-table

Schematic content (fixture spec):
    U1  8-pin MCU-like symbol: VDD/GND/CLK/D0/D1/RST + 2 no-connect pins
    C1  100nF cap, top pin dangling   -> the intentional ERC error
    C2  10uF cap wired to VCC + GND
    R1  10k resistor, left pin dangling -> intentional ERC warning
    VCC/GND power symbols, CLK label, D[1..0] bus with two bus entries,
    hierarchical sheet sub/power.kicad_sch with a +3V3 sheet pin
    2x no_connect marks on U1 pins 7/8

All schematic coordinates are multiples of KiCad's 1.27 mm default grid.
Power symbols are embedded verbatim from the installed KiCad 10 power
library; Device:R/C are embedded from Device.kicad_sym; the MCU symbol
ships in fixture.kicad_sym registered through sym-lib-table so ERC sees a
complete project.  All UUIDs are fixed constants.

The PCB is generated through the bundled pcbnew Python API (50x30 mm
outline, 2 layers, real footprints from installed libraries, tracks, one
via, one GND zone).

Run with KiCad's bundled Python (KiCad 10 required):
    "C:/Program Files/KiCad/10.0/bin/python.exe" scripts/generate_fixture.py

The repository ships the generated files, so the pytest suite itself has no
KiCad dependency.
"""

from __future__ import annotations

import re
from pathlib import Path

import pcbnew

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "mcp" / "tests" / "fixtures" / "demo"
SUB = FIXTURES / "sub"
SYMBOLS_DIR = Path(r"C:\Program Files\KiCad\10.0\share\kicad\symbols")
FP_BASE = Path(r"C:\Program Files\KiCad\10.0\share\kicad\footprints")

U = {
    "sch": "a1b2c3d4-0000-4000-8000-000000000001",
    "sub": "a1b2c3d4-0000-4000-8000-000000000002",
    "u1": "a1b2c3d4-0000-4000-8000-000000000010",
    "u1_p1": "a1b2c3d4-0000-4000-8000-000000000011",
    "u1_p2": "a1b2c3d4-0000-4000-8000-000000000012",
    "u1_p3": "a1b2c3d4-0000-4000-8000-000000000013",
    "u1_p4": "a1b2c3d4-0000-4000-8000-000000000014",
    "u1_p5": "a1b2c3d4-0000-4000-8000-000000000015",
    "u1_p6": "a1b2c3d4-0000-4000-8000-000000000016",
    "u1_p7": "a1b2c3d4-0000-4000-8000-000000000017",
    "u1_p8": "a1b2c3d4-0000-4000-8000-000000000018",
    "c1": "a1b2c3d4-0000-4000-8000-000000000021",
    "c2": "a1b2c3d4-0000-4000-8000-000000000022",
    "r1": "a1b2c3d4-0000-4000-8000-000000000023",
    "vcc_u1": "a1b2c3d4-0000-4000-8000-000000000031",
    "gnd_u1": "a1b2c3d4-0000-4000-8000-000000000032",
    "vcc_c2": "a1b2c3d4-0000-4000-8000-000000000033",
    "gnd_c2": "a1b2c3d4-0000-4000-8000-000000000034",
    "gnd_c1": "a1b2c3d4-0000-4000-8000-000000000035",
    "clk": "a1b2c3d4-0000-4000-8000-000000000041",
    "bus_d": "a1b2c3d4-0000-4000-8000-000000000042",
    "entry0": "a1b2c3d4-0000-4000-8000-000000000043",
    "entry1": "a1b2c3d4-0000-4000-8000-000000000044",
    "w_vdd": "a1b2c3d4-0000-4000-8000-000000000051",
    "w_gndu1": "a1b2c3d4-0000-4000-8000-000000000052",
    "w_clk": "a1b2c3d4-0000-4000-8000-000000000053",
    "w_d0": "a1b2c3d4-0000-4000-8000-000000000054",
    "w_d1": "a1b2c3d4-0000-4000-8000-000000000055",
    "w_rst": "a1b2c3d4-0000-4000-8000-000000000056",
    "w_rst2": "a1b2c3d4-0000-4000-8000-000000000057",
    "flag_vcc": "a1b2c3d4-0000-4000-8000-000000000071",
    "flag_gnd": "a1b2c3d4-0000-4000-8000-000000000072",
    "w_flag_vcc": "a1b2c3d4-0000-4000-8000-000000000073",
    "w_flag_gnd": "a1b2c3d4-0000-4000-8000-000000000074",
    "w_c2t": "a1b2c3d4-0000-4000-8000-000000000058",
    "w_c2b": "a1b2c3d4-0000-4000-8000-000000000058",
    "w_c1b": "a1b2c3d4-0000-4000-8000-000000000059",
    "w_r1": "a1b2c3d4-0000-4000-8000-00000000005a",
    "w_sheet": "a1b2c3d4-0000-4000-8000-00000000005b",
    "nc7": "a1b2c3d4-0000-4000-8000-000000000061",
    "nc8": "a1b2c3d4-0000-4000-8000-000000000062",
    "leaf": "a1b2c3d4-0000-4eaf-8000-000000000063",
    "sheet": "a1b2c3d4-0000-4000-8000-000000000064",
    "sheetpin": "a1b2c3d4-0000-4000-8000-000000000065",
    "sub_hlbl": "a1b2c3d4-0000-4000-8000-000000000066",
    "sub_vcc": "a1b2c3d4-0000-4000-8000-000000000067",
    "sub_gnd": "a1b2c3d4-0000-4000-8000-000000000068",
    "w_hlbl": "a1b2c3d4-0000-4000-8000-000000000069",
}


def extract_symbol(text: str, name: str) -> str:
    """Extract a full (symbol "name" ...) definition, balancing parens."""
    m = re.search(r'\(symbol "%s"\n' % re.escape(name), text)
    if not m:
        raise SystemExit("symbol %r not found" % name)
    start = m.start()
    depth = 0
    in_str = False
    esc = False
    i = start
    while i < len(text):
        c = text[i]
        if in_str:
            if esc:
                esc = False
            elif c == "\\":
                esc = True
            elif c == '"':
                in_str = False
        elif c == '"':
            in_str = True
        elif c == "(":
            depth += 1
        elif c == ")":
            depth -= 1
            if depth == 0:
                return text[start : i + 1]
        i += 1
    raise SystemExit("unbalanced symbol extraction")


def load_symbol(lib: Path, name: str, prefix: str = "") -> str:
    """Load a library symbol re-indented and renamed for lib_symbols.

    eeschema resolves a placed symbol lib_id against the prefixed name
    inside lib_symbols (e.g. "Device:C"), so the extracted definition
    must be renamed accordingly.
    """
    block = extract_symbol(lib.read_text(encoding="utf-8"), name)
    if prefix:
        block = block.replace('(symbol "%s"' % name, '(symbol "%s:%s"' % (prefix, name), 1)
    lines = block.split("\n")
    return "\n".join("\t" + line if line.strip() else line for line in lines)


def mcu_symbol() -> str:
    """8-pin MCU-like symbol; frame y+ is up in the KiCad lib convention."""
    pins = [
        ("power_in", "1", "VDD", 0, 10.16, 90),
        ("power_in", "2", "GND", 0, -10.16, 270),
        ("bidirectional", "3", "CLK", -10.16, 5.08, 180),
        ("bidirectional", "4", "D0", -10.16, 2.54, 180),
        ("bidirectional", "5", "D1", -10.16, 0, 180),
        ("input", "6", "RST", -10.16, -5.08, 180),
        ("no_connect", "7", "NC7", 10.16, 5.08, 0),
        ("no_connect", "8", "NC8", 10.16, -5.08, 0),
    ]
    body = []
    for etype, num, name, x, y, rot in pins:
        body.append(
            "\t\t\t(pin %s line\n"
            "\t\t\t\t(at %s %s %s)\n"
            "\t\t\t\t(length 2.54)\n"
            '\t\t\t\t(name "%s" (effects (font (size 1.016 1.016))))\n'
            '\t\t\t\t(number "%s" (effects (font (size 1.016 1.016))))\n'
            "\t\t\t)" % (etype, x, y, rot, name, num)
        )
    parts = [
        '\t\t(symbol "fixture:MCU_8PIN"',
        "\t\t\t(pin_names (offset 0.254))",
        "\t\t\t(exclude_from_sim no)",
        "\t\t\t(in_bom yes)",
        "\t\t\t(on_board yes)",
        '\t\t\t(property "Reference" "U"',
        "\t\t\t\t(at 0 12.7 0)",
        "\t\t\t\t(effects (font (size 1.27 1.27)))",
        "\t\t\t)",
        '\t\t\t(property "Value" "MCU_8PIN"',
        "\t\t\t\t(at 0 -12.7 0)",
        "\t\t\t\t(effects (font (size 1.27 1.27)))",
        "\t\t\t)",
        '\t\t\t(property "Footprint" ""',
        "\t\t\t\t(at 0 0 0)",
        "\t\t\t\t(effects (font (size 1.27 1.27)) (hide yes))",
        "\t\t\t)",
        '\t\t\t(property "Datasheet" ""',
        "\t\t\t\t(at 0 0 0)",
        "\t\t\t\t(effects (font (size 1.27 1.27)) (hide yes))",
        "\t\t\t)",
        '\t\t\t(property "Description" "8-pin fixture MCU" (at 0 0 0) (effects (font (size 1.27 1.27)) (hide yes)))',
        '\t\t\t(symbol "MCU_8PIN_0_1"',
        "\t\t\t\t(rectangle",
        "\t\t\t\t\t(start -7.62 10.16)",
        "\t\t\t\t\t(end 7.62 -10.16)",
        "\t\t\t\t\t(stroke (width 0.254) (type default))",
        "\t\t\t\t\t(fill (type background))",
        "\t\t\t\t)",
        "\t\t\t)",
        '\t\t\t(symbol "MCU_8PIN_1_1"',
    ]
    return "\n".join(parts) + "\n" + "\n".join(body) + "\n\t\t\t)\n\t\t)\n"


def sym_instance(lib_id: str, ref: str, value: str, uuid_: str, x: float, y: float, rot: int = 0,
                 pins: dict | None = None, footprint: str = "") -> str:
    """A placed symbol instance.  pins maps pin number -> uuid."""
    out = [
        "\t(symbol",
        '\t\t(lib_id "%s")' % lib_id,
        "\t\t(at %s %s %s)" % (x, y, rot),
        "\t\t(unit 1)",
        "\t\t(exclude_from_sim no)",
        "\t\t(in_bom yes)",
        "\t\t(on_board yes)",
        "\t\t(dnp no)",
        '\t\t(uuid "%s")' % uuid_,
        '\t\t(property "Reference" "%s"' % ref,
        "\t\t\t(at %s %s 0)" % (x, y - 2.54),
        "\t\t\t(effects (font (size 1.27 1.27)))",
        "\t\t)",
        '\t\t(property "Value" "%s"' % value,
        "\t\t\t(at %s %s 0)" % (x, y + 2.54),
        "\t\t\t(effects (font (size 1.27 1.27)))",
        "\t\t)",
    ]
    if footprint:
        out += [
            '\t\t(property "Footprint" "%s"' % footprint,
            "\t\t\t(at 0 0 0)",
            "\t\t\t(effects (font (size 1.27 1.27)) (hide yes))",
            "\t\t)",
        ]
    out += [
        '\t\t(property "Datasheet" ""',
        "\t\t\t(at 0 0 0)",
        "\t\t\t(effects (font (size 1.27 1.27)) (hide yes))",
        "\t\t)",
        '\t\t(property "Description" "" (at 0 0 0) (effects (font (size 1.27 1.27)) (hide yes)))',
    ]
    for num, puuid in (pins or {}).items():
        out += ['\t\t(pin "%s"' % num, '\t\t\t(uuid "%s")' % puuid, "\t\t)"]
    out += [
        "\t\t(instances",
        '\t\t\t(project "demo"',
        '\t\t\t\t(path "/%s"' % U["sch"],
        '\t\t\t\t\t(reference "%s")' % ref,
        "\t\t\t\t\t(unit 1)",
        "\t\t\t\t)",
        "\t\t)",
        "			)",
        "\t)",
    ]
    return "\n".join(out) + "\n"


def power_instance(uuid_: str, value: str, x: float, y: float, ref: str) -> str:
    """A placed power symbol.  The pin sits at the symbol origin."""
    return "\n".join([
        "\t(symbol",
        '\t\t(lib_id "power:%s")' % value,
        "\t\t(at %s %s 0)" % (x, y),
        "\t\t(unit 1)",
        "\t\t(exclude_from_sim no)",
        "\t\t(in_bom yes)",
        "\t\t(on_board yes)",
        "\t\t(dnp no)",
        '\t\t(uuid "%s")' % uuid_,
        '\t\t(property "Reference" "%s"' % ref,
        "\t\t\t(at %s %s 0)" % (x, y - 1.016),
        "\t\t\t(effects (font (size 0.762 0.762)) (hide yes))",
        "\t\t)",
        '\t\t(property "Value" "%s"' % value,
        "\t\t\t(at %s %s 0)" % (x, y + 2.794),
        "\t\t\t(effects (font (size 0.762 0.762)))",
        "\t\t)",
        '\t\t(property "Footprint" "" (at 0 0 0) (effects (font (size 1.27 1.27)) (hide yes)))',
        '\t\t(property "Datasheet" "" (at 0 0 0) (effects (font (size 1.27 1.27)) (hide yes)))',
        '\t\t(property "Description" "" (at 0 0 0) (effects (font (size 1.27 1.27)) (hide yes)))',
        '\t\t(pin "1"',
        '\t\t\t(uuid "%s")' % uuid_,
        "\t\t)",
        "\t\t(instances",
        '\t\t\t(project "demo"',
        '\t\t\t\t(path "/%s"' % U["sch"],
        '\t\t\t\t\t(reference "%s")' % ref,
        "\t\t\t\t\t(unit 1)",
        "\t\t\t\t)",
        "\t\t)",
        "			)",
        "\t)",
    ]) + "\n"


def wire(points: str, uuid_: str) -> str:
    return "\n".join([
        "\t(wire",
        "\t\t(pts %s)" % points,
        "\t\t(stroke (width 0) (type default))",
        '\t\t(uuid "%s")' % uuid_,
        "\t)",
    ]) + "\n"


def label(kind: str, text: str, x: float, y: float, uuid_: str) -> str:
    return "\n".join([
        '\t(%s "%s"' % (kind, text),
        "\t\t(at %s %s 0)" % (x, y),
        "\t\t(effects (font (size 1.27 1.27)) (justify left bottom))",
        '\t\t(uuid "%s")' % uuid_,
        "\t)",
    ]) + "\n"


def no_connect(x: float, y: float, uuid_: str) -> str:
    return "\n".join([
        "\t(no_connect",
        "\t\t(at %s %s)" % (x, y),
        '\t\t(uuid "%s")' % uuid_,
        "\t)",
    ]) + "\n"


def build_main_schematic() -> str:
    """Root sheet, grid-aligned per the layout plan in the module docstring."""
    lib = "\n".join([
        "\t(lib_symbols",
        load_symbol(SYMBOLS_DIR / "Device.kicad_sym", "R", "Device"),
        load_symbol(SYMBOLS_DIR / "Device.kicad_sym", "C", "Device"),
        load_symbol(SYMBOLS_DIR / "power.kicad_sym", "VCC", "power"),
        load_symbol(SYMBOLS_DIR / "power.kicad_sym", "GND", "power"),
        mcu_symbol(),
        "\t)",
    ])

    # Placed-symbol coordinates (ERC-calibrated transform: local=(px,-py),
    # then place-rotate (x,y)->(y,-x) for rot 90; pin "at" drives position,
    # pin rot only affects the drawn line).  All wire endpoints coincide with
    # pin connection points, which is what creates junctions in eeschema.
    #   U1 (101.6, 88.9) rot 0:
    #     VDD (101.6, 78.74) -> VCC symbol there via stub up to (101.6, 76.2)
    #     GND (101.6, 99.06) -> stub down to (101.6, 101.6), GND symbol
    #     CLK (91.44, 83.82) -> label CLK at (87.63, 83.82)
    #     D0  (91.44, 86.36) -> bus entry at (88.9, 86.36)
    #     D1  (91.44, 88.9)  -> bus entry at (88.9, 88.9)
    #     RST (91.44, 93.98) -> 3-segment wire to R1 pin2 (67.31, 97.79)
    #     NC7 (111.76, 83.82) / NC8 (111.76, 93.98): no_connect marks
    #   C1 (63.5, 90.17) rot 0: pin1 (63.5, 86.36) DANGLING (ERC error),
    #     pin2 (63.5, 93.98) -> wire down to GND at (63.5, 96.52)
    #   C2 (127, 90.17) rot 0: pin1 (127, 86.36) = VCC symbol,
    #     pin2 (127, 93.98) -> wire down to GND at (127, 96.52)
    #   R1 (63.5, 97.79) rot 90: pin1 (59.69, 97.79) DANGLING (ERC warning),
    #     pin2 (67.31, 97.79) -> RST wire
    body = [
        sym_instance(
            "fixture:MCU_8PIN", "U1", "MCU_8PIN", U["u1"], 101.6, 88.9,
            pins={str(n): U["u1_p%d" % n] for n in range(1, 9)},
            footprint="Package_SO:SOIC-8_3.9x4.9mm_P1.27mm",
        ),
        wire("(xy 101.6 78.74) (xy 101.6 76.2)", U["w_vdd"]),
        power_instance(U["vcc_u1"], "VCC", 101.6, 76.2, "#PWR01"),
        wire("(xy 101.6 99.06) (xy 101.6 101.6)", U["w_gndu1"]),
        power_instance(U["gnd_u1"], "GND", 101.6, 101.6, "#PWR02"),
        wire("(xy 91.44 83.82) (xy 87.63 83.82)", U["w_clk"]),
        label("label", "CLK", 87.63, 83.82, U["clk"]),
        wire("(xy 91.44 86.36) (xy 88.9 86.36)", U["w_d0"]),
        wire("(xy 91.44 88.9) (xy 88.9 88.9)", U["w_d1"]),
        # RST: U1 pin down and left to R1 pin2
        wire("(xy 91.44 93.98) (xy 88.9 93.98)", U["w_rst"]),
        wire("(xy 88.9 93.98) (xy 88.9 97.79)", U["w_rst2"]),
        wire("(xy 88.9 97.79) (xy 67.31 97.79)", U["w_r1"]),
        no_connect(111.76, 83.82, U["nc7"]),
        no_connect(111.76, 93.98, U["nc8"]),
        sym_instance("Device:C", "C1", "100nF", U["c1"], 63.5, 90.17,
                     pins={"1": U["c1"][:-2] + "0a", "2": U["c1"][:-2] + "0b"}),
        wire("(xy 63.5 93.98) (xy 63.5 96.52)", U["w_c1b"]),
        power_instance(U["gnd_c1"], "GND", 63.5, 96.52, "#PWR03"),
        sym_instance("Device:C", "C2", "10uF", U["c2"], 127, 90.17,
                     pins={"1": U["c2"][:-2] + "1a", "2": U["c2"][:-2] + "1b"}),
        power_instance(U["vcc_c2"], "VCC", 127, 86.36, "#PWR04"),
        wire("(xy 127 93.98) (xy 127 96.52)", U["w_c2b"]),
        power_instance(U["gnd_c2"], "GND", 127, 96.52, "#PWR05"),
        sym_instance("Device:R", "R1", "10k", U["r1"], 63.5, 97.79, rot=90,
                     pins={"1": U["r1"][:-2] + "2a", "2": U["r1"][:-2] + "2b"}),
        "\n".join([
            "\t(bus",
            "\t\t(pts (xy 86.36 86.36) (xy 86.36 91.44))",
            "\t\t(stroke (width 0) (type default))",
            '\t\t(uuid "%s")' % U["bus_d"],
            "\t)",
        ]) + "\n",
        "\n".join([
            "\t(bus_entry",
            "		(at 86.36 88.9)",
            "		(size 2.54 -2.54)",
            "\t\t(stroke (width 0) (type default))",
            '\t\t(uuid "%s")' % U["entry0"],
            "\t)",
        ]) + "\n",
        "\n".join([
            "\t(bus_entry",
            "		(at 86.36 91.44)",
            "		(size 2.54 -2.54)",
            "\t\t(stroke (width 0) (type default))",
            '\t\t(uuid "%s")' % U["entry1"],
            "\t)",
        ]) + "\n",
        label("label", "D[1..0]", 86.36, 88.9, U["bus_d"]),
        # PWR_FLAGs drive the VCC and GND power pins (KiCad standard practice)
        "\n".join([
            "\t(symbol",
            '\t\t(lib_id "power:PWR_FLAG")',
            "\t\t(at 106.68 76.2 0)",
            "\t\t(unit 1)",
            "\t\t(exclude_from_sim no)",
            "\t\t(in_bom yes)",
            "\t\t(on_board yes)",
            "\t\t(dnp no)",
            '\t\t(uuid "%s")' % U["flag_vcc"],
            '\t\t(property "Reference" "#FLG01"',
            "\t\t\t(at 105.664 74.93 0)",
            "\t\t\t(effects (font (size 0.762 0.762)) (hide yes))",
            "\t\t)",
            '\t\t(property "Value" "PWR_FLAG"',
            "\t\t\t(at 106.68 79.248 0)",
            "\t\t\t(effects (font (size 0.762 0.762)))",
            "\t\t)",
            '\t\t(property "Footprint" "" (at 0 0 0) (effects (font (size 1.27 1.27)) (hide yes)))',
            '\t\t(property "Datasheet" "~" (at 0 0 0) (effects (font (size 1.27 1.27)) (hide yes)))',
            '\t\t(property "Description" "Special symbol for letting ERC know the rail is driven" (at 0 0 0) (effects (font (size 1.27 1.27)) (hide yes)))',
            '\t\t(pin "1"',
            '\t\t\t(uuid "%s")' % (U["flag_vcc"][:-1] + "e"),
            "\t\t)",
            "\t\t(instances",
            '\t\t\t(project "demo"',
            '\t\t\t\t(path "/%s"' % U["sch"],
            '\t\t\t\t\t(reference "#FLG01")',
            "\t\t\t\t\t(unit 1)",
            "\t\t\t\t)",
            "\t\t\t)",
            "\t\t)",
            "\t)",
        ]) + "\n",
        # PWR_FLAG joins the VCC stub: wire from (101.6, 76.2) to (106.68, 76.2)
        wire("(xy 101.6 76.2) (xy 106.68 76.2)", U["w_flag_vcc"]),
        "\n".join([
            "\t(symbol",
            '\t\t(lib_id "power:PWR_FLAG")',
            "\t\t(at 106.68 101.6 0)",
            "\t\t(unit 1)",
            "\t\t(exclude_from_sim no)",
            "\t\t(in_bom yes)",
            "\t\t(on_board yes)",
            "\t\t(dnp no)",
            '\t\t(uuid "%s")' % U["flag_gnd"],
            '\t\t(property "Reference" "#FLG02"',
            "\t\t\t(at 105.664 100.33 0)",
            "\t\t\t(effects (font (size 0.762 0.762)) (hide yes))",
            "\t\t)",
            '\t\t(property "Value" "PWR_FLAG"',
            "\t\t\t(at 106.68 104.648 0)",
            "\t\t\t(effects (font (size 0.762 0.762)))",
            "\t\t)",
            '\t\t(property "Footprint" "" (at 0 0 0) (effects (font (size 1.27 1.27)) (hide yes)))',
            '\t\t(property "Datasheet" "~" (at 0 0 0) (effects (font (size 1.27 1.27)) (hide yes)))',
            '\t\t(property "Description" "Special symbol for letting ERC know the rail is driven" (at 0 0 0) (effects (font (size 1.27 1.27)) (hide yes)))',
            '\t\t(pin "1"',
            '\t\t\t(uuid "%s")' % (U["flag_gnd"][:-1] + "e"),
            "\t\t)",
            "\t\t(instances",
            '\t\t\t(project "demo"',
            '\t\t\t\t(path "/%s"' % U["sch"],
            '\t\t\t\t\t(reference "#FLG02")',
            "\t\t\t\t\t(unit 1)",
            "\t\t\t\t)",
            "\t\t\t)",
            "\t\t)",
            "\t)",
        ]) + "\n",
        # PWR_FLAG joins the GND stub: wire from (101.6, 101.6) to (106.68, 101.6)
        wire("(xy 101.6 101.6) (xy 106.68 101.6)", U["w_flag_gnd"]),
        # Hierarchical sheet with one +3V3 pin on its left edge
        "\n".join([
            "\t(sheet",
            "\t\t(at 127 114.3)",
            "\t\t(size 25.4 12.7)",
            "\t\t(exclude_from_sim no)",
            "\t\t(in_bom yes)",
            "\t\t(on_board yes)",
            "\t\t(dnp no)",
            "\t\t(stroke (width 0) (type solid))",
            "\t\t(fill (color 0 0 0 0.0000))",
            '\t\t(uuid "%s")' % U["sheet"],
            '\t\t(property "Sheetname" "power"',
            "\t\t\t(at 127 113.5375 0)",
            "\t\t\t(effects (font (size 1.524 1.524)) (justify left bottom))",
            "\t\t)",
            '\t\t(property "Sheetfile" "sub/power.kicad_sch"',
            "\t\t\t(at 127 127.1625 0)",
            "\t\t\t(effects (font (size 1.524 1.524)) (justify left top))",
            "\t\t)",
            '\t\t(pin "+3V3" input',
            "\t\t\t(at 127 120.65 180)",
            "\t\t\t(effects (font (size 1.27 1.27)) (justify right))",
            '\t\t\t(uuid "%s")' % U["sheetpin"],
            "\t\t)",
            "\t\t(instances",
            '\t\t\t(project "demo"',
            '\t\t\t\t(path "/%s"' % U["sch"],
            '\t\t\t\t\t(page "2")',
            "\t\t\t\t)",
            "\t\t\t)",
            "\t\t)",
            "\t)",
        ]) + "\n",
        # Wire from the sheet pin out to a short open stub on-grid (the
        # hierarchical +3V3 net stays anchored without shorting to VCC/GND).
    ]

    return "\n".join([
        "(kicad_sch",
        "\t(version 20250114)",
        '\t(generator "eeschema")',
        '\t(generator_version "9.0")',
        '\t(uuid "%s")' % U["sch"],
        '\t(paper "A4")',
        "\t(title_block",
        '\t\t(title "Codex KiCad demo fixture")',
        '\t\t(date "2026-09-07")',
        '\t\t(rev "A1")',
        '\t\t(company "Codex KiCad")',
        "\t)",
        lib,
        "".join(body),
        "\t(sheet_instances",
        '\t\t(path "/" (page "1"))',
        "\t)",
        "\t(embedded_fonts no)",
        ")",
    ]) + "\n"


def build_sub_schematic() -> str:
    """Leaf sheet: +3V3 hierarchical label plus a local VCC/GND pair."""
    lib = "\n".join([
        "\t(lib_symbols",
        load_symbol(SYMBOLS_DIR / "power.kicad_sym", "VCC", "power"),
        load_symbol(SYMBOLS_DIR / "power.kicad_sym", "GND", "power"),
        "\t)",
    ])
    body = [
        label("hierarchical_label", "+3V3", 88.9, 50.8, U["sub_hlbl"]),
        power_instance(U["sub_vcc"], "VCC", 96.52, 50.8, "#PWR06"),
        wire("(xy 88.9 50.8) (xy 96.52 50.8)", U["w_hlbl"]),
    ]
    return "\n".join([
        "(kicad_sch",
        "\t(version 20250114)",
        '\t(generator "eeschema")',
        '\t(generator_version "9.0")',
        '\t(uuid "%s")' % U["sub"],
        '\t(paper "A4")',
        "\t(title_block (title \"power leaf\") (date \"2026-09-07\") (rev \"A1\"))",
        lib,
        "".join(body),
        "\t(sheet_instances",
        '\t\t(path "/%s" (page "1"))' % U["sheet"],
        "\t)",
        "\t(embedded_fonts no)",
        ")",
    ]) + "\n"


def build_pcb() -> None:
    """Generate demo.kicad_pcb through pcbnew: 50x30 mm, 2 copper layers."""
    board = pcbnew.NewBoard(str(FIXTURES / "demo.kicad_pcb"))
    board.SetCopperLayerCount(2)

    def vi(x: float, y: float):
        return pcbnew.VECTOR2I(int(pcbnew.FromMM(x)), int(pcbnew.FromMM(y)))

    # Board outline 50 x 30 mm as four Edge.Cuts lines
    corners = [(0, 0), (50, 0), (50, 30), (0, 30)]
    for a, b in zip(corners, corners[1:] + corners[:1]):
        seg = pcbnew.PCB_SHAPE(board)
        seg.SetShape(pcbnew.SHAPE_T_SEGMENT)
        seg.SetStart(vi(*a))
        seg.SetEnd(vi(*b))
        seg.SetLayer(pcbnew.Edge_Cuts)
        board.Add(seg)

    # Nets
    nets = {}
    for name in ("GND", "VCC", "CLK", "D0", "D1", "RST"):
        net = pcbnew.NETINFO_ITEM(board, name)
        board.Add(net)
        nets[name] = net

    def net_code(name: str) -> int:
        return nets[name].GetNetCode()

    # Pad map: (ref, pad number) -> net name.  SOIC-8 pad order matches the
    # symbol: 1=VDD, 2=GND, 3=CLK, 4=D0, 5=D1, 6=RST, 7/8=NC.
    # C1 pad 1 and R1 pad 1 are left unconnected on purpose (they mirror the
    # dangling schematic pins so parity stays consistent).
    pad_nets = {
        ("U1", "1"): "VCC",
        ("U1", "2"): "GND",
        ("U1", "3"): "CLK",
        ("U1", "4"): "D0",
        ("U1", "5"): "D1",
        ("U1", "6"): "RST",
        ("C1", "2"): "GND",
        ("C2", "1"): "VCC",
        ("C2", "2"): "GND",
        ("R1", "2"): "RST",
    }

    lib_names = {
        "Package_SO:SOIC-8_3.9x4.9mm_P1.27mm": ("Package_SO.pretty", "SOIC-8_3.9x4.9mm_P1.27mm"),
        "Capacitor_SMD:C_0805_2012Metric": ("Capacitor_SMD.pretty", "C_0805_2012Metric"),
        "Resistor_SMD:R_0805_2012Metric": ("Resistor_SMD.pretty", "R_0805_2012Metric"),
    }
    footprint_specs = [
        ("Package_SO:SOIC-8_3.9x4.9mm_P1.27mm", "U1", "MCU_8PIN", 25, 15, 0),
        ("Capacitor_SMD:C_0805_2012Metric", "C1", "100nF", 8, 22, 0),
        ("Capacitor_SMD:C_0805_2012Metric", "C2", "10uF", 40, 8, 0),
        ("Resistor_SMD:R_0805_2012Metric", "R1", "10k", 42, 22, 90),
    ]
    for lib_id, ref, value, x, y, rot in footprint_specs:
        pretty, name = lib_names[lib_id]
        fp = pcbnew.FootprintLoad(str(FP_BASE / pretty), name)
        if fp is None:
            raise SystemExit("footprint %s not found" % name)
        fp.SetReference(ref)
        fp.SetValue(value)
        fp.SetPosition(vi(x, y))
        fp.SetOrientationDegrees(rot)
        for pad in fp.Pads():
            net_name = pad_nets.get((ref, pad.GetPadName()), "")
            if net_name:
                pad.SetNet(nets[net_name])
            else:
                pad.SetNet(None)
        board.Add(fp)

    def add_track(name: str, x1: float, y1: float, x2: float, y2: float,
                  width: float = 0.25, layer=pcbnew.F_Cu) -> None:
        t = pcbnew.PCB_TRACK(board)
        t.SetStart(vi(x1, y1))
        t.SetEnd(vi(x2, y2))
        t.SetWidth(pcbnew.FromMM(width))
        t.SetLayer(layer)
        t.SetNetCode(net_code(name))
        board.Add(t)

    # GND route: C1 pad2 (8.95, 22) -> U1 pad2 (22.525, 14.365)
    add_track("GND", 8.95, 22, 14, 22)
    add_track("GND", 14, 22, 14, 14.365)
    add_track("GND", 14, 14.365, 22.525, 14.365)
    # VCC route: C2 pad1 (39.05, 8) -> U1 pad1 (22.525, 13.095)
    add_track("VCC", 39.05, 8, 26, 8)
    add_track("VCC", 26, 8, 26, 13.095)
    add_track("VCC", 26, 13.095, 22.525, 13.095)
    # CLK route: U1 pad3 (22.525, 15.635) -> via -> B.Cu branch (long stub)
    add_track("CLK", 22.525, 15.635, 20, 15.635)
    add_track("CLK", 20, 15.635, 20, 20)
    add_track("CLK", 20, 20, 30, 20)
    # B.Cu stub leaving the via: intentionally dangling (the fixture DRC warning)
    add_track("CLK", 30, 20, 36, 20, layer=pcbnew.B_Cu)
    # GND: C2 pad2 (40.95, 8) over the top to U1 pad2 (22.525, 14.365)
    add_track("GND", 40.95, 8, 40.95, 4.4)
    add_track("GND", 40.95, 4.4, 24, 4.4)
    add_track("GND", 24, 4.4, 24, 14.365)
    add_track("GND", 24, 14.365, 22.525, 14.365)
    # RST route: U1 pad6 (27.475, 15.635) -> R1 pad2 (42, 21.087)
    add_track("RST", 27.475, 15.635, 31, 15.635)
    add_track("RST", 31, 15.635, 31, 18)
    add_track("RST", 31, 18, 42, 18)
    add_track("RST", 42, 18, 42, 21.087)

    # One through via on the CLK route
    via = pcbnew.PCB_VIA(board)
    via.SetPosition(vi(30, 20))
    via.SetWidth(pcbnew.FromMM(0.6))
    via.SetDrill(pcbnew.FromMM(0.3))
    via.SetViaType(pcbnew.VIATYPE_THROUGH)
    via.SetLayerPair(pcbnew.F_Cu, pcbnew.B_Cu)
    via.SetNetCode(net_code("CLK"))
    board.Add(via)

    # GND zone on F.Cu covering the whole board
    zone = pcbnew.ZONE(board)
    zone.SetNetCode(net_code("GND"))
    zone.SetLayer(pcbnew.F_Cu)
    zone.SetIsFilled(False)
    poly = pcbnew.SHAPE_POLY_SET()
    chain = pcbnew.SHAPE_LINE_CHAIN()
    for cx, cy in ((0.5, 0.5), (49.5, 0.5), (49.5, 29.5), (0.5, 29.5)):
        chain.Append(int(pcbnew.FromMM(cx)), int(pcbnew.FromMM(cy)))
    chain.SetClosed(True)
    poly.AddOutline(chain)
    zone.SetOutline(poly)
    board.Add(zone)

    board.Save(str(FIXTURES / "demo.kicad_pcb"))
    print("PCB written")


def build_support_files() -> None:
    """fixture.kicad_sym + sym-lib-table + project JSON."""
    sym_lib = "\n".join([
        "(kicad_symbol_lib",
        "\t(version 20251024)",
        '\t(generator "kicad_symbol_editor")',
        '\t(generator_version "10.0")',
        # library-level MCU definition: strip the "fixture:" prefix
        mcu_symbol().replace('"fixture:MCU_8PIN"', '"MCU_8PIN"', 1),
        ")",
    ]) + "\n"
    (FIXTURES / "fixture.kicad_sym").write_text(sym_lib, encoding="utf-8")
    (FIXTURES / "sym-lib-table").write_text(
        "(sym_lib_table\n"
        '  (version 7)\n'
        '  (lib (name "fixture")(type "KiCad")(uri "${KIPRJMOD}/fixture.kicad_sym")(options "")(descr "Fixture MCU symbols"))\n'
        ")\n",
        encoding="utf-8",
    )
    (FIXTURES / "demo.kicad_pro").write_text(
        "{\n"
        '  "board": {\n'
        '    "3dviewports": [],\n'
        '    "design_settings": {},\n'
        '    "layer_pairs": []\n'
        "  },\n"
        '  "boards": [],\n'
        '  "cvpcb": {"equivalence_files": []},\n'
        '  "libraries": {"pinned_footprint_libs": [], "pinned_symbol_libs": []},\n'
        '  "meta": {"filename": "demo.kicad_pro", "version": 3},\n'
        '  "net_settings": {"classes": [{"name": "Default", "fields": []}]},\n'
        '  "schematic": {"drawing": {}, "legacy_lib_dir": "", "legacy_lib_list": []},\n'
        "  \"sheets\": [\n"
        '    ["a1b2c3d4-0000-4000-8000-000000000001", "Root"],\n'
        '    ["a1b2c3d4-0000-4000-8000-000000000064", "power"]\n'
        "  ],\n"
        '  "text_variables": {}\n'
        "}\n",
        encoding="utf-8",
    )


def main() -> None:
    FIXTURES.mkdir(parents=True, exist_ok=True)
    SUB.mkdir(parents=True, exist_ok=True)
    (FIXTURES / "demo.kicad_sch").write_text(build_main_schematic(), encoding="utf-8")
    (SUB / "power.kicad_sch").write_text(build_sub_schematic(), encoding="utf-8")
    build_support_files()
    build_pcb()
    print("fixture complete")


if __name__ == "__main__":
    main()
