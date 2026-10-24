"""Source-time speed curves and exact source-to-output timestamp mapping."""
import math

EASINGS = ("ease-in", "ease-out", "ease-in-out")


def validate(start, end, easing):
    start, end = float(start), float(end)
    if not all(math.isfinite(x) and 0.1 <= x <= 8 for x in (start, end)):
        raise ValueError("시작·끝 배속은 0.1~8 사이로 입력해 주세요.")
    if easing not in EASINGS:
        raise ValueError("지원하지 않는 곡선입니다.")
    return start, end, easing


def speed_at(p, start, end, easing):
    p = max(0.0, min(1.0, p))
    if easing == "ease-in":
        amount = p * p
    elif easing == "ease-out":
        amount = 1 - (1 - p) ** 2
    else:
        amount = 2 * p * p if p < 0.5 else 1 - 2 * (1 - p) ** 2
    return start + (end - start) * amount


def primitive(x, a, b):
    """Integral from zero to x of 1/(a + b*x*x)."""
    if abs(b) < 1e-12:
        return x / a
    if b > 0:
        return math.atan(x * math.sqrt(b / a)) / math.sqrt(a * b)
    return math.atanh(x * math.sqrt(-b / a)) / math.sqrt(-a * b)


def output_time(p, duration, start, end, easing):
    p = max(0.0, min(1.0, p))
    d = end - start
    if abs(d) < 1e-10:
        integral = p / start
    elif easing == "ease-in":
        integral = primitive(p, start, d)
    elif easing == "ease-out":
        integral = primitive(1, end, -d) - primitive(1 - p, end, -d)
    elif p <= 0.5:
        integral = primitive(p, start, 2 * d)
    else:
        integral = (primitive(0.5, start, 2 * d)
                    + primitive(0.5, end, -2 * d)
                    - primitive(1 - p, end, -2 * d))
    return duration * integral


def _number(x):
    return format(x, ".15g")


def _primitive_expr(x, a, b):
    if abs(b) < 1e-12:
        return f"({x})/{_number(a)}"
    root, denom = _number(math.sqrt(abs(b) / a)), _number(math.sqrt(a * abs(b)))
    z = f"(({x})*{root})"
    if b > 0:
        return f"atan({z})/{denom}"
    return f"(0.5*log((1+{z})/(1-{z}))/{denom})"


def video_expression(duration, start, end, easing):
    """Analytic mapping, evaluated by FFmpeg per input frame; no stepped video."""
    p = "ld(0)"
    d = end - start
    if abs(d) < 1e-10:
        result = f"{p}/{_number(start)}"
    elif easing == "ease-in":
        result = _primitive_expr(p, start, d)
    elif easing == "ease-out":
        result = f"({_number(primitive(1, end, -d))}-({_primitive_expr('1-ld(0)', end, -d)}))"
    else:
        first = _primitive_expr(p, start, 2 * d)
        constant = primitive(0.5, start, 2 * d) + primitive(0.5, end, -2 * d)
        second = f"({_number(constant)}-({_primitive_expr('1-ld(0)', end, -2*d)}))"
        result = f"if(lte({p},0.5),{first},{second})"
    return (f"st(0,min(1,max(0,(PTS-STARTPTS)*TB/{_number(duration)})));"
            f"{_number(duration)}*({result})/TB")


def audio_commands(duration, start, end, easing):
    """Drive a single pitch-preserving stretcher on original audio timestamps."""
    interval = max(0.04, duration / 4000)
    lines = []
    for i in range(1, math.ceil(duration / interval)):
        t = i * interval
        tempo = speed_at(t / duration, start, end, easing)
        lines.append(f"{t:.6f} rubberband@curve tempo {tempo:.9f};")
    return "\n".join(lines)
