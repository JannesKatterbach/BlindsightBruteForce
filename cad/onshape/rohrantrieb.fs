FeatureScript 3112;
import(path : "onshape/std/common.fs", version : "3112.0");

// Project Blindsight, variant with a rotating tube (docs/MOTORVARIANTE_ROHR.md).
//
// Every pin is one self-contained tile. Tiles of the same size are packed side by side in any number,
// the frame holds them. Per tile, from the top
//   Deckel mit Führung   printed. Top surface of the display. Its double D slot is the anti-rotation
//                        guide for the rod, two pins locate it on the housing
//   Gewindestange M4     bought M4 rod, cut to length, two flats filed over the guided length. The
//                        flats only remove thread crests, the core stays whole
//   2 Muttern M4         bought DIN 934 nuts, pressed into the hex pocket of the tube
//   Rohr                 printed. Turns, carries the nuts at the top, is centred at the top by the rod
//                        and at the bottom by the bearing. Its D bore is the key for the motor shaft
//   Kugellager MR85ZZ    5 x 8 x 2.5, sits in the bulkhead of the housing and takes the axial force
//   N20 Motor            gearmotor with encoder. Its D shaft only transmits torque, it ends below the
//                        bottom of the D bore, so no axial force reaches the gearbox
//   Gehäuse              printed rectangular shaft. Cavity for the tube, bulkhead with bearing seat,
//                        pocket for the motor. Its outline is the tile size
// Load path when a finger presses a pin. Rod, nuts, tube, bearing inner ring, bearing outer ring,
// bulkhead, housing, floor of the frame. The thread is self locking, the motor holds no load at rest.
// z = 0 is the top surface of the tiles, all sizes in millimetres. Only the feature parameters are
// inputs, everything else follows from the bought parts and the printing rules in RB.

const RB = {
        // tile and printing
        "gap" : 0.2, "wall" : 0.8, "pocketClear" : 0.1,
        // N20 gearmotor with hall encoder, gearbox 12 x 10, D shaft 3 mm with a flat at 2.5 mm
        "motorW" : 12.0, "motorH" : 10.0, "gearboxL" : 9.0, "canL" : 15.0, "encL" : 8.0,
        "shaftD" : 3.0, "shaftFlat" : 2.5, "shaftL" : 10.0, "shaftPlay" : 0.5, "dClear" : 0.05,
        // M4 rod and DIN 934 nuts
        "pitch" : 0.7, "rodD" : 4.0, "rodCore" : 3.2, "flatW" : 3.4, "nutAF" : 7.0, "nutH" : 3.2, "nuts" : 2,
        "rodReserve" : 3.0,
        // cap with the double D guide
        "capT" : 6.0, "slotD" : 4.2, "slotClear" : 0.05, "pinD" : 1.6, "pinL" : 2.5, "pinHoleD" : 1.7,
        // tube
        "headGap" : 1.0, "headD" : 9.6, "pocketAF" : 7.1, "pocketExtra" : 0.3, "headFloor" : 1.0, "tubeD" : 7.0,
        "boreD" : 4.6, "boreGap" : 1.5, "tubeFloor" : 1.0, "collarD" : 5.8, "collarH" : 0.5, "journalChamfer" : 0.3,
        // bearing MR85ZZ in the bulkhead
        "bearID" : 5.0, "bearOD" : 8.0, "bearW" : 2.5, "seatD" : 8.05, "bulkFloor" : 1.2, "bulkHole" : 6.5,
        "cavityD" : 10.2, "motorEndGap" : 0.4,
        // frame
        "floorT" : 2.0, "frameWall" : 4.0, "frameClear" : 0.15, "coverT" : 1.2, "coverOverlap" : 1.0,
        "cableW" : 8.0, "cableH" : 4.0, "screwPilot" : 1.6, "screwClear" : 2.2, "screwDepth" : 8.0
    };

