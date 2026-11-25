# Builds the anti-roll / no-stand squeeze-bottle base in FreeCAD Part Design.
# Run inside FreeCAD (Macro > Macros... > Execute) or headless:
#   freecadcmd -c "exec(open('make_bottle_base.py').read())"
# Writes design/bottle_base.FCStd, design/bottle_base.stl, design/bottle_reference.stl
# All dimensions live in the "Params" spreadsheet - edit a cell and recompute.

import os
import FreeCAD as App
import Part
import Sketcher

HERE = os.path.dirname(os.path.abspath(__file__)) if "__file__" in globals() else os.getcwd()
OUT_DIR = os.path.join(HERE, "design")
os.makedirs(OUT_DIR, exist_ok=True)

# name, value (mm), note
PARAMS = [
    ("bottle_d",  30.5, "measured bottle diameter (1.2 in)"),
    ("clearance",  0.5, "pocket minus bottle; tune with a test ring"),
    ("wall",       3.0, "thinnest wall beside the pocket"),
    ("pocket_d",  None, "=bottle_d + clearance"),
    ("outer",     None, "=pocket_d + 2 * wall"),
    ("point_h",   17.0, "pyramid chamfer size"),
    ("floor",      6.0, "solid between pocket bottom and pyramid"),
    ("grip",      25.0, "how deep the bottle sits in the cap"),
    ("height",    None, "=point_h + floor + grip"),
    ("corner_r",   2.0, "fillet on the 4 vertical edges (0 = sharp)"),
    ("lead_in",    1.0, "chamfer on the pocket mouth"),
    # ---- bottle (ESTIMATES - replace with caliper measurements) ----
    ("overall_l", 167.6, "bottle bottom to needle end (6.6 in)"),
    ("body_h",    70.0, "straight squeezable section"),
    ("shoulder_h", 10.0, "taper from body to neck"),
    ("neck_d",    14.0, "threaded neck diameter"),
    ("neck_h",     6.0, "visible neck height"),
    ("cap_d",     18.0, "applicator cap diameter"),
    ("cap_h",     10.0, "straight part of cap"),
    ("nozzle_h",  10.0, "cone from cap to needle hub"),
    ("nozzle_d",   5.0, "needle hub diameter"),
    ("needle_d",   1.5, "stainless tip outer diameter"),
    ("needle_l",  None, "=overall_l - body_h - shoulder_h - neck_h - cap_h - nozzle_h"),
]

doc = App.newDocument("BottleBase")

# ---------- parameters spreadsheet ----------
ss = doc.addObject("Spreadsheet::Sheet", "Params")
ss.set("A1", "Name"); ss.set("B1", "Value (mm)"); ss.set("C1", "Note")
for i, (name, val, note) in enumerate(PARAMS, start=2):
    ss.set(f"A{i}", name)
    if val is None:
        ss.set(f"B{i}", note)          # formula
        ss.set(f"C{i}", "derived")
    else:
        ss.set(f"B{i}", str(val))
        ss.set(f"C{i}", note)
    ss.setAlias(f"B{i}", name)
doc.recompute()

body = doc.addObject("PartDesign::Body", "Body")
xy = [f for f in body.Origin.OriginFeatures if "XY" in f.Name or getattr(f, "Role", "") == "XY_Plane"][0]


def attach(sk, z_expr=None):
    sk.AttachmentSupport = [(xy, "")]
    sk.MapMode = "FlatFace"
    if z_expr:
        sk.setExpression(".AttachmentOffset.Base.z", z_expr)


# ---------- 1. square sketch, centred on origin ----------
sq = body.newObject("Sketcher::SketchObject", "SquareSketch")
attach(sq)
h = 10.0
pts = [App.Vector(-h, -h, 0), App.Vector(h, -h, 0), App.Vector(h, h, 0), App.Vector(-h, h, 0)]
for a, b in zip(pts, pts[1:] + pts[:1]):
    sq.addGeometry(Part.LineSegment(a, b), False)
cons = []
for i in range(4):
    cons.append(Sketcher.Constraint("Coincident", i, 2, (i + 1) % 4, 1))
