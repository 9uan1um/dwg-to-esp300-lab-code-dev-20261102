"""Bounded camera-signal acquisition; callbacks keep hardware out of this module."""
import math
from dataclasses import dataclass


def grid(radius, step):
    if not all(math.isfinite(v) and v > 0 for v in (radius, step)):
        raise ValueError("Search range and step must be finite and positive.")
    n = math.ceil(radius / step)
    if n > 1000:
        raise ValueError("Search grid is too dense.")
    return sorted(set([0.0, -radius, radius] + [i * step for i in range(-n + 1, n) if abs(i * step) < radius]))


def search_grid(xy_range, xy_step, z_range, z_step):
    xy, zs = grid(xy_range, xy_step), grid(z_range, z_step)
    if len(xy)**2 * len(zs) > 5000:
        raise ValueError("Search exceeds 5000 measurements. Reduce range or increase step.")
    points = sorted(((x, y) for x in xy for y in xy), key=lambda p: (max(abs(p[0]), abs(p[1])), p[1], p[0]))
    return points, zs


def peak_index(samples, contrast=.1):
    """Require a bracketed peak with signal support, not just an argmax."""
    if len(samples) < 5 or any(not math.isfinite(v) or v < 0 for _, v in samples):
        return None
    k = max(range(len(samples)), key=lambda i: samples[i][1])
    peak = samples[k][1]
    if k in (0, len(samples)-1) or peak <= 0:
        return None
    if sum(v >= peak * .2 for _, v in samples) < 3:
        return None
    if max(samples[0][1], samples[-1][1]) >= peak * (1-contrast):
        return None
    return k


@dataclass
class SearchResult:
    x: float
    y: float
    z: float
    samples: list
    verified_score: float
    visited: int


def acquire_focus(points, zs, measure, progress=lambda *args: None):
    """Try nearest XY locations first; sweep Z, refine and remeasure a candidate.

    No image-to-stage calibration is assumed. No qualifying curve means failure,
    never a guessed focus. Finite grids can miss features narrower than their step.
    """
    for visited, (x, y) in enumerate(points, 1):
        samples = []
        for z in zs:
            value = float(measure(x, y, z))
            if not math.isfinite(value) or value < 0:
                raise RuntimeError("Invalid camera score.")
            samples.append((z, value))
            progress(visited, len(points), samples)
        k = peak_index(samples)
        if k is None:
            continue
        lo, hi = samples[k-1][0], samples[k+1][0]
        fine = [(lo + (hi-lo)*i/10, 0) for i in range(11)]
        fine = [(z, float(measure(x, y, z))) for z, _ in fine]
        fk = peak_index(fine, contrast=0)
        if fk is None:
            continue
        z, score = fine[fk]
        verified = float(measure(x, y, z))
        if not math.isfinite(verified) or not .7 * score <= verified <= 1.3 * score:
            continue
        return SearchResult(x, y, z, fine, verified, visited)
    raise RuntimeError("No repeatable focus peak in the XYZ search range. Check camera view/signal or adjust the range and step. Stage remains at the last measured position.")
