#!/usr/bin/env python3
"""描边图标 → 填充图标（供 ArkUI Image.fillColor 着色）。

为什么需要转换
  鸿蒙 Image.fillColor：「仅对 SVG 图源生效，设置后会替换 SVG 图片中所有可绘制元素的**填充**颜色」；
  且 API 21 起 SVG 解析增强（supportSvg2=true）时，图源 fill='none' 的元素不再被着色。
  lucide 图标是**描边**几何（fill="none" + stroke="#000000"），直接放进 Image 会得到
  「黑描边 + 被着色内芯」，深色模式下就是一团黑。改成**纯填充**几何后，图标只剩 fill，
  两种解析模式下都能被 fillColor 正确着色（且跟随深浅色与主题色）。

几何恒等式
  圆头圆角描边(折线 L, 线宽 2r) ≡ ∪ 各线段胶囊体(segment ⊕ 半径 r 圆盘)。
  胶囊体是凸形：逐段输出为独立子路径、统一绕向（nonzero 填充规则）即得并集，
  圆角接头由相邻胶囊体的圆头自动覆盖（同色不透明，重叠处无接缝）。

用法: stroke_to_fill.py <输入目录> [输出目录]   # 输出目录省略则就地改写
"""
import math
import re
import sys
import shutil
from pathlib import Path

R = 1.0              # 半径 = stroke-width / 2
FLAT_TOL = 0.02      # 折线化容差（24 单位视口，≈0.08% 图幅）
CAP_STEPS = 8        # 端头半圆的离散段数

NUM = re.compile(r'[-+]?(?:\d*\.\d+|\d+\.?)(?:[eE][-+]?\d+)?')
HEAD = ('<svg\n  xmlns="http://www.w3.org/2000/svg"\n  width="24"\n  height="24"\n'
        '  viewBox="0 0 24 24"\n  fill="#000000"\n>\n')


# ---------------------------------------------------------------- 路径解析

def tokenize(d):
    out, i = [], 0
    while i < len(d):
        c = d[i]
        if c in 'MmLlHhVvCcSsQqTtAaZz':
            out.append(c)
            i += 1
        elif c in ' ,\r\n\t':
            i += 1
        else:
            m = NUM.match(d, i)
            if not m:
                raise ValueError(f'无法解析 {d[i:i+12]!r}')
            out.append(float(m.group(0)))
            i = m.end()
    return out


def arc_steps(radius, sweep_deg, tol=FLAT_TOL):
    """按弦高 ≈ tol 取圆弧离散步数（弦高 = r·(1-cos(θ/2))）"""
    if radius <= tol:
        return 2
    th = 2 * math.degrees(math.acos(max(-1.0, 1.0 - tol / radius)))
    return max(2, int(math.ceil(sweep_deg / th)))


def _steps(approx_len):
    """按弦长给离散步数（保证弦高 ≈ FLAT_TOL）"""
    return max(2, min(24, int(math.ceil(approx_len ** 0.5 * 3)) + 2))


def cubic(p0, p1, p2, p3):
    steps = _steps(abs(p1[0] - p0[0]) + abs(p1[1] - p0[1]) + abs(p2[0] - p1[0])
                   + abs(p2[1] - p1[1]) + abs(p3[0] - p2[0]) + abs(p3[1] - p2[1]))
    pts = []
    for k in range(1, steps + 1):
        t = k / steps
        mt = 1 - t
        pts.append((mt**3 * p0[0] + 3 * mt**2 * t * p1[0] + 3 * mt * t**2 * p2[0] + t**3 * p3[0],
                    mt**3 * p0[1] + 3 * mt**2 * t * p1[1] + 3 * mt * t**2 * p2[1] + t**3 * p3[1]))
    return pts


def quad(p0, p1, p2):
    return cubic(p0, (p0[0] + 2 / 3 * (p1[0] - p0[0]), p0[1] + 2 / 3 * (p1[1] - p0[1])),
                 (p2[0] + 2 / 3 * (p1[0] - p2[0]), p2[1] + 2 / 3 * (p1[1] - p2[1])), p2)


