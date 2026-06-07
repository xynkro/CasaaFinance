"""Black-Scholes-Merton shared math.

Single canonical home for the standard-normal CDF used across the option
scanners and Greek calculators. Previously each scanner/tracker carried its
own ``_norm_cdf`` one-liner; this module de-duplicates that.

Stdlib-only (no scipy dependency).
"""

from __future__ import annotations

import math


def norm_cdf(x: float) -> float:
    """Standard normal cumulative distribution function (via ``math.erf``)."""
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))
