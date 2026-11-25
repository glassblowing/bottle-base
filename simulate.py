#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10,<3.13"
# dependencies = ["pybullet", "numpy", "trimesh", "scipy"]
# ///
"""Physics test of the bottle + base assembly with PyBullet.

Units: centimetres, grams, seconds (gravity 981 cm/s^2) - keeps Bullet's
collision margins small relative to the 3 mm tip.

Tests
  1. Standing on the point: released upright with a small tilt. Does it fall?
  2. Random drops: tossed onto the table in random orientations. Where does it end up?
  3. Lying on its side: flicked with a spin about its long axis. Does it roll?
  4. Baseline: the bare bottle (no base) under the same tests.

Run: ./simulate.py   (uv installs the dependencies; takes about a minute)
"""
import math, os, sys, tempfile
import numpy as np
import pybullet as p
import trimesh

HERE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "design")
MM = 0.1  # mm -> cm

# ---- geometry / mass assumptions (match the FreeCAD Params sheet) ----
POCKET_FLOOR = 23.0      # mm, bottle bottom height inside base
BOTTLE_D = 30.5
BODY_H = 70.0
WALL_T = 1.0             # bottle wall, mm (for liquid inner radius)
BASE_MASS = 25.0         # g  PLA, ~3 perimeters + 20 % infill
BOTTLE_SHELL = 7.0       # g  LDPE bottle
CAP_NEEDLE = 4.0         # g  cap + stainless needle, near the top
LIQUID_DENSITY = 1.0     # g/cm^3
FILL = {"empty": 0.0, "half": 0.5, "full": 1.0}


def load(name):
    m = trimesh.load(os.path.join(HERE, name))
    m.apply_scale(MM)
    return m


def mass_props(with_base, fill):
    """Return total mass, COM, inertia tensor (about COM) in body frame."""
    parts = []  # (mesh, mass)
    bottle = load("bottle_reference.stl")
    parts.append((bottle, BOTTLE_SHELL))
    z0 = POCKET_FLOOR * MM if with_base else bottle.bounds[0][2]
    cap = trimesh.creation.cylinder(radius=0.9, height=2.6)          # cap + nozzle
    cap.apply_translation([0, 0, z0 + (BODY_H + 16 + 13) * MM])
    parts.append((cap, CAP_NEEDLE))
    if fill > 0:
        r = (BOTTLE_D / 2 - WALL_T) * MM
        h = (BODY_H - 2) * MM * fill
        liq = trimesh.creation.cylinder(radius=r, height=h)
        liq.apply_translation([0, 0, z0 + 0.1 + h / 2])
        parts.append((liq, liq.volume * LIQUID_DENSITY))
    if with_base:
        parts.append((load("bottle_base.stl"), BASE_MASS))

    M = sum(m for _, m in parts)
    com = sum(m * mesh.center_mass for mesh, m in parts) / M
    I = np.zeros((3, 3))
    for mesh, m in parts:
        mesh = mesh.copy()
        mesh.density = m / mesh.volume
        I += mesh.moment_inertia_frame(trimesh.transformations.translation_matrix(com))
    return M, com, I


def make_body(with_base, fill, pos, orn):
    meshes = [load("bottle_reference.stl")]
    if with_base:
        meshes.append(load("bottle_base.stl"))
    else:  # put bare bottle's bottom at z=0 like the assembly frame
        pass
    hull = trimesh.util.concatenate(meshes).convex_hull
    M, com, I = mass_props(with_base, fill)
    # collision shape expressed relative to COM (Bullet's inertial frame)
    hull.apply_translation(-com)
    f = tempfile.NamedTemporaryFile(suffix=".obj", delete=False)
    hull.export(f.name)
    col = p.createCollisionShape(p.GEOM_MESH, fileName=f.name)
    body = p.createMultiBody(baseMass=M, baseCollisionShapeIndex=col,
                             basePosition=pos, baseOrientation=orn)
    p.changeDynamics(body, -1, localInertiaDiagonal=list(np.diag(I)),  # axes aligned by symmetry
                     lateralFriction=0.5, rollingFriction=0.0, spinningFriction=0.0,
                     restitution=0.1, linearDamping=0.0, angularDamping=0.0)
    return body, M, com, hull


def world():
    p.resetSimulation()
    p.setGravity(0, 0, -981)
    p.setTimeStep(1 / 2000)
    p.setPhysicsEngineParameter(numSolverIterations=100)
    plane = p.createCollisionShape(p.GEOM_PLANE)
    fl = p.createMultiBody(0, plane)
    p.changeDynamics(fl, -1, lateralFriction=0.5, restitution=0.1)


def settle(body, max_t=6.0):
    steps = int(max_t * 2000)
    for i in range(steps):
        p.stepSimulation()
        if i > 2000 and i % 200 == 0:
            v, w = p.getBaseVelocity(body)
            if np.linalg.norm(v) < 0.05 and np.linalg.norm(w) < 0.02:
                break
    return state(body)


