"""
cluster.py — group log messages into templates without hand-written rules.

Pipeline
--------
1. ``normalise_message``  — replace the *variable* parts of a message (numbers,
   UUIDs, IPs, hex, durations, sizes, paths, URLs, e-mails, mixed IDs) with
   placeholders such as ``<NUM>`` or ``<IP>``.  After this step the 10,000
   near-identical lines usually collapse to a few hundred distinct strings.
2. ``DrainMiner``         — a compact implementation of the Drain algorithm
   (He et al., ICWS 2017): a fixed-depth prefix tree keyed by token count and
   leading tokens, with a token-wise similarity test at the leaves.  Tokens
   that differ between members of a group become ``<*>`` wildcards, so the
   group's *template* is learnt from the data rather than written by hand.
3. ``tfidf_cluster``      — a fallback that vectorises the normalised strings
   with TF-IDF and runs average-linkage agglomerative clustering on cosine
   distance.  Useful for free-form messages where token positions shift.

``cluster_messages`` wires these together and returns one cluster id per input
message plus a human-readable template for each cluster.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Iterable, Sequence

import numpy as np

# --------------------------------------------------------------------------- #
# 1. Message normalisation
# --------------------------------------------------------------------------- #

#: Ordered (placeholder, regex) substitutions. Order matters: more specific
#: patterns (UUID, IP, durations) must run before the generic number rule.
_SUBSTITUTIONS: list[tuple[str, re.Pattern]] = [
    ("<UUID>", re.compile(r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b")),
    ("<TS>", re.compile(r"\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:[.,]\d+)?(?:Z|[+-]\d{2}:?\d{2})?")),
    ("<TS>", re.compile(r"\b\d{1,2}:\d{2}:\d{2}(?:[.,]\d+)?\b")),
    ("<DATE>", re.compile(r"\b\d{4}-\d{2}-\d{2}\b|\b\d{2}/\d{2}/\d{4}\b")),
    ("<EMAIL>", re.compile(r"\b[\w.+-]+@[\w-]+(?:\.[\w-]+)+\b")),
    ("<URL>", re.compile(r"\b[a-z][a-z0-9+.-]*://[^\s\"'<>]+", re.IGNORECASE)),
    ("<IP>", re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}(?::\d{1,5})?\b")),
    ("<MAC>", re.compile(r"\b(?:[0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}\b")),
    ("<HEX>", re.compile(r"\b0[xX][0-9a-fA-F]+\b")),
    # long hex-looking tokens (hashes, trace ids) that contain both letters and digits
    ("<HEX>", re.compile(r"\b(?=[0-9a-fA-F]*\d)(?=[0-9a-fA-F]*[a-fA-F])[0-9a-fA-F]{10,}\b")),
    ("<DUR>", re.compile(
        r"(?<![\w.])\d+(?:\.\d+)?\s?(?:ns|us|µs|ms|s|sec|secs|seconds?|m|min|mins|minutes?|h|hr|hrs|hours?)\b"
    )),
    ("<SIZE>", re.compile(r"(?<![\w.])\d+(?:\.\d+)?\s?(?:B|KB|MB|GB|TB|KiB|MiB|GiB|bytes?)\b")),
    ("<PATH>", re.compile(r"(?<![\w:])(?:/[\w.\-@%+]+){2,}/?")),      # /var/log/app.log
    ("<PATH>", re.compile(r"\b[A-Za-z]:\\(?:[^\\\s]+\\?)+")),         # C:\Temp\x.log
    # alphanumeric tokens of 8+ chars mixing letters and digits: txn9f8a7b2c, AKIA3F...
    ("<ID>", re.compile(r"\b(?=[A-Za-z0-9]*\d)(?=[A-Za-z0-9]*[A-Za-z])[A-Za-z0-9]{8,}\b")),
    # Whole numeric tokens only ("order=98765" -> "order=<NUM>", "abc123" untouched).
    # Short integers (1-3 digits: HTTP codes, retry counts, percentages) are kept —
    # Drain turns them into <*> when they vary and preserves them when they are
    # constant, so "502 Bad Gateway" survives while "attempt 3/5" generalises.
    ("<NUM>", re.compile(r"(?<![A-Za-z0-9<.])[-+]?(?:\d+\.\d+|\d{4,})(?![A-Za-z0-9>])")),
]
_RE_WS = re.compile(r"\s+")


def normalise_message(message: str) -> str:
    """Replace variable fragments of a message with typed placeholders."""
    text = message
    for placeholder, pattern in _SUBSTITUTIONS:
        text = pattern.sub(placeholder, text)
    return _RE_WS.sub(" ", text).strip()


# --------------------------------------------------------------------------- #
# 2. Drain-style template mining
# --------------------------------------------------------------------------- #

WILDCARD = "<*>"


@dataclass
class Template:
    """A learnt log template (one cluster)."""
    id: int
    tokens: list[str]
    members: int = 0  # number of distinct normalised strings merged into it

    @property
    def text(self) -> str:
        return " ".join(self.tokens)


class _Node:
    __slots__ = ("children", "templates")

    def __init__(self) -> None:
        self.children: dict = {}
        self.templates: list[Template] = []


class DrainMiner:
    """Minimal Drain implementation.

    Parameters
    ----------
    depth : int
        Total tree depth. ``depth - 2`` leading tokens are used as tree keys
        (root -> token count -> token_1 -> ... -> leaf).
    sim_threshold : float
        Minimum fraction of positions that must match for a message to join
        an existing template (0.4-0.6 works for most logs).
    max_children : int
        Maximum branches per node; overflow goes to a shared ``<*>`` branch.
    """

    def __init__(self, depth: int = 4, sim_threshold: float = 0.5, max_children: int = 100):
        self.depth = max(depth, 3)
        self.sim_threshold = sim_threshold
        self.max_children = max_children
        self.root = _Node()
        self.templates: list[Template] = []

    # -- helpers ------------------------------------------------------------
    @staticmethod
    def _is_variable(token: str) -> bool:
        """Tokens with digits or placeholders should not create tree branches."""
        return (token.startswith("<") and token.endswith(">")) or any(c.isdigit() for c in token)

    @staticmethod
    def _similarity(template: Sequence[str], tokens: Sequence[str]) -> tuple[float, int]:
        """Fraction of equal positions (wildcards count as non-matching, as in Drain)."""
        same = params = 0
        for a, b in zip(template, tokens):
            if a == WILDCARD:
                params += 1
            elif a == b:
                same += 1
        return same / max(len(tokens), 1), params

    # -- main entry point ---------------------------------------------------
    def add(self, message: str) -> Template:
        """Insert one normalised message and return the template it joined."""
        tokens = message.split() or ["<EMPTY>"]

        # Layer 1: group by token count.
        node = self.root.children.setdefault(len(tokens), _Node())

        # Layers 2..depth-1: group by leading tokens (variables -> "<*>").
        for i in range(min(self.depth - 2, len(tokens))):
            key = WILDCARD if self._is_variable(tokens[i]) else tokens[i]
            if key not in node.children:
                if key != WILDCARD and len(node.children) >= self.max_children:
                    key = WILDCARD
                node.children.setdefault(key, _Node())
            node = node.children[key]

        # Leaf: pick the most similar template, or start a new one.
        best, best_sim, best_params = None, -1.0, -1
        for template in node.templates:
            sim, params = self._similarity(template.tokens, tokens)
            if sim > best_sim or (sim == best_sim and params > best_params):
                best, best_sim, best_params = template, sim, params

        if best is None or best_sim < self.sim_threshold:
            best = Template(id=len(self.templates), tokens=list(tokens))
            self.templates.append(best)
            node.templates.append(best)
        else:
            # Positions that differ become wildcards: the template is learnt.
            best.tokens = [a if a == b else WILDCARD for a, b in zip(best.tokens, tokens)]
        best.members += 1
        return best


# --------------------------------------------------------------------------- #
# 3. TF-IDF + agglomerative fallback
# --------------------------------------------------------------------------- #

MAX_TFIDF_UNIQUE = 3000  # cap for the O(n^2) agglomerative step


def _vote_template(messages: Sequence[str], weights: Sequence[int]) -> str:
    """Derive a display template for a cluster by majority vote per token.

    Members with the most common token count vote position-by-position;
    tokens that win fewer than 60% of the votes become ``<*>``.
    """
    token_lists = [m.split() for m in messages]
    length_votes = Counter()
    for toks, w in zip(token_lists, weights):
        length_votes[len(toks)] += w
    modal_len = length_votes.most_common(1)[0][0]
    chosen = [(t, w) for t, w in zip(token_lists, weights) if len(t) == modal_len]
    total = sum(w for _, w in chosen)
    out = []
    for pos in range(modal_len):
        votes = Counter()
        for toks, w in chosen:
            votes[toks[pos]] += w
        token, count = votes.most_common(1)[0]
        out.append(token if count / total >= 0.6 else WILDCARD)
    return " ".join(out)


def tfidf_cluster(unique_msgs: Sequence[str], counts: Sequence[int], similarity: float) -> np.ndarray:
    """Cluster unique normalised messages; returns a label per unique message."""
    from sklearn.cluster import AgglomerativeClustering
    from sklearn.feature_extraction.text import CountVectorizer
    from sklearn.preprocessing import normalize

    n = len(unique_msgs)
    if n == 1:
        return np.zeros(1, dtype=int)

    # Binary token presence *without* IDF weighting: IDF would up-weight exactly
    # the one-off tokens (ids, hashes) that should be ignored. Instead, tokens
    # that occur in a single *log line* overall are dropped — those are leftover
    # variables the normaliser missed and can never help group anything.
    vectoriser = CountVectorizer(token_pattern=r"[^\s]+", lowercase=True, binary=True)
    matrix = vectoriser.fit_transform(unique_msgs).astype(float)
    support = np.asarray(matrix.T @ np.asarray(counts, dtype=float)).ravel()  # lines per token
    keep = np.flatnonzero(support >= 2)
    if len(keep):
        matrix = matrix[:, keep]
    matrix = normalize(matrix, norm="l2")  # rows -> unit length (zero rows stay zero)

    # Cluster the most frequent strings; assign the long tail to the nearest centroid.
    order = np.argsort(-np.asarray(counts))
    head = order[:MAX_TFIDF_UNIQUE]
    tail = order[MAX_TFIDF_UNIQUE:]

    # Rows are L2-normalised, so X·Xᵀ is the cosine similarity. Computing the
    # distance matrix ourselves keeps all-zero rows (messages made only of
    # singleton tokens) from crashing sklearn's cosine metric.
    head_matrix = matrix[head]
    distance = 1.0 - (head_matrix @ head_matrix.T).toarray()
    np.fill_diagonal(distance, 0.0)
    distance = np.clip(distance, 0.0, 2.0)

    model = AgglomerativeClustering(
        n_clusters=None,
        distance_threshold=max(1.0 - similarity, 1e-6),
        metric="precomputed",
        linkage="average",
    )
    labels = np.empty(n, dtype=int)
    labels[head] = model.fit_predict(distance)

    if len(tail):
        k = labels[head].max() + 1
        centroids = np.vstack([
            np.asarray(head_matrix[labels[head] == c].mean(axis=0)).ravel() for c in range(k)
        ])
        norms = np.linalg.norm(centroids, axis=1, keepdims=True) + 1e-12
        sims = np.asarray(matrix[tail] @ (centroids / norms).T)  # sparse @ dense -> dense
        best = sims.argmax(axis=1)
        best_sim = sims.max(axis=1)
        for i, (row, lab, s) in enumerate(zip(tail, best, best_sim)):
            labels[row] = lab if s >= similarity else k + i  # too different -> own cluster
    return labels


# --------------------------------------------------------------------------- #
# 4. Public API
# --------------------------------------------------------------------------- #


@dataclass
class ClusterResult:
    labels: np.ndarray                 # cluster id per input message
    templates: dict[int, str]          # cluster id -> template text
    method: str
    n_unique: int                      # distinct strings after normalisation
    normalised: list[str] = field(default_factory=list)


def cluster_messages(messages: Iterable[str], method: str = "drain", similarity: float = 0.5,
                     depth: int = 4) -> ClusterResult:
    """Group messages into templates.

    Parameters
    ----------
    messages : iterable of raw message strings (one per log line)
    method : "drain" (default) or "tfidf"
    similarity : 0-1, higher = stricter grouping (more, smaller clusters)
    depth : Drain tree depth (number of leading tokens used = depth - 2)
    """
    messages = list(messages)
    if not messages:
        return ClusterResult(labels=np.array([], dtype=int), templates={}, method=method, n_unique=0)

    normalised = [normalise_message(m) for m in messages]
    counts = Counter(normalised)
    # Most frequent strings first so they define the templates.
    unique_msgs = [m for m, _ in counts.most_common()]
    unique_counts = [counts[m] for m in unique_msgs]

    if method == "tfidf":
        unique_labels = tfidf_cluster(unique_msgs, unique_counts, similarity)
        members: dict[int, list[tuple[str, int]]] = {}
        for msg, cnt, lab in zip(unique_msgs, unique_counts, unique_labels):
            members.setdefault(int(lab), []).append((msg, cnt))
        raw_templates = {
            lab: _vote_template([m for m, _ in rows], [c for _, c in rows]) for lab, rows in members.items()
        }
    else:
        miner = DrainMiner(depth=depth, sim_threshold=similarity)
        unique_labels = np.array([miner.add(m).id for m in unique_msgs], dtype=int)
        raw_templates = {t.id: t.text for t in miner.templates}

    # Map every line to its cluster, then renumber clusters by size (0 = largest).
    label_of = {m: int(l) for m, l in zip(unique_msgs, unique_labels)}
    line_labels = np.array([label_of[m] for m in normalised], dtype=int)
    size = Counter(line_labels.tolist())
    renumber = {old: new for new, (old, _) in enumerate(size.most_common())}
    line_labels = np.array([renumber[l] for l in line_labels], dtype=int)
    templates = {renumber[old]: text for old, text in raw_templates.items() if old in renumber}

    return ClusterResult(labels=line_labels, templates=templates, method=method,
                         n_unique=len(unique_msgs), normalised=normalised)


if __name__ == "__main__":  # quick manual check
    demo = [
        "Database connection timeout after 5000ms (host=10.0.3.17:5432)",
        "Database connection timeout after 5012ms (host=10.0.3.18:5432)",
        "Upstream timeout calling payment-svc POST /v1/charge (order=12345) after 10000ms",
        "Upstream timeout calling payment-svc POST /v1/charge (order=99) after 10003ms",
        "Slow query took 1203ms: SELECT * FROM orders WHERE id = 42",
    ]
    for d in demo:
        print(normalise_message(d))
    res = cluster_messages(demo)
    print(res.labels, res.templates)
