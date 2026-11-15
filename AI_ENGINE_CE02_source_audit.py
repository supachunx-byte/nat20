#!/usr/bin/env python3
"""Read-only, pinned-source qualification evidence for Nat20-Rust.

This deliberately DOES NOT claim to run CE-02's independent gameplay gates.
It reports reproducible code observations, provenance, and untested gates.
No third-party Python dependencies are required.
"""
import argparse
import hashlib
import json
import pathlib
import re
import subprocess
import sys
from datetime import datetime, timezone

PIN = "9aaca2fdb061cbd00e4772472cd0937bbe8e1b44"
READS = {
    "dice": "core/src/components/dice.rs",
    "d20": "core/src/components/d20.rs",
    "prompt": "core/src/engine/prompt.rs",
    "execution": "core/src/components/actions/execution.rs",
    "state": "core/src/engine/engine_state.rs",
    "inventory": "core/src/components/items/inventory.rs",
    "reaction_prompt": "core/src/engine/action_prompt.rs",
}

def git(root, *args):
    return subprocess.check_output(["git", *args], cwd=root, text=True).strip()

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--output", default="ce02-source-evidence.json")
    a = parser.parse_args()
    root = pathlib.Path(a.repo_root).resolve()
    sources = {name: (root / rel).read_text(encoding="utf8") for name, rel in READS.items()}
    files = {name: {"path": READS[name], "sha256": hashlib.sha256(src.encode()).hexdigest()}
             for name, src in sources.items()}
    head = git(root, "rev-parse", "HEAD")
    merge_base = git(root, "merge-base", PIN, "HEAD")
    if merge_base != PIN:
        raise SystemExit("FAIL: pinned upstream commit is not an ancestor of HEAD")
    changed = git(root, "diff", "--name-only", PIN, "HEAD").splitlines()
    allowed = lambda p: p.startswith("ai_engine_ce02/") or p == ".github/workflows/ai_engine_ce02.yml"
    unapproved = [p for p in changed if not allowed(p)]
    if unapproved:
        raise SystemExit(f"FAIL: source changes outside experiment paths: {unapproved}")

    # These checks report source-level obstacles. They do not count as runtime gate tests.
    findings = [
        {
            "gate": "G07",
            "observation": "DiceSet::roll uses a local rand::rng()",
            "detected": "let mut rng = rand::rng();" in sources["dice"],
            "classification": "SOURCE_LEVEL_REPLAY_GAP_IF_DETECTED",
            "source": READS["dice"],
        },
        {
            "gate": "G07",
            "observation": "D20Check::roll uses a local rand::rng()",
            "detected": "let mut rng = rand::rng();" in sources["d20"],
            "classification": "SOURCE_LEVEL_REPLAY_GAP_IF_DETECTED",
            "source": READS["d20"],
        },
        {
            "gate": "G08",
            "observation": "PromptScope/PendingEvent are not marked Serializable in normal derive declarations",
            "detected": bool(re.search(r"#\[derive\(Debug, Default\)\]\s*pub struct PromptScope\b", sources["prompt"])) and
                        bool(re.search(r"#\[derive\(Debug, Clone\)\]\s*pub struct PendingEvent\b", sources["prompt"])),
            "classification": "SOURCE_LEVEL_PERSISTENCE_GAP_IF_DETECTED",
            "source": READS["prompt"],
        },
        {
            "gate": "G08",
            "observation": "ActionExecution has only Debug/Clone derives (no serde)",
            "detected": bool(re.search(r"#\[derive\(Debug, Clone\)\]\s*pub struct ActionExecution\b", sources["execution"])),
            "classification": "SOURCE_LEVEL_PERSISTENCE_GAP_IF_DETECTED",
            "source": READS["execution"],
        },
        {
            "gate": "G09",
            "observation": "Inventory is a Vec<ItemId> without per-copy instance IDs",
            "detected": bool(re.search(r"pub struct Inventory\s*\{\s*items:\s*Vec<ItemId>", sources["inventory"])),
            "classification": "SOURCE_LEVEL_IDENTITY_GAP_IF_DETECTED",
            "source": READS["inventory"],
        },
    ]
    report = {
        "project": "AI ENGINE", "experiment": "CE-02", "candidate": "Nat20-Rust",
        "upstream": "MadsWedendahlKruse/nat20", "pin": PIN,
        "evaluation_head": head,
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "changed_paths_relative_to_pin": changed,
        "files_checked": files,
        "source_observations": findings,
        "independent_runtime_acceptance": {x: "NOT_EXECUTED" for x in ("G07", "G08", "G09")},
        "warning": "Native tests and source inspection are supporting evidence. Never report G07/G08/G09 PASS from this file alone.",
        "original_source_unchanged": not unapproved,
    }
    pathlib.Path(a.output).write_text(json.dumps(report, indent=2) + "\n", encoding="utf8")
    print(json.dumps({"upstream_pin": PIN, "evaluation_head": head,
                      "candidate_source_unmodified": not unapproved,
                      "source_gaps_detected": sum(o["detected"] for o in findings),
                      "G07": "NOT_EXECUTED", "G08": "NOT_EXECUTED", "G09": "NOT_EXECUTED"}, indent=2))
    return 0

if __name__ == "__main__":
    sys.exit(main())
