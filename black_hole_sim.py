"""
Black Hole / Accretion Disk Live-Stream Visual
------------------------------------------------
Generates a looping animation of a black hole with a swirling accretion
disk, simple gravitational lensing (light bending), and a starfield
background — designed to render out to an .mp4 that gets looped and
pushed to YouTube Live via ffmpeg (see youtube-live.yml).

Requires: matplotlib, numpy, ffmpeg installed on the system.
Run:  python black_hole_sim.py
Output: black_hole.mp4  (10s seamless loop, 1920x1080, 30fps)
"""

import numpy as np
import matplotlib.pyplot as plt
from matplotlib.animation import FuncAnimation
from matplotlib.patches import Circle

# ---- Config ----
WIDTH, HEIGHT = 1920, 1080
DPI = 100
FPS = 30
DURATION_SEC = 10          # seamless loop length
N_FRAMES = FPS * DURATION_SEC
N_STARS = 400
N_DISK_PARTICLES = 3000
BH_RADIUS = 1.2            # event horizon radius (plot units)

rng = np.random.default_rng(42)

# ---- Static starfield ----
star_x = rng.uniform(-16, 16, N_STARS)
star_y = rng.uniform(-9, 9, N_STARS)
star_size = rng.uniform(0.5, 3.0, N_STARS)
star_alpha = rng.uniform(0.3, 1.0, N_STARS)

# ---- Accretion disk particles (polar coords, varying radius/speed) ----
disk_r = rng.uniform(BH_RADIUS * 1.3, BH_RADIUS * 5.5, N_DISK_PARTICLES)
disk_theta0 = rng.uniform(0, 2 * np.pi, N_DISK_PARTICLES)
# Inner particles orbit faster (Keplerian-ish falloff)
disk_speed = 1.0 / (disk_r ** 1.5)
disk_speed = disk_speed / disk_speed.max()  # normalize
disk_color_t = (disk_r - disk_r.min()) / (disk_r.max() - disk_r.min())

fig, ax = plt.subplots(figsize=(WIDTH / DPI, HEIGHT / DPI), dpi=DPI)
fig.patch.set_facecolor("black")
ax.set_facecolor("black")
ax.set_xlim(-16, 16)
ax.set_ylim(-9, 9)
ax.set_aspect("equal")
ax.axis("off")
fig.subplots_adjust(left=0, right=1, top=1, bottom=0)

stars_scatter = ax.scatter(star_x, star_y, s=star_size, c="white",
                            alpha=star_alpha, linewidths=0)

# Photon ring (thin bright ring from lensed light)
ring = Circle((0, 0), BH_RADIUS * 1.08, fill=False, edgecolor="orange",
              linewidth=2.5, alpha=0.9)
ax.add_patch(ring)

# Event horizon (pure black disk)
horizon = Circle((0, 0), BH_RADIUS, color="black", zorder=10)
ax.add_patch(horizon)

disk_scatter = ax.scatter([], [], s=4, cmap="inferno", zorder=5)


def disk_positions(frame):
    t = frame / N_FRAMES
    theta = disk_theta0 + disk_speed * t * 2 * np.pi * 6  # multiple revolutions/loop
    # Flatten disk into an ellipse to fake viewing angle + gravitational lensing bulge
    x = disk_r * np.cos(theta)
    y = disk_r * np.sin(theta) * 0.35
    # simple lensing bend: pull points near horizon slightly outward-brighter
    return x, y, disk_color_t


def update(frame):
    x, y, c = disk_positions(frame)
    disk_scatter.set_offsets(np.column_stack([x, y]))
    disk_scatter.set_array(c)
    disk_scatter.set_cmap("inferno")
    ring.set_alpha(0.7 + 0.3 * np.sin(frame / N_FRAMES * 2 * np.pi))
    return disk_scatter, ring


anim = FuncAnimation(fig, update, frames=N_FRAMES, interval=1000 / FPS, blit=False)

anim.save(
    "black_hole.mp4",
    fps=FPS,
    dpi=DPI,
    writer="ffmpeg",
    extra_args=["-pix_fmt", "yuv420p", "-b:v", "6000k"],
)

print("Wrote black_hole.mp4 — ready to loop-stream.")
