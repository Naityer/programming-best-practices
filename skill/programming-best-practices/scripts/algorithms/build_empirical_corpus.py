#!/usr/bin/env python3
"""Build the labelled executable corpus used by empirical release gates."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

REPEATED = {
    "python": ("case.py", "def f(available, requested):\n    for item in requested:\n        if item in available:\n            print(item)\n"),
    "jvm": ("Case.java", "class Case { void f(java.util.List<Integer> a, java.util.List<Integer> r) { for (int x:r) { if(a.contains(x)) use(x); } } }"),
    "js-ts": ("case.ts", "function f(a:number[],r:number[]){ for(const x of r){ if(a.includes(x)) use(x); } }"),
    "dotnet": ("Case.cs", "class Case { void F(List<int> a,List<int> r){ foreach(var x in r){ if(a.Contains(x)) Use(x); } } }"),
    "go": ("case.go", "package main\nimport \"slices\"\nfunc f(a,r []int){ for _,x:=range r { if slices.Contains(a,x){ println(x) } } }"),
    "rust": ("case.rs", "fn f(a:&[i32],r:&[i32]){ for x in r { if a.contains(x){ println!(\"{}\",x); } } }"),
    "cpp": ("case.cpp", "#include <algorithm>\nvoid f(V a,V r){ for(auto x:r){ if(std::find(a.begin(),a.end(),x)!=a.end()){ use(x); } } }"),
}
CONCAT = {
    "python": ("case.py", "def f(parts):\n    out=''\n    for part in parts:\n        out += part\n    return out\n"),
    "jvm": ("Case.java", "class Case { String f(String[] p){ String o=\"\"; for(String x:p){o+=x;} return o;} }"),
    "js-ts": ("case.ts", "function f(p:string[]){let o='';for(const x of p){o+=x;}return o;}"),
    "dotnet": ("Case.cs", "class Case { string F(string[] p){var o=\"\";foreach(var x in p){o+=x;}return o;} }"),
    "go": ("case.go", "package main\nfunc f(p []string)string{o:=\"\";for _,x:=range p{o+=x};return o}"),
    "rust": ("case.rs", "fn f(p:Vec<String>)->String{let mut o=String::new();for x in p{o+=&x;}o}"),
    "cpp": ("case.cpp", "std::string f(V p){std::string o;for(auto x:p){o+=x;}return o;}"),
}
ALL_PAIRS_NEGATIVE = {
    "python": ("case.py", "def f(xs,ys):\n    for x in xs:\n        for y in ys:\n            print(x*y)\n"),
    "jvm": ("Case.java", "class Case { void f(int[] xs,int[] ys){for(int x:xs){for(int y:ys){use(x*y);}}} }"),
    "js-ts": ("case.ts", "function f(xs:number[],ys:number[]){for(const x of xs){for(const y of ys){use(x*y);}}}"),
    "dotnet": ("Case.cs", "class Case {void F(int[] xs,int[] ys){foreach(var x in xs){foreach(var y in ys){Use(x*y);}}}}"),
    "go": ("case.go", "package main\nfunc f(xs,ys []int){for _,x:=range xs{for _,y:=range ys{println(x*y)}}}"),
    "rust": ("case.rs", "fn f(xs:&[i32],ys:&[i32]){for x in xs{for y in ys{println!(\"{}\",x*y);}}}"),
    "cpp": ("case.cpp", "void f(V xs,V ys){for(auto x:xs){for(auto y:ys){use(x*y);}}}"),
}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--core", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    core = json.loads(args.core.read_text(encoding="utf-8"))
    cases = list(core["cases"])
    for ecosystem, (filename, source) in REPEATED.items():
        cases.append({"id": f"repeated-membership-{ecosystem}", "files": {filename: source}, "expected": {"pbp.algorithm.search.repeated-linear-membership": "ASSISTED"}})
    for ecosystem, (filename, source) in CONCAT.items():
        cases.append({"id": f"repeated-concat-{ecosystem}", "files": {filename: source}, "expected": {"pbp.algorithm.sequence.repeated-concatenation": "ASSISTED"}})
    for ecosystem, (filename, source) in ALL_PAIRS_NEGATIVE.items():
        cases.append({"id": f"all-pairs-negative-{ecosystem}", "files": {filename: source}, "expected": {}})
    result = {"schema_version": "1.0.0", "scope": "Atlas core plus executable seven-ecosystem behavioral corpus", "cases": cases}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"empirical cases={len(cases)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

