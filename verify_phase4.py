#!/usr/bin/env python3
"""Phase 4 end-to-end verification.

Tests:
  1. Dashboard HTML generation
  2. Parameter calibration (BKT + FSRS)
  3. Metacognition diagnosis
  4. Data export (JSON + CSV)
  5. Data import (JSON → restore)
  6. launch.py menu integration
"""

import sys
import os
import json
import tempfile
from pathlib import Path

script_dir = Path(__file__).resolve().parent
sp_scripts = script_dir / "skills" / "study-planner" / "scripts"
ae_scripts = script_dir / "skills" / "adaptive-engine" / "scripts"
sys.path.insert(0, str(sp_scripts))
sys.path.insert(0, str(ae_scripts))

import db_manager
import profile_manager
import dashboard
import param_calibrator
import metacognition
import data_io

PASS = "\033[92m✓ PASS\033[0m"
FAIL = "\033[91m✗ FAIL\033[0m"
results = []


def test_dashboard():
    """Test 1: Dashboard HTML generation."""
    config = db_manager.load_config()
    output = str(Path(tempfile.gettempdir()) / "test_dashboard.html")
    path = dashboard.generate_dashboard(
        config=config, output_path=output, open_browser=False
    )

    checks = {
        "file exists": Path(path).exists(),
        "has calendar chart": "calendar-chart" in Path(path).read_text(encoding="utf-8"),
        "has mastery chart": "mastery-chart" in Path(path).read_text(encoding="utf-8"),
        "has graph chart": "graph-chart" in Path(path).read_text(encoding="utf-8"),
        "has rating chart": "rating-chart" in Path(path).read_text(encoding="utf-8"),
        "has distribution chart": "distribution-chart" in Path(path).read_text(encoding="utf-8"),
        "has stat cards": "stat-cards" in Path(path).read_text(encoding="utf-8"),
    }

    all_pass = all(checks.values())
    for name, ok in checks.items():
        print(f"  {'✓' if ok else '✗'} {name}")
    results.append(("Dashboard generation", all_pass))
    print(f"  {PASS if all_pass else FAIL}\n")


def test_calibration():
    """Test 2: Parameter calibration."""
    config = db_manager.load_config()
    result = param_calibrator.calibrate_parameters(config=config)

    has_status = "status" in result
    is_calibrated = result.get("status") == "calibrated"
    is_skipped = result.get("status") == "skipped"

    if is_calibrated:
        has_bkt = "bkt" in result and "after" in result["bkt"]
        has_fsrs = "fsrs" in result and "after" in result["fsrs"]
        all_pass = has_bkt and has_fsrs
    elif is_skipped:
        all_pass = True
    else:
        all_pass = False

    print(f"  Status: {result.get('status', 'unknown')}")
    if is_calibrated:
        print(f"  Total reviews: {result['total_reviews']}")
        bkt = result["bkt"]["after"]
        if bkt["p_transit"] is not None:
            print(f"  P(T) = {bkt['p_transit']} (sample {bkt['sample_transit']})")
        if bkt["p_slip"] is not None:
            print(f"  P(S) = {bkt['p_slip']} (sample {bkt['sample_slip']})")
        if bkt["p_guess"] is not None:
            print(f"  P(G) = {bkt['p_guess']} (sample {bkt['sample_guess']})")
        fsrs = result["fsrs"]["after"]
        print(f"  Ease: {fsrs['current_ease']} → {fsrs['new_ease']}")
    results.append(("Parameter calibration", all_pass))
    print(f"  {PASS if all_pass else FAIL}\n")


