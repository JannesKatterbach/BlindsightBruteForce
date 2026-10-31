"use strict";
// Motor sketch. Relations and dimensions like Onshape. Select first and click a relation, or click the relation
// first and then the elements (the tool stays active). The dimension tool measures one or two elements, the
// text is placed with the mouse and the value typed in.

(() => {
  const typeInfo = (type) => (schema.sketch_constraints || []).find((t) => t.name === type);

  /** References sorted to a signature of the type, or null if the elements do not fit. */
  function fits(type, refs) {
    const info = typeInfo(type);
    if (!info || new Set(refs).size !== refs.length) return null;
    const kinds = refs.map(Sketch.kindOf);
    for (const sig of info.signatures) {
      if (sig.length !== refs.length) continue;
      if (sig.every((k, i) => k === kinds[i])) return refs.slice();
      if (refs.length === 2 && sig.every((k, i) => k === kinds[1 - i])) return refs.slice().reverse();
    }
    return null;
  }

  /** Constraints a relation creates for a selection (several lines at once like Onshape), or null. */
  function planRelation(type, refs) {
    const lines = refs.filter((r) => Sketch.kindOf(r) === "line");
    const points = refs.filter((r) => Sketch.kindOf(r) === "point");
    if ((type === "horizontal" || type === "vertical") && lines.length && lines.length === refs.length) return lines.map((r) => [r]);
    if (type === "fix" && points.length && points.length === refs.length) return points.filter((r) => r !== "o").map((r) => [r]);
    if (["parallel", "perpendicular", "equal"].includes(type) && refs.length > 2 && refs.every((r) => Sketch.kindOf(r) === Sketch.kindOf(refs[0]))) {
      return refs.slice(1).map((r) => fits(type, [refs[0], r])).every(Boolean) ? refs.slice(1).map((r) => [refs[0], r]) : null;
    }
    if (type === "coincident" && refs.length > 2 && points.length === refs.length) return refs.slice(1).map((r) => [refs[0], r]);
    const single = fits(type, refs);
    return single ? [single] : null;
  }

  function addRelations(type, plan) {
    return Sketch.commit((sk) => {
      plan.forEach((refs) => {
        const at = type === "fix" ? Sketch.point(refs[0]).slice() : null;
        sk.constraints.push(makeConstraint(type, refs, { at }));
      });
    });
  }

  /** Toolbar click on a relation. Apply to the selection or arm the tool and collect clicks. */
  function relation(type) {
    const refs = [...SK.sel].filter((r) => r[0] !== "c");
    const plan = refs.length ? planRelation(type, refs) : null;
    if (plan) {
      SK.sel.clear();
      addRelations(type, plan);
      return;
    }
    Sketch.setTool(type);
    SK.pick = refs;
    SK.sel.clear();
    Sketch.renderAll();
  }

  /** A click while a relation tool is armed. */
  function pickForRelation(ref) {
    const i = SK.pick.indexOf(ref);
    if (i >= 0) SK.pick.splice(i, 1);
    else SK.pick.push(ref);
    const plan = fits(SK.tool, SK.pick);
    if (plan) {
      const type = SK.tool;
      SK.pick = [];
      addRelations(type, [plan]);
      return;
    }
    if (SK.pick.length >= 2) SK.pick = [ref];  // the elements do not fit, start again with the last one
    Sketch.renderAll();
  }

  // --- Dimensions --------------------------------------------------------------------------------------------
  const parallelLines = (a, b) => {
    const [p, q] = Sketch.ends(Sketch.entityIndex(a)), [r, s] = Sketch.ends(Sketch.entityIndex(b));
    const d1 = [q[0] - p[0], q[1] - p[1]], d2 = [s[0] - r[0], s[1] - r[1]];
    return Math.abs(d1[0] * d2[1] - d1[1] * d2[0]) < 1e-6 * (Math.hypot(...d1) * Math.hypot(...d2) || 1);
  };

  /** Type of the dimension for the picked elements, or null. */
  function dimensionFor(refs) {
    const kinds = refs.map(Sketch.kindOf);
    if (refs.length === 1) {
      if (kinds[0] === "line") return { type: "length", refs };
      if (kinds[0] === "curve") return { type: SK.sk.entities[Sketch.entityIndex(refs[0])].type === "arc" ? "radius" : "diameter", refs };
      return null;
    }
    if (kinds.includes("curve")) return null;
    if (kinds[0] === "line" && kinds[1] === "line") return { type: parallelLines(refs[0], refs[1]) ? "distance" : "angle", refs };
    if (kinds[0] === "line") return { type: "distance", refs: [refs[1], refs[0]] };
    return { type: "distance", refs };
  }

  /** A click on an element with the dimension tool. */
  function pickForDimension(ref) {
    if (SK.pick.includes(ref)) return;
    const refs = SK.pick.length === 1 ? [SK.pick[0], ref] : [ref];
    let dim = dimensionFor(refs);
    if (!dim) { SK.pick = [ref]; dim = dimensionFor([ref]); }
    else SK.pick = refs;
    SK.dimPlace = dim;
    Sketch.renderAll();
  }

  /** Distance between two points measured horizontally or vertically when the text lies beside them. */
  function placedType(dim, label) {
    if (dim.type !== "distance") return dim.type;
    const kinds = dim.refs.map(Sketch.kindOf);
    if (kinds[0] !== "point" || kinds[1] !== "point") return dim.type;
    const a = Sketch.point(dim.refs[0]), b = Sketch.point(dim.refs[1]);
    const inX = label[0] > Math.min(a[0], b[0]) && label[0] < Math.max(a[0], b[0]);
    const inY = label[1] > Math.min(a[1], b[1]) && label[1] < Math.max(a[1], b[1]);
    if (inX && !inY) return "hdistance";
    if (inY && !inX) return "vdistance";
    return "distance";
  }

  /** Click on free space while a dimension waits for its position. Ask for the value and add it. */
  function placeDimension(label) {
    const dim = SK.dimPlace;
    if (!dim) return false;
    const type = placedType(dim, label);
    const current = Sketch.measure(type, dim.refs);
    SK.dimPlace = null;
    SK.pick = [];
    askValue(t(`ui.sk.dim.${type}`), type === "angle" ? fmtDeg(current) : fmtLen(current), label, (value) => {
      Sketch.commit((sk) => { sk.constraints.push(makeConstraint(type, dim.refs, { value, label })); });
    });
    Sketch.renderAll();
    return true;
  }

  /** Change the value of dimension k (double click on its text). */
  function editDimension(k) {
    const c = SK.sk.constraints[k];
    if (!c || c.value === null) return;
    askValue(typeInfo(c.type) ? typeInfo(c.type).label : c.type, c.type === "angle" ? fmtDeg(c.value) : fmtLen(c.value), c.label || Sketch.defaultLabel(c), (value) => {
      Sketch.commit((sk) => { sk.constraints[k].value = value; });
    });
  }

  /** Input field at the position at (mm) of the drawing. Enter accepts, Esc or leaving cancels. */
  function askValue(label, initial, at, onValue) {
    const input = $("#skInput"), v = SK.view, [W, H] = Sketch.canvasSize();
    const sx = (at[0] - v.cx) / v.k + W / 2, sy = -(at[1] - v.cy) / v.k + H / 2;
    input.hidden = false;
    input.value = initial;
    input.title = label;
    input.placeholder = label;
    input.style.left = Math.max(4, Math.min(W - 110, sx - 48)) + "px";
    input.style.top = Math.max(4, Math.min(H - 30, sy - 14)) + "px";
    const done = (accept) => {
      input.hidden = true;
      input.onkeydown = null;
      input.onblur = null;
      if (!accept) { Sketch.renderAll(); return; }
      const value = parseFloat(String(input.value).replace(",", "."));
      if (Number.isFinite(value)) onValue(value);
    };
    input.onkeydown = (e) => {
      if (e.key === "Enter") { e.preventDefault(); done(true); } else if (e.key === "Escape") { e.preventDefault(); done(false); }
    };
    // Focus after the mouse down of this click, its default action would blur the field again
    setTimeout(() => {
      if (input.hidden) return;
      input.focus();
      input.select();
      input.onblur = () => done(false);
    }, 0);
  }

  Object.assign(Sketch, { fits, planRelation, relation, pickForRelation, pickForDimension, placeDimension, editDimension, askValue, typeInfo });
})();
