FeatureScript 3112;
import(path : "onshape/std/common.fs", version : "3112.0");

// Project Blindsight, variant with a rotating tube (docs/MOTORVARIANTE_ROHR.md).
// One unit per grid point. A threaded rod M4 with two flats (double D) is guided against rotation in a
// fixed bush in G0. A tube with two M4 nuts in a hex pocket at its top turns on a flanged bearing
// MF128ZZ in the bearing plate and is driven from below by an N20 gearmotor through a D bore (torque
// only, the axial force goes into the bearing). z = 0 is the top face of G0, all sizes in millimetres.
// The threads are shown as plain cylinders. All values except the feature parameters are preliminary
// design assumptions and live in RB_DIMS.

const RB_DIMS = {
        "rodD" : 4.0, "flatW" : 3.4, "flatClear" : 0.05,
        "g0T" : 6.0, "bushD" : 8.0, "bushL" : 10.0, "rotGap" : 1.2,
        "headD" : 10.0, "nutAF" : 7.0, "nutH" : 3.2, "nuts" : 2, "pocketExtra" : 0.3, "headFloor" : 1.0,
        "shimT" : 0.3, "shimOD" : 9.4,
        "bearID" : 8.0, "bearOD" : 12.0, "bearW" : 3.5, "flangeD" : 13.6, "flangeW" : 0.8, "bearPlateT" : 4.0,
        "ringID" : 7.6, "ringOD" : 10.4, "ringT" : 0.8,
        "tubeD" : 8.0, "boreD" : 5.0, "rodReserve" : 4.0, "boreBelowRod" : 2.0, "tubeFloor" : 8.0,
        "shaftD" : 3.0, "shaftFlat" : 2.5, "shaftL" : 10.0, "shaftIn" : 6.0, "dBoreClear" : 0.05, "shaftPlay" : 0.5,
        "motorW" : 12.0, "motorH" : 10.0, "gearboxL" : 9.0, "canL" : 15.0, "encL" : 8.0, "pocketClear" : 0.1,
        "motorPlateT" : 8.0, "plateMargin" : 5.0, "spacerD" : 4.0, "spacerInset" : 3.0
    };

const RB_MM = millimeter;

annotation { "Feature Type Name" : "Rohrantrieb" }
export const rohrantrieb = defineFeature(function(context is Context, id is Id, definition is map)
    precondition
    {
        annotation { "Name" : "Hub oberhalb von G0" }
        isLength(definition.stroke, { (millimeter) : [5, 40, 500] } as LengthBoundSpec);

        annotation { "Name" : "Ausfahrstellung zur Ansicht" }
        isLength(definition.extension, { (millimeter) : [0, 0, 500] } as LengthBoundSpec);

        annotation { "Name" : "Raster" }
        isLength(definition.pitch, { (millimeter) : [10, 15, 200] } as LengthBoundSpec);

        annotation { "Name" : "Einheiten in x" }
        isInteger(definition.nx, { (unitless) : [1, 1, 20] } as IntegerBoundSpec);

        annotation { "Name" : "Einheiten in y" }
        isInteger(definition.ny, { (unitless) : [1, 1, 20] } as IntegerBoundSpec);

        annotation { "Name" : "Abstand messen und melden" }
        definition.check is boolean;
    }
    {
        const z = rbLevels(definition.stroke);
        const ext = min(definition.extension, definition.stroke);
        const pitch = definition.pitch;
        var centers = [];
        for (var j = 0; j < definition.ny; j += 1)
        {
            for (var i = 0; i < definition.nx; i += 1)
            {
                centers = append(centers, vector(i * pitch, j * pitch));
            }
        }
        const plates = rbPlates(context, id + "plates", z, centers, pitch, definition.nx, definition.ny);
        var units = [];
        for (var k = 0; k < size(centers); k += 1)
        {
            units = append(units, rbUnit(context, id + ("u" ~ k), z, centers[k], ext, k));
        }
        if (definition.check)
        {
            rbReport(context, id, plates, units);
        }
    }, { "stroke" : 40 * millimeter, "extension" : 20 * millimeter, "pitch" : 15 * millimeter, "nx" : 3, "ny" : 3, "check" : true });