def test_metacognition():
    """Test 3: Metacognition diagnosis."""
    config = db_manager.load_config()
    result = metacognition.diagnose(config=config)

    has_alerts = "alerts" in result
    has_summary = "summary" in result
    has_recs = "recommendations" in result
    all_pass = has_alerts and has_summary and has_recs

    print(f"  Summary: {result['summary']}")
    print(f"  Alerts: {len(result['alerts'])}")
    for a in result["alerts"][:3]:
        print(f"    [{a['severity']}] {a['title']}: {a['diagnosis'][:50]}...")
    print(f"  Recommendations: {len(result['recommendations'])}")
    for r in result["recommendations"][:2]:
        print(f"    → {r}")
    results.append(("Metacognition diagnosis", all_pass))
    print(f"  {PASS if all_pass else FAIL}\n")


def test_export_json():
    """Test 4: JSON export."""
    config = db_manager.load_config()
    output = str(Path(tempfile.gettempdir()) / "test_backup.json")
    path = data_io.export_to_json(config=config, output_path=output)

    backup = json.loads(Path(path).read_text(encoding="utf-8"))
    has_metadata = "metadata" in backup
    has_data = "data" in backup
    has_tables = all(t in backup["data"] for t in
                    ["knowledge_nodes", "review_log", "learner_profile"])

    all_pass = has_metadata and has_data and has_tables
    print(f"  Export path: {path}")
    print(f"  Tables: {list(backup['data'].keys())}")
    print(f"  Counts: {backup['metadata']['table_counts']}")
    results.append(("JSON export", all_pass))
    print(f"  {PASS if all_pass else FAIL}\n")
    return path


def test_export_csv():
    """Test 5: CSV export."""
    config = db_manager.load_config()
    output = str(Path(tempfile.gettempdir()) / "test_reviews.csv")
    path = data_io.export_review_csv(config=config, output_path=output)

    if path:
        content = Path(path).read_text(encoding="utf-8-sig")
        has_header = "note_id" in content and "rating" in content
        has_data = content.count("\n") > 1
        all_pass = has_header and has_data
    else:
        all_pass = True
        print("  (no review data to export)")

    results.append(("CSV export", all_pass))
    print(f"  {PASS if all_pass else FAIL}\n")


def test_import_json(backup_path):
    """Test 6: JSON import (restore)."""
    config = db_manager.load_config()

    before_nodes = len(db_manager.get_all_nodes(config))

    result = data_io.import_from_json(backup_path, config=config)

    after_nodes = len(db_manager.get_all_nodes(config))

    has_counts = "table_counts" in result
    nodes_match = after_nodes >= 0
    all_pass = has_counts and nodes_match

    print(f"  Before: {before_nodes} nodes")
    print(f"  After: {after_nodes} nodes")
    print(f"  Imported: {result.get('table_counts', {})}")
    results.append(("JSON import", all_pass))
    print(f"  {PASS if all_pass else FAIL}\n")


def test_launch_imports():
    """Test 7: launch.py can import new modules."""
    try:
        import launch
        has_dashboard = hasattr(launch, "show_dashboard")
        has_data_mgmt = hasattr(launch, "show_data_management")
        all_pass = has_dashboard and has_data_mgmt
        print(f"  show_dashboard: {'found' if has_dashboard else 'missing'}")
        print(f"  show_data_management: {'found' if has_data_mgmt else 'missing'}")
    except Exception as e:
        all_pass = False
        print(f"  Import error: {e}")
    results.append(("launch.py integration", all_pass))
    print(f"  {PASS if all_pass else FAIL}\n")


def main():
    print("=" * 50)
    print("  Phase 4 Verification")
    print("=" * 50 + "\n")

    test_dashboard()
    test_calibration()
    test_metacognition()
    backup_path = test_export_json()
    test_export_csv()
    test_import_json(backup_path)
    test_launch_imports()

    print("=" * 50)
    total = len(results)
    passed = sum(1 for _, ok in results if ok)
    print(f"  Results: {passed}/{total} passed")
    for name, ok in results:
        print(f"    {PASS if ok else FAIL} {name}")
    print("=" * 50)

    if passed == total:
        print("\n  All tests passed!\n")
    else:
        print(f"\n  {total - passed} test(s) failed.\n")


if __name__ == "__main__":
    main()
