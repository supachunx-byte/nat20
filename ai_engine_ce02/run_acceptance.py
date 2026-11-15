#!/usr/bin/env python3
"""CE-02 independent Nat20-Rust knockout probes. Test harness only.

Runs against the pinned, unchanged Nat20-Rust engine from a GitHub Actions checkout.
Creates two *untracked, ephemeral* files in core/tests/ and deletes them in finally.
Never writes a production source file and never interprets native success as gate PASS.

G07: Two clean test-process dice traces under identical inputs (partial subgate).
G08: Compile-time serializer feasibility check. NOT a crash/restart test.
G09: Distinct copies of one item definition in native Inventory (partial subgate).
"""

import argparse
import datetime as dt
import json
import os
import pathlib
import re
import subprocess
import sys

PIN = "9aaca2fdb061cbd00e4772472cd0937bbe8e1b44"

RUNTIME_RS = r'''// CE-02 independent probes: disposable integration test, no engine edits.
use nat20_core::components::{
    dice::{DiceSet, DieSize},
    id::ItemId,
    items::inventory::Inventory,
};

#[test]
fn g07_emit_rolls() {
    // One process, fixed call pattern; a second process repeats the same inputs.
    // This does NOT supply a seed: the API does not accept one. It is only an
    // independent negative control for uncontrolled gameplay randomness.
    let result = DiceSet::new(24, DieSize::D20).roll();
    println!("CE02_G07_ROLLS={:?}", result.rolls());
    assert_eq!(result.rolls().len(), 24);
    assert!(result.rolls().iter().all(|&die| (1..=20).contains(&die)));
}

#[test]
fn g09_distinct_item_copies() {
    let item_definition = ItemId::new("nat20_core", "item.ce02_two_copies");
    let mut inventory = Inventory::new();
    inventory.add_item(item_definition.clone());
    inventory.add_item(item_definition.clone());
    assert_eq!(inventory.items().len(), 2, "two copies must remain in inventory");
    println!("CE02_G09_DEFINITION_IDS_COLLIDE={}", inventory.items()[0] == inventory.items()[1]);
    // Distinct physical copies require stable instance identities; the native
    // inventory entries expose only the same ItemId (definition identifier).
    assert_ne!(inventory.items()[0], inventory.items()[1],
        "G09 native inventory does not distinguish two copies of one item definition");
}
'''

SERIALIZE_RS = r'''// CE-02 G08 *capability* check. This is not a restart test.
use nat20_core::engine::engine_state::EngineState;
use serde::Serialize;

fn require_serializable<T: Serialize>() {}

#[test]
fn g08_snapshot_state_is_serializable() {
    require_serializable::<EngineState>();
}
'''