/** Heights of all parts (z values in millimetres as lengths), derived from the stroke and RB_DIMS. */
function rbLevels(stroke is ValueWithUnits) returns map
{
    const d = RB_DIMS;
    var z = {};
    z.headTop = -(d.bushL + d.rotGap) * RB_MM;
    z.pocketBottom = z.headTop - (d.nuts * d.nutH + d.pocketExtra) * RB_MM;
    z.nutTop = z.headTop - 0.2 * RB_MM;
    z.nutBottom = z.nutTop - d.nuts * d.nutH * RB_MM;
    z.headBottom = z.pocketBottom - d.headFloor * RB_MM;
    z.bearTop = z.headBottom - d.shimT * RB_MM;
    z.bearBottom = z.bearTop - d.bearW * RB_MM;
    z.plateTop = z.bearTop - d.flangeW * RB_MM;
    z.plateBottom = z.plateTop - d.bearPlateT * RB_MM;
    z.ringTop = z.bearBottom - 0.1 * RB_MM;
    z.ringBottom = z.ringTop - d.ringT * RB_MM;
    z.rodLen = stroke - z.nutBottom + d.rodReserve * RB_MM;
    z.boreEnd = -z.rodLen - d.boreBelowRod * RB_MM;
    z.tubeBottom = z.boreEnd - d.tubeFloor * RB_MM;
    z.motorFace = z.tubeBottom - (d.shaftL - d.shaftIn) * RB_MM;
    z.motorPlateBottom = z.motorFace - d.motorPlateT * RB_MM;
    z.motorBottom = z.motorFace - (d.gearboxL + d.canL + d.encL) * RB_MM;
    z.flatLen = stroke + (d.bushL + 2) * RB_MM;
    return z;
}

// -- Geometry helpers ------------------------------------------------------------------------------------
function rbCyl(context is Context, id is Id, c is Vector, z0 is ValueWithUnits, z1 is ValueWithUnits, r is ValueWithUnits) returns Query
{
    fCylinder(context, id, { "bottomCenter" : vector(c[0], c[1], z0), "topCenter" : vector(c[0], c[1], z1), "radius" : r });
    return qCreatedBy(id, EntityType.BODY);
}

function rbBox(context is Context, id is Id, x0, y0, z0, x1, y1, z1) returns Query
{
    fCuboid(context, id, { "corner1" : vector(x0, y0, z0), "corner2" : vector(x1, y1, z1) });
    return qCreatedBy(id, EntityType.BODY);
}

/** Box centred on c with the given width in x and y. */
function rbCbox(context is Context, id is Id, c is Vector, wx is ValueWithUnits, wy is ValueWithUnits, z0 is ValueWithUnits, z1 is ValueWithUnits) returns Query
{
    return rbBox(context, id, c[0] - wx / 2, c[1] - wy / 2, z0, c[0] + wx / 2, c[1] + wy / 2, z1);
}

/** Hexagonal prism, width across flats af, flats parallel to x. */
function rbHex(context is Context, id is Id, c is Vector, z0 is ValueWithUnits, z1 is ValueWithUnits, af is ValueWithUnits) returns Query
{
    const sketch = newSketchOnPlane(context, id + "sk", { "sketchPlane" : plane(vector(c[0], c[1], z0), vector(0, 0, 1), vector(1, 0, 0)) });
    const r = af / sqrt(3);
    var points = [];
    for (var k = 0; k <= 6; k += 1)
    {
        const a = (30 + 60 * k) * degree;
        points = append(points, vector(r * cos(a), r * sin(a)));
    }
    skPolyline(sketch, "hex", { "points" : points });
    skSolve(sketch);
    opExtrude(context, id + "ex", { "entities" : qSketchRegion(id + "sk"), "direction" : vector(0, 0, 1),
                "endBound" : BoundingType.BLIND, "endDepth" : z1 - z0 });
    opDeleteBodies(context, id + "del", { "entities" : qCreatedBy(id + "sk") });
    return qCreatedBy(id + "ex", EntityType.BODY);
}

