"use strict";
// Motor Skizze. Geometrie Hilfen fuer die Anzeige (gerechnet wird im Kern).

(() => {
  /** Punkt i (zyklisch). */
  const point = (i) => SK.sk.points[((i % skCount()) + skCount()) % skCount()];
  /** Richtung der Seite i (von Punkt i nach Punkt i+1). */
  const sideVec = (i) => { const a = point(i), b = point(i + 1); return [b[0] - a[0], b[1] - a[1]]; };
  const sideLen = (i) => Math.hypot(...sideVec(i));
  const sideMid = (i) => { const a = point(i), b = point(i + 1); return [(a[0] + b[0]) / 2, (a[1] + b[1]) / 2]; };

  /** Innenwinkel an Punkt i in Grad (0 bis 360). */
  function interiorAngle(i) {
    const q = point(i), p = point(i - 1), r = point(i + 1);
    const a = [p[0] - q[0], p[1] - q[1]], b = [r[0] - q[0], r[1] - q[1]];
    const angle = Math.atan2(b[0] * a[1] - b[1] * a[0], a[0] * b[0] + a[1] * b[1]) * 180 / Math.PI;
    return angle >= 0 ? angle : angle + 360;
  }

  /** Winkel zwischen den Richtungen zweier Seiten in Grad (0 bis 180). */
  function angleBetweenSides(a, b) {
    const da = sideVec(a), db = sideVec(b);
    return Math.abs(Math.atan2(da[0] * db[1] - da[1] * db[0], da[0] * db[0] + da[1] * db[1])) * 180 / Math.PI;
  }

  /** Abstand eines Punktes zu einem konvexen Polygon (0 innerhalb). */
  function distancePointPolygon(px, py, poly) {
    let inside = true, best = Infinity;
    for (let i = 0; i < poly.length; i++) {
      const a = poly[i], b = poly[(i + 1) % poly.length];
      if ((b[0] - a[0]) * (py - a[1]) - (b[1] - a[1]) * (px - a[0]) < 0) inside = false;
      const dx = b[0] - a[0], dy = b[1] - a[1], l2 = dx * dx + dy * dy;
      const t = l2 ? Math.max(0, Math.min(1, ((px - a[0]) * dx + (py - a[1]) * dy) / l2)) : 0;
      best = Math.min(best, Math.hypot(px - (a[0] + t * dx), py - (a[1] + t * dy)));
    }
    return inside ? 0 : best;
  }

  /** Lotabstand einer Referenz zur Geraden durch Seite i. */
  function distanceSideRef(i, ref) {
    const a = point(i), d = sideVec(i), L = sideLen(i) || 1, r = refPos(ref);
    return Math.abs((d[0] * (r[1] - a[1]) - d[1] * (r[0] - a[0])) / L);
  }

  /** Position einer Referenz (Stange im Ursprung, Zahnrad bei (-Achsabstand, 0)). */
  const refPos = (ref) => (ref === "gear" ? [-cfg.motor.center_distance, 0] : [0, 0]);

  /** Zahnrad als Rechteck im Stangenrahmen. */
  function gearBox() {
    const m = cfg.motor, r = m.gear_diameter / 2, h = m.gear_width / 2, cd = m.center_distance;
    return [[-cd - r, -h], [-cd + r, -h], [-cd + r, h], [-cd - r, h]];
  }

  /** Abstand Gehaeuse zur Stangenoberflaeche. */
  const housingClearance = () => distancePointPolygon(0, 0, SK.sk.points) - cfg.rod.diameter / 2;

  /** Seite, deren Endpunkte die beiden Punkte sind, sonst null. */
  function adjacentSide(points) {
    const [a, b] = [...points].sort((x, y) => x - y);
    if (b === a + 1) return a;
    if (a === 0 && b === skCount() - 1) return b;
    return null;
  }

  /** Naechste Seite zum Punkt (mx, my) innerhalb von 9 Bildschirmpixeln, mit Parameter t auf der Seite. */
  function nearestSide(mx, my) {
    let best = null;
    for (let i = 0; i < skCount(); i++) {
      const a = point(i), d = sideVec(i), l2 = d[0] * d[0] + d[1] * d[1] || 1;
      const t = Math.max(0, Math.min(1, ((mx - a[0]) * d[0] + (my - a[1]) * d[1]) / l2));
      const dist = Math.hypot(mx - (a[0] + t * d[0]), my - (a[1] + t * d[1]));
      if (dist < 9 * SK.view.k && (!best || dist < best.dist)) best = { i, t, dist };
    }
    return best;
  }

  Object.assign(Sketch, {
    point, sideVec, sideLen, sideMid, interiorAngle, angleBetweenSides, distancePointPolygon, distanceSideRef, refPos,
    gearBox, housingClearance, adjacentSide, nearestSide,
  });
})();
