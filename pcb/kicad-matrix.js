// Erzeugt den KiCad 7 Schaltplan für die Motormatrix (Wurzelblatt + ein Blatt pro Reihe, alle Reihen nutzen dieselbe Datei).
// Läuft im Browser (window.MotorMatrix) und in Node (module.exports).
(function (root) {
  "use strict";

  const G = 2.54;                 // Rastermaß im Schaltplan
  const FILE_VERSION = 20230121;  // Dateiformat KiCad 7, KiCad 8 und 9 lesen es ein
  const ROW_FILE = "reihe.kicad_sch";
  const MAX_SIDE = 40;

  // ── Hilfsfunktionen ─────────────────────────────────────────
  const num = (v) => {
    const r = Math.round(v * 10000) / 10000;
    return Object.is(r, -0) ? "0" : String(r);
  };
  const q = (s) => '"' + String(s).replace(/\\/g, "\\\\").replace(/"/g, '\\"') + '"';
  const sn = (v) => Math.round(v / 1.27) * 1.27;  // aufs 1,27 mm Raster
  const fx = (justify, hide) => `(effects (font (size 1.27 1.27))${justify ? ` (justify ${justify})` : ""}${hide ? " hide" : ""})`;

  // Feste UUIDs, damit derselbe Aufbau immer dieselbe Datei ergibt
  function uuidMaker(seed) {
    let n = 0;
    return () => {
      n += 1;
      const h = (seed * 2654435761 + n * 40503).toString(16).padStart(8, "0").slice(-8);
      const c = n.toString(16).padStart(12, "0").slice(-12);
      return `${h}-${c.slice(0, 4)}-4${c.slice(4, 7)}-8${c.slice(7, 10)}-${h.slice(0, 4)}${c.slice(4, 12)}`;
    };
  }

  // ── Bauteile (Symbole) ──────────────────────────────────────
  // Pins: [nummer, name, typ]. Links und rechts Signale, oben Versorgung, unten Masse.
  const PARTS = {
    DRV8220: {
      lib: "BlindSight:DRV8220DRL", ref: "U", value: "DRV8220DRL", w: 10.16,
      footprint: "Package_TO_SOT_SMD:SOT-563", datasheet: "https://www.ti.com/lit/gpn/DRV8220",
      mpn: "DRV8220DRLR",
      left: [["1", "IN1", "input"], ["2", "IN2", "input"]],
      right: [["6", "OUT1", "output"], ["4", "OUT2", "output"]],
      top: [["5", "VM", "power_in"]], bottom: [["3", "GND", "power_in"]],
    },
    HC595: {
      lib: "BlindSight:74HC595", ref: "U", value: "74HC595", w: 12.7,
      footprint: "Package_SO:SOIC-16_3.9x9.9mm_P1.27mm", datasheet: "https://www.ti.com/lit/ds/symlink/sn74hc595.pdf",
      mpn: "SN74HC595DR",
      left: [["14", "SER", "input"], ["11", "SRCLK", "input"], ["12", "RCLK", "input"], ["10", "~{SRCLR}", "input"], ["13", "~{OE}", "input"]],
      right: [["15", "QA", "tri_state"], ["1", "QB", "tri_state"], ["2", "QC", "tri_state"], ["3", "QD", "tri_state"],
        ["4", "QE", "tri_state"], ["5", "QF", "tri_state"], ["6", "QG", "tri_state"], ["7", "QH", "tri_state"], ["9", "QH'", "output"]],
      top: [["16", "VCC", "power_in"]], bottom: [["8", "GND", "power_in"]],
    },
    HC165: {
      lib: "BlindSight:74HC165", ref: "U", value: "74HC165", w: 12.7,
      footprint: "Package_SO:SOIC-16_3.9x9.9mm_P1.27mm", datasheet: "https://www.ti.com/lit/ds/symlink/sn74hc165.pdf",
      mpn: "SN74HC165DR",
      left: [["11", "A", "input"], ["12", "B", "input"], ["13", "C", "input"], ["14", "D", "input"], ["3", "E", "input"],
        ["4", "F", "input"], ["5", "G", "input"], ["6", "H", "input"], ["10", "SER", "input"], ["2", "CLK", "input"],
        ["15", "CLK_INH", "input"], ["1", "SH/~{LD}", "input"]],
      right: [["9", "QH", "output"], ["7", "~{QH}", "output"]],
      top: [["16", "VCC", "power_in"]], bottom: [["8", "GND", "power_in"]],
    },
    HC244: {
      lib: "BlindSight:74HC244", ref: "U", value: "74HC244", w: 12.7,
      footprint: "Package_SO:SOIC-20W_7.5x12.8mm_P1.27mm", datasheet: "https://www.ti.com/lit/ds/symlink/sn74hc244.pdf",
      mpn: "SN74HC244DWR",
      left: [["2", "1A1", "input"], ["4", "1A2", "input"], ["6", "1A3", "input"], ["8", "1A4", "input"], ["11", "2A1", "input"],
        ["13", "2A2", "input"], ["15", "2A3", "input"], ["17", "2A4", "input"], ["1", "~{1OE}", "input"], ["19", "~{2OE}", "input"]],
      right: [["18", "1Y1", "tri_state"], ["16", "1Y2", "tri_state"], ["14", "1Y3", "tri_state"], ["12", "1Y4", "tri_state"],
        ["9", "2Y1", "tri_state"], ["7", "2Y2", "tri_state"], ["5", "2Y3", "tri_state"], ["3", "2Y4", "tri_state"]],
      top: [["20", "VCC", "power_in"]], bottom: [["10", "GND", "power_in"]],
    },
    MOTOR: {
      lib: "BlindSight:N20_Encoder_Pads", ref: "J", value: "N20 Encoder", w: 10.16,
      footprint: "Connector_PinHeader_2.54mm:PinHeader_1x06_P2.54mm_Vertical", datasheet: "",
      mpn: "Lötpads, Kabel des N20 direkt anlöten",
      left: [["1", "M1", "passive"], ["2", "M2", "passive"], ["3", "VCC", "passive"], ["4", "GND", "passive"], ["5", "A", "passive"], ["6", "B", "passive"]],
      right: [], top: [], bottom: [],
    },
    RPACK: {
      lib: "BlindSight:R_Pack04", ref: "RN", value: "10k", w: 7.62,
      footprint: "Resistor_SMD:R_Array_Convex_4x0603", datasheet: "", mpn: "4x 10k 0603 Array",
      left: [["1", "R1.1", "passive"], ["2", "R2.1", "passive"], ["3", "R3.1", "passive"], ["4", "R4.1", "passive"]],
      right: [["8", "R1.2", "passive"], ["7", "R2.2", "passive"], ["6", "R3.2", "passive"], ["5", "R4.2", "passive"]],
      top: [], bottom: [],
    },
    CTRL: {
      lib: "BlindSight:ESP32_Anschluss", ref: "J", value: "ESP32", w: 12.7,
      footprint: "Connector_PinHeader_2.54mm:PinHeader_1x08_P2.54mm_Vertical", datasheet: "", mpn: "Stiftleiste 1x8",
      left: [], top: [], bottom: [],
      right: [["1", "GND", "passive"], ["2", "SCK_O", "passive"], ["3", "MOSI", "passive"], ["4", "LATCH", "passive"],
        ["5", "OE_N", "passive"], ["6", "SCK_I", "passive"], ["7", "MISO", "passive"], ["8", "LOAD_N", "passive"]],
    },
    BUCK: {
      lib: "BlindSight:Buck_Modul", ref: "J", value: "Buck 12V auf 3,3V", w: 12.7,
      footprint: "Connector_PinHeader_2.54mm:PinHeader_1x04_P2.54mm_Vertical", datasheet: "", mpn: "Buck Modul, mind. 2 A",
      left: [["1", "IN+", "passive"], ["2", "IN-", "passive"]], right: [["3", "OUT+", "passive"], ["4", "OUT-", "passive"]],
      top: [], bottom: [],
    },
    POWER_IN: {
      lib: "BlindSight:Klemme_12V", ref: "J", value: "12V Eingang", w: 7.62,
      footprint: "TerminalBlock_Phoenix:TerminalBlock_Phoenix_MKDS-1,5-2-5.08_1x02_P5.08mm_Horizontal", datasheet: "",
      mpn: "Schraubklemme 5,08 mm",
      right: [["1", "+", "passive"], ["2", "-", "passive"]], left: [], top: [], bottom: [],
    },
  };
  // Zweipolige Bauteile senkrecht, Pin 1 oben
  const TWO_PIN = {
    C: { lib: "Device:C", ref: "C", footprint: "Capacitor_SMD:C_0603_1608Metric" },
    CP: { lib: "Device:C_Polarized", ref: "C", footprint: "Capacitor_THT:CP_Radial_D10.0mm_P5.00mm" },
    R: { lib: "Device:R", ref: "R", footprint: "Resistor_SMD:R_0603_1608Metric" },
    F: { lib: "Device:Fuse", ref: "F", footprint: "Fuse:Fuseholder_Blade_Mini_Keystone_3568" },
  };
  const POWER = { "+12V": "power:+12V", "+3V3": "power:+3V3", GND: "power:GND", FLAG: "power:PWR_FLAG" };

  // Pinlage eines Bauteils in Bibliothekskoordinaten (y nach oben)
  function layoutPins(p) {
    const n = Math.max(p.left.length, p.right.length, 1);
    const h = G * (n + 1);
    const pins = {};
    const side = (list, x, ang, s) => list.forEach(([nr, name, type], i) => {
      pins[nr] = { x, y: h / 2 - G * (i + 1), ang, side: s, name, type };
    });
    side(p.left, -p.w / 2 - G, 0, "L");
    side(p.right, p.w / 2 + G, 180, "R");
    const row = (list, y, ang, s) => list.forEach(([nr, name, type], i) => {
      pins[nr] = { x: G * (i - (list.length - 1) / 2), y, ang, side: s, name, type };
    });
    row(p.top, h / 2 + G, 270, "T");
    row(p.bottom, -h / 2 - G, 90, "B");
    return { pins, h };
  }

  function libIC(p) {
    const { pins, h } = layoutPins(p);
    const short = p.lib.split(":")[1];
    const pinText = Object.entries(pins).map(([nr, pin]) =>
      `      (pin ${pin.type} line (at ${num(pin.x)} ${num(pin.y)} ${pin.ang}) (length ${G})\n` +
      `        (name ${q(pin.name)} ${fx()})\n        (number ${q(nr)} ${fx()})\n      )`).join("\n");
    return `    (symbol ${q(p.lib)} (pin_names (offset 1.016)) (in_bom yes) (on_board yes)
      (property "Reference" ${q(p.ref)} (at ${num(-p.w / 2)} ${num(h / 2 + 1.27)} 0) ${fx("left bottom")})
      (property "Value" ${q(p.value)} (at ${num(-p.w / 2)} ${num(-h / 2 - 1.27)} 0) ${fx("left top")})
      (property "Footprint" ${q(p.footprint)} (at 0 0 0) ${fx(null, true)})
      (property "Datasheet" ${q(p.datasheet || "~")} (at 0 0 0) ${fx(null, true)})
      (symbol ${q(short + "_0_1")}
        (rectangle (start ${num(-p.w / 2)} ${num(h / 2)}) (end ${num(p.w / 2)} ${num(-h / 2)})
          (stroke (width 0.254) (type default)) (fill (type background)))
      )
      (symbol ${q(short + "_1_1")}
${pinText}
      )
    )`;
  }

  function libTwoPin(kind) {
    const t = TWO_PIN[kind];
    const short = t.lib.split(":")[1];
    const body = {
      C: `(polyline (pts (xy -2.032 -0.762) (xy 2.032 -0.762)) (stroke (width 0.508) (type default)) (fill (type none)))
        (polyline (pts (xy -2.032 0.762) (xy 2.032 0.762)) (stroke (width 0.508) (type default)) (fill (type none)))`,
      CP: `(rectangle (start -2.286 0.508) (end 2.286 1.016) (stroke (width 0) (type default)) (fill (type none)))
        (polyline (pts (xy -1.778 2.286) (xy -0.762 2.286)) (stroke (width 0) (type default)) (fill (type none)))
        (polyline (pts (xy -1.27 2.794) (xy -1.27 1.778)) (stroke (width 0) (type default)) (fill (type none)))
        (rectangle (start 2.286 -0.508) (end -2.286 -1.016) (stroke (width 0) (type default)) (fill (type outline)))`,
      R: `(rectangle (start -1.016 -2.54) (end 1.016 2.54) (stroke (width 0.254) (type default)) (fill (type none)))`,
      F: `(rectangle (start -0.762 -2.54) (end 0.762 2.54) (stroke (width 0.254) (type default)) (fill (type none)))
        (polyline (pts (xy 0 2.54) (xy 0 -2.54)) (stroke (width 0) (type default)) (fill (type none)))`,
    }[kind];
    return `    (symbol ${q(t.lib)} (pin_numbers hide) (pin_names (offset 0.254) hide) (in_bom yes) (on_board yes)
      (property "Reference" ${q(t.ref)} (at 2.54 1.27 0) ${fx("left")})
      (property "Value" ${q(kind)} (at 2.54 -1.27 0) ${fx("left")})
      (property "Footprint" ${q(t.footprint)} (at 0 0 0) ${fx(null, true)})
      (property "Datasheet" "~" (at 0 0 0) ${fx(null, true)})
      (symbol ${q(short + "_0_1")}
        ${body}
      )
      (symbol ${q(short + "_1_1")}
        (pin passive line (at 0 3.81 270) (length 1.27) (name "~" ${fx()}) (number "1" ${fx()}))
        (pin passive line (at 0 -3.81 90) (length 1.27) (name "~" ${fx()}) (number "2" ${fx()}))
      )
    )`;
  }

  function libPower(name) {
    const lib = POWER[name];
    const short = lib.split(":")[1];
    if (name === "FLAG") {
      return `    (symbol "power:PWR_FLAG" (power) (pin_numbers hide) (pin_names (offset 0) hide) (in_bom yes) (on_board yes)
      (property "Reference" "#FLG" (at 0 1.905 0) ${fx(null, true)})
      (property "Value" "PWR_FLAG" (at 0 3.81 0) ${fx()})
      (property "Footprint" "" (at 0 0 0) ${fx(null, true)})
      (property "Datasheet" "~" (at 0 0 0) ${fx(null, true)})
      (symbol "PWR_FLAG_0_0"
        (pin power_out line (at 0 0 90) (length 0) (name "pwr" ${fx()}) (number "1" ${fx()}))
      )
      (symbol "PWR_FLAG_0_1"
        (polyline (pts (xy 0 0) (xy 0 1.27) (xy -1.016 1.905) (xy 0 2.54) (xy 1.016 1.905) (xy 0 1.27))
          (stroke (width 0) (type default)) (fill (type none)))
      )
    )`;
    }
    const gnd = name === "GND";
    const gfx = gnd
      ? `(polyline (pts (xy 0 0) (xy 0 -1.27) (xy 1.27 -1.27) (xy 0 -2.54) (xy -1.27 -1.27) (xy 0 -1.27)) (stroke (width 0) (type default)) (fill (type none)))`
      : `(polyline (pts (xy -0.762 1.27) (xy 0 2.54)) (stroke (width 0) (type default)) (fill (type none)))
        (polyline (pts (xy 0 0) (xy 0 2.54)) (stroke (width 0) (type default)) (fill (type none)))
        (polyline (pts (xy 0 2.54) (xy 0.762 1.27)) (stroke (width 0) (type default)) (fill (type none)))`;
    return `    (symbol ${q(lib)} (power) (pin_names (offset 0)) (in_bom yes) (on_board yes)
      (property "Reference" "#PWR" (at 0 ${gnd ? -6.35 : -3.81} 0) ${fx(null, true)})
      (property "Value" ${q(name)} (at 0 ${gnd ? -3.81 : 3.556} 0) ${fx()})
      (property "Footprint" "" (at 0 0 0) ${fx(null, true)})
      (property "Datasheet" "" (at 0 0 0) ${fx(null, true)})
      (symbol ${q(short + "_0_1")}
        ${gfx}
      )
      (symbol ${q(short + "_1_1")}
        (pin power_in line (at 0 0 ${gnd ? 270 : 90}) (length 0) hide (name ${q(name)} ${fx()}) (number "1" ${fx()}))
      )
    )`;
  }

  // ── Ein Blatt mit Bauteilen, Stummeln, Labels ───────────────
  // Jeder Pin bekommt einen kurzen Draht nach außen und am Ende ein Netzlabel oder ein Versorgungssymbol
  class Sheet {
    constructor(project, uuid, instancePaths) {
      this.project = project;
      this.uuid = uuid;
      this.paths = instancePaths;  // [{path, refs: Map}] eine pro Blattinstanz
      this.items = [];
      this.libs = new Set();
      this.pwr = 0;
    }

    // refFn(pathIndex) liefert die Referenz für diese Instanz
    symbol(lib, x, y, refFn, value, footprint, extra = {}) {
      this.libs.add(lib);
      const id = this.uuid();
      const pins = extra.pinNumbers || [];
      const props = [
        `    (property "Reference" ${q(refFn(0))} (at ${num(x + (extra.refDx ?? 0))} ${num(y + (extra.refDy ?? -1.27))} 0) ${fx(extra.hideRef ? null : "left bottom", extra.hideRef)})`,
        `    (property "Value" ${q(value)} (at ${num(x + (extra.valDx ?? 0))} ${num(y + (extra.valDy ?? 1.27))} 0) ${fx(extra.hideVal ? null : "left top", extra.hideVal)})`,
        `    (property "Footprint" ${q(footprint || "")} (at ${num(x)} ${num(y)} 0) ${fx(null, true)})`,
        `    (property "Datasheet" ${q(extra.datasheet || "~")} (at ${num(x)} ${num(y)} 0) ${fx(null, true)})`,
      ];
      for (const [k, v] of Object.entries(extra.fields || {})) {
        props.push(`    (property ${q(k)} ${q(v)} (at ${num(x)} ${num(y)} 0) ${fx(null, true)})`);
      }
      const inst = this.paths.map((p, i) =>
        `        (path ${q(p)} (reference ${q(refFn(i))}) (unit 1))`).join("\n");
      this.items.push(`  (symbol (lib_id ${q(lib)}) (at ${num(x)} ${num(y)} 0) (unit 1)
    (in_bom ${extra.power ? "no" : "yes"}) (on_board ${extra.power ? "no" : "yes"}) (dnp ${extra.dnp ? "yes" : "no"})
    (uuid ${q(id)})
${props.join("\n")}
${pins.map((nr) => `    (pin ${q(nr)} (uuid ${q(this.uuid())}))`).join("\n")}
    (instances
      (project ${q(this.project)}
${inst}
      )
    )
  )`);
    }

    wire(x1, y1, x2, y2) {
      this.items.push(`  (wire (pts (xy ${num(x1)} ${num(y1)}) (xy ${num(x2)} ${num(y2)}))
    (stroke (width 0) (type default))
    (uuid ${q(this.uuid())})
  )`);
    }

    label(name, x, y, ang) {
      const just = { 0: "left bottom", 90: "left bottom", 180: "right bottom", 270: "right bottom" }[ang];
      this.items.push(`  (label ${q(name)} (at ${num(x)} ${num(y)} ${ang}) (fields_autoplaced)
    ${fx(just)}
    (uuid ${q(this.uuid())})
  )`);
    }

    hlabel(name, shape, x, y, ang) {
      const just = ang === 180 ? "right" : "left";
      this.items.push(`  (hierarchical_label ${q(name)} (shape ${shape}) (at ${num(x)} ${num(y)} ${ang}) (fields_autoplaced)
    ${fx(just)}
    (uuid ${q(this.uuid())})
  )`);
    }

    noConnect(x, y) {
      this.items.push(`  (no_connect (at ${num(x)} ${num(y)}) (uuid ${q(this.uuid())}))`);
    }

    power(name, x, y, refBase) {
      x = sn(x);
      y = sn(y);
      const n = ++this.pwr;
      const flag = name === "FLAG";
      this.symbol(POWER[name], x, y, (i) => `${flag ? "#FLG" : "#PWR"}${refBase(i)}${String(n).padStart(3, "0")}`,
        flag ? "PWR_FLAG" : name, "", { power: true, hideRef: true, pinNumbers: ["1"], valDy: name === "GND" ? 3.81 : -3.81 });
    }

    // Verbindet einen Pin mit einem Netz. net: "GND", "+3V3", "+12V", "NC", "H:Name:shape" oder ein Labelname
    connect(px, py, side, net, refBase) {
      if (net === "NC") { this.noConnect(px, py); return; }
      const d = { L: [-G, 0, 180], R: [G, 0, 0], T: [0, -G, 90], B: [0, G, 270] }[side];
      const ex = px + d[0];
      const ey = py + d[1];
      this.wire(px, py, ex, ey);
      if (net === "GND" || net === "+3V3" || net === "+12V") { this.power(net, ex, ey, refBase); return; }
      if (net.startsWith("H:")) {
        const [, name, shape] = net.split(":");
        this.hlabel(name, shape, ex, ey, d[2]);
        return;
      }
      this.label(net, ex, ey, d[2]);
    }

    // Bauteil mit Netzzuordnung je Pin platzieren
    place(part, x, y, refFn, nets, refBase, extra = {}) {
      x = sn(x);
      y = sn(y);
      const { pins, h } = layoutPins(part);
      const pos = { refDx: 1.27, refDy: -h / 2 - 0.8, valDx: 1.27, valDy: h / 2 + 0.8 };
      this.symbol(part.lib, x, y, refFn, extra.value || part.value, part.footprint,
        { ...pos, ...extra, datasheet: part.datasheet, pinNumbers: Object.keys(pins), fields: { MPN: part.mpn || "", LCSC: "" } });
      for (const [nr, pin] of Object.entries(pins)) {
        const net = nets[nr];
        if (net === undefined) throw new Error(`Pin ${nr} von ${part.lib} ohne Netz`);
        this.connect(x + pin.x, y - pin.y, pin.side, net, refBase);
      }
    }

    // Zweipoliges Bauteil senkrecht, Pin 1 oben
    placeTwo(kind, x, y, refFn, value, net1, net2, refBase, footprint) {
      x = sn(x);
      y = sn(y);
      const t = TWO_PIN[kind];
      this.symbol(t.lib, x, y, refFn, value, footprint || t.footprint, { pinNumbers: ["1", "2"], refDx: 2.54, refDy: -0.635, valDx: 2.54, valDy: 1.905 });
      this.connect(x, y - 3.81, "T", net1, refBase);
      this.connect(x, y + 3.81, "B", net2, refBase);
    }

    text(s, x, y, size = 2) {
      this.items.push(`  (text ${q(s)} (at ${num(x)} ${num(y)} 0)
    (effects (font (size ${size} ${size})) (justify left bottom))
    (uuid ${q(this.uuid())})
  )`);
    }

    file(paper, libText, tail = "") {
      return `(kicad_sch (version ${FILE_VERSION}) (generator eeschema)

  (uuid ${q(this.fileUuid)})

  (paper ${paper})

  (lib_symbols
${libText}
  )

${this.items.join("\n\n")}
${tail}
)
`;
    }
  }

  function paperFor(w, h) {
    const sizes = [["A4", 297, 210], ["A3", 420, 297], ["A2", 594, 420], ["A1", 841, 594], ["A0", 1189, 841]];
    for (const [name, pw, ph] of sizes) if (w <= pw - 20 && h <= ph - 20) return q(name);
    return `"User" ${num(Math.ceil(w + 40))} ${num(Math.ceil(h + 40))}`;
  }

  // ── Plan: Bits, Referenzen, Zahlen ───────────────────────────
  function plan(rows, cols) {
    if (!(rows >= 1 && rows <= MAX_SIDE && cols >= 1 && cols <= MAX_SIDE)) {
      throw new Error(`Reihen und Spalten müssen zwischen 1 und ${MAX_SIDE} liegen`);
    }
    const K = Math.ceil((2 * cols) / 8);       // Schieberegister je Typ und Reihe
    const chips = rows * K;
    const bits = chips * 8;
    const refs = {
      driver: (r, c) => `U${(r + 1) * 100 + c + 1}`,
      buffer: (r) => `U${(r + 1) * 100 + 50}`,
      sr595: (r, i) => `U${(r + 1) * 100 + 51 + i}`,
      sr165: (r, i) => `U${(r + 1) * 100 + 71 + i}`,
      pads: (r, c) => `J${(r + 1) * 100 + c + 1}`,
      rpack: (r, i) => `RN${(r + 1) * 100 + i + 1}`,
      vmCap: (r, c) => `C${(r + 1) * 100 + c + 1}`,
      logicCap: (r, k) => `C${(r + 1) * 100 + 50 + k}`,
      bulk12: (r) => `C${(r + 1) * 100 + 90}`,
      bulk33: (r) => `C${(r + 1) * 100 + 91}`,
    };
    const QN = ["QA", "QB", "QC", "QD", "QE", "QF", "QG", "QH"];
    const IN = ["A", "B", "C", "D", "E", "F", "G", "H"];
    // Ausgang: zuerst gesendetes Bit landet im letzten Chip der Kette bei QH
    const outIndex = (r, b) => {
      const g = r * K + Math.floor(b / 8);
      return (chips - 1 - g) * 8 + (7 - (b % 8));
    };
    // Eingang: zuerst gelesenes Bit ist H des Chips direkt am MISO (Reihe 1, erster Chip)
    const inIndex = (r, b) => (r * K + Math.floor(b / 8)) * 8 + (7 - (b % 8));
    const motor = (r, c) => {
      const b1 = 2 * c;
      const b2 = 2 * c + 1;
      return {
        row: r + 1, col: c + 1, pads: refs.pads(r, c), driver: refs.driver(r, c), vmCap: refs.vmCap(r, c),
        rpack: refs.rpack(r, Math.floor(c / 2)),
        in1: { chip: refs.sr595(r, Math.floor(b1 / 8)), pin: QN[b1 % 8], frameBit: outIndex(r, b1) },
        in2: { chip: refs.sr595(r, Math.floor(b2 / 8)), pin: QN[b2 % 8], frameBit: outIndex(r, b2) },
        encA: { chip: refs.sr165(r, Math.floor(b1 / 8)), pin: IN[b1 % 8], frameBit: inIndex(r, b1) },
        encB: { chip: refs.sr165(r, Math.floor(b2 / 8)), pin: IN[b2 % 8], frameBit: inIndex(r, b2) },
      };
    };
    const count = {
      drivers: rows * cols, pads: rows * cols, sr595: chips, sr165: chips, buffers: rows,
      rpacks: rows * Math.ceil(cols / 2), capsVm: rows * cols, capsLogic: rows * (2 * K + 1), capsBulk: rows * 2,
    };
    return { rows, cols, K, chips, bits, refs, motor, count, QN, IN };
  }

  // ── Blatt für eine Reihe ────────────────────────────────────
  function buildRowSheet(P, project, uuid, rowPaths) {
    const s = new Sheet(project, uuid, rowPaths);
    s.fileUuid = uuid();
    const { cols, K, refs, QN, IN } = P;
    const R = (fn) => (i) => fn(i);
    const pwrBase = (i) => String(i + 1);
    const nets595 = [];
    const nets165 = [];

    // Puffer für Takt und Steuerleitungen dieser Reihe
    const yTop = 52;
    const pitch = 55;
    s.text("Puffer für Takte und Steuerleitungen", 12, 20, 2);
    s.place(PARTS.HC244, 38, yTop, R((i) => refs.buffer(i)), {
      2: "H:SCK_O:input", 4: "H:LATCH:input", 6: "H:OE_N:input", 8: "H:SCK_I:input", 11: "H:LOAD_N:input",
      13: "GND", 15: "GND", 17: "GND", 1: "GND", 19: "GND",
      18: "SCK_O_B", 16: "LATCH_B", 14: "OE_N_B", 12: "SCK_I_B", 9: "LOAD_N_B", 7: "NC", 5: "NC", 3: "NC",
      20: "+3V3", 10: "GND",
    }, pwrBase);
    s.placeTwo("C", 52, 28, R((i) => refs.logicCap(i, 0)), "100n", "+3V3", "GND", pwrBase);

    // Ausgangskette 74HC595
    s.text("Ausgänge 74HC595, je Motor IN1 und IN2 für den Treiber", 80, 20, 2);
    for (let i = 0; i < K; i++) {
      const nets = { 11: "SCK_O_B", 12: "LATCH_B", 10: "+3V3", 13: "OE_N_B", 16: "+3V3", 8: "GND" };
      nets[14] = i === 0 ? "H:DOUT_IN:input" : `D_${i}`;
      nets[9] = i === K - 1 ? "H:DOUT_NEXT:output" : `D_${i + 1}`;
      const pinOf = { QA: "15", QB: "1", QC: "2", QD: "3", QE: "4", QF: "5", QG: "6", QH: "7" };
      for (let b = 0; b < 8; b++) {
        const bit = i * 8 + b;
        const c = Math.floor(bit / 2);
        nets[pinOf[QN[b]]] = c < cols ? `M${c + 1}_IN${(bit % 2) + 1}` : "NC";
      }
      nets595.push(nets);
      const cx = 100 + i * pitch;
      s.place(PARTS.HC595, cx, yTop, R((j) => refs.sr595(j, i)), nets, pwrBase);
      s.placeTwo("C", cx + 14, 28, R((j) => refs.logicCap(j, 1 + i)), "100n", "+3V3", "GND", pwrBase);
    }

    // Eingangskette 74HC165
    const y165 = 120;
    s.text("Encoder Eingänge 74HC165, je Motor A und B", 80, 86, 2);
    for (let i = 0; i < K; i++) {
      const pinOf = { A: "11", B: "12", C: "13", D: "14", E: "3", F: "4", G: "5", H: "6" };
      const nets = { 2: "SCK_I_B", 1: "LOAD_N_B", 15: "GND", 16: "+3V3", 8: "GND", 7: "NC" };
      nets[9] = i === 0 ? "H:DIN_OUT:output" : `I_${i}`;
      nets[10] = i === K - 1 ? "H:DIN_NEXT:input" : `I_${i + 1}`;
      for (let b = 0; b < 8; b++) {
        const bit = i * 8 + b;
        const c = Math.floor(bit / 2);
        nets[pinOf[IN[b]]] = c < cols ? `M${c + 1}_${bit % 2 ? "B" : "A"}` : "GND";
      }
      nets165.push(nets);
      const cx = 100 + i * pitch;
      s.place(PARTS.HC165, cx, y165, R((j) => refs.sr165(j, i)), nets, pwrBase);
      s.placeTwo("C", cx + 14, 92, R((j) => refs.logicCap(j, 1 + K + i)), "100n", "+3V3", "GND", pwrBase);
    }

    // Puffer Kondensatoren der Reihe
    s.text("Stütz-Kondensatoren der Reihe", 12, 98, 1.5);
    s.placeTwo("C", 25, 112, R((i) => refs.bulk12(i)), "22u 25V", "+12V", "GND", pwrBase, "Capacitor_SMD:C_1206_3216Metric");
    s.placeTwo("C", 45, 112, R((i) => refs.bulk33(i)), "10u", "+3V3", "GND", pwrBase, "Capacitor_SMD:C_0805_2012Metric");

    // Motorkanäle: Treiber, Kondensator, Lötpads
    const perLine = Math.min(cols, 7);
    const top = 175;
    const bw = 78;
    const bh = 46;
    s.text("Motorkanäle, je Motor ein DRV8220 und sechs Lötpads", 12, top - 12, 2);
    for (let c = 0; c < cols; c++) {
      const bx = 12 + (c % perLine) * bw;
      const by = top + Math.floor(c / perLine) * bh;
      s.text(`Motor ${c + 1}`, bx, by, 1.5);
      s.place(PARTS.DRV8220, bx + 22, by + 12, R((i) => refs.driver(i, c)), {
        1: `M${c + 1}_IN1`, 2: `M${c + 1}_IN2`, 6: `M${c + 1}_OUT1`, 4: `M${c + 1}_OUT2`, 5: "+12V", 3: "GND",
      }, pwrBase);
      s.placeTwo("C", bx + 42, by + 30, R((i) => refs.vmCap(i, c)), "100n 25V", "+12V", "GND", pwrBase);
      s.place(PARTS.MOTOR, bx + 64, by + 14, R((i) => refs.pads(i, c)), {
        1: `M${c + 1}_OUT1`, 2: `M${c + 1}_OUT2`, 3: "+3V3", 4: "GND", 5: `M${c + 1}_A`, 6: `M${c + 1}_B`,
      }, pwrBase);
    }

    // Pull-ups für Encoder, nur bestücken wenn die Encoderplatine keine hat
    const ry = top + Math.ceil(cols / perLine) * bh + 14;
    const rpPerLine = 8;
    s.text("Pull-ups für die Encoder, nicht bestückt (DNP), nur nötig ohne Pull-ups auf der Encoderplatine", 12, ry - 6, 2);
    for (let i = 0; i < Math.ceil(cols / 2); i++) {
      const c1 = 2 * i;
      const c2 = 2 * i + 1;
      const nets = {
        1: `M${c1 + 1}_A`, 2: `M${c1 + 1}_B`, 3: c2 < cols ? `M${c2 + 1}_A` : "NC", 4: c2 < cols ? `M${c2 + 1}_B` : "NC",
        8: "+3V3", 7: "+3V3", 6: c2 < cols ? "+3V3" : "NC", 5: c2 < cols ? "+3V3" : "NC",
      };
      s.place(PARTS.RPACK, 30 + (i % rpPerLine) * 55, ry + 12 + Math.floor(i / rpPerLine) * 28, R((j) => refs.rpack(j, i)), nets, pwrBase, { dnp: true });
    }

    const w = Math.max(100 + K * pitch, 12 + perLine * bw, 30 + Math.min(rpPerLine, Math.ceil(cols / 2)) * 55);
    const h = ry + 12 + Math.ceil(Math.ceil(cols / 2) / rpPerLine) * 28 + 10;
    return { sheet: s, w, h, nets595, nets165 };
  }

  // Versorgungssymbol mit PWR_FLAG daneben, verbunden über einen kurzen Draht
  function flag(s, net, x, y) {
    x = sn(x);
    y = sn(y);
    s.power(net, x, y, () => "0");
    s.wire(x, y, x + 7.62, y);
    s.power("FLAG", x + 7.62, y, () => "0");
  }

  // ── Wurzelblatt ─────────────────────────────────────────────
  function buildRoot(P, project, uuid, rootUuid, sheetUuids) {
    const s = new Sheet(project, uuid, [`/${rootUuid}`]);
    s.fileUuid = rootUuid;
    const one = (ref) => () => ref;
    const pw = () => "0";

    s.text("Blindsight Motormatrix", 20, 20, 3);
    s.text(`${P.rows} x ${P.cols} Motoren N20 mit Encoder, je Motor ein DRV8220, Steuerung über Schieberegister`, 20, 26, 1.8);

    // Versorgung
    s.text("Versorgung 12 V", 20, 40, 2);
    s.place(PARTS.POWER_IN, 25, 58, one("J1"), { 1: "VIN", 2: "GND" }, pw);
    s.placeTwo("F", 52, 58, one("F1"), "Sicherung", "VIN", "+12V", pw);
    s.placeTwo("CP", 72, 58, one("C1"), "1000u 25V", "+12V", "GND", pw);
    flag(s, "+12V", 90, 50);
    flag(s, "GND", 90, 66);

    s.text("3,3 V für Logik und Encoder", 20, 86, 2);
    s.place(PARTS.BUCK, 35, 102, one("J3"), { 1: "+12V", 2: "GND", 3: "+3V3", 4: "GND" }, pw);
    s.placeTwo("C", 68, 102, one("C2"), "100u", "+3V3", "GND", pw, "Capacitor_SMD:C_1206_3216Metric");
    flag(s, "+3V3", 90, 96);

    s.text("Anschluss ESP32, 7 Signale und GND", 20, 126, 2);
    s.place(PARTS.CTRL, 30, 148, one("J2"), {
      1: "GND", 2: "SCK_O", 3: "MOSI", 4: "LATCH", 5: "OE_N", 6: "SCK_I", 7: "MISO", 8: "LOAD_N",
    }, pw);
    s.placeTwo("R", 70, 148, one("R1"), "10k", "+3V3", "OE_N", pw);
    s.text("R1 hält OE_N beim Start hoch, alle Treiber bleiben aus", 20, 168, 1.5);

    // Reihenblätter
    const sw = sn(40);
    const sh = sn(22.86);
    const perCol = 7;
    const pinsL = [["SCK_O", "input"], ["LATCH", "input"], ["OE_N", "input"], ["SCK_I", "input"], ["LOAD_N", "input"], ["DOUT_IN", "input"], ["DIN_OUT", "output"]];
    const pinsR = [["DOUT_NEXT", "output"], ["DIN_NEXT", "input"]];
    for (let r = 0; r < P.rows; r++) {
      const sx = sn(140 + Math.floor(r / perCol) * 100);
      const sy = sn(30 + (r % perCol) * (sh + 10));
      const id = sheetUuids[r];
      const pinText = [];
      pinsL.forEach(([name, kind], i) => {
        const py = sy + 2.54 * (i + 1);
        pinText.push(`    (pin ${q(name)} ${kind} (at ${num(sx)} ${num(py)} 180) ${fx("left")}\n      (uuid ${q(uuid())})\n    )`);
        let net = name === "DOUT_IN" ? (r === 0 ? "MOSI" : `DKETTE_${r}`) : name === "DIN_OUT" ? (r === 0 ? "MISO" : `IKETTE_${r}`) : name;
        s.connect(sx, py, "L", net, pw);
      });
      pinsR.forEach(([name, kind], i) => {
        const py = sy + 2.54 * (i + 1);
        pinText.push(`    (pin ${q(name)} ${kind} (at ${num(sx + sw)} ${num(py)} 0) ${fx("right")}\n      (uuid ${q(uuid())})\n    )`);
        let net;
        if (name === "DOUT_NEXT") net = r === P.rows - 1 ? "NC" : `DKETTE_${r + 1}`;
        else net = r === P.rows - 1 ? "GND" : `IKETTE_${r + 1}`;
        s.connect(sx + sw, py, "R", net, pw);
      });
      s.items.push(`  (sheet (at ${num(sx)} ${num(sy)}) (size ${sw} ${sh}) (fields_autoplaced)
    (stroke (width 0.1524) (type solid))
    (fill (color 0 0 0 0.0000))
    (uuid ${q(id)})
    (property "Sheetname" ${q(`Reihe ${r + 1}`)} (at ${num(sx)} ${num(sy - 0.7116)} 0)
      ${fx("left bottom")}
    )
    (property "Sheetfile" ${q(ROW_FILE)} (at ${num(sx)} ${num(sy + sh + 0.5846)} 0)
      ${fx("left top")}
    )
${pinText.join("\n")}
    (instances
      (project ${q(project)}
        (path ${q("/" + rootUuid)} (page ${q(String(r + 2))}))
      )
    )
  )`);
    }
    const w = 140 + Math.ceil(P.rows / perCol) * 100;
    const h = Math.max(175, 30 + Math.min(P.rows, perCol) * (sh + 10) + 10);
    return { sheet: s, w, h };
  }

  // ── Alles zusammen ──────────────────────────────────────────
  function generate(opts = {}) {
    const rows = Number(opts.rows ?? 14);
    const cols = Number(opts.cols ?? 14);
    const project = opts.project || "blindsight_motormatrix";
    const P = plan(rows, cols);
    const uuid = uuidMaker(rows * 1000 + cols);
    const rootUuid = uuid();
    const sheetUuids = Array.from({ length: rows }, () => uuid());
    const rowPaths = sheetUuids.map((id) => `/${rootUuid}/${id}`);

    const row = buildRowSheet(P, project, uuid, rowPaths);
    const rootS = buildRoot(P, project, uuid, rootUuid, sheetUuids);

    const libsFor = (sheet) => [...sheet.libs].sort().map((lib) => {
      const part = Object.values(PARTS).find((p) => p.lib === lib);
      if (part) return libIC(part);
      const two = Object.entries(TWO_PIN).find(([, t]) => t.lib === lib);
      if (two) return libTwoPin(two[0]);
      const pw = Object.entries(POWER).find(([, l]) => l === lib);
      return libPower(pw[0]);
    }).join("\n");

    const rowText = row.sheet.file(paperFor(row.w, row.h), libsFor(row.sheet));
    const rootText = rootS.sheet.file(paperFor(rootS.w, rootS.h), libsFor(rootS.sheet), `
  (sheet_instances
    (path "/" (page "1"))
  )`);
    const pro = JSON.stringify({
      meta: { filename: `${project}.kicad_pro`, version: 1 },
      sheets: [[rootUuid, ""], ...sheetUuids.map((id, r) => [id, `Reihe ${r + 1}`])],
    }, null, 2) + "\n";

    return {
      plan: P,
      files: [
        { name: `${project}.kicad_pro`, text: pro },
        { name: `${project}.kicad_sch`, text: rootText },
        { name: ROW_FILE, text: rowText },
      ],
      bom: bom(P),
    };
  }

  function bom(P) {
    const c = P.count;
    return [
      { ref: "U x01 bis x40", what: "Motortreiber DRV8220DRL", qty: c.drivers, fp: PARTS.DRV8220.footprint, how: "JLCPCB" },
      { ref: "U x51 ...", what: "Schieberegister 74HC595", qty: c.sr595, fp: PARTS.HC595.footprint, how: "JLCPCB" },
      { ref: "U x71 ...", what: "Schieberegister 74HC165", qty: c.sr165, fp: PARTS.HC165.footprint, how: "JLCPCB" },
      { ref: "U x50", what: "Puffer 74HC244", qty: c.buffers, fp: PARTS.HC244.footprint, how: "JLCPCB" },
      { ref: "C x01 ...", what: "100 nF 25 V an VM", qty: c.capsVm, fp: TWO_PIN.C.footprint, how: "JLCPCB" },
      { ref: "C x50 ...", what: "100 nF an Logik", qty: c.capsLogic, fp: TWO_PIN.C.footprint, how: "JLCPCB" },
      { ref: "C x90", what: "22 µF 25 V je Reihe", qty: P.rows, fp: "Capacitor_SMD:C_1206_3216Metric", how: "JLCPCB" },
      { ref: "C x91", what: "10 µF je Reihe", qty: P.rows, fp: "Capacitor_SMD:C_0805_2012Metric", how: "JLCPCB" },
      { ref: "RN", what: "10 kΩ Array, nicht bestücken (DNP)", qty: c.rpacks, fp: PARTS.RPACK.footprint, how: "nur bei Bedarf" },
      { ref: "J x01 ...", what: "Lötpads je Motor (6 Löcher)", qty: c.pads, fp: PARTS.MOTOR.footprint, how: "Kabel von Hand" },
      { ref: "J1", what: "Schraubklemme 12 V", qty: 1, fp: PARTS.POWER_IN.footprint, how: "von Hand" },
      { ref: "F1", what: "Flachsicherung mit Halter", qty: 1, fp: TWO_PIN.F.footprint, how: "von Hand" },
      { ref: "C1", what: "1000 µF 25 V Elko", qty: 1, fp: TWO_PIN.CP.footprint, how: "von Hand" },
      { ref: "J3", what: "Buck Modul 12 V auf 3,3 V", qty: 1, fp: PARTS.BUCK.footprint, how: "von Hand" },
      { ref: "C2", what: "100 µF an 3,3 V", qty: 1, fp: "Capacitor_SMD:C_1206_3216Metric", how: "JLCPCB" },
      { ref: "R1", what: "10 kΩ Pull-up an OE_N", qty: 1, fp: TWO_PIN.R.footprint, how: "JLCPCB" },
      { ref: "J2", what: "Stiftleiste 1x8 zum ESP32", qty: 1, fp: PARTS.CTRL.footprint, how: "von Hand" },
    ];
  }

  // ── ZIP ohne Kompression (für den Download im Browser) ─────
  function crc32(bytes) {
    let c;
    const table = crc32.t || (crc32.t = Array.from({ length: 256 }, (_, n) => {
      c = n;
      for (let k = 0; k < 8; k++) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1;
      return c >>> 0;
    }));
    let crc = 0xffffffff;
    for (const b of bytes) crc = table[(crc ^ b) & 0xff] ^ (crc >>> 8);
    return (crc ^ 0xffffffff) >>> 0;
  }

  function zip(files) {
    const enc = new TextEncoder();
    const parts = [];
    const central = [];
    let offset = 0;
    const u16 = (v) => [v & 0xff, (v >>> 8) & 0xff];
    const u32 = (v) => [v & 0xff, (v >>> 8) & 0xff, (v >>> 16) & 0xff, (v >>> 24) & 0xff];
    for (const f of files) {
      const name = enc.encode(f.name);
      const data = enc.encode(f.text);
      const crc = crc32(data);
      const head = [...u32(0x04034b50), ...u16(20), ...u16(0x0800), ...u16(0), ...u16(0), ...u16(0x21),
        ...u32(crc), ...u32(data.length), ...u32(data.length), ...u16(name.length), ...u16(0)];
      parts.push(new Uint8Array(head), name, data);
      central.push([...u32(0x02014b50), ...u16(20), ...u16(20), ...u16(0x0800), ...u16(0), ...u16(0), ...u16(0x21),
        ...u32(crc), ...u32(data.length), ...u32(data.length), ...u16(name.length), ...u16(0), ...u16(0), ...u16(0),
        ...u16(0), ...u32(0), ...u32(offset)], name);
      offset += head.length + name.length + data.length;
    }
    let size = 0;
    const centralParts = [];
    for (let i = 0; i < central.length; i += 2) {
      const h = new Uint8Array(central[i]);
      centralParts.push(h, central[i + 1]);
      size += h.length + central[i + 1].length;
    }
    const end = new Uint8Array([...u32(0x06054b50), ...u16(0), ...u16(0), ...u16(files.length), ...u16(files.length),
      ...u32(size), ...u32(offset), ...u16(0)]);
    return new Blob([...parts, ...centralParts, end], { type: "application/zip" });
  }

  const api = { generate, plan, bom, zip, crc32, PARTS, MAX_SIDE };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else root.MotorMatrix = api;
})(typeof window !== "undefined" ? window : globalThis);