cons += [
    Sketcher.Constraint("Horizontal", 0), Sketcher.Constraint("Horizontal", 2),
    Sketcher.Constraint("Vertical", 1), Sketcher.Constraint("Vertical", 3),
    Sketcher.Constraint("Symmetric", 0, 1, 1, 2, -1, 1),   # corners symmetric about origin
]
sq.addConstraint(cons)
iw = sq.addConstraint(Sketcher.Constraint("DistanceX", 0, 1, 0, 2, 2 * h))
ih = sq.addConstraint(Sketcher.Constraint("DistanceY", 1, 1, 1, 2, 2 * h))
sq.setExpression(f"Constraints[{iw}]", "Params.outer")
sq.setExpression(f"Constraints[{ih}]", "Params.outer")

# ---------- 2. pad ----------
pad = body.newObject("PartDesign::Pad", "Pad")
pad.Profile = sq
pad.setExpression("Length", "Params.height")
doc.recompute()

# ---------- 3. pyramid point: chamfer the 4 bottom edges ----------
def edges_where(shape, test):
    return [f"Edge{i}" for i, e in enumerate(shape.Edges, start=1) if test(e)]

bottom = edges_where(pad.Shape, lambda e: all(abs(v.Point.z) < 1e-6 for v in e.Vertexes))
point = body.newObject("PartDesign::Chamfer", "Point")
point.Base = (pad, bottom)
point.setExpression("Size", "Params.point_h")
doc.recompute()
last = point

# ---------- 4. optional rounded vertical corners ----------
if ss.get("corner_r") > 0:
    vert = edges_where(last.Shape, lambda e: len(e.Vertexes) == 2
                       and abs(e.Vertexes[0].Point.x - e.Vertexes[1].Point.x) < 1e-6
                       and abs(e.Vertexes[0].Point.y - e.Vertexes[1].Point.y) < 1e-6)
    fil = body.newObject("PartDesign::Fillet", "Corners")
    fil.Base = (last, vert)
    fil.setExpression("Radius", "Params.corner_r")
    doc.recompute()
    if fil.Shape.isNull() or not fil.Shape.isValid():
        print("Corner fillet failed - removing it")
        body.removeObject(fil); doc.removeObject(fil.Name); doc.recompute()
    else:
        last = fil

# ---------- 5. bottle pocket from the top face ----------
cs = body.newObject("Sketcher::SketchObject", "PocketSketch")
attach(cs, "Params.height")
cs.addGeometry(Part.Circle(App.Vector(0, 0, 0), App.Vector(0, 0, 1), 15), False)
cs.addConstraint(Sketcher.Constraint("Coincident", 0, 3, -1, 1))
idia = cs.addConstraint(Sketcher.Constraint("Diameter", 0, 30))
cs.setExpression(f"Constraints[{idia}]", "Params.pocket_d")

pocket = body.newObject("PartDesign::Pocket", "BottlePocket")
pocket.Profile = cs
pocket.setExpression("Length", "Params.grip")
doc.recompute()
last = pocket

# ---------- 6. lead-in chamfer on the pocket mouth ----------
if ss.get("lead_in") > 0:
    top_z = ss.get("height")
    mouth = edges_where(last.Shape, lambda e: isinstance(e.Curve, Part.Circle)
                        and abs(e.Curve.Center.z - top_z) < 1e-6)
    li = body.newObject("PartDesign::Chamfer", "LeadIn")
    li.Base = (last, mouth)
    li.setExpression("Size", "Params.lead_in")
    doc.recompute()
    last = li

body.Tip = last
doc.recompute()

# ---------- 7. the bottle: a stack of cylinders/cones in its own body ----------
bottle = doc.addObject("PartDesign::Body", "Bottle")
bxy = [f for f in bottle.Origin.OriginFeatures if "XY" in f.Name or getattr(f, "Role", "") == "XY_Plane"][0]
# sit the bottle on the pocket floor
bottle.setExpression(".Placement.Base.z", "Params.point_h + Params.floor")