function rbSubtract(context is Context, id is Id, target is Query, tools is Query)
{
    opBoolean(context, id, { "targets" : target, "tools" : tools, "operationType" : BooleanOperationType.SUBTRACTION });
}

function rbUnite(context is Context, id is Id, tools is Query)
{
    opBoolean(context, id, { "tools" : tools, "operationType" : BooleanOperationType.UNION });
}

/** Cylinder with flats at |x| > half the width (one flat if single). */
function rbFlatted(context is Context, id is Id, c is Vector, z0 is ValueWithUnits, z1 is ValueWithUnits, r is ValueWithUnits,
    width is ValueWithUnits, single is boolean) returns Query
{
    const body = rbCyl(context, id + "c", c, z0, z1, r);
    var cutters = [rbCbox(context, id + "a", c + vector(width / 2 + r, 0 * RB_MM), 2 * r, 3 * r, z0 - RB_MM, z1 + RB_MM)];
    if (!single)
    {
        cutters = append(cutters, rbCbox(context, id + "b", c - vector(width / 2 + r, 0 * RB_MM), 2 * r, 3 * r, z0 - RB_MM, z1 + RB_MM));
    }
    rbSubtract(context, id + "cut", body, qUnion(cutters));
    return body;
}

function rbFinish(context is Context, q is Query, name is string, col is Color)
{
    setProperty(context, { "entities" : q, "propertyType" : PropertyType.NAME, "value" : name });
    setProperty(context, { "entities" : q, "propertyType" : PropertyType.APPEARANCE, "value" : col });
}

// -- Plates and spacers ----------------------------------------------------------------------------------
function rbPlates(context is Context, id is Id, z is map, centers is array, pitch is ValueWithUnits, nx is number, ny is number) returns map
{
    const d = RB_DIMS;
    const m = pitch / 2 + d.plateMargin * RB_MM;
    const x0 = -m;
    const y0 = -m;
    const x1 = (nx - 1) * pitch + m;
    const y1 = (ny - 1) * pitch + m;
    // G0 with a bore for every guide bush
    const g0 = rbBox(context, id + "g0", x0, y0, -d.g0T * RB_MM, x1, y1, 0 * RB_MM);
    var holes = [];
    for (var k = 0; k < size(centers); k += 1)
    {
        holes = append(holes, rbCyl(context, id + ("g0h" ~ k), centers[k], -d.g0T * RB_MM - RB_MM, RB_MM, d.bushD / 2 * RB_MM));
    }
    rbSubtract(context, id + "g0cut", g0, qUnion(holes));
    rbFinish(context, g0, "G0 Deckplatte", color(0.55, 0.58, 0.63, 0.55));
    // Bearing plate with a bore for every flanged bearing
    const bp = rbBox(context, id + "bp", x0, y0, z.plateBottom, x1, y1, z.plateTop);
    holes = [];
    for (var k = 0; k < size(centers); k += 1)
    {
        holes = append(holes, rbCyl(context, id + ("bph" ~ k), centers[k], z.plateBottom - RB_MM, z.plateTop + RB_MM, d.bearOD / 2 * RB_MM));
    }
    rbSubtract(context, id + "bpcut", bp, qUnion(holes));
    rbFinish(context, bp, "Lagerplatte", color(0.75, 0.78, 0.83, 0.55));
    // Motor plate with a pocket for every gearbox
    const mp = rbBox(context, id + "mp", x0, y0, z.motorPlateBottom, x1, y1, z.motorFace);
    holes = [];
    for (var k = 0; k < size(centers); k += 1)
    {
        holes = append(holes, rbCbox(context, id + ("mph" ~ k), centers[k], (d.motorW + d.pocketClear * 2) * RB_MM,
                    (d.motorH + d.pocketClear * 2) * RB_MM, z.motorPlateBottom - RB_MM, z.motorFace + RB_MM));
    }
    rbSubtract(context, id + "mpcut", mp, qUnion(holes));
    rbFinish(context, mp, "Motorplatte", color(0.75, 0.78, 0.83, 0.55));
    // Spacers at the four corners between the plates
    const inset = d.spacerInset * RB_MM + d.spacerD / 2 * RB_MM;
    const corners = [vector(x0 + inset, y0 + inset), vector(x1 - inset, y0 + inset), vector(x0 + inset, y1 - inset), vector(x1 - inset, y1 - inset)];
    var spacers = [];
    for (var k = 0; k < 4; k += 1)
    {
        const upper = rbCyl(context, id + ("su" ~ k), corners[k], z.plateTop, -d.g0T * RB_MM, d.spacerD / 2 * RB_MM);
        const lower = rbCyl(context, id + ("sl" ~ k), corners[k], z.motorFace, z.plateBottom, d.spacerD / 2 * RB_MM);
        rbFinish(context, qUnion([upper, lower]), "Distanzbolzen", color(0.7, 0.7, 0.72));
        spacers = append(spacers, upper);
        spacers = append(spacers, lower);
    }
    return { "g0" : g0, "bearingPlate" : bp, "motorPlate" : mp, "spacers" : qUnion(spacers) };
}