def arc_to_points(p0, rx, ry, phi_deg, large, sweep, p1):
    """SVG 椭圆弧（端点参数）→ 离散点，规范 F.6.5"""
    if rx == 0 or ry == 0:
        return [p1]
    rx, ry = abs(rx), abs(ry)
    phi = math.radians(phi_deg)
    cosp, sinp = math.cos(phi), math.sin(phi)
    dx, dy = (p0[0] - p1[0]) / 2, (p0[1] - p1[1]) / 2
    x1p, y1p = cosp * dx + sinp * dy, -sinp * dx + cosp * dy
    lam = (x1p / rx) ** 2 + (y1p / ry) ** 2
    if lam > 1:
        s = math.sqrt(lam)
        rx, ry = rx * s, ry * s
    num = rx**2 * ry**2 - rx**2 * y1p**2 - ry**2 * x1p**2
    den = rx**2 * y1p**2 + ry**2 * x1p**2
    coef = math.sqrt(max(0.0, num / den)) if den else 0.0
    if large == sweep:
        coef = -coef
    cxp, cyp = coef * rx * y1p / ry, -coef * ry * x1p / rx
    cx = cosp * cxp - sinp * cyp + (p0[0] + p1[0]) / 2
    cy = sinp * cxp + cosp * cyp + (p0[1] + p1[1]) / 2

    def ang(ux, uy, vx, vy):
        n = math.hypot(ux, uy) * math.hypot(vx, vy)
        a = math.acos(max(-1.0, min(1.0, (ux * vx + uy * vy) / n))) if n else 0.0
        return -a if ux * vy - uy * vx < 0 else a

    t1 = ang(1, 0, (x1p - cxp) / rx, (y1p - cyp) / ry)
    dt = ang((x1p - cxp) / rx, (y1p - cyp) / ry, (-x1p - cxp) / rx, (-y1p - cyp) / ry)
    if not sweep and dt > 0:
        dt -= 2 * math.pi
    elif sweep and dt < 0:
        dt += 2 * math.pi
    steps = arc_steps(max(rx, ry), abs(math.degrees(dt)))
    out = []
    for k in range(1, steps + 1):
        t = t1 + dt * k / steps
        out.append((cx + rx * math.cos(t) * cosp - ry * math.sin(t) * sinp,
                    cy + rx * math.cos(t) * sinp + ry * math.sin(t) * cosp))
    return out


def flatten_path(d):
    """→ [(闭合?, [(x,y), …]), …] 每段首点为起点"""
    toks = tokenize(d)
    subs, cur, closed = [], [], False
    pos = start = (0.0, 0.0)
    pc = pq = None
    i, cmd = 0, None

    def need(n):
        nonlocal i
        vals = toks[i:i + n]
        if len(vals) < n or any(isinstance(v, str) for v in vals):
            raise ValueError(f'参数不足 {d}')
        i += n
        return vals

    while i < len(toks):
        if isinstance(toks[i], str):
            cmd = toks[i]
            i += 1
            if cmd in 'Zz':
                if cur:
                    cur.append(start)
                    subs.append((True, cur))
                    cur = []
                pos, pc, pq = start, None, None
                continue
            if cmd in 'Mm':
                x, y = need(2)
                pos = (x, y) if cmd == 'M' else (pos[0] + x, pos[1] + y)
                if cur:
                    subs.append((closed, cur))
                cur, closed, start = [pos], False, pos
                pc = pq = None
                cmd = 'L' if cmd == 'M' else 'l'
                continue
        rel, c = cmd.islower(), cmd.upper()
        if c == 'L':
            x, y = need(2)
            pos = (pos[0] + x, pos[1] + y) if rel else (x, y)
            cur.append(pos)
            pc = pq = None
        elif c == 'H':
            x, = need(1)
            pos = (pos[0] + x, pos[1]) if rel else (x, pos[1])
            cur.append(pos)
            pc = pq = None
        elif c == 'V':
            y, = need(1)
            pos = (pos[0], pos[1] + y) if rel else (pos[0], y)
            cur.append(pos)
            pc = pq = None
        elif c in 'CS':
            if c == 'C':
                x1, y1, x2, y2, x, y = need(6)
            else:
                x2, y2, x, y = need(4)
                x1 = 2 * pos[0] - pc[0] if pc else pos[0]
                y1 = 2 * pos[1] - pc[1] if pc else pos[1]
            if rel:
                p1 = (pos[0] + x1, pos[1] + y1)
                p2 = (pos[0] + x2, pos[1] + y2)
                p3 = (pos[0] + x, pos[1] + y)
            else:
                p1, p2, p3 = (x1, y1), (x2, y2), (x, y)
            cur.extend(cubic(pos, p1, p2, p3))
            pc, pq, pos = p2, None, p3
        elif c in 'QT':
            if c == 'Q':
                x1, y1, x, y = need(4)
            else:
                x, y = need(2)
                x1 = 2 * pos[0] - pq[0] if pq else pos[0]
                y1 = 2 * pos[1] - pq[1] if pq else pos[1]
            if rel:
                p1, p3 = (pos[0] + x1, pos[1] + y1), (pos[0] + x, pos[1] + y)
            else:
                p1, p3 = (x1, y1), (x, y)
            cur.extend(quad(pos, p1, p3))
            pq, pc, pos = p1, None, p3
        elif c == 'A':
            rx, ry, rot, large, sweep, x, y = need(7)
            p = (pos[0] + x, pos[1] + y) if rel else (x, y)
            cur.extend(arc_to_points(pos, rx, ry, rot, int(large), int(sweep), p))
            pc = pq = None
            pos = p
        else:
            raise ValueError(f'不支持的命令 {cmd}')
    if cur:
        subs.append((closed, cur))
    return subs