z_parts = []  # running z expression for the start of each section
def stack(kind, name, height, r1, r2=None):
    f = bottle.newObject(f"PartDesign::Additive{kind}", name)
    f.AttachmentSupport = [(bxy, "")]
    f.MapMode = "FlatFace"
    if z_parts:
        f.setExpression(".AttachmentOffset.Base.z", " + ".join(z_parts))
    f.setExpression("Height", height)
    if kind == "Cylinder":
        f.setExpression("Radius", r1)
    else:
        f.setExpression("Radius1", r1)
        f.setExpression("Radius2", r2)
    z_parts.append(height)
    return f

stack("Cylinder", "BottleBody", "Params.body_h",    "Params.bottle_d / 2")
stack("Cone",     "Shoulder",   "Params.shoulder_h", "Params.bottle_d / 2", "Params.neck_d / 2")
stack("Cylinder", "Neck",       "Params.neck_h",     "Params.neck_d / 2")
stack("Cylinder", "Cap",        "Params.cap_h",      "Params.cap_d / 2")
stack("Cone",     "Nozzle",     "Params.nozzle_h",   "Params.cap_d / 2", "Params.nozzle_d / 2")
tip = stack("Cylinder", "Needle", "Params.needle_l", "Params.needle_d / 2")
bottle.Tip = tip
doc.recompute()

bs = bottle.Shape
print(f"bottle: valid={bs.isValid()} length={bs.BoundBox.ZLength:.1f} mm, needle_l={ss.get('needle_l'):.1f} mm")
print(f"bottle overlaps base: {bs.common(body.Shape).Volume:.3f} mm^3 (should be 0)")

# Lying on its side: the table touches the base's flat face at its top rim and
# the bottle body at its shoulder. How far is the needle end above the table?
half = ss.get("outer") / 2
z_rim = ss.get("height")
z_body_top = ss.get("point_h") + ss.get("floor") + ss.get("body_h")
z_end = ss.get("point_h") + ss.get("floor") + ss.get("overall_l")
slope = (half - ss.get("bottle_d") / 2) / (z_body_top - z_rim)
table_at_end = half - slope * (z_end - z_rim)          # table distance from axis
clear = table_at_end - ss.get("needle_d") / 2
print(f"on its side: needle end is {clear:.1f} mm above the table")

# ---------- report + export ----------
s = body.Shape
bb = s.BoundBox
print(f"valid={s.isValid()} solids={len(s.Solids)} volume={s.Volume:.0f} mm^3")
print(f"bbox: {bb.XLength:.2f} x {bb.YLength:.2f} x {bb.ZLength:.2f} mm")
print("features:", [o.Name for o in body.Group if o.TypeId.startswith("PartDesign::") or o.TypeId.startswith("Sketcher")])

doc.saveAs(os.path.join(OUT_DIR, "bottle_base.FCStd"))
import Mesh
Mesh.export([body], os.path.join(OUT_DIR, "bottle_base.stl"))
Mesh.export([bottle], os.path.join(OUT_DIR, "bottle_reference.stl"))
print("saved to", OUT_DIR)

# ---------- display settings (only when FreeCAD's GUI is loaded) ----------
# Show just the finished parts; hide sketches and intermediate features.
for b in (body, bottle):
    for o in b.Group:
        o.Visibility = (o == b.Tip)
    b.Visibility = True
ss.Visibility = False

if App.GuiUp:
    import FreeCADGui as Gui
    for b in (body, bottle):
        for o in b.Group:
            if o.ViewObject:
                o.ViewObject.Visibility = (o == b.Tip)
        b.ViewObject.Visibility = True
    body.ViewObject.ShapeAppearance = [App.Material(DiffuseColor=(0.20, 0.45, 0.85))]   # blue base
    body.ViewObject.Transparency = 55
    bottle.ViewObject.ShapeAppearance = [App.Material(DiffuseColor=(0.95, 0.95, 0.92))]  # white bottle
    view = Gui.ActiveDocument.ActiveView
    view.viewIsometric()
    view.fitAll()
    doc.save()
