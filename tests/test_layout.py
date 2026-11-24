"""Data-driven clusters (I31): balanced, deterministic, and usable by the network."""

import numpy as np
from test_proofs import random_world

from yovahti.world.layout import rhythm_clusters


def test_rhythm_clusters_are_balanced_and_deterministic():
    w = random_world(np.random.default_rng(1), 700, 40)
    a, b = rhythm_clusters(w, 700), rhythm_clusters(w, 700)
    assert a == b and len(a) == 40
    sizes = np.bincount([int(v[1:]) for v in a.values()])[1:]
    assert sorted(sizes) == [10, 10, 10, 10]
