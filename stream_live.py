"""
Black Hole Live Stream — with live YouTube chat + real space data overlays
----------------------------------------------------------------------------
Renders the black hole animation frame-by-frame in real time (instead of a
pre-baked loop) and burns in:
  - the latest YouTube live chat message + author
  - live space stats: current ISS position, today's near-Earth asteroid count

Frames are written as raw RGB bytes directly to ffmpeg's stdin, which pushes
them to YouTube over RTMP. Two background threads poll the YouTube Chat API
and the space-data APIs on their own schedule (a few seconds apart) so they
never block the render loop — only the shared `state` dict is touched.

ENV VARS REQUIRED:
  YOUTUBE_STREAM_KEY   - your RTMP stream key from YouTube Studio > Go Live
  YOUTUBE_API_KEY      - a YouTube Data API v3 key (console.cloud.google.com)
  YOUTUBE_VIDEO_ID     - the video ID of your live broadcast (from the
                          YouTube Studio URL once you've created the stream)

Install: pip install numpy matplotlib requests google-api-python-client
Run:     python stream_live.py
"""

import os
import time
import threading
import subprocess
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Circle, Rectangle
import requests
from scipy.io import wavfile

# ---------------- Config ----------------
WIDTH, HEIGHT = 1024, 576   # trimmed from 1280x720 for real-time headroom
FPS = 18                     # trimmed from 20 — blitting below should recover most of this, but leaving margin
DPI = 100
BH_RADIUS = 1.2
N_DISK_PARTICLES = 1000     # trimmed from 1500

STREAM_KEY = os.environ["YOUTUBE_STREAM_KEY"]
API_KEY = os.environ.get("YOUTUBE_API_KEY")
VIDEO_ID = os.environ.get("YOUTUBE_VIDEO_ID")

RTMP_URL = f"rtmp://a.rtmp.youtube.com/live2/{STREAM_KEY}"

# Shared, thread-safe-enough state (single writer per key; GIL covers us for
# simple dict item assignment of small values).
state = {
    "chat_author": "",
    "chat_text": "Waiting for chat...",
    "iss_lat": None,
    "iss_lon": None,
    "asteroid_count": None,
}

# ---------------- "Did you know" fact rotation ----------------
# Shown continuously, cycling every FACT_INTERVAL_SEC — keeps the screen
# from feeling static during quiet chat stretches.
FACT_INTERVAL_SEC = 15
BLACK_HOLE_FACTS = [
    "A black hole's event horizon is the point past which not even light can escape.",
    "Sagittarius A*, our galaxy's central black hole, has a mass ~4 million times the Sun's.",
    "Time slows down near a black hole — a effect called gravitational time dilation.",
    "The first-ever image of a black hole (M87*) was released in 2019 by the Event Horizon Telescope.",
    "Stellar-mass black holes form when massive stars collapse at the end of their lives.",
    "Black holes can 'evaporate' over immense timescales via Hawking radiation.",
    "Spinning black holes drag spacetime around with them — an effect called frame-dragging.",
    "Supermassive black holes sit at the center of nearly every large galaxy, including ours.",
    "Nothing marks the event horizon in space — an astronaut crossing it wouldn't feel a boundary.",
    "Two black holes merging release more energy in a fraction of a second than the entire visible universe.",
    # Moons & dwarf planets
    "Jupiter's moon Europa may hide a liquid ocean beneath its icy crust — a top target in the search for life.",
    "Pluto was reclassified as a dwarf planet in 2006, alongside Eris, Ceres, Haumea, and Makemake.",
    # Supernovae, magnetars, gamma-ray bursts
    "A supernova can briefly outshine its entire host galaxy before fading over weeks.",
    "Magnetars have magnetic fields trillions of times stronger than Earth's — strong enough to distort atoms.",
    "Gamma-ray bursts release more energy in seconds than the Sun will over its entire lifetime.",
    # Diffuse / large-scale structure
    "Dark matter makes up about 27% of the universe, but has never been directly observed — only its gravity.",
    "Galaxies aren't scattered randomly — they're strung along vast cosmic filaments, like a web.",
    "Cosmic voids are enormous nearly-empty regions of space, some spanning hundreds of millions of light-years.",
    "The cosmic microwave background is leftover light from just 380,000 years after the Big Bang.",
    "Cosmic rays are high-energy particles, some originating from outside our galaxy entirely.",
    "Stellar winds are streams of charged particles blown off stars, shaping the space around them.",
    "The space between stars isn't empty — it's filled with thin interstellar gas and dust.",
    "Galaxy clusters are the largest gravitationally-bound structures in the universe, holding thousands of galaxies.",
]