// Locating pins of the cap, in two opposite corners outside the tube cavity
const RB_PINS = [vector(5.4, 4.4), vector(-5.4, -4.4)];

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

        annotation { "Name" : "Gewinde darstellen" }
        definition.threads is boolean;

        annotation { "Name" : "Rahmen erzeugen" }
        definition.frame is boolean;

        annotation { "Name" : "Abstand messen und melden" }
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
        var tile0 = {};
        for (var e in first)
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
                for (var n = 0; n < size(first); n += 1)
                {
                    const e = first[n];
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
        if (definition.frame)
        {
            rbFrame(context, id + "frame", z, definition.nx, definition.ny, px, py);
        }
        if (definition.check)
        {
            rbReport(context, id, z, tiles, px, py);
        }
    }, { "stroke" : 40 * millimeter, "extension" : 20 * millimeter, "nx" : 3, "ny" : 3, "threads" : true, "frame" : true,
            "check" : true });

/** Heights of all parts (lengths), derived from the stroke and RB. */
function rbLevels(stroke is ValueWithUnits) returns map
{
    const d = RB;
    var z = {};
    z.capBottom = -d.capT * RB_MM;
    z.headTop = z.capBottom - d.headGap * RB_MM;
    z.pocketBottom = z.headTop - (d.nuts * d.nutH + d.pocketExtra) * RB_MM;
    z.nutTop = z.headTop - 0.2 * RB_MM;
    z.nutBottom = z.nutTop - d.nuts * d.nutH * RB_MM;
    z.headBottom = z.pocketBottom - d.headFloor * RB_MM;
    z.bodyTop = z.headBottom - (d.headD - d.tubeD) / 2 * RB_MM;
    // The rod still has the reserve below the nuts at full stroke
    z.rodLen = stroke - z.nutBottom + d.rodReserve * RB_MM;
    z.boreEnd = -z.rodLen - d.boreGap * RB_MM;
    z.dTop = z.boreEnd - d.tubeFloor * RB_MM;
    z.shaftTop = z.dTop - d.shaftPlay * RB_MM;
    z.motorFace = z.shaftTop - d.shaftL * RB_MM;
    z.bearBottom = z.motorFace + d.bulkFloor * RB_MM;
    z.bearTop = z.bearBottom + d.bearW * RB_MM;
    z.collarTop = z.bearTop + d.collarH * RB_MM;
    z.bodyBottom = z.collarTop + (d.tubeD - d.collarD) / 2 * RB_MM;
    z.motorBottom = z.motorFace - (d.gearboxL + d.canL + d.encL) * RB_MM;
    z.housingBottom = z.motorBottom - d.motorEndGap * RB_MM;
    z.floorBottom = z.housingBottom - d.floorT * RB_MM;
    // The flats cover the guide over the whole stroke and end above the nuts
    z.flatLen = stroke + (d.capT + 0.5) * RB_MM;
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

/** Hexagonal prism on the z axis, width across flats af, flats facing x. */
function rbHex(context is Context, id is Id, z0 is ValueWithUnits, z1 is ValueWithUnits, af is ValueWithUnits) returns Query
{
    const sketch = newSketchOnPlane(context, id + "sk", { "sketchPlane" : plane(vector(0 * RB_MM, 0 * RB_MM, z0), vector(0, 0, 1), vector(1, 0, 0)) });
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
    const o = vector(0, 0) * RB_MM;
    const body = rbCyl(context, id + "c", o, z0, z1, r);
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

// -- One tile at the origin ------------------------------------------------------------------------------
/** Returns [key, query, part name, colour] for every part of the tile. */
function rbBuildTile(context is Context, id is Id, z is map, ext is ValueWithUnits, threads is boolean) returns array
{
    const d = RB;
    const o = vector(0, 0) * RB_MM;
    const hx = (d.motorW / 2 + d.pocketClear + d.wall) * RB_MM;
    const hy = (d.motorH / 2 + d.pocketClear + d.wall) * RB_MM;

    // Housing. Cavity for the tube, bulkhead with bearing seat and shaft hole, pocket for the motor
    const housing = rbBox(context, id + "housing", -hx, -hy, z.housingBottom, hx, hy, z.capBottom);
    var cuts = [
        rbCyl(context, id + "cavity", o, z.bearTop, z.capBottom + RB_MM, d.cavityD / 2 * RB_MM),
        rbCyl(context, id + "seat", o, z.bearBottom, z.bearTop + 0.01 * RB_MM, d.seatD / 2 * RB_MM),
        rbCyl(context, id + "bulkhole", o, z.motorFace - RB_MM, z.bearBottom + 0.01 * RB_MM, d.bulkHole / 2 * RB_MM),
        rbCbox(context, id + "mpocket", o, (d.motorW + 2 * d.pocketClear) * RB_MM, (d.motorH + 2 * d.pocketClear) * RB_MM,
            z.housingBottom - RB_MM, z.motorFace)
    ];
    for (var i = 0; i < size(RB_PINS); i += 1)
    {
        cuts = append(cuts, rbCyl(context, id + ("pinhole" ~ i), RB_PINS[i] * RB_MM, z.capBottom - (d.pinL + 0.5) * RB_MM,
                z.capBottom + RB_MM, d.pinHoleD / 2 * RB_MM));
    }
    rbSubtract(context, id + "housingcut", housing, qUnion(cuts));

    // Cap with the double D guide and two locating pins
    const cap = rbBox(context, id + "cap", -hx, -hy, z.capBottom, hx, hy, 0 * RB_MM);
    const slot = rbFlatted(context, id + "slot", z.capBottom - RB_MM, RB_MM, d.slotD / 2 * RB_MM, (d.flatW + 2 * d.slotClear) * RB_MM, false);
    rbSubtract(context, id + "capcut", cap, slot);
    var capParts = [cap];
    for (var i = 0; i < size(RB_PINS); i += 1)
    {
        capParts = append(capParts, rbCyl(context, id + ("pin" ~ i), RB_PINS[i] * RB_MM, z.capBottom - d.pinL * RB_MM,
                    z.capBottom + 0.5 * RB_MM, d.pinD / 2 * RB_MM));
    }
    rbUnite(context, id + "capunite", qUnion(capParts));

    // Tube as a solid of revolution with 45 degree transitions, so it prints upright without support
    const rj = d.bearID / 2;
    const tube = rbRevolve(context, id + "tube", [
                [0, rbMm(z.bearBottom)], [rj - d.journalChamfer, rbMm(z.bearBottom)], [rj, rbMm(z.bearBottom) + d.journalChamfer],
                [rj, rbMm(z.bearTop)], [d.collarD / 2, rbMm(z.bearTop)], [d.collarD / 2, rbMm(z.collarTop)],
                [d.tubeD / 2, rbMm(z.bodyBottom)], [d.tubeD / 2, rbMm(z.bodyTop)], [d.headD / 2, rbMm(z.headBottom)],
                [d.headD / 2, rbMm(z.headTop)], [0, rbMm(z.headTop)]
            ]);
    const tubeCuts = qUnion([
                rbHex(context, id + "pocket", z.pocketBottom, z.headTop + RB_MM, d.pocketAF * RB_MM),
                rbCyl(context, id + "bore", o, z.boreEnd, z.pocketBottom + 0.01 * RB_MM, d.boreD / 2 * RB_MM),
                // D bore, the key for the motor shaft. Deeper than the shaft reaches
                rbFlatted(context, id + "dbore", z.bearBottom - RB_MM, z.dTop, (d.shaftD / 2 + d.dClear) * RB_MM,
                    (2 * d.shaftFlat - d.shaftD + 2 * d.dClear) * RB_MM, true)
            ]);
    rbSubtract(context, id + "tubecut", tube, tubeCuts);

    // Threaded rod. Both ridges start at angle 0 a whole number of pitches apart, so rod and nuts mesh
    const pitch = d.pitch * RB_MM;
    const tip = ext;
    const rodBottom = ext - z.rodLen;
    const zStart = rodBottom - pitch;
    var rod;
    if (threads)
    {
        rod = rbCyl(context, id + "rod", o, rodBottom - RB_MM, tip + RB_MM, d.rodCore / 2 * RB_MM);
        const turns = ceil((tip + RB_MM - zStart) / pitch);
        const ridge = rbThread(context, id + "rodthread", zStart, turns, 1.55, 2.0, 0.607, 0.0875);
        rbUnite(context, id + "rodunite", qUnion([rod, ridge]));
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

    // Two M4 nuts with the matching internal thread
    var nuts = [];
    for (var i = 0; i < d.nuts; i += 1)
    {
        const top = z.nutTop - i * d.nutH * RB_MM;
        nuts = append(nuts, rbHex(context, id + ("nut" ~ i), top - d.nutH * RB_MM, top, d.nutAF * RB_MM));
    }
    var nutCuts = [rbCyl(context, id + "nutbore", o, z.nutBottom - RB_MM, z.nutTop + RB_MM, (threads ? 1.65 : 2.05) * RB_MM)];
    if (threads)
    {
        const zTap = zStart + floor((z.nutBottom - RB_MM - zStart) / pitch) * pitch;
        const turns = ceil((z.nutTop + RB_MM - zTap) / pitch);
        nutCuts = append(nutCuts, rbThread(context, id + "tap", zTap, turns, 1.62, 2.08, 0.642, 0.11));
    }
    rbSubtract(context, id + "nutcut", qUnion(nuts), qUnion(nutCuts));

    // Bearing MR85ZZ
    const bearing = rbCyl(context, id + "bearing", o, z.bearBottom, z.bearTop, d.bearOD / 2 * RB_MM);
    rbSubtract(context, id + "bearingcut", bearing, rbCyl(context, id + "bearinghole", o, z.bearBottom - RB_MM, z.bearTop + RB_MM,
            d.bearID / 2 * RB_MM));

    // N20 gearmotor with encoder, gearbox face up against the bulkhead
    const gearbox = rbCbox(context, id + "gearbox", o, d.motorW * RB_MM, d.motorH * RB_MM, z.motorFace - d.gearboxL * RB_MM, z.motorFace);
    const canTop = z.motorFace - d.gearboxL * RB_MM;
    const canBottom = canTop - d.canL * RB_MM;
    const can = rbCyl(context, id + "can", o, canBottom, canTop, d.motorW / 2 * RB_MM);
    const canBox = rbCbox(context, id + "canbox", o, d.motorW * RB_MM, d.motorH * RB_MM, canBottom - RB_MM, canTop + RB_MM);
    opBoolean(context, id + "canshape", { "tools" : qUnion([can, canBox]), "operationType" : BooleanOperationType.INTERSECTION });
    const encoder = rbCbox(context, id + "encoder", o, d.motorW * RB_MM, d.motorH * RB_MM, z.motorBottom, canBottom);
    const shaft = rbFlatted(context, id + "shaft", z.motorFace, z.shaftTop, d.shaftD / 2 * RB_MM, (2 * d.shaftFlat - d.shaftD) * RB_MM, true);
    rbUnite(context, id + "motorunite", qUnion([gearbox, can, encoder, shaft]));

    return [
            ["housing", housing, "Gehäuse", color(0.78, 0.80, 0.84, 0.35)],
            ["cap", cap, "Deckel mit Führung", color(0.96, 0.78, 0.25, 0.85)],
            ["tube", tube, "Rohr", color(0.92, 0.45, 0.18)],
            ["nuts", qUnion(nuts), "Mutter M4", color(0.62, 0.64, 0.68)],
            ["rod", rod, "Gewindestange M4", color(0.30, 0.31, 0.35)],
            ["bearing", bearing, "Kugellager MR85ZZ", color(0.45, 0.50, 0.58)],
            ["motor", gearbox, "N20 Motor mit Encoder", color(0.25, 0.42, 0.62)]
        ];
}

// -- Frame -----------------------------------------------------------------------------------------------
/** Base frame with floor, walls and cable slots, and a cover frame that holds the outer tiles down. */
function rbFrame(context is Context, id is Id, z is map, nx is number, ny is number, px is ValueWithUnits, py is ValueWithUnits)
{
    const d = RB;
    const hx = (d.motorW / 2 + d.pocketClear + d.wall) * RB_MM;
    const hy = (d.motorH / 2 + d.pocketClear + d.wall) * RB_MM;
    const c = d.frameClear * RB_MM;
    const w = d.frameWall * RB_MM;
    const ix0 = -hx - c;
    const iy0 = -hy - c;
    const ix1 = (nx - 1) * px + hx + c;
    const iy1 = (ny - 1) * py + hy + c;
    const base = rbBox(context, id + "base", ix0 - w, iy0 - w, z.floorBottom, ix1 + w, iy1 + w, 0 * RB_MM);
    var cuts = [rbBox(context, id + "inner", ix0, iy0, z.housingBottom, ix1, iy1, RB_MM)];
    for (var j = 0; j < ny; j += 1)
    {
        for (var i = 0; i < nx; i += 1)
        {
            cuts = append(cuts, rbCbox(context, id + ("cable" ~ i ~ "x" ~ j), vector(i * px, j * py), d.cableW * RB_MM, d.cableH * RB_MM,
                    z.floorBottom - RB_MM, z.housingBottom + RB_MM));
        }
    }
    const screws = [vector(ix0 - w / 2, iy0 - w / 2), vector(ix1 + w / 2, iy0 - w / 2), vector(ix0 - w / 2, iy1 + w / 2), vector(ix1 + w / 2, iy1 + w / 2)];
    for (var k = 0; k < 4; k += 1)
    {
        cuts = append(cuts, rbCyl(context, id + ("pilot" ~ k), screws[k], -d.screwDepth * RB_MM, RB_MM, d.screwPilot / 2 * RB_MM));
    }
    rbSubtract(context, id + "basecut", base, qUnion(cuts));
    rbFinish(context, base, "Grundrahmen", color(0.55, 0.57, 0.60, 0.5));

    const ov = d.coverOverlap * RB_MM;
    const cover = rbBox(context, id + "cover", ix0 - w, iy0 - w, 0 * RB_MM, ix1 + w, iy1 + w, d.coverT * RB_MM);
    var coverCuts = [rbBox(context, id + "window", ix0 + c + ov, iy0 + c + ov, -RB_MM, ix1 - c - ov, iy1 - c - ov, (d.coverT + 1) * RB_MM)];
    for (var k = 0; k < 4; k += 1)
    {
        coverCuts = append(coverCuts, rbCyl(context, id + ("clear" ~ k), screws[k], -RB_MM, (d.coverT + 1) * RB_MM, d.screwClear / 2 * RB_MM));
    }
    rbSubtract(context, id + "covercut", cover, qUnion(coverCuts));
    rbFinish(context, cover, "Abdeckrahmen", color(0.30, 0.32, 0.36));
}

// -- Clearance check -------------------------------------------------------------------------------------
function rbGap(context is Context, a is Query, b is Query) returns number
{
    return roundToPrecision(evDistance(context, { "side0" : a, "side1" : b }).distance / RB_MM, 3);
}

function rbReport(context is Context, id is Id, z is map, tiles is array, px is ValueWithUnits, py is ValueWithUnits)
{
    const u = tiles[0];
    var checks = [
        ["Rohr zu Gehäuse", rbGap(context, u.tube, u.housing), 0.25],
        ["Rohr zu Deckel", rbGap(context, u.tube, u.cap), 0.5],
        ["Muttern zu Deckel", rbGap(context, u.nuts, u.cap), 0.5],
        ["Stange zu Rohr", rbGap(context, u.rod, u.tube), 0.2],
        ["Stange zu Muttern (Gewindespiel)", rbGap(context, u.rod, u.nuts), 0.03],
        ["Stange zu Deckel (Führungsspiel)", rbGap(context, u.rod, u.cap), 0.03],
        ["Motor zu Rohr (D Welle)", rbGap(context, u.motor, u.tube), 0.03]
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
