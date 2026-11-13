FeatureScript 3112;
import(path : "onshape/std/common.fs", version : "3112.0");

// Project Blindsight, variant with a rotating tube (docs/MOTORVARIANTE_ROHR.md).
//
// One tile per pin, four parts, tiles packed side by side in any number.
//   Gehäuse     printed. A rectangular sleeve, as wide as the N20 plus two walls. Its closed top is the
//               Sicherung, a double D slot that keeps the rod from turning. The motor sits in the open
//               bottom, the rectangular pocket takes its torque
//   Rohr        printed. Open at the top, M4 thread tapped into the open end, free bore below, closed
//               bottom with a D bore for the motor shaft. Stands on the gearbox face, which carries it
//   Stange      bought M4 threaded rod with two flats where it runs through the Sicherung
//   N20 Motor   bought gearmotor with encoder, stands on the floor of the tray
// The motor turns the tube, the thread in the open end moves the rod, the Sicherung stops the rod from
// turning with it. The thread is self locking, a finger on the pin cannot turn the tube back.
// Load path when a finger presses a pin. Rod, thread, tube, gearbox face, motor, floor of the tray. The
// D shaft only carries torque, it ends below the bottom of the D bore.
// z = 0 is the top surface of the tiles, all sizes in millimetres.

const RB = {
        // tile and printing rules
        "gap" : 0.2, "wall" : 0.8, "pocketClear" : 0.1,
        // N20 gearmotor with hall encoder
        "motorW" : 12.0, "motorH" : 10.0, "gearboxL" : 9.0, "canL" : 15.0, "encL" : 8.0,
        "bossD" : 4.0, "bossH" : 0.5, "shaftD" : 3.0, "shaftFlat" : 2.5, "shaftL" : 10.0,
        // M4 rod
        "pitch" : 0.7, "rodD" : 4.0, "rodCore" : 3.2, "flatW" : 3.4, "rodReserve" : 3.0,
        // Sicherung (top of the housing)
        "topT" : 6.0, "slotD" : 4.2, "slotClear" : 0.05,
        // tube
        "tubeD" : 8.0, "topGap" : 1.0, "threadL" : 8.0, "boreD" : 4.6, "boreGap" : 1.5, "tubeFloor" : 1.0,
        "shaftPlay" : 0.5, "dClear" : 0.05, "recessD" : 5.0, "recessH" : 1.0, "chamfer" : 0.5,
        // tray
        "floorT" : 2.0, "rimT" : 2.0, "rimH" : 10.0, "trayClear" : 0.15, "cableW" : 8.0, "cableH" : 4.0
    };

const RB_MM = millimeter;

annotation { "Feature Type Name" : "Rohrantrieb" }
export const rohrantrieb = defineFeature(function(context is Context, id is Id, definition is map)
    precondition
    {
        annotation { "Name" : "Hub der Stange" }
        isLength(definition.stroke, { (millimeter) : [5, 40, 200] } as LengthBoundSpec);

        annotation { "Name" : "Ausfahrstellung zur Ansicht" }
        isLength(definition.extension, { (millimeter) : [0, 20, 200] } as LengthBoundSpec);

        annotation { "Name" : "Kacheln in x" }
        isInteger(definition.nx, { (unitless) : [1, 3, 20] } as IntegerBoundSpec);

        annotation { "Name" : "Kacheln in y" }
        isInteger(definition.ny, { (unitless) : [1, 3, 20] } as IntegerBoundSpec);

        // Without "Default" a boolean starts unchecked in the dialog
        annotation { "Name" : "Gewinde darstellen", "Default" : true }
        definition.threads is boolean;

        annotation { "Name" : "Wanne erzeugen", "Default" : true }
        definition.tray is boolean;

        annotation { "Name" : "Abstand messen und melden", "Default" : true }
        definition.check is boolean;
    }
    {
        const d = RB;
        const z = rbLevels(definition.stroke);
        const ext = min(definition.extension, definition.stroke);
        const px = (d.motorW + 2 * d.pocketClear + 2 * d.wall + d.gap) * RB_MM;
        const py = (d.motorH + 2 * d.pocketClear + 2 * d.wall + d.gap) * RB_MM;

        // Build the first tile at the origin, then copy its parts to every other grid point
        const first = rbBuildTile(context, id + "t0", z, ext, definition.threads);
        var tile0 = { "shaftGap" : first.shaftGap };
        for (var e in first.parts)
        {
            rbFinish(context, e[1], e[2] ~ " 1", e[3]);
            tile0[e[0]] = e[1];
        }
        var tiles = [tile0];
        for (var j = 0; j < definition.ny; j += 1)
        {
            for (var i = 0; i < definition.nx; i += 1)
            {
                const k = j * definition.nx + i;
                if (k == 0)
                {
                    continue;
                }
                var tile = {};
                for (var n = 0; n < size(first.parts); n += 1)
                {
                    const e = first.parts[n];
                    const pid = id + ("p" ~ k ~ "x" ~ n);
                    opPattern(context, pid, { "entities" : e[1], "transforms" : [transform(vector(i * px, j * py, 0 * RB_MM))],
                                "instanceNames" : ["t" ~ k] });
                    const q = qCreatedBy(pid, EntityType.BODY);
                    rbFinish(context, q, e[2] ~ " " ~ (k + 1), e[3]);
                    tile[e[0]] = q;
                }
                tiles = append(tiles, tile);
            }
        }
        if (definition.tray)
        {
            rbTray(context, id + "tray", z, definition.nx, definition.ny, px, py);
        }
        if (definition.check)
        {
            rbReport(context, id, z, tiles, px, py);
        }
    }, { "stroke" : 40 * millimeter, "extension" : 20 * millimeter, "nx" : 3, "ny" : 3, "threads" : true, "tray" : true,
            "check" : true });