# ---------------------------------------------------------------- 元素 → 折线

def attrs_of(s):
    # 属性名可带数字（x1 / y1 / x2 / y2）
    return {k: v for k, v in re.findall(r'([a-zA-Z][a-zA-Z0-9-]*)\s*=\s*"([^"]*)"', s)}


def fnum(a, key, default=0.0):
    v = a.get(key)
    return float(v) if v not in (None, '') else default


def polylines_of(tag, a):
    if tag == 'path':
        return flatten_path(a['d'])
    if tag == 'circle':
        cx, cy, r = fnum(a, 'cx'), fnum(a, 'cy'), fnum(a, 'r')
        n = arc_steps(r, 360)
        pts = [(cx + r * math.cos(k / n * 2 * math.pi), cy + r * math.sin(k / n * 2 * math.pi))
               for k in range(n + 1)]
        return [(True, pts)]
    if tag == 'ellipse':
        cx, cy, rx, ry = fnum(a, 'cx'), fnum(a, 'cy'), fnum(a, 'rx'), fnum(a, 'ry')
        n = arc_steps(max(rx, ry), 360)
        pts = [(cx + rx * math.cos(k / n * 2 * math.pi), cy + ry * math.sin(k / n * 2 * math.pi))
               for k in range(n + 1)]
        return [(True, pts)]
    if tag == 'line':
        return [(False, [(fnum(a, 'x1'), fnum(a, 'y1')), (fnum(a, 'x2'), fnum(a, 'y2'))])]
    if tag == 'rect':
        x, y, w, h = fnum(a, 'x'), fnum(a, 'y'), fnum(a, 'width'), fnum(a, 'height')
        rx = fnum(a, 'rx', fnum(a, 'ry'))
        ry = fnum(a, 'ry', rx)
        if rx <= 0 or ry <= 0:
            pts = [(x, y), (x + w, y), (x + w, y + h), (x, y + h), (x, y)]
        else:
            n_c = arc_steps(max(rx, ry), 90)

            def arcp(c, a0, a1, n=n_c):
                return [(c[0] + rx * math.cos(a0 + (a1 - a0) * k / n),
                         c[1] + ry * math.sin(a0 + (a1 - a0) * k / n)) for k in range(n + 1)]
            pts = (arcp((x + rx, y + ry), math.pi, 1.5 * math.pi)
                   + arcp((x + w - rx, y + ry), 1.5 * math.pi, 2 * math.pi)
                   + arcp((x + w - rx, y + h - ry), 0, 0.5 * math.pi)
                   + arcp((x + rx, y + h - ry), 0.5 * math.pi, math.pi))
            pts.append(pts[0])
        return [(True, pts)]
    if tag in ('polygon', 'polyline'):
        nums = [float(v) for v in NUM.findall(a.get('points', ''))]
        return [(tag == 'polygon', [(nums[i], nums[i + 1]) for i in range(0, len(nums) - 1, 2)])]
    return []


# ---------------------------------------------------------------- 描边 → 胶囊体

def fmt(v):
    s = f'{v:.2f}'.rstrip('0').rstrip('.')
    return s if s not in ('-0', '') else '0'


def cap_points(p0, p1, n=CAP_STEPS):
    """胶囊体采样多边形（用于定绕向）"""
    dx, dy = p1[0] - p0[0], p1[1] - p0[1]
    ln = math.hypot(dx, dy)
    if ln < 1e-9:
        return [(p0[0] + R * math.cos(k / n * 2 * math.pi), p0[1] + R * math.sin(k / n * 2 * math.pi))
                for k in range(n)]
    ux, uy = dx / ln, dy / ln
    nx, ny = -uy * R, ux * R
    pts = [(p0[0] + nx, p0[1] + ny), (p1[0] + nx, p1[1] + ny)]
    a0 = math.atan2(ny, nx)
    pts += [(p1[0] + R * math.cos(a0 - math.pi * k / n), p1[1] + R * math.sin(a0 - math.pi * k / n))
            for k in range(1, n)]
    pts += [(p1[0] - nx, p1[1] - ny), (p0[0] - nx, p0[1] - ny)]
    a0 = math.atan2(-ny, -nx)
    pts += [(p0[0] + R * math.cos(a0 - math.pi * k / n), p0[1] + R * math.sin(a0 - math.pi * k / n))
            for k in range(1, n)]
    return pts