# ---------------- Background: poll live chat ----------------
def poll_chat():
    if not (API_KEY and VIDEO_ID):
        return
    from googleapiclient.discovery import build
    youtube = build("youtube", "v3", developerKey=API_KEY)

    # Resolve the active liveChatId from the broadcast video
    resp = youtube.videos().list(part="liveStreamingDetails", id=VIDEO_ID).execute()
    items = resp.get("items", [])
    if not items:
        return
    live_chat_id = items[0]["liveStreamingDetails"].get("activeLiveChatId")
    if not live_chat_id:
        return

    next_page = None
    while True:
        try:
            resp = youtube.liveChatMessages().list(
                liveChatId=live_chat_id,
                part="snippet,authorDetails",
                pageToken=next_page,
            ).execute()
            for item in resp.get("items", []):
                state["chat_author"] = item["authorDetails"]["displayName"]
                state["chat_text"] = item["snippet"]["displayMessage"]
            next_page = resp.get("nextPageToken")
            poll_interval = resp.get("pollingIntervalMillis", 5000) / 1000
        except Exception as e:
            print("chat poll error:", e)
            poll_interval = 10
        time.sleep(poll_interval)


# ---------------- Background: poll live space data ----------------
def poll_space_data():
    while True:
        try:
            iss = requests.get("http://api.open-notify.org/iss-now.json", timeout=5).json()
            pos = iss["iss_position"]
            state["iss_lat"] = float(pos["latitude"])
            state["iss_lon"] = float(pos["longitude"])
        except Exception as e:
            print("ISS fetch error:", e)

        nasa_key = os.environ.get("NASA_API_KEY", "DEMO_KEY")
        try:
            today = time.strftime("%Y-%m-%d")
            r = requests.get(
                "https://api.nasa.gov/neo/rest/v1/feed",
                params={"start_date": today, "end_date": today, "api_key": nasa_key},
                timeout=10,
            ).json()
            state["asteroid_count"] = r.get("element_count")
        except Exception as e:
            print("NASA fetch error:", e)

        time.sleep(60)  # refresh every minute — plenty for a slowly-changing stat


# ---------------- Rendering ----------------
rng = np.random.default_rng(1)
star_x = rng.uniform(-11, 11, 300)
star_y = rng.uniform(-6, 6, 300)
disk_r = rng.uniform(BH_RADIUS * 1.3, BH_RADIUS * 5.5, N_DISK_PARTICLES)
disk_theta0 = rng.uniform(0, 2 * np.pi, N_DISK_PARTICLES)
disk_speed = (1.0 / (disk_r ** 1.5))
disk_speed /= disk_speed.max()
# Temperature: hot white-blue near the horizon, cooling to deep red/orange
# further out. We build a custom colormap instead of a stock one so the
# inner edge reads as "white-hot" rather than just bright yellow.
from matplotlib.colors import LinearSegmentedColormap
TEMP_CMAP = LinearSegmentedColormap.from_list(
    "accretion_temp",
    ["#ffffff", "#bfe1ff", "#ffd27f", "#ff8a3d", "#8a1d00"],
)
disk_temp = (disk_r - disk_r.min()) / (disk_r.max() - disk_r.min())  # 0=hot/inner, 1=cool/outer

# Split disk particles into a "near-side halo" copy that renders as a thin
# arc above/below the black hole — approximating light from the far side of
# the disk bending over the poles (the effect that gives Gargantua its
# signature halo look).
halo_mask = rng.random(N_DISK_PARTICLES) < 0.35  # subset used for the lensed arc

fig, ax = plt.subplots(figsize=(WIDTH / DPI, HEIGHT / DPI), dpi=DPI)
fig.patch.set_facecolor("black")
ax.set_facecolor("black")
ax.set_xlim(-11, 11)
ax.set_ylim(-6, 6)
ax.set_aspect("equal")
ax.axis("off")
fig.subplots_adjust(left=0, right=1, top=1, bottom=0)

