"""Real-project netlist snapshots for semantic-regression tests.

Derived from KiCad 10.0.6 demo exports (``complex_hierarchy`` and
``pic_programmer``).  They capture the real CLI output shape — nested
``(comp (ref …))`` records, ``(sheetpath (names …))`` hierarchy, and
``pinfunction``/``pintype`` node fields — without any runtime kicad-cli
dependency.  Trimming notes:

- ``complex_hierarchy``: kept U101 (78L05), U201/U301 op-amps, D101, C104,
  and the P102 connector.  ``+12V`` has no power_out source; U101 consumes it
  on pin VI and drives ``power_out`` on VCC (the regulator input pattern).
- ``pic_programmer``: VPP is charged passively through D10/C3/C9 from the
  transformer secondary, so no component drives it with ``power_out`` — the
  real heuristic blind spot that must stay a reported finding.
"""

COMPLEX_HIERARCHY_NETLIST = """(export (version "E") (design (sheet (number "1") (name "/")))
 (components
  (comp (ref "C104") (value "47uF/20V") (footprint "Capacitor_SMD:CP_Elec_8x10") (tstamps "c104")
   (unit (name "C") (pin "1") (pin "2")) (sheetpath (names "/") (tstamps "c104")))
  (comp (ref "D101") (value "1N4007") (footprint "Diode_THT:D_DO-41_SOD81") (tstamps "d101")
   (unit (name "D") (pin "1") (pin "2")) (sheetpath (names "/") (tstamps "d101")))
  (comp (ref "P101") (value "CONN_2") (footprint "Connector_PinHeader_2.54mm") (tstamps "p101")
   (unit (name "P") (pin "1") (pin "2")) (sheetpath (names "/") (tstamps "p101")))
  (comp (ref "P102") (value "CONN_2") (footprint "Connector_PinHeader_2.54mm") (tstamps "p102")
   (unit (name "P") (pin "1") (pin "2")) (sheetpath (names "/") (tstamps "p102")))
  (comp (ref "U101") (value "78L05") (footprint "Package_TO_SOT_SMD:SOT-89") (tstamps "u101")
   (unit (name "U") (pin "1") (pin "2") (pin "3")) (sheetpath (names "/") (tstamps "u101")))
  (comp (ref "U201") (value "TL072") (footprint "Package_SO:SOIC-8_3.9x4.9mm_P1.27mm") (tstamps "u201")
   (unit (name "U") (pin "1") (pin "2") (pin "4") (pin "8")) (sheetpath (names "/ampli_ht_vertical/") (tstamps "u201")))
  (comp (ref "U301") (value "TL072") (footprint "Package_SO:SOIC-8_3.9x4.9mm_P1.27mm") (tstamps "u301")
   (unit (name "U") (pin "1") (pin "2") (pin "4") (pin "8")) (sheetpath (names "/ampli_ht_horizontal/") (tstamps "u301")))
  (comp (ref "U102") (value "ICL7660") (footprint "Package_SO:SOIC-8_3.9x4.9mm_P1.27mm") (tstamps "u102")
   (unit (name "U") (pin "3") (pin "5") (pin "8")) (sheetpath (names "/") (tstamps "u102"))))
 (nets
  (net (code "1") (name "+12V")
   (node (ref "C104") (pin "1") (pintype "passive"))
   (node (ref "D101") (pin "1") (pinfunction "K_1") (pintype "passive"))
   (node (ref "U101") (pin "3") (pinfunction "VI_3") (pintype "input"))
   (node (ref "U201") (pin "8") (pinfunction "V+_8") (pintype "power_in"))
   (node (ref "U301") (pin "8") (pinfunction "V+_8") (pintype "power_in")))
  (net (code "2") (name "VCC")
   (node (ref "C102") (pin "1") (pintype "passive"))
   (node (ref "U101") (pin "1") (pinfunction "VO_1") (pintype "power_out"))
   (node (ref "U102") (pin "8") (pinfunction "V+_8") (pintype "power_in")))
  (net (code "3") (name "GND")
   (node (ref "C104") (pin "2") (pintype "passive"))
   (node (ref "U101") (pin "2") (pinfunction "GND_2") (pintype "input"))
   (node (ref "U102") (pin "3") (pinfunction "GND_3") (pintype "power_in")))
  (net (code "4") (name "HT")
   (node (ref "P101") (pin "1") (pinfunction "P1_1") (pintype "passive"))
   (node (ref "Q302") (pin "3") (pinfunction "C_3") (pintype "passive")))
  (net (code "5") (name "/12Vext")
   (node (ref "D101") (pin "2") (pinfunction "A_2") (pintype "passive"))
   (node (ref "P102") (pin "1") (pinfunction "P1_1") (pintype "passive")))))
"""

