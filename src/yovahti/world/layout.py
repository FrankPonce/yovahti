"""Data-driven clusters (I31): the Slovak dataset has no coordinates, so geographic
neighbourhoods cannot be rebuilt. The next best, labelled as such: group sites whose *weekly
traffic rhythm* is alike (offices with offices, nightlife with nightlife). Agents then plan a
cluster whose cells behave alike, instead of ten sites that are merely adjacent in id order.

Method: per site, the mean log traffic of its capacity layers for each of the 168 hours of the
week, on the training weeks only, centred and scaled; first two principal components; sites
ordered by angle around the centre and cut into balanced groups of ``size``. Deterministic.
"""

from __future__ import annotations

import re

import numpy as np

from yovahti.world.data import WorldData


def site_of(sector: str) -> str:
    return sector.split("/")[0]


def rhythm(world: WorldData, train_end: int) -> tuple[list[str], np.ndarray]:
    """Sites and their [n_sites, 168] standardised weekly rhythm."""
    lt = world.times[:train_end].tz_convert("Europe/Bratislava")
    how = (lt.day_of_week * 24 + lt.hour).to_numpy()
    y = np.log1p(world.vol["LTE_1800"][:train_end] + world.vol["NR_2100"][:train_end]
                 + world.vol["NR_3500"][:train_end])
    sites = sorted({site_of(s) for s in world.sectors},
                   key=lambda x: int(re.sub(r"\D", "", x) or 0))
    idx = {s: [i for i, sec in enumerate(world.sectors) if site_of(sec) == s] for s in sites}
    prof = np.zeros((len(sites), 168))
    for j, s in enumerate(sites):
        ys = y[:, idx[s]].mean(axis=1)
        prof[j] = np.bincount(how, ys, 168) / np.maximum(np.bincount(how, minlength=168), 1)
    prof -= prof.mean(axis=1, keepdims=True)
    prof /= np.maximum(prof.std(axis=1, keepdims=True), 1e-9)
    return sites, prof


def rhythm_clusters(world: WorldData, train_end: int, size: int = 10) -> dict[str, str]:
    sites, prof = rhythm(world, train_end)
    x = prof - prof.mean(axis=0)
    _, _, vt = np.linalg.svd(x, full_matrices=False)
    pc = x @ vt[:2].T
    order = np.argsort(np.arctan2(pc[:, 1], pc[:, 0]), kind="stable")
    return {sites[i]: f"R{k // size + 1:02d}" for k, i in enumerate(order)}


def within_similarity(world: WorldData, train_end: int, clusters: dict[str, str]) -> float:
    """Mean correlation of weekly rhythms between sites of the same cluster."""
    sites, prof = rhythm(world, train_end)
    with np.errstate(invalid="ignore", divide="ignore"):
        c = np.corrcoef(prof)
    lab = np.array([clusters[s] for s in sites])
    same = (lab[:, None] == lab[None, :]) & ~np.eye(len(sites), dtype=bool)
    return float(np.nanmean(c[same]))      # sites without capacity traffic have no rhythm
