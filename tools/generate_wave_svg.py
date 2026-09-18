"""
Generate aria-wave.svg — Aria animated voice waveform.
Feel: iOS/macOS spring physics — bars overshoot, bounce, settle organically.
Run: python tools/generate_wave_svg.py
"""

import math, textwrap
from pathlib import Path

# ── Config ────────────────────────────────────────────────────────────────────
BARS    = 15
W, H    = 196, 86
BAR_W   = 4          # thin, like AirPods/iOS audio viz
GAP     = 9
STEP    = BAR_W + GAP
CENTER  = BARS // 2   # index 7

MARGIN_X = (W - BARS * STEP + GAP) / 2
MID_Y    = H / 2

def gaussian(i, sigma=4.2):
    return math.exp(-((i - CENTER) ** 2) / (2 * sigma ** 2))

# ── Colors ────────────────────────────────────────────────────────────────────
def bar_color(i):
    dist = abs(i - CENTER)
    if dist == 0: return "#ff6d4a"
    if dist == 1: return "#ff7055"
    if dist == 2: return "#ff7a60"
    if dist == 3: return "#c8f7e5"
    if dist == 4: return "#a7f3d0"
    if dist == 5: return "#6ecba8"
    if dist == 6: return "#3d7d68"
    return "#263035"

def glow_class(i):
    dist = abs(i - CENTER)
    if dist <= 1: return " gh"
    if dist <= 3: return " gw"
    return ""

# ── Spring-physics keyframes ──────────────────────────────────────────────────
# Simulate iOS spring: ramp up fast, overshoot peak, snap back, tiny bounce, rest.
# All via scaleY so the bar stays centred on MID_Y via transform-origin.
def spring_kf(i):
    g   = gaussian(i)
    mn  = round(0.03 + (1 - g) * 0.18, 3)   # quiet floor
    pk  = round(g * 1.00 + 0.04, 3)          # full peak
    os  = round(pk * 1.18, 3)                # overshoot (+18%)
    s1  = round(pk * 0.88, 3)                # first settle
    b1  = round(pk * 1.06, 3)                # micro bounce
    s2  = round(pk * 0.97, 3)                # final settle ≈ pk

    # Opacity mirrors scale
    op_mn = round(0.18 + g * 0.30, 2)
    op_pk = round(0.62 + g * 0.38, 2)

    # Easing per segment:
    # 0→20%  fast ramp up    cubic-bezier(.22,1,.36,1)
    # 20→35% overshoot       ease-out
    # 35→55% snap back       cubic-bezier(.55,0,.1,1)
    # 55→68% micro bounce    ease-in-out
    # 68→80% settle          ease-out
    # 80→100% return to floor cubic-bezier(.65,0,.35,1)
    return f"""
    @keyframes w{i} {{
      0%   {{ transform:scaleY({mn}); opacity:{op_mn}; animation-timing-function:cubic-bezier(.22,1,.36,1) }}
      20%  {{ transform:scaleY({os}); opacity:{op_pk}; animation-timing-function:ease-out }}
      35%  {{ transform:scaleY({s1}); opacity:{op_pk}; animation-timing-function:cubic-bezier(.55,0,.1,1) }}
      55%  {{ transform:scaleY({b1}); opacity:{op_pk}; animation-timing-function:ease-in-out }}
      68%  {{ transform:scaleY({s2}); opacity:{op_pk}; animation-timing-function:ease-out }}
      80%  {{ transform:scaleY({s2}); opacity:{op_pk}; animation-timing-function:cubic-bezier(.65,0,.35,1) }}
      100% {{ transform:scaleY({mn}); opacity:{op_mn} }}
    }}"""

# ── Timing — asymmetric, organic ─────────────────────────────────────────────
# Centre is fastest; edges are slowest. Offsets break perfect mirror symmetry
# so it feels hand-animated rather than computed.
_BASE_DUR  = [0.50, 0.54, 0.58, 0.62, 0.66, 0.72, 0.78]  # dist 0..6
_BASE_DLAY = [0, .04, .09, .14, .19, .25, .31]             # dist 0..6
_JITTER    = [0, .02, -.01, .03, -.02, .01, -.03]          # break symmetry

def duration(i):
    dist = abs(i - CENTER)
    return round(_BASE_DUR[min(dist, 6)], 3)

def delay(i):
    dist   = abs(i - CENTER)
    side   = 1 if i > CENTER else -1
    jitter = _JITTER[min(dist, 6)] * side
    return round(max(0, _BASE_DLAY[min(dist, 6)] + jitter), 3)

# ── Rect elements ─────────────────────────────────────────────────────────────
def rect(i):
    x   = round(MARGIN_X + i * STEP, 2)
    col = bar_color(i)
    dur = duration(i)
    dly = delay(i)
    gc  = glow_class(i)
    tx  = round(x + BAR_W / 2, 2)
    return (
        f'  <rect class="b{gc}" '
        f'x="{x}" y="{round(MID_Y - (H - 14)/2, 2)}" '
        f'width="{BAR_W}" height="{H - 14}" rx="{BAR_W // 2}" '
        f'fill="{col}" '
        f'style="animation:w{i} {dur}s linear infinite {dly}s;'
        f'transform-origin:{tx}px {MID_Y}px"/>'
    )

# ── Build SVG ─────────────────────────────────────────────────────────────────
kf_block   = "\n".join(spring_kf(i) for i in range(BARS))
rect_block = "\n".join(rect(i) for i in range(BARS))

svg = f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}">
  <defs>
    <filter id="fh" x="-100%" y="-100%" width="300%" height="300%">
      <feGaussianBlur stdDeviation="4" result="b"/>
      <feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge>
    </filter>
    <filter id="fw" x="-60%" y="-60%" width="220%" height="220%">
      <feGaussianBlur stdDeviation="2.5" result="b"/>
      <feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge>
    </filter>
  </defs>
  <style>
    .b {{ transform-box:fill-box }}
    .gh {{ filter:url(#fh) }}
    .gw {{ filter:url(#fw) }}
{textwrap.indent(kf_block, "    ")}
  </style>
{rect_block}
</svg>"""

out = Path(__file__).parent.parent / "api" / "static" / "aria-wave.svg"
out.write_text(svg, encoding="utf-8")
print(f"Written {out}  ({len(svg):,} bytes, {BARS} bars)")
print(f"ViewBox {W}x{H}, bar {BAR_W}px w / {GAP}px gap")
