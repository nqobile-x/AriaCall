"""
Generate Aria wave SVGs:
  aria-wave.svg  — welcome screen (spring-physics, 15 bars)
  aria-call.svg  — call panel (greeting-burst-then-idle, 17 bars, bigger)

Run: python tools/generate_wave_svg.py
"""

import math, textwrap
from pathlib import Path

OUT = Path(__file__).parent.parent / "api" / "static"

# ── Shared helpers ─────────────────────────────────────────────────────────────

def gaussian(i, center, sigma):
    return math.exp(-((i - center) ** 2) / (2 * sigma ** 2))

def bar_color(dist):
    if dist == 0: return "#ff6d4a"
    if dist == 1: return "#ff7055"
    if dist == 2: return "#ff7a60"
    if dist == 3: return "#c8f7e5"
    if dist == 4: return "#a7f3d0"
    if dist == 5: return "#6ecba8"
    if dist == 6: return "#3d7d68"
    if dist == 7: return "#264f42"
    return "#1a2e2a"

def glow_id(dist):
    if dist <= 1: return "fh"
    if dist <= 3: return "fw"
    return None

# ────────────────────────────────────────────────────────────────────────────────
# 1.  aria-wave.svg  (welcome screen, 15 bars, 196×86)
# ────────────────────────────────────────────────────────────────────────────────

