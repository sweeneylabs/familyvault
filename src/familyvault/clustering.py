"""
FamilyVault Face Clustering
Groups detected faces into people by comparing their embeddings.
Runs incrementally: only faces with no person_id yet are considered on
each run, so re-running after adding more photos never disturbs
already-named people.

Algorithm: incremental nearest-centroid matching, applied uniformly to
both existing people and brand-new clusters formed within this batch.
For each unclustered face, in order:
  - Compare it against the current mean embedding of every existing
    person AND every provisional new person created so far in this
    same run.
  - If the closest match is within MATCH_THRESHOLD, the face joins
    that person and that person's running mean is updated to include it.
  - Otherwise the face starts a brand-new (unnamed) person of its own.

This deliberately does NOT use pairwise clustering (e.g. DBSCAN on raw
face-to-face distances) for new people. An earlier version did, and
testing against synthetic embeddings caught a real problem with that
approach: in 512-dimensional space, two embeddings of the very same
person can end up farther from *each other* than each one is from
their shared mean — pairwise distance isn't a reliable same-person
signal here even when centroid distance is. Comparing every face to a
running centroid (mean of all known members so far) sidesteps that
entirely, and is the same principle step 1 (existing-person matching)
already relied on — this just extends it to also cover clusters being
formed for the first time.

Threshold note: embeddings are L2-normalized before comparison, so
Euclidean distance and cosine similarity are directly related
(distance = sqrt(2 - 2*cosine_similarity)). MATCH_THRESHOLD is
expressed in that normalized Euclidean distance. It's a heuristic, not
a certainty — expect some manual splitting/merging of results,
especially early on with a small library of known faces.
"""

from __future__ import annotations

import numpy as np
from dataclasses import dataclass

# Normalized Euclidean distance threshold for "same person". Roughly
# corresponds to a cosine similarity of ~0.64 (dist = sqrt(2 - 2*0.64)).
# Conservative on purpose: in a family library, wrongly merging two
# different people is worse than leaving a real match unmatched for a
# later, more confident pass. Tune this constant (and re-run
# `cluster-faces`) if results look too split (raise it) or too merged
# (lower it) once you've eyeballed some real results.
MATCH_THRESHOLD = 0.85


def _decode_embedding(blob: bytes) -> np.ndarray:
    """Decode a stored embedding BLOB back into a float32 numpy array."""
    return np.frombuffer(blob, dtype=np.float32)


def _normalize_one(vec: np.ndarray) -> np.ndarray:
    """L2-normalize a single vector to unit length."""
    norm = np.linalg.norm(vec)
    if norm == 0:
        return vec
    return vec / norm


@dataclass
class ClusterAssignment:
    """
    One face's outcome from a clustering run.

    person_id is the real database.people.id for a match against an
    existing person, or a negative placeholder (-1, -2, ...) for a
    brand-new person — the caller creates the real row and remaps
    before writing to the database (see new_people_specs on
    cluster_faces()).
    """
    face_id: int
    person_id: int
    is_new_person: bool


def cluster_faces(
    unclustered_faces: list[dict],
    existing_people: list[dict],
    match_threshold: float | None = None,
) -> tuple[list[ClusterAssignment], list[dict]]:
    """
    Assign a batch of not-yet-clustered faces to people.

    Args:
        unclustered_faces: Rows from database.get_faces_needing_clustering()
            — each a dict with at least 'id' and 'embedding' (bytes).
        existing_people: Rows from database.get_people_with_faces() —
            each a dict with 'id' and 'embeddings' (list of raw
            embedding bytes for that person's already-assigned faces),
            used to compute each person's current mean embedding.
        match_threshold: Override for MATCH_THRESHOLD, for tuning
            without editing this file. None uses the module default.

    Returns:
        (assignments, new_people_specs):
          assignments — one ClusterAssignment per input face, in the
            same order as unclustered_faces.
          new_people_specs — one dict per brand-new person needed,
            currently just {"face_count": n}, indexed such that
            placeholder -(i+1) corresponds to new_people_specs[i].
    """
    if match_threshold is None:
        match_threshold = MATCH_THRESHOLD

    if not unclustered_faces:
        return [], []

    # Every centroid we can match against — seeded from existing
    # people, then grown with brand-new provisional people as this
    # batch is processed. Parallel lists + an id->index map for O(1)
    # lookups when updating a running mean.
    centroid_ids: list[int] = []
    centroid_sums: list[np.ndarray] = []   # running sum of unit-normalized member embeddings
    centroid_counts: list[int] = []
    centroid_means: list[np.ndarray] = []  # normalize(sum) — recomputed whenever a member joins
    id_to_index: dict[int, int] = {}

    for person in existing_people:
        if not person["embeddings"]:
            continue
        member_vecs = [_normalize_one(_decode_embedding(e)) for e in person["embeddings"]]
        s = np.sum(member_vecs, axis=0)
        idx = len(centroid_ids)
        centroid_ids.append(person["id"])
        centroid_sums.append(s)
        centroid_counts.append(len(member_vecs))
        centroid_means.append(_normalize_one(s))
        id_to_index[person["id"]] = idx

    assignments: list[ClusterAssignment] = []
    new_people_specs: list[dict] = []
    next_placeholder = -1

    for face in unclustered_faces:
        vec = _normalize_one(_decode_embedding(face["embedding"]))

        best_id = None
        best_dist = None
        if centroid_means:
            matrix = np.stack(centroid_means)
            dists = np.linalg.norm(matrix - vec, axis=1)
            idx = int(np.argmin(dists))
            best_dist = float(dists[idx])
            best_id = centroid_ids[idx]

        if best_id is not None and best_dist <= match_threshold:
            cidx = id_to_index[best_id]
            centroid_sums[cidx] = centroid_sums[cidx] + vec
            centroid_counts[cidx] += 1
            centroid_means[cidx] = _normalize_one(centroid_sums[cidx])

            is_new = best_id < 0
            if is_new:
                new_people_specs[-(best_id) - 1]["face_count"] += 1
            assignments.append(ClusterAssignment(face_id=face["id"], person_id=best_id, is_new_person=is_new))
        else:
            placeholder = next_placeholder
            next_placeholder -= 1

            idx = len(centroid_ids)
            centroid_ids.append(placeholder)
            centroid_sums.append(vec.copy())
            centroid_counts.append(1)
            centroid_means.append(vec.copy())
            id_to_index[placeholder] = idx

            new_people_specs.append({"face_count": 1})
            assignments.append(ClusterAssignment(face_id=face["id"], person_id=placeholder, is_new_person=True))

    return assignments, new_people_specs