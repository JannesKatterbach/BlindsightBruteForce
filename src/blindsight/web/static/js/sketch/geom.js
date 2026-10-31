"use strict";
// Motor sketch. Geometry of points and entities, hit testing and inference for the display (the core solves).

(() => {
  const entityIndex = (ref) => +ref.slice(1);
  const isPointRef = (ref) => ref === "o" || ref[0] === "p" || (ref[0] === "e" && SK.sk.entities[entityIndex(ref)] && SK.sk.entities[entityIndex(ref)].type === "point");

  /** Position of a point reference (point, point entity or origin). */
  function point(ref) {
    if (ref === "o") return [0, 0];
    let i = entityIndex(ref);
    if (ref[0] === "e") i = SK.sk.entities[i].points[0];
    return SK.sk.points[i];
  }

  /** Kind of a reference like in the core. point, line or curve (circle or arc). */
  function kindOf(ref) {
    if (isPointRef(ref)) return "point";
    const e = SK.sk.entities[entityIndex(ref)];
    return e ? (e.type === "line" ? "line" : "curve") : null;
  }

  const ends = (k) => SK.sk.entities[k].points.map((p) => SK.sk.points[p]);

  /** Centre and radius of a circle or arc. */
  function curve(k) {
    const e = SK.sk.entities[k];
    const c = SK.sk.points[e.points[0]];
    if (e.type === "circle") return { c, r: e.radius };
    const s = SK.sk.points[e.points[1]];
    return { c, r: Math.hypot(s[0] - c[0], s[1] - c[1]) };
  }

  /** Start and sweep angle (radians, counter clockwise) of an arc. */
  function arcAngles(k) {
    const [c, s, t] = SK.sk.entities[k].points.map((p) => SK.sk.points[p]);
    const a0 = Math.atan2(s[1] - c[1], s[0] - c[0]);
    const a1 = Math.atan2(t[1] - c[1], t[0] - c[0]);
    let sweep = (a1 - a0) % (2 * Math.PI);
    if (sweep <= 0) sweep += 2 * Math.PI;
    return { a0, sweep };
  }

  const midpoint = (a, b) => [(a[0] + b[0]) / 2, (a[1] + b[1]) / 2];
  const lineLength = (k) => { const [a, b] = ends(k); return Math.hypot(b[0] - a[0], b[1] - a[1]); };

  /** Distance of p to the segment a b and the parameter of the foot point. */
  function segmentDistance(p, a, b) {
    const dx = b[0] - a[0], dy = b[1] - a[1], l2 = dx * dx + dy * dy || 1;
    const t = Math.max(0, Math.min(1, ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / l2));
    return { d: Math.hypot(p[0] - a[0] - t * dx, p[1] - a[1] - t * dy), t };
  }

  /** Distance of p to an entity (lines as segments, arcs only within their sweep). */
  function entityDistance(k, p) {
    const e = SK.sk.entities[k];
    if (e.type === "line") { const [a, b] = ends(k); return segmentDistance(p, a, b).d; }
    if (e.type === "point") return Math.hypot(p[0] - point(`e${k}`)[0], p[1] - point(`e${k}`)[1]);
    const { c, r } = curve(k);
    const d = Math.abs(Math.hypot(p[0] - c[0], p[1] - c[1]) - r);
    if (e.type === "circle") return d;
    const { a0, sweep } = arcAngles(k);
    let a = Math.atan2(p[1] - c[1], p[0] - c[0]) - a0;
    a = ((a % (2 * Math.PI)) + 2 * Math.PI) % (2 * Math.PI);
    return a <= sweep ? d : Infinity;
  }

  /** Entity that owns a point. */
  function ownerOf(pointIndex) {
    return SK.sk.entities.findIndex((e) => e.points.includes(pointIndex));
  }

  /**
   * What lies under the mouse at p (mm). Points first (also the origin and the centres of circles), then
   * entities. Returns a reference ("p3", "e2", "o") or null. skip excludes points (e.g. the dragged one).
   */
  function hit(p, skip = new Set()) {
    const k = SK.view.k;
    let best = null, bestD = SK_POINT_PX * k;
    SK.sk.points.forEach((q, i) => {
      if (skip.has(`p${i}`)) return;
      const d = Math.hypot(p[0] - q[0], p[1] - q[1]);
      if (d < bestD) { best = `p${i}`; bestD = d; }
    });
    if (!skip.has("o") && Math.hypot(p[0], p[1]) < bestD) { best = "o"; bestD = Math.hypot(p[0], p[1]); }
    if (best) {  // a sketch point entity is selected as the entity
      const owner = best[0] === "p" ? ownerOf(+best.slice(1)) : -1;
      return owner >= 0 && SK.sk.entities[owner].type === "point" ? `e${owner}` : best;
    }
    bestD = SK_CURVE_PX * k;
    SK.sk.entities.forEach((e, i) => {
      if (e.type === "point" || skip.has(`e${i}`)) return;
      const d = entityDistance(i, p);
      if (d < bestD) { best = `e${i}`; bestD = d; }
    });
    return best;
  }

  /**
   * Inference while drawing (like Onshape). Snap to existing points and the origin (coincident), else to
   * lines and curves (point on it), else to the grid. Returns {x, y, ref, kind}.
   */
  function infer(p, skip = new Set()) {
    const k = SK.view.k;
    let best = null, bestD = SK_SNAP_PX * k;
    const consider = (ref, q, kind) => {
      const d = Math.hypot(p[0] - q[0], p[1] - q[1]);
      if (d < bestD) { best = { x: q[0], y: q[1], ref, kind }; bestD = d; }
    };
    SK.sk.points.forEach((q, i) => { if (!skip.has(`p${i}`)) consider(`p${i}`, q, "point"); });
    consider("o", [0, 0], "point");
    if (best) return best;
    SK.sk.entities.forEach((e, i) => {
      if (e.type === "point" || skip.has(`e${i}`)) return;
      if (entityDistance(i, p) >= bestD) return;
      if (e.type === "line") {
        const [a, b] = ends(i), { t } = segmentDistance(p, a, b);
        consider(`e${i}`, [a[0] + t * (b[0] - a[0]), a[1] + t * (b[1] - a[1])], "on");
      } else {
        const { c, r } = curve(i), d = Math.hypot(p[0] - c[0], p[1] - c[1]) || 1;
        consider(`e${i}`, [c[0] + ((p[0] - c[0]) * r) / d, c[1] + ((p[1] - c[1]) * r) / d], "on");
      }
    });
    if (best) return best;
    const grid = parseFloat($("#skSnap").value);
    const s = (v) => (grid > 0 ? Math.round(v / grid) * grid : v);
    return { x: s(p[0]), y: s(p[1]), ref: null, kind: null };
  }

  /** Horizontal or vertical inference for a line from a to b, or null. */
  function axisInference(a, b) {
    const ang = (Math.atan2(Math.abs(b[1] - a[1]), Math.abs(b[0] - a[0])) * 180) / Math.PI;
    if (Math.hypot(b[0] - a[0], b[1] - a[1]) < SK_EPS) return null;
    if (ang < SK_AXIS_SNAP_DEG) return "horizontal";
    if (ang > 90 - SK_AXIS_SNAP_DEG) return "vertical";
    return null;
  }

  /** Angle in degrees (0 to 180) between two lines as the core measures it (corner if the ends are coincident). */
  function lineAngle(a, b) {
    const ea = SK.sk.entities[entityIndex(a)].points.map((p) => `p${p}`), eb = SK.sk.entities[entityIndex(b)].points.map((p) => `p${p}`);
    let i = 0, j = 0;
    for (const c of SK.sk.constraints) {
      if (c.type !== "coincident" || !c.enabled || c.refs.length !== 2) continue;
      for (let x = 0; x < 2; x++) for (let y = 0; y < 2; y++) if (new Set(c.refs).has(ea[x]) && new Set(c.refs).has(eb[y])) { i = x; j = y; }
    }
    const la = ends(entityIndex(a)), lb = ends(entityIndex(b));
    const d1 = [la[1 - i][0] - la[i][0], la[1 - i][1] - la[i][1]], d2 = [lb[1 - j][0] - lb[j][0], lb[1 - j][1] - lb[j][1]];
    return (Math.abs(Math.atan2(d1[0] * d2[1] - d1[1] * d2[0], d1[0] * d2[0] + d1[1] * d2[1])) * 180) / Math.PI;
  }

  /** Corner of two lines for the angle display (common end or intersection of their lines). */
  function lineIntersection(a, b) {
    const [p, q] = ends(entityIndex(a)), [r, s] = ends(entityIndex(b));
    const d1 = [q[0] - p[0], q[1] - p[1]], d2 = [s[0] - r[0], s[1] - r[1]];
    const den = d1[0] * d2[1] - d1[1] * d2[0];
    if (Math.abs(den) < SK_EPS) return midpoint(midpoint(p, q), midpoint(r, s));
    const t = ((r[0] - p[0]) * d2[1] - (r[1] - p[1]) * d2[0]) / den;
    return [p[0] + t * d1[0], p[1] + t * d1[1]];
  }

  /** Signed distance of point p to the line through entity k (positive left of start -> end). */
  function pointLineDistance(p, k) {
    const [a, b] = ends(k), d = [b[0] - a[0], b[1] - a[1]], n = Math.hypot(...d) || 1;
    return (d[0] * (p[1] - a[1]) - d[1] * (p[0] - a[0])) / n;
  }

  /** Current value of a dimension (mm or degrees), measured on the drawing. */
  function measure(type, refs) {
    if (type === "length") return lineLength(entityIndex(refs[0]));
    if (type === "diameter") return 2 * curve(entityIndex(refs[0])).r;
    if (type === "radius") return curve(entityIndex(refs[0])).r;
    if (type === "angle") return lineAngle(refs[0], refs[1]);
    const kinds = refs.map(kindOf);
    if (type === "hdistance") return Math.abs(point(refs[1])[0] - point(refs[0])[0]);
    if (type === "vdistance") return Math.abs(point(refs[1])[1] - point(refs[0])[1]);
    if (kinds[0] === "point" && kinds[1] === "point") { const a = point(refs[0]), b = point(refs[1]); return Math.hypot(b[0] - a[0], b[1] - a[1]); }
    if (kinds[0] === "point") return Math.abs(pointLineDistance(point(refs[0]), entityIndex(refs[1])));
    if (kinds[1] === "point") return Math.abs(pointLineDistance(point(refs[1]), entityIndex(refs[0])));
    const [a, b] = ends(entityIndex(refs[1]));
    return Math.abs(pointLineDistance(midpoint(a, b), entityIndex(refs[0])));
  }

  /** Bounding box of all geometry (for fitting the view). */
  function bounds() {
    const pts = [[0, 0]];
    SK.sk.entities.forEach((e, k) => {
      if (e.type === "circle") { const { c, r } = curve(k); pts.push([c[0] - r, c[1] - r], [c[0] + r, c[1] + r]); }
      else e.points.forEach((p) => pts.push(SK.sk.points[p]));
    });
    SK.sk.constraints.forEach((c) => { if (c.label) pts.push(c.label); });  // dimension texts stay in view
    const xs = pts.map((p) => p[0]), ys = pts.map((p) => p[1]);
    return { x0: Math.min(...xs), y0: Math.min(...ys), x1: Math.max(...xs), y1: Math.max(...ys) };
  }

  Object.assign(Sketch, {
    entityIndex, isPointRef, point, kindOf, ends, curve, arcAngles, midpoint, lineLength, segmentDistance, entityDistance, ownerOf,
    hit, infer, axisInference, lineAngle, lineIntersection, pointLineDistance, measure, bounds,
  });
})();