ax.scatter(star_x, star_y, s=1.5, c="white", alpha=0.7, linewidths=0)
ring = Circle((0, 0), BH_RADIUS * 1.08, fill=False, edgecolor="#ffe4b3", linewidth=2, alpha=0.9)
ax.add_patch(ring)
ax.add_patch(Circle((0, 0), BH_RADIUS, color="black", zorder=10))
disk_scatter = ax.scatter([], [], s=3, zorder=5)
halo_scatter = ax.scatter([], [], s=2.5, zorder=6)  # lensed arc, drawn over the horizon

# ---------------- Extra background objects (decorative, labeled) ----------------
# Companion star — a fixed bright point with a soft glow, upper right.
COMPANION_POS = (7.8, 3.6)
COMPANION_NAME = "HD-227 Companion Star"
for radius, alpha in [(0.45, 0.08), (0.28, 0.15), (0.14, 0.35), (0.06, 0.9)]:
    ax.add_patch(Circle(COMPANION_POS, radius, color="#bfe1ff", alpha=alpha, zorder=3))
ax.text(COMPANION_POS[0], COMPANION_POS[1] - 0.7, COMPANION_NAME,
        color="#bfe1ff", fontsize=8, family="monospace", ha="center", zorder=3)

# Distant nebula — soft translucent cluster, lower left.
NEBULA_CENTER = (-8.3, -3.4)
NEBULA_NAME = "Helix Remnant Nebula"
neb_rng = np.random.default_rng(7)
neb_x = NEBULA_CENTER[0] + neb_rng.normal(0, 1.1, 220)
neb_y = NEBULA_CENTER[1] + neb_rng.normal(0, 0.7, 220)
neb_colors = neb_rng.choice(["#ff8a3d", "#c96bff", "#ff5f8a"], size=220)
ax.scatter(neb_x, neb_y, s=neb_rng.uniform(6, 22, 220), c=neb_colors,
           alpha=0.12, linewidths=0, zorder=2)
ax.text(NEBULA_CENTER[0], NEBULA_CENTER[1] - 1.9, NEBULA_NAME,
        color="#c96bff", fontsize=8, family="monospace", ha="center", zorder=3)

# Rogue planet — small object that slowly drifts across the upper frame.
PLANET_NAME = "Rogue Planet Kepler-X"
planet_dot = ax.scatter([], [], s=40, c="#8fd694", zorder=7)
planet_ring = Circle((0, 0), 0.14, fill=False, edgecolor="#8fd694", linewidth=1, alpha=0.6, zorder=7)
ax.add_patch(planet_ring)
planet_label = ax.text(0, 0, PLANET_NAME, color="#8fd694", fontsize=8,
                        family="monospace", ha="center", va="bottom", zorder=7)

# Pulsar — fixed point, lower right, blinks on a steady rhythm.
PULSAR_POS = (9.0, -4.3)
PULSAR_NAME = "PSR B0611+22 Pulsar"
pulsar_glow = Circle(PULSAR_POS, 0.35, color="#ffffff", alpha=0.15, zorder=3)
ax.add_patch(pulsar_glow)
pulsar_dot = ax.scatter([PULSAR_POS[0]], [PULSAR_POS[1]], s=25, c="#ffffff", zorder=7)
ax.text(PULSAR_POS[0], PULSAR_POS[1] - 0.5, PULSAR_NAME,
        color="#ffffff", fontsize=8, family="monospace", ha="center", zorder=3)

# Distant spiral galaxy — small faint spiral smudge, upper left corner.
GALAXY_CENTER = (-9.2, 4.6)
GALAXY_NAME = "NGC-994 Spiral Galaxy"
gal_rng = np.random.default_rng(13)
gal_arm_t = gal_rng.uniform(0, 4 * np.pi, 260)
gal_r = 0.05 + gal_arm_t * 0.045
gal_x = GALAXY_CENTER[0] + gal_r * np.cos(gal_arm_t) + gal_rng.normal(0, 0.04, 260)
gal_y = GALAXY_CENTER[1] + gal_r * np.sin(gal_arm_t) * 0.5 + gal_rng.normal(0, 0.04, 260)
ax.scatter(gal_x, gal_y, s=gal_rng.uniform(2, 6, 260), c="#d9c9ff",
           alpha=0.35, linewidths=0, zorder=3)
ax.text(GALAXY_CENTER[0], GALAXY_CENTER[1] + 0.75, GALAXY_NAME,
        color="#d9c9ff", fontsize=8, family="monospace", ha="center", zorder=3)