def shoelace(pts):
    return sum(pts[i][0] * pts[(i + 1) % len(pts)][1] - pts[(i + 1) % len(pts)][0] * pts[i][1]
               for i in range(len(pts))) / 2


def capsule(p0, p1):
    """线段 → 胶囊体 path 子串（圆头圆角；端头用显式采样点，不用 A 弧——
    正好半圆的 sweep 语义在退化情形下有歧义，显式点列可构造即校验）"""
    dx, dy = p1[0] - p0[0], p1[1] - p0[1]
    ln = math.hypot(dx, dy)
    if ln < 1e-9:
        cx, cy = p0
        pts = [(cx + R * math.cos(k / 16 * 2 * math.pi),
                cy + R * math.sin(k / 16 * 2 * math.pi)) for k in range(16)]
        return emit_poly(pts)
    ux, uy = dx / ln, dy / ln
    nx, ny = -uy * R, ux * R
    a1 = (p0[0] + nx, p0[1] + ny)
    b1 = (p1[0] + nx, p1[1] + ny)
    b2 = (p1[0] - nx, p1[1] - ny)
    a2 = (p0[0] - nx, p0[1] - ny)
    pts = [a1, b1]
    a0 = math.atan2(ny, nx)                       # p1 端头：自 +n 绕过 +u 到 -n
    pts += [(p1[0] + R * math.cos(a0 - math.pi * k / CAP_STEPS),
             p1[1] + R * math.sin(a0 - math.pi * k / CAP_STEPS)) for k in range(1, CAP_STEPS)]
    pts += [b2, a2]
    a0 = math.atan2(-ny, -nx)                     # p0 端头：自 -n 绕过 -u 到 +n
    pts += [(p0[0] + R * math.cos(a0 - math.pi * k / CAP_STEPS),
             p0[1] + R * math.sin(a0 - math.pi * k / CAP_STEPS)) for k in range(1, CAP_STEPS)]
    return emit_poly(pts)


def emit_poly(pts):
    """点列 → 子路径：统一绕向（nonzero 下重叠同向才不相消），相对坐标压缩体积"""
    if shoelace(pts) < 0:
        pts = pts[:1] + pts[:0:-1]
    out = [f'M{fmt(pts[0][0])} {fmt(pts[0][1])}']
    for k in range(1, len(pts)):
        out.append(f'l{fmt(pts[k][0] - pts[k - 1][0])} {fmt(pts[k][1] - pts[k - 1][1])}')
    out.append('Z')
    return ''.join(out)


def convert(src):
    body = src[src.index('>', src.index('<svg')) + 1:src.rindex('</svg>')]
    subs = []
    for m in re.finditer(r'<(path|circle|ellipse|rect|line|polygon|polyline)\s([^>]*?)/?>', body):
        for closed, pts in polylines_of(m.group(1), attrs_of(m.group(2))):
            if closed and len(pts) > 1 and pts[0] != pts[-1]:
                pts = pts + [pts[0]]
            for i in range(len(pts) - 1):
                subs.append(capsule(pts[i], pts[i + 1]))
    return (HEAD + '  <path d="' + ''.join(subs) + '" />\n</svg>\n')


def is_stroked(text):
    """是否描边几何：根元素 fill="none" 且带 stroke（QwenPaw 原生图标与 heart_fill 是纯填充）"""
    root = text[:text.index('>', text.index('<svg'))]
    return 'fill="none"' in root and 'stroke=' in root


def main(argv):
    if len(argv) < 2:
        print(__doc__)
        return 1
    src_dir = Path(argv[1])
    dst_dir = Path(argv[2]) if len(argv) > 2 else src_dir
    if dst_dir != src_dir:
        dst_dir.mkdir(parents=True, exist_ok=True)
    done = skipped = 0
    for f in sorted(src_dir.rglob('*.svg')):
        text = f.read_text(encoding='utf-8')
        out = dst_dir / f.name
        if not is_stroked(text):           # 已是填充几何
            if out != f:
                shutil.copyfile(f, out)
            skipped += 1
            continue
        out.write_text(convert(text), encoding='utf-8')
        done += 1
    print(f'转换 {done} 个，跳过（原生填充）{skipped} 个 → {dst_dir}')
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
