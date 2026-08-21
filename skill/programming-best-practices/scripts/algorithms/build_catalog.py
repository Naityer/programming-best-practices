#!/usr/bin/env python3
"""Build the canonical Atlas 6-24 knowledge catalog and case contracts.

This stores decision knowledge only.  It never stores copyable implementations
of algorithms or cryptographic primitives.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

LANGUAGES = ("python", "java", "javascript", "csharp", "go", "rust", "cpp")

TAXONOMY = {
    ("search", 6, 1): "Linear Search|Binary Search|Exponential Search|Interpolation Search|Jump Search|Hash Lookup|Tree Search|Trie Search|Nearest Neighbor|Quickselect|Order Statistics|Hash Table|Balanced Tree|B-Tree|Trie|Bloom Filter|Inverted Index",
    ("sorting", 7, 1): "Insertion Sort|Selection Sort|Bubble Sort|Shell Sort|Merge Sort|Quick Sort|Heap Sort|Introsort|TimSort|Counting Sort|Radix Sort|Bucket Sort|External Sort|Topological Sort",
    ("selection", 8, 1): "Minimum|Maximum|Quickselect|Heap Top-K|Partial Sort|nth element|Median Selection|Tournament Selection",
    ("graphs", 9, 1): "BFS|DFS|Iterative DFS|Bidirectional Search|0-1 BFS|Dijkstra|Bellman-Ford|Floyd-Warshall|Johnson|A*|Bidirectional Dijkstra|Connected Components|Union-Find DSU|Tarjan SCC|Kosaraju SCC|Bridge Detection|Articulation Points|Kruskal|Prim|Boruvka|Topological Sort|Kahn|DFS Topological Sort|Longest Path in DAG|Critical Path|Ford-Fulkerson|Edmonds-Karp|Dinic|Push-Relabel|Min-Cost Max-Flow|Bipartite Matching|Hopcroft-Karp|Hungarian Algorithm|Stable Matching",
    ("strings", 10, 1): "Naive Search|KMP|Z Algorithm|Rabin-Karp|Boyer-Moore|Boyer-Moore-Horspool|Trie|Aho-Corasick|Suffix Array|Suffix Tree|Suffix Automaton|Longest Common Subsequence|Longest Common Substring|Edit Distance|Levenshtein|Damerau-Levenshtein|Rolling Hash|Palindrome Algorithms|Manacher|Tokenization|Prefix Matching",
    ("dynamic-programming", 11, 1): "Memoization|Tabulation|Knapsack|Coin Change|LCS|LIS|Edit Distance|Matrix Chain Multiplication|Interval DP|Grid DP|Tree DP|Bitmask DP|Digit DP",
    ("greedy", 12, 1): "Interval Scheduling|Activity Selection|Huffman|Fractional Knapsack|Job Scheduling|Kruskal|Prim|Dijkstra",
    ("divide-and-conquer", 13, 1): "Merge Sort|Quick Sort|Binary Search|Quickselect|Closest Pair|Karatsuba|FFT-based Algorithms",
    ("backtracking", 14, 2): "Backtracking|Branch and Bound|Minimax|Alpha-Beta Pruning|Constraint Search|Exact Cover|Algorithm X",
    ("numerical", 15, 2): "Bisection|Newton-Raphson|Secant|Brent|Trapezoidal Integration|Simpson Integration|Gaussian Quadrature|Monte Carlo Integration|Gaussian Elimination|LU|QR|Cholesky|SVD|Eigenvalue Methods|Conjugate Gradient|DFT|FFT|IFFT|Linear Interpolation|Polynomial Interpolation|Lagrange Interpolation|Newton Interpolation|Spline Interpolation",
    ("optimization", 16, 2): "Gradient Descent|Stochastic Gradient Descent|Momentum|Nesterov|AdaGrad|RMSProp|Adam|Newton Optimization|Quasi-Newton|BFGS|L-BFGS|Conjugate Gradient|Projected Gradient|Lagrange Multipliers|Interior Point|Simplex|Branch and Bound|Dynamic Programming|Local Search|Simulated Annealing|Genetic Algorithms|Evolution Strategies|Particle Swarm Optimization|Tabu Search",
    ("data-analysis", 17, 1): "Mean|Weighted Mean|Median|Variance|Standard Deviation|Covariance|Correlation|Percentiles|Histograms|Welford|Reservoir Sampling|Bloom Filter|Count-Min Sketch|HyperLogLog|Streaming Quantiles|Sliding Window|Exponential Moving Average",
    ("machine-learning", 18, 3): "Logistic Regression|Naive Bayes|k-NN|Decision Tree|Random Forest|Gradient Boosting|SVM|Linear Classifiers|Neural Networks|Linear Regression|Ridge|Lasso|Elastic Net|Decision Tree Regression|Random Forest Regression|Gradient Boosting Regression|K-Means|K-Medoids|DBSCAN|Hierarchical Clustering|Gaussian Mixture Models|PCA|SVD|ICA|Random Projection|t-SNE|UMAP|Isolation Forest|One-Class SVM|Local Outlier Factor|Statistical Thresholds",
    ("computational-geometry", 19, 2): "Convex Hull|Graham Scan|Jarvis March|Sweep Line|Closest Pair|Point in Polygon|Line Intersection|Voronoi|Delaunay|R-Tree Search",
    ("cache", 20, 1): "LRU|LFU|FIFO|TTL|2Q|Clock",
    ("scheduling", 21, 2): "FIFO|Round Robin|Priority Scheduling|Shortest Job First|Earliest Deadline First|Weighted Fair Scheduling|Interval Scheduling",
    ("data-processing", 22, 1): "Nested Loop Join|Hash Join|Sort-Merge Join|Batching|Partitioning|External Sort|Hash Aggregation|Sort Aggregation",
    ("compression", 23, 2): "Run-Length Encoding|Huffman|LZ77|LZ78|LZW|Delta Encoding|Dictionary Encoding",
    ("security", 24, 1): "Cryptographic Hashing|Password Hashing|MAC|AEAD|Key Derivation|CSPRNG|Digital Signatures",
}

FAMILY_REQUIREMENTS = {
    "sorting": ["ordering relation is valid", "stability and mutation requirements are known"],
    "graphs": ["graph direction, weighting and edge-domain constraints are known"],
    "numerical": ["precision, conditioning and convergence requirements are known"],
    "optimization": ["objective, constraints and exactness requirements are known"],
    "machine-learning": ["dataset, target, baseline, metric, latency and interpretability requirements are available"],
    "security": ["a maintained vetted library and threat model are selected"],
}


def slug(value: str) -> str:
    normalized = value.lower().replace("a*", "a-star").replace("0-1", "zero-one")
    return re.sub(r"[^a-z0-9]+", "-", normalized).strip("-")


def _entry(family: str, section: int, tier: int, name: str) -> dict:
    identifier = f"{family}.{slug(name)}"
    approximate = any(token in name.lower() for token in ("monte carlo", "bloom", "count-min", "hyperloglog", "t-sne", "umap", "metaheur"))
    return {
        "id": identifier,
        "display_name": name,
        "family": family,
        "tier": tier,
        "problem": f"Apply {name} when its {family.replace('-', ' ')} problem signature and constraints are proven.",
        "preconditions": FAMILY_REQUIREMENTS.get(family, ["the problem signature and all hard semantic constraints are known"]),
        "contraindications": ["a hard requirement is UNKNOWN or CONTRADICTED", "a simpler adequate standard-library operation exists"],
        "complexity": {"time": "implementation-dependent", "space": "implementation-dependent", "variants": ["average", "worst", "amortized when applicable"]},
        "memory": "implementation-dependent",
        "exactness": "approximate-or-stochastic" if approximate else "exact-or-implementation-dependent",
        "stability": "implementation-dependent",
        "alternatives": [],
        "common_misuses": ["selecting by Big-O alone", "ignoring semantic, memory, size or side-effect constraints"],
        "recipes": [{
            "id": f"{identifier}.assess",
            "correction_level": "MANUAL",
            "strategy": "Prove the Problem Signature and hard requirements, then prefer a maintained standard/library mapping.",
            "validation": ["reanalyze", "differential-test", "property-based-test", "benchmark when performance motivates the change"],
        }],
        "standard_mappings": {language: [] for language in LANGUAGES},
        "references": [f"Atlas §{section}"],
    }


def _case_contracts(identifier: str) -> list[dict]:
    return [
        {"kind": "positive", "evidence": {"kind": "standard-api", "binding": "resolved"}, "expected": {"status": "recognized", "correction_level": None}},
        {"kind": "negative", "evidence": {"kind": "name-only", "binding": "unresolved"}, "expected": {"status": "unknown", "correction_level": None}},
        {"kind": "misuse", "requirements": [{"name": "catalog hard precondition", "state": "CONTRADICTED", "hard": True}], "expected": {"status": "incorrect", "correction_level": "BLOCKED"}},
        {"kind": "alternative", "requirements": [{"name": "catalog hard precondition", "state": "PROVEN", "hard": True}], "expected": {"status": "acceptable", "correction_level": "MANUAL"}},
        {"kind": "edge", "requirements": [{"name": "catalog hard precondition", "state": "UNKNOWN", "hard": True}], "expected": {"status": "ambiguous", "correction_level": "MANUAL"}},
    ]

def build(existing: dict) -> tuple[dict, dict]:
    by_id = {entry["id"]: entry for entry in existing.get("algorithms", [])}
    for (family, section, tier), names in TAXONOMY.items():
        for name in names.split("|"):
            candidate = _entry(family, section, tier, name)
            by_id.setdefault(candidate["id"], candidate)
    for entry in by_id.values():
        if not entry.get("recipes"):
            section_match = re.search(r"\d+", str(entry.get("references", ["Atlas §6"])[0]))
            section = int(section_match.group()) if section_match else 6
            entry["recipes"] = _entry(entry["family"], section, entry["tier"], entry.get("display_name", entry["id"]))["recipes"]
        entry.setdefault("display_name", entry["id"].split(".")[-1].replace("-", " ").title())
        entry.setdefault("standard_mappings", {language: [] for language in LANGUAGES})
        for language in LANGUAGES:
            entry["standard_mappings"].setdefault(language, [])
    algorithms = sorted(by_id.values(), key=lambda item: (item["tier"], item["family"], item["id"]))
    catalog = {
        **existing,
        "schema_version": "1.0.0",
        "catalog_version": "1.0.0",
        "policy": {
            **existing.get("policy", {}),
            "selection": "Problem Signature -> hard requirements -> counterevidence -> alternative competition -> contextual ranking",
            "cryptography": "recognize and route to vetted libraries; never emit primitive implementation code",
        },
        "families": sorted({entry["family"] for entry in algorithms}),
        "algorithms": algorithms,
    }
    contracts = {
        "schema_version": "1.0.0",
        "catalog_version": catalog["catalog_version"],
        "case_kinds": ["positive", "negative", "misuse", "alternative", "edge"],
        "algorithms": [{"algorithm_id": entry["id"], "cases": _case_contracts(entry["id"])} for entry in algorithms],
    }
    return catalog, contracts


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalog", type=Path, required=True)
    parser.add_argument("--cases", type=Path, required=True)
    args = parser.parse_args()
    existing = json.loads(args.catalog.read_text(encoding="utf-8"))
    catalog, contracts = build(existing)
    args.catalog.write_text(json.dumps(catalog, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    args.cases.parent.mkdir(parents=True, exist_ok=True)
    args.cases.write_text(json.dumps(contracts, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"catalog={len(catalog['algorithms'])}; contracts={sum(len(item['cases']) for item in contracts['algorithms'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

