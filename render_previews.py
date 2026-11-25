# Renders the README pictures in docs/images/ from design/bottle_base.FCStd,
# with transparent backgrounds, cropped to the parts.
#
# Needs FreeCAD's GUI (it renders through the 3D view), but no window:
#   QT_QPA_PLATFORM=offscreen freecad render_previews.py
#   flatpak run --env=QT_QPA_PLATFORM=offscreen org.freecad.FreeCAD render_previews.py
#
# Offscreen, FreeCAD ignores camera commands and keeps the view saved in the
# file, so each shot rotates the *scene* to make that fixed camera see it from
# the angle we want.

import math
import os

import FreeCAD as App
import FreeCADGui as Gui
import Part
import numpy as np

try:
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QImage
except ImportError:
    from PySide2.QtCore import Qt
    from PySide2.QtGui import QImage

V = App.Vector
HERE = os.path.dirname(os.path.abspath(__file__))
MODEL = os.path.join(HERE, "design", "bottle_base.FCStd")
OUT = os.path.join(HERE, "docs", "images")

BLUE = (0.20, 0.45, 0.85)
TABLE = (0.62, 0.60, 0.56)


def camera(azimuth, elevation):
    """Camera orientation looking at the origin from the given direction (degrees).
    azimuth 0 = from -Y (front), positive turns toward +X."""
    a, e = math.radians(azimuth), math.radians(elevation)
    Z = V(math.sin(a) * math.cos(e), -math.cos(a) * math.cos(e), math.sin(e))
    X = V(0, 0, 1).cross(Z).normalize()
    Y = Z.cross(X)
    return App.Rotation(App.Matrix(X.x, Y.x, Z.x, 0, X.y, Y.y, Z.y, 0, X.z, Y.z, Z.z, 0, 0, 0, 0, 1))


def color(obj, rgb):
    obj.ViewObject.ShapeAppearance = [App.Material(DiffuseColor=rgb)]
    obj.ViewObject.Transparency = 0


def cutaway(shape, name, doc):
    """Keep the half of a shape with y >= 0 (the far side from a front camera)."""
    keep = Part.makeBox(1000, 500, 1000, V(-500, 0, -500))
    f = doc.addObject("Part::Feature", name)
    f.Shape = shape.common(keep)
    return f


def shoot(doc, objs, cam, filename, width=1400):
    view = Gui.getDocument(doc.Name).ActiveView
    T = App.Placement(V(0, 0, 0), view.getCameraOrientation().multiply(cam.inverted()))
    for o in objs:
        o.Placement = T.multiply(o.Placement)
    doc.recompute()
    view.fitAll()
    Gui.updateGui()
    path = os.path.join(OUT, filename)
    view.saveImage(path, 4200, 2800, "Transparent")  # big, then cropped
    crop(path, width)
    print("wrote", path)


def crop(path, width):
    img = QImage(path).convertToFormat(QImage.Format_ARGB32)
    w, h = img.width(), img.height()
    a = np.frombuffer(img.constBits(), np.uint8, count=img.sizeInBytes()) \
        .reshape(h, img.bytesPerLine())[:, : w * 4].reshape(h, w, 4)[:, :, 3]
    ys, xs = np.nonzero(a > 8)
    m = 24
    x0, y0 = max(xs.min() - m, 0), max(ys.min() - m, 0)
    x1, y1 = min(xs.max() + m, w - 1), min(ys.max() + m, h - 1)
    out = img.copy(int(x0), int(y0), int(x1 - x0 + 1), int(y1 - y0 + 1))
    if out.width() > width:
        out = out.scaledToWidth(width, Qt.SmoothTransformation)
    out.save(path)


def open_model():
    doc = App.openDocument(MODEL)
    Gui.updateGui()
    p = doc.getObject("Params")
    base, bottle = doc.getObject("Body"), doc.getObject("Bottle")
    z_b = bottle.Placement.Base.z
    bottle.setExpression(".Placement.Base.z", None)  # free it to move; file is never saved
    return doc, p, base, bottle, z_b


def shot_base():
    """The base alone, pointed end up."""
    doc, p, base, bottle, _ = open_model()
    bottle.ViewObject.Visibility = False
    base.Placement = App.Placement(V(0, 0, 0), App.Rotation(V(1, 0, 0), 180))
    doc.recompute()
    color(base, BLUE)
    shoot(doc, [base], camera(35, 28), "base.png", 900)
    App.closeDocument(doc.Name)


def shot_upright():
    """Cut-away of the bottle standing in the base (as it would if it could)."""
    doc, p, base, bottle, _ = open_model()
    cut = cutaway(base.Shape, "BaseCutaway", doc)
    base.ViewObject.Visibility = False
    color(cut, BLUE)
    shoot(doc, [cut, bottle], camera(20, 15), "assembly.png", 900)
    App.closeDocument(doc.Name)


def shot_lying():
    """Cut-away of the bottle lying on a table, resting on the base's flat face
    and the bottle's shoulder."""
    doc, p, base, bottle, z_b = open_model()
    half = p.get("outer") / 2
    tilt = math.degrees(math.atan((half - p.get("bottle_d") / 2) /
                                  (z_b + p.get("body_h") - p.get("height"))))
    rot = App.Rotation(V(0, 1, 0), 90 + tilt)
    base.Placement = App.Placement(V(0, 0, 0), rot)
    bottle.Placement = App.Placement(rot.multVec(V(0, 0, z_b)), rot)
    doc.recompute()
    cut = cutaway(base.Shape, "BaseCutaway", doc)
    base.ViewObject.Visibility = False
    zmin = min(base.Shape.BoundBox.ZMin, bottle.Shape.BoundBox.ZMin)
    bb = base.Shape.BoundBox.united(bottle.Shape.BoundBox)
    table = doc.addObject("Part::Feature", "Table")
    table.Shape = Part.makeBox(bb.XLength + 50, 110, 3, V(bb.XMin - 25, -55, zmin - 3))
    doc.recompute()
    color(cut, BLUE)
    color(table, TABLE)
    shoot(doc, [cut, bottle, table], camera(20, 25), "lying-on-table.png", 1400)
    App.closeDocument(doc.Name)


os.makedirs(OUT, exist_ok=True)
# FreeCAD's GUI swallows stdout, so report to a log file as well
import traceback
with open(os.path.join(HERE, "render_previews.log"), "w") as log:
    for shot in (shot_base, shot_upright, shot_lying):
        try:
            shot()
            log.write(f"ok   {shot.__name__}\n")
        except Exception:
            log.write(f"FAIL {shot.__name__}\n{traceback.format_exc()}\n")
os._exit(0)  # quit FreeCAD's GUI