# Comet — drifts slowly across the lower frame with a trailing tail.
COMET_NAME = "Icarus Comet"
comet_head = ax.scatter([], [], s=18, c="#ffe9b3", zorder=7)
comet_tail = ax.scatter([], [], s=6, c="#ffe9b3", zorder=6)
comet_label = ax.text(0, 0, COMET_NAME, color="#ffe9b3", fontsize=8,
                       family="monospace", ha="center", va="top", zorder=7)

# Star cluster — tight group of small white/blue points, top band.
CLUSTER_CENTER = (-3.5, 5.1)
CLUSTER_NAME = "M-12 Star Cluster"
clu_rng = np.random.default_rng(21)
clu_x = CLUSTER_CENTER[0] + clu_rng.normal(0, 0.35, 35)
clu_y = CLUSTER_CENTER[1] + clu_rng.normal(0, 0.22, 35)
ax.scatter(clu_x, clu_y, s=clu_rng.uniform(3, 9, 35), c="#eaf3ff",
           alpha=0.85, linewidths=0, zorder=3)
ax.text(CLUSTER_CENTER[0], CLUSTER_CENTER[1] + 0.55, CLUSTER_NAME,
        color="#eaf3ff", fontsize=8, family="monospace", ha="center", zorder=3)

# Supernova remnant — slowly pulsing colorful shell, top band.
REMNANT_CENTER = (1.5, 5.1)
REMNANT_NAME = "Supernova Remnant SN-1181"
remnant_ring = Circle(REMNANT_CENTER, 0.3, fill=False, edgecolor="#ff6ec7",
                       linewidth=1.5, alpha=0.6, zorder=3)
ax.add_patch(remnant_ring)
ax.text(REMNANT_CENTER[0], REMNANT_CENTER[1] + 0.55, REMNANT_NAME,
        color="#ff6ec7", fontsize=8, family="monospace", ha="center", zorder=3)

# Protoplanetary disk — young star with a small flattened ring of debris, top band.
PROTO_CENTER = (6.0, 5.1)
PROTO_NAME = "TW Hya Protoplanetary Disk"
proto_rng = np.random.default_rng(29)
proto_theta = proto_rng.uniform(0, 2 * np.pi, 60)
proto_r = proto_rng.uniform(0.15, 0.32, 60)
proto_x = PROTO_CENTER[0] + proto_r * np.cos(proto_theta)
proto_y = PROTO_CENTER[1] + proto_r * np.sin(proto_theta) * 0.35
ax.scatter(proto_x, proto_y, s=4, c="#ffcf8a", alpha=0.7, linewidths=0, zorder=3)
ax.scatter([PROTO_CENTER[0]], [PROTO_CENTER[1]], s=25, c="#ffffff", zorder=4)
ax.text(PROTO_CENTER[0], PROTO_CENTER[1] + 0.5, PROTO_NAME,
        color="#ffcf8a", fontsize=8, family="monospace", ha="center", zorder=3)

# Asteroid field — scattered small rocky dots, bottom-right corner.
ASTEROID_CENTER = (6.3, -5.4)
ASTEROID_NAME = "Asteroid Field"
ast_rng = np.random.default_rng(33)
ast_x = ASTEROID_CENTER[0] + ast_rng.uniform(-1.4, 1.4, 45)
ast_y = ASTEROID_CENTER[1] + ast_rng.uniform(-0.3, 0.3, 45)
ax.scatter(ast_x, ast_y, s=ast_rng.uniform(2, 6, 45), c="#a89a86",
           alpha=0.75, linewidths=0, zorder=3)
ax.text(ASTEROID_CENTER[0], ASTEROID_CENTER[1] - 0.45, ASTEROID_NAME,
        color="#a89a86", fontsize=8, family="monospace", ha="center", zorder=3)

# Neutron star — tiny, extremely bright pinpoint, mid-left (outside the disk).
NEUTRON_POS = (-9.0, 0.0)
NEUTRON_NAME = "Neutron Star RX-3"
neutron_glow = Circle(NEUTRON_POS, 0.18, color="#cfe8ff", alpha=0.2, zorder=3)
ax.add_patch(neutron_glow)
neutron_dot = ax.scatter([NEUTRON_POS[0]], [NEUTRON_POS[1]], s=14, c="#ffffff", zorder=7)
ax.text(NEUTRON_POS[0], NEUTRON_POS[1] - 0.4, NEUTRON_NAME,
        color="#cfe8ff", fontsize=8, family="monospace", ha="center", zorder=3)

