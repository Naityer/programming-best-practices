from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[2] / "skill" / "programming-best-practices" / "scripts"
sys.path.insert(0, str(SCRIPTS))

from algorithms import analyze_repository


class MoreBehavioralCrossLanguageTests(unittest.TestCase):
    def _analyze(self, fixtures: dict[str, str]) -> list[dict]:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name, source in fixtures.items():
                (root / name).write_text(source, encoding="utf-8")
            return analyze_repository(root, use_cache=False)["algorithms"]

    def test_incremental_string_construction_is_shared_across_ecosystems(self) -> None:
        fixtures = {
            "case.py": "def f(parts):\n    out = ''\n    for part in parts:\n        out += part\n    return out\n",
            "Case.java": "class Case { String f(String[] parts) { String out=\"\"; for(String part:parts){ out += part; } return out; } }",
            "case.ts": "function f(parts:string[]){ let out=''; for(const part of parts){ out += part; } return out; }",
            "Case.cs": "class Case { string F(string[] parts){ var output=\"\"; foreach(var part in parts){ output += part; } return output; } }",
            "case.go": "package main\nfunc f(parts []string) string { out := \"\"; for _, part := range parts { out += part }; return out }",
            "case.rs": "fn f(parts: Vec<String>) -> String { let mut out=String::new(); for part in parts { out += &part; } out }",
            "case.cpp": "#include <string>\n#include <vector>\nstd::string f(std::vector<std::string> parts){ std::string out; for(auto part:parts){ out += part; } return out; }",
        }
        findings = [item for item in self._analyze(fixtures) if item["rule_id"] == "pbp.algorithm.sequence.repeated-concatenation"]
        self.assertEqual(set(fixtures), {item["primary_location"]["file"] for item in findings})
        self.assertEqual({"incremental-sequence-construction"}, {item["problem_signature"]["problem"] for item in findings})

    def test_key_equality_join_is_detected_but_plain_all_pairs_is_not(self) -> None:
        fixtures = {
            "join.py": "def f(users, orders):\n    for user in users:\n        for order in orders:\n            if user.id == order.user_id:\n                print(user, order)\n",
            "Join.java": "class Join { void f(User[] users, Order[] orders){ for(User user:users){ for(Order order:orders){ if(user.id == order.userId) use(user,order); } } } }",
            "join.ts": "function f(users:any[],orders:any[]){ for(const user of users){ for(const order of orders){ if(user.id === order.userId) use(user,order); } } }",
            "Join.cs": "class Join { void F(User[] users, Order[] orders){ foreach(var user in users){ foreach(var order in orders){ if(user.Id == order.UserId) Use(user,order); } } } }",
            "join.go": "package main\nfunc f(users []User, orders []Order){ for _, user := range users { for _, order := range orders { if user.id == order.userId { use(user,order) } } } }",
            "join.rs": "fn f(users: Vec<User>, orders: Vec<Order>){ for user in users { for order in &orders { if user.id == order.user_id { use_pair(&user,order); } } } }",
            "join.cpp": "void f(Users users, Orders orders){ for(auto user:users){ for(auto order:orders){ if(user.id == order.user_id){ use(user,order); } } } }",
            "all_pairs.py": "def f(xs, ys):\n    for x in xs:\n        for y in ys:\n            print(x * y)\n",
        }
        findings = [item for item in self._analyze(fixtures) if item["rule_id"] == "pbp.algorithm.data.nested-equality-join"]
        self.assertEqual(set(fixtures) - {"all_pairs.py"}, {item["primary_location"]["file"] for item in findings})


if __name__ == "__main__":
    unittest.main()