def build_wave():
    BARS, W, H = 15, 196, 86
    BAR_W, GAP = 4, 9
    STEP   = BAR_W + GAP
    CENTER = BARS // 2
    MID_Y  = H / 2
    MARGIN = (W - BARS * STEP + GAP) / 2

    _BASE_DUR  = [0.50, 0.54, 0.58, 0.62, 0.66, 0.72, 0.78]
    _BASE_DLAY = [0, .04, .09, .14, .19, .25, .31]
    _JITTER    = [0, .02, -.01, .03, -.02, .01, -.03]

    def g(i):   return gaussian(i, CENTER, 4.2)
    def mn(i):  return round(0.03 + (1 - g(i)) * 0.18, 3)
    def pk(i):  return round(g(i) * 1.00 + 0.04, 3)
    def os_(i): return round(pk(i) * 1.18, 3)
    def s1(i):  return round(pk(i) * 0.88, 3)
    def b1(i):  return round(pk(i) * 1.06, 3)
    def s2(i):  return round(pk(i) * 0.97, 3)
    def op_mn(i): return round(0.18 + g(i) * 0.30, 2)
    def op_pk(i): return round(0.62 + g(i) * 0.38, 2)

    def dur(i):
        d = abs(i - CENTER)
        return round(_BASE_DUR[min(d, 6)] + [0,.03,.07,.02,.05,.01,.04][min(d,6)], 3)

    def dly(i):
        d = abs(i - CENTER)
        side = 1 if i > CENTER else -1
        return round(max(0, _BASE_DLAY[min(d,6)] + _JITTER[min(d,6)] * side), 3)

    def kf(i):
        return f"""
    @keyframes w{i} {{
      0%   {{transform:scaleY({mn(i)});opacity:{op_mn(i)};animation-timing-function:cubic-bezier(.22,1,.36,1)}}
      20%  {{transform:scaleY({os_(i)});opacity:{op_pk(i)};animation-timing-function:ease-out}}
      35%  {{transform:scaleY({s1(i)});opacity:{op_pk(i)};animation-timing-function:cubic-bezier(.55,0,.1,1)}}
      55%  {{transform:scaleY({b1(i)});opacity:{op_pk(i)};animation-timing-function:ease-in-out}}
      68%  {{transform:scaleY({s2(i)});opacity:{op_pk(i)};animation-timing-function:ease-out}}
      80%  {{transform:scaleY({s2(i)});opacity:{op_pk(i)};animation-timing-function:cubic-bezier(.65,0,.35,1)}}
      100% {{transform:scaleY({mn(i)});opacity:{op_mn(i)}}}
    }}"""

    def rect(i):
        x  = round(MARGIN + i * STEP, 2)
        d  = abs(i - CENTER)
        gc = glow_id(d)
        gf = f' filter:url(#{gc});' if gc else ''
        tx = round(x + BAR_W / 2, 2)
        return (f'  <rect class="b" x="{x}" y="{round(MID_Y-(H-14)/2,2)}" '
                f'width="{BAR_W}" height="{H-14}" rx="{BAR_W//2}" fill="{bar_color(d)}" '
                f'style="animation:w{i} {dur(i)}s linear infinite {dly(i)}s;{gf}'
                f'transform-origin:{tx}px {MID_Y}px"/>')

    kf_block   = "\n".join(kf(i) for i in range(BARS))
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
    .b {{transform-box:fill-box}}
{textwrap.indent(kf_block, "    ")}
  </style>
{rect_block}
</svg>"""
    return svg


# ────────────────────────────────────────────────────────────────────────────────
# 2.  aria-call.svg  (call panel, 17 bars, 280×120)
#     Greeting burst radiates from centre, then spring-idle takes over.
# ────────────────────────────────────────────────────────────────────────────────

def build_call():
    BARS, W, H = 17, 280, 120
    BAR_W, GAP = 5, 11
    STEP   = BAR_W + GAP
    CENTER = BARS // 2   # 8
    MID_Y  = H / 2
    MARGIN = (W - BARS * STEP + GAP) / 2

    GREET_DUR  = 1.4   # seconds the greeting burst plays

    def g(i):   return gaussian(i, CENTER, 5.0)
    def mn(i):  return round(0.02 + (1 - g(i)) * 0.15, 3)
    def pk(i):  return round(g(i) * 1.02 + 0.03, 3)
    def os_(i): return round(min(pk(i) * 1.22, 0.99), 3)
    def s1(i):  return round(pk(i) * 0.87, 3)
    def b1(i):  return round(pk(i) * 1.05, 3)
    def op_mn(i): return round(0.15 + g(i) * 0.30, 2)
    def op_pk(i): return round(0.65 + g(i) * 0.35, 2)

    def dur(i):
        d = abs(i - CENTER)
        return round(0.45 + d * 0.07, 3)

    def idle_dly(i):
        return round(GREET_DUR + abs(i - CENTER) * 0.03, 3)

    # Greeting burst: bars wake up radiating from centre
    def greet_kf(i):
        d   = abs(i - CENTER)
        # each bar's burst is delayed proportional to distance from centre
        pct_sleep = min(int(d / (BARS // 2) * 35), 30)   # 0%..30% asleep
        pct_burst = pct_sleep + 22
        pct_setl  = min(pct_burst + 18, 90)
        return f"""
    @keyframes g{i} {{
      0%          {{transform:scaleY(0.02);opacity:0}}
      {pct_sleep}% {{transform:scaleY(0.02);opacity:0;animation-timing-function:cubic-bezier(.22,1,.36,1)}}
      {pct_burst}% {{transform:scaleY({os_(i)});opacity:1;animation-timing-function:ease-out}}
      {pct_setl}%  {{transform:scaleY({s1(i)});opacity:{op_pk(i)}}}
      100%         {{transform:scaleY({pk(i)});opacity:{op_pk(i)}}}
    }}"""

    # Idle spring physics (same as wave.svg but continuous after greeting)
    def idle_kf(i):
        return f"""
    @keyframes w{i} {{
      0%   {{transform:scaleY({mn(i)});opacity:{op_mn(i)};animation-timing-function:cubic-bezier(.22,1,.36,1)}}
      20%  {{transform:scaleY({os_(i)});opacity:{op_pk(i)};animation-timing-function:ease-out}}
      38%  {{transform:scaleY({s1(i)});opacity:{op_pk(i)};animation-timing-function:cubic-bezier(.55,0,.1,1)}}
      58%  {{transform:scaleY({b1(i)});opacity:{op_pk(i)};animation-timing-function:ease-in-out}}
      75%  {{transform:scaleY({pk(i)});opacity:{op_pk(i)};animation-timing-function:cubic-bezier(.65,0,.35,1)}}
      100% {{transform:scaleY({mn(i)});opacity:{op_mn(i)}}}
    }}"""

    def rect(i):
        x   = round(MARGIN + i * STEP, 2)
        d   = abs(i - CENTER)
        gc  = glow_id(d)
        gf  = f' filter:url(#{gc});' if gc else ''
        tx  = round(x + BAR_W / 2, 2)
        # Two-stage animation: greeting burst (once, forwards) then idle (infinite after)
        anim = (
            f"g{i} {GREET_DUR}s ease-out 0s forwards,"
            f"w{i} {dur(i)}s linear infinite {idle_dly(i)}s"
        )
        return (f'  <rect class="b" x="{x}" y="{round(MID_Y-(H-18)/2,2)}" '
                f'width="{BAR_W}" height="{H-18}" rx="{BAR_W//2}" fill="{bar_color(d)}" '
                f'style="animation:{anim};{gf}'
                f'transform-origin:{tx}px {MID_Y}px"/>')

    kf_block   = "\n".join(greet_kf(i) + idle_kf(i) for i in range(BARS))
    rect_block = "\n".join(rect(i) for i in range(BARS))

    svg = f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}">
  <defs>
    <filter id="fh" x="-100%" y="-100%" width="300%" height="300%">
      <feGaussianBlur stdDeviation="5" result="b"/>
      <feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge>
    </filter>
    <filter id="fw" x="-60%" y="-60%" width="220%" height="220%">
      <feGaussianBlur stdDeviation="3" result="b"/>
      <feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge>
    </filter>
  </defs>
  <style>
    .b {{transform-box:fill-box}}
{textwrap.indent(kf_block, "    ")}
  </style>
{rect_block}
</svg>"""
    return svg


# ── Write ──────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    wave = build_wave()
    call = build_call()

    (OUT / "aria-wave.svg").write_text(wave, encoding="utf-8")
    print(f"aria-wave.svg  {len(wave):,} bytes  (15 bars, spring-physics)")

    (OUT / "aria-call.svg").write_text(call, encoding="utf-8")
    print(f"aria-call.svg  {len(call):,} bytes  (17 bars, greeting-burst → idle)")