def state(body):
    pos, orn = p.getBasePositionAndOrientation(body)
    R = np.array(p.getMatrixFromQuaternion(orn)).reshape(3, 3)
    axis_up = R[:, 2][2]                       # bottle axis . world up
    if axis_up > 0.9:
        return "STANDING upright"
    if axis_up < -0.9:
        return "standing on its head"
    if abs(axis_up) < 0.35:
        # which local direction points down? flat face => +-x or +-y within ~10 deg
        down = R.T @ np.array([0, 0, -1.0])
        ang = math.degrees(math.atan2(down[1], down[0])) % 90
        flat = min(ang, 90 - ang) < 10
        return "on its side, flat face down" if flat else "on its side, on a corner/round"
    return f"leaning ({math.degrees(math.acos(max(-1,min(1,axis_up)))):.0f} deg from vertical)"


def upright_test(with_base, fill, tilt_deg):
    world()
    M, com, I = mass_props(with_base, fill)
    orn = p.getQuaternionFromEuler([math.radians(tilt_deg), 0, 0])
    # place lowest hull point just above the floor
    body, _, _, hull = make_body(with_base, fill, [0, 0, 50], orn)
    R = np.array(p.getMatrixFromQuaternion(orn)).reshape(3, 3)
    lowest = (hull.vertices @ R.T)[:, 2].min()
    p.resetBasePositionAndOrientation(body, [0, 0, -lowest + 0.01], orn)
    return settle(body)


def random_drop(with_base, fill, rng):
    world()
    q = trimesh.transformations.random_quaternion(rng.random(3))  # w,x,y,z
    orn = [q[1], q[2], q[3], q[0]]
    body, _, _, hull = make_body(with_base, fill, [0, 0, 50], orn)
    R = np.array(p.getMatrixFromQuaternion(orn)).reshape(3, 3)
    lowest = (hull.vertices @ R.T)[:, 2].min()
    p.resetBasePositionAndOrientation(body, [0, 0, -lowest + rng.uniform(0.5, 5)], orn)
    p.resetBaseVelocity(body, [0, 0, 0], list(rng.normal(0, 3, 3)))
    return settle(body)


def roll_test(with_base, fill, spin):
    """Lay it flat-face-down, then spin it about its long axis (rad/s)."""
    world()
    orn = p.getQuaternionFromEuler([math.radians(90), 0, 0])
    body, _, com, hull = make_body(with_base, fill, [0, 0, 50], orn)
    R = np.array(p.getMatrixFromQuaternion(orn)).reshape(3, 3)
    lowest = (hull.vertices @ R.T)[:, 2].min()
    p.resetBasePositionAndOrientation(body, [0, 0, -lowest + 0.01], orn)
    for _ in range(2000):
        p.stepSimulation()                       # let it settle first
    start, orn0 = p.getBasePositionAndOrientation(body)
    axis = np.array(p.getMatrixFromQuaternion(orn0)).reshape(3, 3)[:, 2]
    p.resetBaseVelocity(body, [0, 0, 0], list(axis * spin))
    settle(body)
    end, _ = p.getBasePositionAndOrientation(body)
    return np.linalg.norm(np.array(end[:2]) - np.array(start[:2])) * 10  # mm travelled


def main():
    p.connect(p.DIRECT)
    rng = np.random.default_rng(1)

    print("\n=== mass model ===")
    for label, wb in (("with base", True), ("bare bottle", False)):
        for name, f in FILL.items():
            M, com, _ = mass_props(wb, f)
            bottom = 0.0 if wb else POCKET_FLOOR
            print(f"{label:12s} {name:5s}: {M:5.1f} g, centre of mass {com[2]*10 - bottom:5.1f} mm "
                  f"above {'the base tip' if wb else 'the bottle bottom'}")

    print("\n=== 1. released upright with a small tilt ===")
    for wb in (True, False):
        for name, f in FILL.items():
            res = [upright_test(wb, f, t) for t in (0.5, 1, 2, 5)]
            print(f"{'base' if wb else 'bare':4s} {name:5s}: " +
                  ", ".join(f"{t}deg -> {r.split(',')[0]}" for t, r in zip((0.5, 1, 2, 5), res)))

    print("\n=== 2. 60 random drops each ===")
    for wb in (True, False):
        for name, f in FILL.items():
            counts = {}
            for _ in range(60):
                r = random_drop(wb, f, rng)
                counts[r] = counts.get(r, 0) + 1
            print(f"{'base' if wb else 'bare':4s} {name:5s}: {counts}")

    print("\n=== 3. lying down, flicked with a spin about its long axis ===")
    for wb in (True, False):
        for name, f in FILL.items():
            out = [roll_test(wb, f, s) for s in (2, 5, 10, 20)]
            print(f"{'base' if wb else 'bare':4s} {name:5s}: " +
                  ", ".join(f"{s} rad/s -> {d:.0f} mm" for s, d in zip((2, 5, 10, 20), out)))
    p.disconnect()


if __name__ == "__main__":
    main()