// -- One unit --------------------------------------------------------------------------------------------
function rbUnit(context is Context, id is Id, z is map, c is Vector, ext is ValueWithUnits, k is number) returns map
{
    const d = RB_DIMS;
    const n = " " ~ (k + 1);
    // Guide bush (fixed, POM) with the double D bore
    const bush = rbCyl(context, id + "bush", c, -d.bushL * RB_MM, 0 * RB_MM, d.bushD / 2 * RB_MM);
    const bore = rbFlatted(context, id + "bushbore", c, -d.bushL * RB_MM - RB_MM, RB_MM, (d.rodD / 2 + d.flatClear) * RB_MM,
        (d.flatW + 2 * d.flatClear) * RB_MM, false);
    rbSubtract(context, id + "bushcut", bush, bore);
    rbFinish(context, bush, "Führungsbuchse" ~ n, color(0.95, 0.92, 0.78));

    // Threaded rod M4 (thread not shown) with the flats on the upper part
    const tip = ext;
    const rodBottom = ext - z.rodLen;
    const rod = rbCyl(context, id + "rod", c, rodBottom, tip, d.rodD / 2 * RB_MM);
    const flats = qUnion([
                rbCbox(context, id + "rfa", c + vector((d.flatW / 2 + 2) * RB_MM, 0 * RB_MM), 4 * RB_MM, 6 * RB_MM, tip - z.flatLen, tip + RB_MM),
                rbCbox(context, id + "rfb", c - vector((d.flatW / 2 + 2) * RB_MM, 0 * RB_MM), 4 * RB_MM, 6 * RB_MM, tip - z.flatLen, tip + RB_MM)
            ]);
    rbSubtract(context, id + "rodflats", rod, flats);
    rbFinish(context, rod, "Gewindestange M4" ~ n, color(0.25, 0.26, 0.29));

    // Rotating tube. Head with the hex pocket, body with the free bore, floor with the D bore for the shaft
    const head = rbCyl(context, id + "head", c, z.headBottom, z.headTop, d.headD / 2 * RB_MM);
    const body = rbCyl(context, id + "body", c, z.tubeBottom, z.headBottom, d.tubeD / 2 * RB_MM);
    rbUnite(context, id + "tubeunite", qUnion([head, body]));
    const tube = head;
    const pocket = rbHex(context, id + "pocket", c, z.pocketBottom, z.headTop + RB_MM, (d.nutAF + 0.1) * RB_MM);
    const tubeBore = rbCyl(context, id + "tbore", c, z.boreEnd, z.pocketBottom + 0.01 * RB_MM, d.boreD / 2 * RB_MM);
    // The D bore is deeper than the shaft goes in, so the shaft carries no axial force
    const dBore = rbFlatted(context, id + "dbore", c, z.tubeBottom - RB_MM, z.tubeBottom + (d.shaftIn + d.shaftPlay) * RB_MM,
        (d.shaftD / 2 + d.dBoreClear) * RB_MM, (d.shaftFlat * 2 - d.shaftD + 2 * d.dBoreClear) * RB_MM, true);
    const groove = rbCyl(context, id + "groove", c, z.ringBottom, z.ringTop, d.tubeD / 2 * RB_MM + RB_MM);
    const grooveCore = rbCyl(context, id + "groovecore", c, z.ringBottom - RB_MM, z.ringTop + RB_MM, d.ringID / 2 * RB_MM);
    rbSubtract(context, id + "groovecut", groove, grooveCore);
    rbSubtract(context, id + "tubecut", tube, qUnion([pocket, tubeBore, dBore, groove]));
    rbFinish(context, tube, "Rohr" ~ n, color(0.85, 0.68, 0.28));

    // Two M4 hex nuts in the pocket (thread not shown)
    var nuts = [];
    for (var i = 0; i < d.nuts; i += 1)
    {
        const top = z.nutTop - i * d.nutH * RB_MM;
        const nut = rbHex(context, id + ("nut" ~ i), c, top - d.nutH * RB_MM, top, d.nutAF * RB_MM);
        const nutHole = rbCyl(context, id + ("nuth" ~ i), c, top - d.nutH * RB_MM - RB_MM, top + RB_MM, d.rodD / 2 * RB_MM);
        rbSubtract(context, id + ("nutcut" ~ i), nut, nutHole);
        rbFinish(context, nut, "Mutter M4" ~ n, color(0.62, 0.64, 0.68));
        nuts = append(nuts, nut);
    }

    // Shim on the inner ring, flanged bearing, retaining ring
    const shim = rbCyl(context, id + "shim", c, z.bearTop, z.headBottom, d.shimOD / 2 * RB_MM);
    rbSubtract(context, id + "shimcut", shim, rbCyl(context, id + "shimh", c, z.bearTop - RB_MM, z.headBottom + RB_MM, d.bearID / 2 * RB_MM));
    rbFinish(context, shim, "Distanzscheibe" ~ n, color(0.62, 0.64, 0.68));
    const bearing = rbCyl(context, id + "bear", c, z.bearBottom, z.bearTop, d.bearOD / 2 * RB_MM);
    const flange = rbCyl(context, id + "flange", c, z.plateTop, z.bearTop, d.flangeD / 2 * RB_MM);
    rbUnite(context, id + "bearunite", qUnion([bearing, flange]));
    rbSubtract(context, id + "bearcut", bearing, rbCyl(context, id + "bearh", c, z.bearBottom - RB_MM, z.bearTop + RB_MM, d.bearID / 2 * RB_MM));
    rbFinish(context, bearing, "Flanschlager MF128ZZ" ~ n, color(0.45, 0.5, 0.58));
    const ring = rbCyl(context, id + "ring", c, z.ringBottom, z.ringTop, d.ringOD / 2 * RB_MM);
    rbSubtract(context, id + "ringcut", ring, rbCyl(context, id + "ringh", c, z.ringBottom - RB_MM, z.ringTop + RB_MM, d.ringID / 2 * RB_MM));
    rbFinish(context, ring, "Sicherungsring 8" ~ n, color(0.15, 0.15, 0.17));

    // N20 gearmotor with encoder, gearbox face up, D shaft into the tube floor
    const gearbox = rbCbox(context, id + "gearbox", c, d.motorW * RB_MM, d.motorH * RB_MM, z.motorFace - d.gearboxL * RB_MM, z.motorFace);
    const canTop = z.motorFace - d.gearboxL * RB_MM;
    const canBottom = canTop - d.canL * RB_MM;
    const can = rbCyl(context, id + "can", c, canBottom, canTop, d.motorW / 2 * RB_MM);
    const canCut = rbCbox(context, id + "canbox", c, d.motorW * RB_MM, d.motorH * RB_MM, canBottom - RB_MM, canTop + RB_MM);
    opBoolean(context, id + "canshape", { "tools" : qUnion([can, canCut]), "operationType" : BooleanOperationType.INTERSECTION });
    const encoder = rbCbox(context, id + "enc", c, d.motorW * RB_MM, d.motorH * RB_MM, z.motorBottom, canBottom);
    const shaft = rbFlatted(context, id + "shaft", c, z.motorFace, z.motorFace + d.shaftL * RB_MM, d.shaftD / 2 * RB_MM,
        (d.shaftFlat * 2 - d.shaftD) * RB_MM, true);
    rbUnite(context, id + "motorunite", qUnion([gearbox, can, encoder, shaft]));
    rbFinish(context, gearbox, "N20 Motor mit Encoder" ~ n, color(0.31, 0.47, 0.65));

    return { "bush" : bush, "rod" : rod, "tube" : tube, "nuts" : qUnion(nuts), "shim" : shim, "bearing" : bearing,
            "ring" : ring, "motor" : gearbox };
}