/** Heights of all parts (lengths), derived from the stroke and RB. */
function rbLevels(stroke is ValueWithUnits) returns map
{
    const d = RB;
    var z = {};
    z.slotBottom = -d.topT * RB_MM;
    z.tubeTop = z.slotBottom - d.topGap * RB_MM;
    z.threadBottom = z.tubeTop - d.threadL * RB_MM;
    // At full stroke the rod still reaches the reserve below the thread
    z.rodLen = stroke - z.threadBottom + d.rodReserve * RB_MM;
    z.boreEnd = -z.rodLen - d.boreGap * RB_MM;
    z.dTop = z.boreEnd - d.tubeFloor * RB_MM;
    z.shaftTop = z.dTop - d.shaftPlay * RB_MM;
    z.motorFace = z.shaftTop - d.shaftL * RB_MM;
    z.tubeBottom = z.motorFace;
    z.motorBottom = z.motorFace - (d.gearboxL + d.canL + d.encL) * RB_MM;
    z.housingBottom = z.motorBottom;
    z.floorBottom = z.motorBottom - d.floorT * RB_MM;
    // The flats cover the Sicherung over the whole stroke
    z.flatLen = stroke + (d.topT + 0.5) * RB_MM;
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

/** Solid of revolution about the z axis. Points are [radius, z] pairs in millimetres. */
function rbRevolve(context is Context, id is Id, pts is array) returns Query
{
    const sketch = newSketchOnPlane(context, id + "sk", { "sketchPlane" : plane(vector(0, 0, 0) * RB_MM, vector(0, -1, 0), vector(1, 0, 0)) });
    var points = [];
    for (var p in pts)
    {
        points = append(points, vector(p[0], p[1]) * RB_MM);
    }
    points = append(points, points[0]);
    skPolyline(sketch, "profile", { "points" : points });
    skSolve(sketch);
    opRevolve(context, id + "rev", { "entities" : qSketchRegion(id + "sk"), "axis" : line(vector(0, 0, 0) * RB_MM, vector(0, 0, 1)),
                "angleForward" : 2 * PI * radian, "angleBack" : 0 * radian });
    opDeleteBodies(context, id + "del", { "entities" : qCreatedBy(id + "sk") });
    return qCreatedBy(id + "rev", EntityType.BODY);
}

/**
 * Right hand thread ridge on the z axis, swept along a helix that starts at angle 0 at height z0.
 * The trapezoid runs from radius rIn (width wIn) to rOut (width wOut). Ridges that start at the same
 * angle and a whole number of pitches apart mesh with each other.
 */
function rbThread(context is Context, id is Id, z0 is ValueWithUnits, turns is number, rIn is number, rOut is number,
    wIn is number, wOut is number) returns Query
{
    opHelix(context, id + "helix", { "direction" : vector(0, 0, 1), "axisStart" : vector(0, 0, 0) * RB_MM,
                "startPoint" : vector((rIn + rOut) / 2 * RB_MM, 0 * RB_MM, z0), "interval" : vector(0, turns),
                "clockwise" : true, "helicalPitch" : RB.pitch * RB_MM, "spiralPitch" : 0 * RB_MM });
    const sketch = newSketchOnPlane(context, id + "sk", { "sketchPlane" : plane(vector(0 * RB_MM, 0 * RB_MM, z0), vector(0, -1, 0), vector(1, 0, 0)) });
    skPolyline(sketch, "profile", { "points" : [vector(rIn, -wIn / 2) * RB_MM, vector(rOut, -wOut / 2) * RB_MM, vector(rOut, wOut / 2) * RB_MM,
                    vector(rIn, wIn / 2) * RB_MM, vector(rIn, -wIn / 2) * RB_MM] });
    skSolve(sketch);
    opSweep(context, id + "sweep", { "profiles" : qSketchRegion(id + "sk"), "path" : qCreatedBy(id + "helix", EntityType.EDGE) });
    opDeleteBodies(context, id + "del", { "entities" : qUnion([qCreatedBy(id + "sk"), qCreatedBy(id + "helix")]) });
    return qCreatedBy(id + "sweep", EntityType.BODY);
}

function rbSubtract(context is Context, id is Id, target is Query, tools is Query)
{
    opBoolean(context, id, { "targets" : target, "tools" : tools, "operationType" : BooleanOperationType.SUBTRACTION });
}

function rbUnite(context is Context, id is Id, tools is Query)
{
    opBoolean(context, id, { "tools" : tools, "operationType" : BooleanOperationType.UNION });
}

/** Cylinder on the z axis with flats at |x| > half the width (only at +x if single). */
function rbFlatted(context is Context, id is Id, z0 is ValueWithUnits, z1 is ValueWithUnits, r is ValueWithUnits,
    width is ValueWithUnits, single is boolean) returns Query
{
    const body = rbCyl(context, id + "c", vector(0, 0) * RB_MM, z0, z1, r);
    var cutters = [rbCbox(context, id + "a", vector(width / 2 + r, 0 * RB_MM), 2 * r, 3 * r, z0 - RB_MM, z1 + RB_MM)];
    if (!single)
    {
        cutters = append(cutters, rbCbox(context, id + "b", vector(-width / 2 - r, 0 * RB_MM), 2 * r, 3 * r, z0 - RB_MM, z1 + RB_MM));
    }
    rbSubtract(context, id + "cut", body, qUnion(cutters));
    return body;
}

function rbFinish(context is Context, q is Query, name is string, col is Color)
{
    setProperty(context, { "entities" : q, "propertyType" : PropertyType.NAME, "value" : name });
    setProperty(context, { "entities" : q, "propertyType" : PropertyType.APPEARANCE, "value" : col });
}

function rbMm(v is ValueWithUnits) returns number
{
    return v / RB_MM;
}

function rbGap(context is Context, a is Query, b is Query) returns number
{
    return roundToPrecision(evDistance(context, { "side0" : a, "side1" : b }).distance / RB_MM, 3);
}

// -- One tile at the origin ------------------------------------------------------------------------------
/** Returns the parts as [key, query, part name, colour] and the clearance of the motor shaft in the tube. */
function rbBuildTile(context is Context, id is Id, z is map, ext is ValueWithUnits, threads is boolean) returns map
{
    const d = RB;
    const o = vector(0, 0) * RB_MM;
    const hx = (d.motorW / 2 + d.pocketClear + d.wall) * RB_MM;
    const hy = (d.motorH / 2 + d.pocketClear + d.wall) * RB_MM;
    const pitch = d.pitch * RB_MM;

    // Housing. Rectangular sleeve, closed top with the double D slot (the Sicherung)
    const housing = rbBox(context, id + "housing", -hx, -hy, z.housingBottom, hx, hy, 0 * RB_MM);
    rbSubtract(context, id + "housingcut", housing, qUnion([
                rbCbox(context, id + "inside", o, (d.motorW + 2 * d.pocketClear) * RB_MM, (d.motorH + 2 * d.pocketClear) * RB_MM,
                    z.housingBottom - RB_MM, z.slotBottom),
                rbFlatted(context, id + "slot", z.slotBottom - RB_MM, RB_MM, d.slotD / 2 * RB_MM, (d.flatW + 2 * d.slotClear) * RB_MM, false)
            ]));

    // Rod. M4 with two flats where it runs through the Sicherung
    const tip = ext;
    const rodBottom = ext - z.rodLen;
    const zStart = rodBottom - pitch;
    var rod;
    if (threads)
    {
        rod = rbCyl(context, id + "rod", o, rodBottom - RB_MM, tip + RB_MM, d.rodCore / 2 * RB_MM);
        const turns = ceil((tip + RB_MM - zStart) / pitch);
        rbUnite(context, id + "rodunite", qUnion([rod, rbThread(context, id + "rodthread", zStart, turns, 1.55, 2.0, 0.607, 0.0875)]));
    }
    else
    {
        rod = rbCyl(context, id + "rod", o, rodBottom - RB_MM, tip + RB_MM, d.rodD / 2 * RB_MM);
    }
    const t = rbMm(tip);
    const b = rbMm(rodBottom);
    const fx = (d.flatW / 2 + 2) * RB_MM;
    rbSubtract(context, id + "rodcut", rod, qUnion([
                rbRevolve(context, id + "tipcut", [[0, t], [1.6, t], [2.6, t - 1.0], [2.6, t + 3], [0, t + 3]]),
                rbRevolve(context, id + "endcut", [[0, b], [1.6, b], [2.6, b + 1.0], [2.6, b - 3], [0, b - 3]]),
                rbCbox(context, id + "flata", vector(fx, 0 * RB_MM), 4 * RB_MM, 6 * RB_MM, tip - z.flatLen, tip + 2 * RB_MM),
                rbCbox(context, id + "flatb", vector(-fx, 0 * RB_MM), 4 * RB_MM, 6 * RB_MM, tip - z.flatLen, tip + 2 * RB_MM)
            ]));

    // Tube. Open end at the top with the M4 thread, free bore, closed bottom with the D bore
    const r = d.tubeD / 2;
    const c = d.chamfer;
    const tube = rbRevolve(context, id + "tube", [
                [0, rbMm(z.tubeBottom)], [r - c, rbMm(z.tubeBottom)], [r, rbMm(z.tubeBottom) + c],
                [r, rbMm(z.tubeTop) - c], [r - c, rbMm(z.tubeTop)], [0, rbMm(z.tubeTop)]
            ]);
    var tubeCuts = [
        rbCyl(context, id + "threadhole", o, z.threadBottom - 0.01 * RB_MM, z.tubeTop + RB_MM, (threads ? 1.65 : 2.05) * RB_MM),
        rbCyl(context, id + "bore", o, z.boreEnd, z.threadBottom, d.boreD / 2 * RB_MM),
        rbFlatted(context, id + "dbore", z.tubeBottom - RB_MM, z.dTop, (d.shaftD / 2 + d.dClear) * RB_MM,
            (2 * d.shaftFlat - d.shaftD + 2 * d.dClear) * RB_MM, true),
        rbCyl(context, id + "recess", o, z.tubeBottom - RB_MM, z.tubeBottom + d.recessH * RB_MM, d.recessD / 2 * RB_MM)
    ];
    if (threads)
    {
        // Internal thread, starts a whole number of pitches from the rod thread so both mesh
        const zTap = zStart + floor((z.threadBottom - RB_MM - zStart) / pitch) * pitch;
        const turns = ceil((z.tubeTop + RB_MM - zTap) / pitch);
        tubeCuts = append(tubeCuts, rbThread(context, id + "tap", zTap, turns, 1.62, 2.08, 0.642, 0.11));
    }
    rbSubtract(context, id + "tubecut", tube, qUnion(tubeCuts));

    // N20 gearmotor with encoder. Gearbox face up, the tube stands on it
    const gearbox = rbCbox(context, id + "gearbox", o, d.motorW * RB_MM, d.motorH * RB_MM, z.motorFace - d.gearboxL * RB_MM, z.motorFace);
    const canTop = z.motorFace - d.gearboxL * RB_MM;
    const canBottom = canTop - d.canL * RB_MM;
    const can = rbCyl(context, id + "can", o, canBottom, canTop, d.motorW / 2 * RB_MM);
    const canBox = rbCbox(context, id + "canbox", o, d.motorW * RB_MM, d.motorH * RB_MM, canBottom - RB_MM, canTop + RB_MM);
    opBoolean(context, id + "canshape", { "tools" : qUnion([can, canBox]), "operationType" : BooleanOperationType.INTERSECTION });
    const encoder = rbCbox(context, id + "encoder", o, d.motorW * RB_MM, d.motorH * RB_MM, z.motorBottom, canBottom);
    const boss = rbCyl(context, id + "boss", o, z.motorFace - 0.1 * RB_MM, z.motorFace + d.bossH * RB_MM, d.bossD / 2 * RB_MM);
    const shaft = rbFlatted(context, id + "shaft", z.motorFace, z.shaftTop, d.shaftD / 2 * RB_MM, (2 * d.shaftFlat - d.shaftD) * RB_MM, true);
    // The tube stands on the gearbox face on purpose, so measure the shaft alone before it joins the motor
    const shaftGap = rbGap(context, qUnion([shaft, boss]), tube);
    rbUnite(context, id + "motorunite", qUnion([gearbox, can, encoder, boss, shaft]));

    return {
            "shaftGap" : shaftGap,
            "parts" : [
                ["housing", housing, "Gehäuse mit Sicherung", color(0.80, 0.82, 0.86, 0.4)],
                ["tube", tube, "Rohr", color(0.92, 0.45, 0.18)],
                ["rod", rod, "Gewindestange M4", color(0.30, 0.31, 0.35)],
                ["motor", gearbox, "N20 Motor mit Encoder", color(0.25, 0.42, 0.62)]
            ]
        };
}

// -- Tray ------------------------------------------------------------------------------------------------
/** Floor with a low rim. Holds the tiles together, carries the load, cable slot under every motor. */
function rbTray(context is Context, id is Id, z is map, nx is number, ny is number, px is ValueWithUnits, py is ValueWithUnits)
{
    const d = RB;
    const hx = (d.motorW / 2 + d.pocketClear + d.wall) * RB_MM;
    const hy = (d.motorH / 2 + d.pocketClear + d.wall) * RB_MM;
    const c = d.trayClear * RB_MM;
    const w = d.rimT * RB_MM;
    const x0 = -hx - c;
    const y0 = -hy - c;
    const x1 = (nx - 1) * px + hx + c;
    const y1 = (ny - 1) * py + hy + c;
    const top = z.housingBottom + d.rimH * RB_MM;
    const tray = rbBox(context, id + "tray", x0 - w, y0 - w, z.floorBottom, x1 + w, y1 + w, top);
    var cuts = [rbBox(context, id + "inner", x0, y0, z.housingBottom, x1, y1, top + RB_MM)];
    for (var j = 0; j < ny; j += 1)
    {
        for (var i = 0; i < nx; i += 1)
        {
            cuts = append(cuts, rbCbox(context, id + ("cable" ~ i ~ "x" ~ j), vector(i * px, j * py), d.cableW * RB_MM, d.cableH * RB_MM,
                    z.floorBottom - RB_MM, z.housingBottom + RB_MM));
        }
    }
    rbSubtract(context, id + "traycut", tray, qUnion(cuts));
    rbFinish(context, tray, "Wanne", color(0.45, 0.47, 0.50));
}

// -- Clearance check -------------------------------------------------------------------------------------
function rbReport(context is Context, id is Id, z is map, tiles is array, px is ValueWithUnits, py is ValueWithUnits)
{
    const u = tiles[0];
    var checks = [
        ["Stange zu Rohr (Gewindespiel)", rbGap(context, u.rod, u.tube), 0.03],
        ["Stange zu Sicherung (Führungsspiel)", rbGap(context, u.rod, u.housing), 0.03],
        ["Rohr zu Gehäuse", rbGap(context, u.tube, u.housing), 0.5],
        ["Motorwelle zu Rohr (D Sitz)", u.shaftGap, 0.03],
        ["Motor zu Gehäuse", rbGap(context, u.motor, u.housing), 0.05]
    ];
    if (size(tiles) > 1)
    {
        checks = append(checks, ["Gehäuse zu Nachbarkachel", rbGap(context, u.housing, tiles[1].housing), 0.15]);
        checks = append(checks, ["Motor zu Nachbarmotor", rbGap(context, u.motor, tiles[1].motor), 1.05]);
    }
    var text = "Rohrantrieb. Raster " ~ roundToPrecision(px / RB_MM, 2) ~ " x " ~ roundToPrecision(py / RB_MM, 2) ~
        " mm, Bautiefe " ~ roundToPrecision(-z.floorBottom / RB_MM, 2) ~ " mm, Stange " ~ roundToPrecision(z.rodLen / RB_MM, 2) ~
        " mm. Abstände in mm.";
    var ok = true;
    for (var c in checks)
    {
        text = text ~ " " ~ c[0] ~ " " ~ c[1] ~ ";";
        if (c[1] < c[2] - 0.000001)
        {
            ok = false;
            text = text ~ " ZU KLEIN (mindestens " ~ c[2] ~ ");";
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