PIC_PROGRAMMER_VPP_NETLIST = """(export (version "E") (design (sheet (number "1") (name "/")))
 (components
  (comp (ref "C3") (value "47uF") (footprint "Capacitor_THT:CP_Radial_D8") (tstamps "c3")
   (unit (name "C") (pin "1") (pin "2")) (sheetpath (names "/") (tstamps "c3")))
  (comp (ref "C9") (value "10uF") (footprint "Capacitor_SMD:C_0805") (tstamps "c9")
   (unit (name "C") (pin "1") (pin "2")) (sheetpath (names "/") (tstamps "c9")))
  (comp (ref "D10") (value "1N4148") (footprint "Diode_SMD:D_SOD-123") (tstamps "d10")
   (unit (name "D") (pin "1") (pin "2")) (sheetpath (names "/") (tstamps "d10")))
  (comp (ref "Q2") (value "BC337") (footprint "Package_TO_SOT_THT:TO-92_Inline") (tstamps "q2")
   (unit (name "Q") (pin "1") (pin "2") (pin "3")) (sheetpath (names "/") (tstamps "q2")))
  (comp (ref "R7") (value "1k") (footprint "Resistor_SMD:R_0805") (tstamps "r7")
   (unit (name "R") (pin "1") (pin "2")) (sheetpath (names "/") (tstamps "r7")))
  (comp (ref "R16") (value "2k2") (footprint "Resistor_SMD:R_0805") (tstamps "r16")
   (unit (name "R") (pin "1") (pin "2")) (sheetpath (names "/") (tstamps "r16"))))
 (nets
  (net (code "1") (name "VPP")
   (node (ref "C3") (pin "1") (pintype "passive"))
   (node (ref "C9") (pin "1") (pintype "passive"))
   (node (ref "D10") (pin "1") (pinfunction "K_1") (pintype "passive"))
   (node (ref "Q2") (pin "3") (pinfunction "E_3") (pintype "passive"))
   (node (ref "R7") (pin "1") (pintype "passive"))
   (node (ref "R16") (pin "2") (pintype "passive")))))
"""

# Synthetic connector-entry rail in the real export shape: a single +5V rail
# fed only through connector P1 with a root-sheet power_in consumer.
CONNECTOR_RAIL_NETLIST = """(export (version "E") (design (sheet (number "1") (name "/")))
 (components
  (comp (ref "P1") (value "CONN_2") (footprint "Connector_PinHeader_2.54mm") (tstamps "p1")
   (unit (name "P") (pin "1") (pin "2")) (sheetpath (names "/") (tstamps "p1")))
  (comp (ref "U1") (value "74HC04") (footprint "Package_SO:SOIC-14") (tstamps "u1")
   (unit (name "U") (pin "14") (pin "7")) (sheetpath (names "/") (tstamps "u1"))))
 (nets
  (net (code "1") (name "+5V")
   (node (ref "P1") (pin "1") (pinfunction "1_1") (pintype "passive"))
   (node (ref "U1") (pin "14") (pinfunction "VCC_14") (pintype "power_in")))))
"""
