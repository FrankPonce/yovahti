"""Live check on the guarantee (E28, E29): is the forecast's miss rate still near alpha?

The arbiter's no-congestion proof holds only while traffic stays at or under the forecast it
checked; conformal calibration makes that true for a share 1 - alpha of slept quarter-hours,
for exchangeable weeks. Weeks drift (holidays, growth, a new stadium), so the guarantee has to
be *watched*, not assumed. Every day this monitor takes the conformal scores of the last
``window_days`` (actual receiving traffic / the forecast the planner checked, over the
quarter-hours it let sleep), and

* raises an alarm when the share above the planning margin exceeds alpha by more than
  ``z`` standard errors (overall, and for night and day separately, Mondrian groups). The
  standard error uses the number of distinct sector-days, not of quarter-hours: a sector's
  quarter-hours in one night move together, and counting them as independent made the
  monitor alarm on clean weeks;
* suggests the margin that would restore alpha on that recent window (split conformal).

The suggestion is advice for the operator or a policy, not applied automatically: widening
the margin costs energy, and a one-off event should not reset the dial.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from yovahti.forecast.bound import Scores, margin


@dataclass
class Check:
    day: int                 # world day index the check ran at (end of window)
    n: int                   # scored points in the window
    miss: float              # share of scores above the current margin
    limit: float             # alpha + z * standard error
    alarm: bool
    groups: dict             # {"night"/"day": miss}
    suggested_margin: float  # restores alpha on the window


def daily_checks(sc: Scores, current_margin: float, alpha: float = 0.10,
                 window_days: int = 7, z: float = 3.0) -> list[Check]:
    day = sc.t // 96
    out = []
    for d in range(int(day.min()) + window_days - 1, int(day.max()) + 1):
        w = (day > d - window_days) & (day <= d)
        r = sc.r[w]
        n = len(r)
        if n < 100:
            continue
        miss = float(np.mean(r > current_margin))
        n_eff = len(np.unique(sc.s[w] * 10_000 + day[w]))          # sector-days
        limit = alpha + z * np.sqrt(alpha * (1 - alpha) / n_eff)
        groups, alarm = {}, miss > limit
        for g in ("night", "day"):
            gm = w & (sc.night == (g == "night"))
            if gm.sum() >= 100:
                ng = len(np.unique(sc.s[gm] * 10_000 + day[gm]))
                gmiss = float(np.mean(sc.r[gm] > current_margin))
                groups[g] = round(gmiss, 4)
                alarm |= gmiss > alpha + z * np.sqrt(alpha * (1 - alpha) / ng)
        out.append(Check(d, n, round(miss, 4), round(float(limit), 4), bool(alarm), groups,
                         round(margin(r, alpha), 3)))
    return out