// -- Clearance check -------------------------------------------------------------------------------------
function rbGap(context is Context, a is Query, b is Query) returns ValueWithUnits
{
    return evDistance(context, { "side0" : a, "side1" : b }).distance;
}

function rbReport(context is Context, id is Id, plates is map, units is array)
{
    const u = units[0];
    const fixed = qUnion([plates.g0, plates.bearingPlate, plates.motorPlate, plates.spacers]);
    const checks = [
            ["Rohr zu Führungsbuchse", rbGap(context, u.tube, u.bush), 1.0],
            ["Rohr zu Platten und Bolzen", rbGap(context, u.tube, fixed), 1.0],
            ["Muttern zu Führungsbuchse", rbGap(context, u.nuts, u.bush), 1.0],
            ["Sicherungsring zu Lagerplatte", rbGap(context, u.ring, plates.bearingPlate), 0.5],
            ["Stange zu Rohr", rbGap(context, u.rod, u.tube), 0.3],
            ["Motorwelle zu Rohr (Schiebesitz)", rbGap(context, u.motor, u.tube), 0.03]
        ];
    var text = "Rohrantrieb Abstände (mm).";
    var ok = true;
    for (var c in checks)
    {
        const mm = roundToPrecision(c[1] / RB_MM, 3);
        text = text ~ " " ~ c[0] ~ " " ~ mm ~ ";";
        if (mm < c[2] - 0.000001)
        {
            ok = false;
            text = text ~ " ZU KLEIN (mindestens " ~ c[2] ~ ");";
        }
    }
    if (size(units) > 1)
    {
        // Neighbouring units (the first two in x) must keep the clearance of the project, 1.05 mm
        const pairs = [["Motor zu Nachbarmotor", units[0].motor, units[1].motor],
                ["Lager zu Nachbarlager", units[0].bearing, units[1].bearing],
                ["Rohr zu Nachbarrohr", units[0].tube, units[1].tube]];
        for (var p in pairs)
        {
            const mm = roundToPrecision(rbGap(context, p[1], p[2]) / RB_MM, 3);
            text = text ~ " " ~ p[0] ~ " " ~ mm ~ ";";
            if (mm < 1.05)
            {
                ok = false;
                text = text ~ " ZU KLEIN (mindestens 1.05);";
            }
        }
    }
    println(text);
    if (ok)
    {
        reportFeatureInfo(context, id, text);
    }
    else
    {
        reportFeatureWarning(context, id, text);
    }
}