def run(cmd, root, log_path, timeout):
    try:
        p = subprocess.run(cmd, cwd=root, text=True, stdout=subprocess.PIPE,
                           stderr=subprocess.STDOUT, timeout=timeout, check=False)
        log_path.write_text(p.stdout, encoding="utf-8")
        return {"exit_code": p.returncode, "log": str(log_path.name), "output": p.stdout}
    except subprocess.TimeoutExpired as exc:
        output = exc.stdout or b""
        if isinstance(output, bytes):
            output = output.decode("utf-8", errors="replace")
        log_path.write_text(output + "\nCE02_TIMEOUT\n", encoding="utf-8")
        return {"exit_code": None, "log": str(log_path.name), "output": output, "timeout": True}


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--repo-root", default=".")
    p.add_argument("--output", default="ce02-independent-gates.json")
    p.add_argument("--log-dir", default="ce02-probe-logs")
    a = p.parse_args()
    root = pathlib.Path(a.repo_root).resolve()
    logdir = root / a.log_dir
    logdir.mkdir(parents=True, exist_ok=True)
    output = root / a.output
    temp_runtime = root / "core/tests/ai_engine_ce02_runtime.rs"
    temp_compile = root / "core/tests/ai_engine_ce02_snapshot_contract.rs"
    created_files = []
    report = {
        "project": "AI ENGINE", "experiment": "CE-02",
        "candidate": "Nat20-Rust", "upstream_pin": PIN,
        "timestamp_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
        "classification_rule": "Native test success does not certify independent acceptance. Negative controls may fail intentionally.",
        "gates": {}, "errors": [],
        "limitations": [
            "G07 compares clean-process raw dice under identical inputs, but the current API has no caller-seed parameter; this is not full seeded event replay.",
            "G08 checks the direct EngineState serde contract only. No pending Shield decision was saved, process-killed, and restored.",
            "G09 checks native Inventory copy identity only; charge use, transfer, ownership enforcement, and persistence remain untested.",
        ],
    }

    try:
        if temp_runtime.exists() or temp_compile.exists():
            raise RuntimeError("Refusing to replace an existing test file in core/tests/")
        head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip()
        ancestor = subprocess.run(["git", "merge-base", "--is-ancestor", PIN, head], cwd=root, check=False)
        if ancestor.returncode != 0:
            raise RuntimeError("Pinned upstream source is not an ancestor of checkout HEAD")
        report["evaluation_head"] = head
        temp_runtime.write_text(RUNTIME_RS, encoding="utf-8")
        created_files.append(temp_runtime)
        temp_compile.write_text(SERIALIZE_RS, encoding="utf-8")
        created_files.append(temp_compile)

        # Cargo builds this disposable test source against the *unchanged* core.
        # Invoking cargo twice launches two fresh, independent test processes.
        base = ["cargo", "test", "--locked", "-p", "nat20_core", "--test", "ai_engine_ce02_runtime"]
        runs = []
        for tag in ["a", "b"]:
            result = run(base + ["g07_emit_rolls", "--", "--exact", "--nocapture"],
                         root, logdir / f"g07-{tag}.log", 360)
            m = re.search(r"CE02_G07_ROLLS=\[([0-9,\s]+)\]", result["output"])
            rolls = [int(x.strip()) for x in m.group(1).split(",")] if m else None
            runs.append({"exit_code": result["exit_code"], "rolls": rolls, "log": result["log"]})
        if all(x["exit_code"] == 0 and x["rolls"] is not None and len(x["rolls"]) == 24 for x in runs):
            same = runs[0]["rolls"] == runs[1]["rolls"]
            g07 = "NOT_VALIDATED_SAME_ROLLS_NO_SEED_CONTROL" if same else "FAIL_UNCONTROLLED_CLEAN_PROCESS_ROLLS"
        else:
            same = None
            g07 = "PROBE_INFRA_ERROR"
        report["gates"]["G07"] = {
            "status": g07, "subgate": "clean_process_identical_inputs_raw_dice",
            "observed_identical": same, "runs": runs,
            "full_gate": "NOT_PASSED", "seed_injection": "NOT_AVAILABLE_IN_TESTED_PUBLIC_ROLL_API",
        }

        g09run = run(base + ["g09_distinct_item_copies", "--", "--exact", "--nocapture"],
                     root, logdir / "g09-identity.log", 360)
        marker = re.search(r"CE02_G09_DEFINITION_IDS_COLLIDE=(true|false)", g09run["output"])
        if g09run["exit_code"] != 0 and marker and marker.group(1) == "true" and "test result: FAILED" in g09run["output"]:
            g09 = "FAIL_NATIVE_INVENTORY_COPY_ID_COLLISION"
        elif g09run["exit_code"] == 0 and marker and marker.group(1) == "false":
            g09 = "PARTIAL_PASS_NATIVE_COPY_IDS_ONLY"
        else:
            g09 = "PROBE_INFRA_ERROR"
        report["gates"]["G09"] = {
            "status": g09, "subgate": "two_identical_definition_entries_have_distinct_identity",
            "reported_definition_ids_collide": marker.group(1) == "true" if marker else None,
            "test_exit_code": g09run["exit_code"], "log": g09run["log"],
            "full_gate": "NOT_PASSED",
        }

        g08run = run(["cargo", "test", "--locked", "-p", "nat20_core", "--test",
                      "ai_engine_ce02_snapshot_contract", "--no-run"],
                     root, logdir / "g08-serde-contract.log", 360)
        stderr = g08run["output"]
        # Recognize *only* the expected missing trait; unrelated compile failures
        # are infrastructure failures, not evidence against the candidate.
        missing_serialize = (
            "EngineState: serde::Serialize" in stderr
            or "EngineState: serde_core::ser::Serialize" in stderr
            or ("EngineState" in stderr and "Serialize" in stderr and "E0277" in stderr)
        )
        if g08run["exit_code"] != 0 and missing_serialize:
            g08 = "BLOCKED_DIRECT_ENGINESTATE_SERIALIZATION"
        elif g08run["exit_code"] == 0:
            g08 = "SERDE_COMPILES_RESTART_STILL_NOT_TESTED"
        else:
            g08 = "PROBE_INFRA_ERROR"
        report["gates"]["G08"] = {
            "status": g08, "subgate": "direct_engine_state_serde_compile",
            "test_exit_code": g08run["exit_code"], "log": g08run["log"],
            "full_gate": "NOT_EXECUTED", "actual_crash_restart": "NOT_EXECUTED",
        }
    except Exception as exc:
        report["errors"].append(f"{type(exc).__name__}: {exc}")
    finally:
        for f in reversed(created_files):
            if f.exists():
                f.unlink()
        report["candidate_source_modified_persistently"] = False
        report["all_independent_gates_passed"] = False
        output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(json.dumps({"status": {k: v.get("status") for k, v in report["gates"].items()},
                          "errors": report["errors"], "report": str(output)}, indent=2))

    if report["errors"] or len(report["gates"]) != 3 or any(
        x["status"] == "PROBE_INFRA_ERROR" for x in report["gates"].values()
    ):
        return 2  # Test harness/infrastructure problem, NOT candidate failure.
    return 1  # Predefined independent acceptance gates not all satisfied.


if __name__ == "__main__":
    sys.exit(main())