# Quasar — bright core with two thin opposing jets, mid-right (outside the disk).
QUASAR_POS = (9.0, 0.0)
QUASAR_NAME = "Quasar 3C-99"
quasar_glow = Circle(QUASAR_POS, 0.4, color="#c9a3ff", alpha=0.15, zorder=3)
ax.add_patch(quasar_glow)
quasar_core = ax.scatter([QUASAR_POS[0]], [QUASAR_POS[1]], s=20, c="#e9d9ff", zorder=7)
ax.plot([QUASAR_POS[0] - 0.9, QUASAR_POS[0] + 0.9],
        [QUASAR_POS[1], QUASAR_POS[1]], color="#c9a3ff", linewidth=1, alpha=0.6, zorder=3)
ax.text(QUASAR_POS[0], QUASAR_POS[1] - 0.5, QUASAR_NAME,
        color="#c9a3ff", fontsize=8, family="monospace", ha="center", zorder=3)

chat_text_obj = ax.text(-10.6, -5.4, "", color="white", fontsize=10,
                         family="monospace", va="bottom")
data_text_obj = ax.text(-10.6, 5.0, "", color="#7fd8ff", fontsize=10,
                         family="monospace", va="top")
fact_text_obj = ax.text(0, -4.6, "", color="#ffd27f", fontsize=10,
                         family="monospace", va="top", ha="center", wrap=True)

# ---------------- Audio-reactive visualizer ----------------
# Lets viewers *see* the ambient soundtrack, not just hear it — a small bar
# visualizer driven by the actual audio samples playing at that moment.
N_BARS = 24
VIS_BASELINE_Y = -5.75
VIS_MAX_HEIGHT = 0.55
bar_x = np.linspace(-4.2, 4.2, N_BARS)
bar_width = (8.4 / N_BARS) * 0.7
bar_patches = []
for bx in bar_x:
    rect = Rectangle((bx - bar_width / 2, VIS_BASELINE_Y), bar_width, 0.01,
                      color="#7fd8ff", alpha=0.85, zorder=8)
    ax.add_patch(rect)
    bar_patches.append(rect)
ax.text(0, VIS_BASELINE_Y - 0.25, "LIVE AUDIO", color="#7fd8ff", fontsize=7,
        family="monospace", ha="center", zorder=8, alpha=0.6)

# Audio data + smoothing state, populated in main() once the ambient wav
# exists. bar_smooth persists across frames for less jittery motion.
audio_samples = None   # mono float array, set in main()
audio_sr = 44100
audio_duration = None
bar_smooth = np.zeros(N_BARS)
FFT_WINDOW = 2048
BAND_EDGES = np.logspace(np.log10(30), np.log10(6000), N_BARS + 1)


def compute_bar_heights(frame_idx):
    """Read the audio samples that correspond to this video frame's timestamp
    and turn them into N_BARS smoothed frequency-band heights."""
    global bar_smooth
    if audio_samples is None:
        return bar_smooth  # no audio loaded yet — keep bars flat
    t_sec = (frame_idx / FPS) % audio_duration
    start = int(t_sec * audio_sr)
    idx = (start + np.arange(FFT_WINDOW)) % len(audio_samples)
    segment = audio_samples[idx] * np.hanning(FFT_WINDOW)
    mag = np.abs(np.fft.rfft(segment))
    freqs = np.fft.rfftfreq(FFT_WINDOW, d=1 / audio_sr)
    raw = np.zeros(N_BARS)
    for i in range(N_BARS):
        mask = (freqs >= BAND_EDGES[i]) & (freqs < BAND_EDGES[i + 1])
        raw[i] = mag[mask].mean() if mask.any() else 0.0
    raw = np.log1p(raw)
    raw = raw / (raw.max() + 1e-9) * VIS_MAX_HEIGHT
    bar_smooth = 0.65 * bar_smooth + 0.35 * raw
    return bar_smooth


# --- One-time setup for blitting ---
# Everything static (starfield, nebula, galaxy, star cluster, asteroid field,
# protoplanetary disk dots, quasar glow/jets, companion star) gets rendered
# once here and cached as `background`. Only the artists in DYNAMIC_ARTISTS
# get redrawn per frame, which is what makes real-time rendering fast enough
# to keep pace with FPS.
DYNAMIC_ARTISTS = [
    ring, disk_scatter, halo_scatter,
    remnant_ring, neutron_dot,
    pulsar_dot, pulsar_glow,
    planet_dot, planet_ring, planet_label,
    comet_head, comet_tail, comet_label,
    chat_text_obj, data_text_obj, fact_text_obj,
    *bar_patches,
]
for artist in DYNAMIC_ARTISTS:
    artist.set_animated(True)

fig.canvas.draw()
background = fig.canvas.copy_from_bbox(ax.bbox)


def render_frame(frame_idx):
    t = frame_idx / (FPS * 10)  # 10s revolution cycle
    theta = disk_theta0 + disk_speed * t * 2 * np.pi * 6
    x = disk_r * np.cos(theta)
    y = disk_r * np.sin(theta) * 0.35

    # --- Doppler beaming: approaching side (moving toward +x, roughly the
    # side where cos(theta) crosses from - to +, i.e. where local velocity
    # has a positive x-component) is brighter/bluer; receding side dimmer.
    # Local tangential velocity direction ~ derivative of position w.r.t. theta.
    vel_x = -np.sin(theta)  # direction of motion in x
    approach = np.clip(vel_x, -1, 1)  # -1 = fully receding, +1 = fully approaching
    brightness = 0.45 + 0.55 * (approach * 0.5 + 0.5)  # 0.45..1.0
    # Shift color temp slightly hotter (toward 0) on the approaching side,
    # cooler (toward 1) on the receding side — mimics blue/red shift.
    shifted_temp = np.clip(disk_temp - approach * 0.15, 0, 1)
    colors = TEMP_CMAP(shifted_temp)
    colors[:, 3] = brightness  # use alpha channel to carry brightness

    disk_scatter.set_offsets(np.column_stack([x, y]))
    disk_scatter.set_color(colors)

    # Lensed halo: same particles, mirrored to sit just above/below the
    # horizon regardless of orbital phase, faint and thin.
    hx = x[halo_mask]
    hy = np.sign(y[halo_mask]) * (BH_RADIUS * 1.15 + np.abs(y[halo_mask]) * 0.15)
    halo_colors = colors[halo_mask].copy()
    halo_colors[:, 3] *= 0.35  # much fainter than the main disk
    halo_scatter.set_offsets(np.column_stack([hx, hy]))
    halo_scatter.set_color(halo_colors)

    ring.set_alpha(0.7 + 0.3 * np.sin(t * 2 * np.pi))

    # Rogue planet: slow linear drift across the top of the frame, looping
    # back around every ~90 seconds.
    drift_t = (frame_idx / (FPS * 90)) % 1.0
    px = -12 + drift_t * 24
    py = 4.6 + 0.4 * np.sin(drift_t * 4 * np.pi)
    planet_dot.set_offsets([[px, py]])
    planet_ring.center = (px, py)
    planet_label.set_position((px, py - 0.35))

    # Pulsar: sharp periodic blink (fast on, slow fade) rather than a smooth
    # sine, to read as a "pulse" rather than a breathing glow.
    pulse_phase = (frame_idx % (FPS * 2)) / (FPS * 2)  # 2s pulse cycle
    pulse_alpha = max(0.0, 1.0 - pulse_phase * 3)  # sharp spike, quick decay
    pulsar_dot.set_alpha(0.3 + 0.7 * pulse_alpha)
    pulsar_glow.set_alpha(0.05 + 0.25 * pulse_alpha)

    # Comet: drifts right-to-left across the lower frame, looping every ~70s,
    # with a short trailing tail of fading points behind its direction of travel.
    comet_t = (frame_idx / (FPS * 70)) % 1.0
    cx = 12 - comet_t * 24
    cy = -3.0 + 0.6 * np.sin(comet_t * 3 * np.pi)
    comet_head.set_offsets([[cx, cy]])
    tail_n = 12
    tail_offsets = np.linspace(0.05, 0.9, tail_n)
    tail_x = cx + tail_offsets * 1.3  # tail trails behind (to the right, since moving left)
    tail_y = cy + tail_offsets * 0.15
    comet_tail.set_offsets(np.column_stack([tail_x, tail_y]))
    comet_tail.set_alpha(0.5)
    comet_label.set_position((cx, cy - 0.3))

    # Supernova remnant: slow breathing pulse (expand + fade, reset, repeat).
    sn_phase = (frame_idx % (FPS * 8)) / (FPS * 8)
    remnant_ring.set_radius(0.3 + sn_phase * 0.5)
    remnant_ring.set_alpha(0.6 * (1 - sn_phase))

    # Neutron star: fast subtle flicker, distinct from the pulsar's sharp pulse.
    flicker = 0.7 + 0.3 * np.sin(frame_idx * 0.9)
    neutron_dot.set_alpha(flicker)

    chat = state["chat_text"][:70]
    author = state["chat_author"]
    chat_text_obj.set_text(f"CHAT | {author}: {chat}" if author else "")

    data_lines = []
    if state["iss_lat"] is not None:
        data_lines.append(f"ISS position: {state['iss_lat']:.1f}, {state['iss_lon']:.1f}")
    if state["asteroid_count"] is not None:
        data_lines.append(f"Near-Earth asteroids tracked today: {state['asteroid_count']}")
    data_text_obj.set_text("\n".join(data_lines))

    fact_idx = (frame_idx // (FPS * FACT_INTERVAL_SEC)) % len(BLACK_HOLE_FACTS)
    fact_text_obj.set_text(f"DID YOU KNOW? {BLACK_HOLE_FACTS[fact_idx]}")

    # Audio-reactive bars: read the audio playing at this frame's timestamp
    # and update each bar's height so viewers can see the sound, not just
    # hear it.
    heights = compute_bar_heights(frame_idx)
    for rect, h in zip(bar_patches, heights):
        rect.set_height(max(h, 0.01))

    # --- Blit only the artists that actually changed this frame instead of
    # redrawing the whole canvas (starfield, nebula, galaxy, cluster, etc.
    # stay cached in `background` since they never move). This is the fix
    # for the "speed=0.58x" real-time lag seen in the ffmpeg log — a full
    # fig.canvas.draw() every frame re-renders dozens of static artists for
    # no reason.
    fig.canvas.restore_region(background)
    for artist in DYNAMIC_ARTISTS:
        ax.draw_artist(artist)
    fig.canvas.blit(ax.bbox)
    buf = np.asarray(fig.canvas.buffer_rgba())
    return buf[:, :, :3].tobytes()  # drop alpha -> rgb24




# ---------------- Main ----------------
def main():
    global audio_samples, audio_sr, audio_duration

    threading.Thread(target=poll_chat, daemon=True).start()
    threading.Thread(target=poll_space_data, daemon=True).start()

    # Ensure the ambient soundtrack exists (generate it if this is a fresh
    # checkout / first run). It's a fully synthesized, seamless loop — no
    # copyrighted material — so it's safe to stream indefinitely.
    ambient_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "space_ambient.wav")
    if not os.path.exists(ambient_path):
        from generate_space_ambient import generate as generate_ambient
        generate_ambient(path=ambient_path)

    # Load the same audio into memory so the visualizer can read the exact
    # samples that ffmpeg is playing at any given moment (see compute_bar_heights).
    sr, data = wavfile.read(ambient_path)
    mono = data.astype(np.float32).mean(axis=1) if data.ndim > 1 else data.astype(np.float32)
    mono /= np.max(np.abs(mono)) + 1e-9
    audio_samples = mono
    audio_sr = sr
    audio_duration = len(mono) / sr

    ffmpeg_cmd = [
        "ffmpeg", "-y",
        "-f", "rawvideo", "-pixel_format", "rgb24",
        "-video_size", f"{WIDTH}x{HEIGHT}", "-framerate", str(FPS),
        "-i", "-",
        "-stream_loop", "-1", "-i", ambient_path,
        "-c:v", "libx264", "-preset", "veryfast", "-b:v", "3000k",
        "-maxrate", "3000k", "-bufsize", "6000k", "-pix_fmt", "yuv420p", "-g", str(FPS * 2),
        "-c:a", "aac", "-b:a", "128k", "-ar", "44100",
        "-shortest",
        "-f", "flv", RTMP_URL,
    ]
    proc = subprocess.Popen(ffmpeg_cmd, stdin=subprocess.PIPE)

    frame_idx = 0
    try:
        while True:
            frame_bytes = render_frame(frame_idx)
            proc.stdin.write(frame_bytes)
            frame_idx += 1
    except (BrokenPipeError, KeyboardInterrupt):
        pass
    finally:
        proc.stdin.close()
        proc.wait()


if __name__ == "__main__":
    main()
