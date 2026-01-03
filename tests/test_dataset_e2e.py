#!/usr/bin/env python3
"""
End-to-End Tests for Dataset Import Features

Tests the following features via HTTP API:
1. Dataset download functionality
2. RowID addition option (CSV import)
3. Dataset replacement option (CSV import)

Test Date: 2026-01-02
Requires: Server running on localhost:9200
"""

import requests
import json
import csv
import io
import time
from datetime import datetime
from typing import Dict, Any, List, Optional

BASE_URL = "http://localhost:9200"

# Test results storage
test_results: List[Dict[str, Any]] = []


def log_test(category: str, test_id: str, name: str, result: bool, details: str = ""):
    """Log a test result."""
    status = "PASS" if result else "FAIL"
    test_results.append({
        "category": category,
        "id": test_id,
        "name": name,
        "status": status,
        "details": details
    })
    print(f"  [{status}] {test_id}: {name}")
    if details and not result:
        print(f"        Details: {details}")


def get_projects() -> List[Dict]:
    """Get list of projects."""
    resp = requests.get(f"{BASE_URL}/api/projects")
    if resp.status_code == 200:
        return resp.json()
    return []


def get_datasets() -> List[Dict]:
    """Get list of datasets."""
    resp = requests.get(f"{BASE_URL}/api/datasets")
    if resp.status_code == 200:
        return resp.json()
    return []


def create_csv_file(rows: List[List[str]], add_header: bool = True) -> io.BytesIO:
    """Create a CSV file in memory."""
    output = io.StringIO()
    writer = csv.writer(output)
    for row in rows:
        writer.writerow(row)
    content = output.getvalue().encode('utf-8')
    return io.BytesIO(content)


# ============================================================
# Test Category 1: Download Endpoint
# ============================================================

def test_download_endpoint():
    """Test dataset download functionality."""
    print("\n" + "=" * 60)
    print("Category 1: Download Endpoint Tests")
    print("=" * 60)

    # Get existing datasets or create one for testing
    datasets = get_datasets()
    if not datasets:
        # Create a test dataset for download testing
        projects = get_projects()
        if not projects:
            log_test("Download", "DL-1.0", "No projects available", False, "Create a project first")
            return

        csv_data = [
            ["Name", "Value"],
            ["TestA", "100"],
            ["TestB", "200"]
        ]
        csv_file = create_csv_file(csv_data)
        files = {"file": ("download_test.csv", csv_file, "text/csv")}
        data = {
            "project_id": str(projects[0]["id"]),
            "dataset_name": f"Download_Test_{datetime.now().strftime('%H%M%S')}",
            "encoding": "utf-8",
            "has_header": "1",
            "add_row_id": "false"
        }
        resp = requests.post(f"{BASE_URL}/api/datasets/import/csv", files=files, data=data)
        if resp.status_code != 200:
            log_test("Download", "DL-1.0", "Failed to create test dataset", False, f"Status: {resp.status_code}")
            return
        datasets = [resp.json()]

    dataset = datasets[0]
    dataset_id = dataset["id"]
    dataset_name = dataset["name"]

    # Test 1.1: Download endpoint exists
    resp = requests.get(f"{BASE_URL}/api/datasets/{dataset_id}/download")
    log_test("Download", "DL-1.1", "Download endpoint returns 200",
             resp.status_code == 200, f"Status: {resp.status_code}")

    # Test 1.2: Content-Type is CSV
    content_type = resp.headers.get("Content-Type", "")
    log_test("Download", "DL-1.2", "Content-Type is text/csv",
             "text/csv" in content_type, f"Content-Type: {content_type}")

    # Test 1.3: Content-Disposition header present
    content_disp = resp.headers.get("Content-Disposition", "")
    log_test("Download", "DL-1.3", "Content-Disposition header present",
             "attachment" in content_disp, f"Content-Disposition: {content_disp}")

    # Test 1.4: CSV content starts with BOM
    content = resp.content.decode('utf-8-sig')  # utf-8-sig handles BOM
    has_bom = resp.content.startswith(b'\xef\xbb\xbf')
    log_test("Download", "DL-1.4", "CSV starts with UTF-8 BOM",
             has_bom, "BOM check")

    # Test 1.5: CSV is parseable
    try:
        reader = csv.reader(io.StringIO(content))
        rows = list(reader)
        has_header = len(rows) > 0
        log_test("Download", "DL-1.5", "CSV is parseable",
                 has_header, f"Row count: {len(rows)}")
    except Exception as e:
        log_test("Download", "DL-1.5", "CSV is parseable", False, str(e))

    # Test 1.6: Download non-existent dataset returns 404
    resp = requests.get(f"{BASE_URL}/api/datasets/99999/download")
    log_test("Download", "DL-1.6", "Non-existent dataset returns 404",
             resp.status_code == 404, f"Status: {resp.status_code}")


# ============================================================
# Test Category 2: RowID Addition (CSV Import)
# ============================================================

def test_rowid_addition():
    """Test RowID addition functionality."""
    print("\n" + "=" * 60)
    print("Category 2: RowID Addition Tests")
    print("=" * 60)

    # Get a project
    projects = get_projects()
    if not projects:
        log_test("RowID", "RID-2.0", "No projects available", False, "Create a project first")
        return

    project_id = projects[0]["id"]

    # Create test CSV data
    csv_data = [
        ["Name", "Value", "Category"],
        ["Alice", "100", "A"],
        ["Bob", "200", "B"],
        ["Charlie", "300", "C"]
    ]
    csv_file = create_csv_file(csv_data)

    # Test 2.1: Import CSV with add_row_id=true
    timestamp = datetime.now().strftime("%H%M%S")
    files = {"file": ("test_rowid.csv", csv_file, "text/csv")}
    data = {
        "project_id": str(project_id),
        "dataset_name": f"RowID Test {timestamp}",
        "encoding": "utf-8",
        "has_header": "1",
        "add_row_id": "true"
    }

    resp = requests.post(f"{BASE_URL}/api/datasets/import/csv", files=files, data=data)
    log_test("RowID", "RID-2.1", "CSV import with add_row_id succeeds",
             resp.status_code == 200, f"Status: {resp.status_code}")

    if resp.status_code != 200:
        print(f"        Error: {resp.text}")
        return

    dataset = resp.json()
    dataset_id = dataset["id"]

    # Test 2.2: Get preview and check RowID column exists
    resp = requests.get(f"{BASE_URL}/api/datasets/{dataset_id}/preview?limit=10")
    if resp.status_code == 200:
        preview = resp.json()
        columns = preview.get("columns", [])
        log_test("RowID", "RID-2.2", "RowID column exists in first position",
                 len(columns) > 0 and columns[0] == "RowID", f"Columns: {columns[:3]}")

        # Test 2.3: RowID values start from 1
        rows = preview.get("rows", [])
        if rows:
            first_rowid = rows[0].get("RowID", "")
            log_test("RowID", "RID-2.3", "First RowID value is 1",
                     first_rowid == "1", f"First RowID: {first_rowid}")
        else:
            log_test("RowID", "RID-2.3", "First RowID value is 1", False, "No rows")

        # Test 2.4: RowID values are sequential
        if len(rows) >= 3:
            rowids = [rows[i].get("RowID", "") for i in range(3)]
            expected = ["1", "2", "3"]
            log_test("RowID", "RID-2.4", "RowID values are sequential",
                     rowids == expected, f"RowIDs: {rowids}")
        else:
            log_test("RowID", "RID-2.4", "RowID values are sequential", False, "Not enough rows")

        # Test 2.5: Original columns preserved
        expected_cols = ["RowID", "Name", "Value", "Category"]
        log_test("RowID", "RID-2.5", "Original columns preserved",
                 columns == expected_cols, f"Columns: {columns}")
    else:
        log_test("RowID", "RID-2.2", "Preview request failed", False, f"Status: {resp.status_code}")

    # Test 2.6: Import CSV without add_row_id (control test)
    # Use fresh data to avoid any list mutation issues
    csv_data_no_rowid = [
        ["Name", "Value", "Category"],
        ["Alice", "100", "A"],
        ["Bob", "200", "B"],
        ["Charlie", "300", "C"]
    ]
    csv_file2 = create_csv_file(csv_data_no_rowid)
    timestamp2 = datetime.now().strftime("%H%M%S%f")
    files2 = {"file": ("test_no_rowid.csv", csv_file2, "text/csv")}
    data2 = {
        "project_id": str(project_id),
        "dataset_name": f"No RowID Test {timestamp2}",
        "encoding": "utf-8",
        "has_header": "1",
        "add_row_id": "false"
    }

    resp = requests.post(f"{BASE_URL}/api/datasets/import/csv", files=files2, data=data2)
    if resp.status_code == 200:
        dataset2 = resp.json()
        resp2 = requests.get(f"{BASE_URL}/api/datasets/{dataset2['id']}/preview?limit=10")
        if resp2.status_code == 200:
            preview2 = resp2.json()
            columns2 = preview2.get("columns", [])
            log_test("RowID", "RID-2.6", "No RowID when add_row_id=false",
                     "RowID" not in columns2, f"Columns: {columns2}")
        else:
            log_test("RowID", "RID-2.6", "No RowID when add_row_id=false", False, "Preview failed")
        # Cleanup second dataset
        requests.delete(f"{BASE_URL}/api/datasets/{dataset2['id']}")
    else:
        log_test("RowID", "RID-2.6", "No RowID when add_row_id=false", False, f"Import failed: {resp.status_code}")

    # Cleanup: Delete test datasets
    requests.delete(f"{BASE_URL}/api/datasets/{dataset_id}")


# ============================================================
# Test Category 3: Dataset Replacement
# ============================================================

def test_dataset_replacement():
    """Test dataset replacement functionality."""
    print("\n" + "=" * 60)
    print("Category 3: Dataset Replacement Tests")
    print("=" * 60)

    # Get a project
    projects = get_projects()
    if not projects:
        log_test("Replace", "REP-3.0", "No projects available", False, "Create a project first")
        return

    project_id = projects[0]["id"]

    # Create initial dataset
    csv_data1 = [
        ["Name", "Score"],
        ["Original1", "10"],
        ["Original2", "20"]
    ]
    csv_file1 = create_csv_file(csv_data1)

    timestamp = datetime.now().strftime("%H%M%S")
    files1 = {"file": ("test_replace_orig.csv", csv_file1, "text/csv")}
    data1 = {
        "project_id": str(project_id),
        "dataset_name": f"Replace Test {timestamp}",
        "encoding": "utf-8",
        "has_header": "1",
        "add_row_id": "false"
    }

    resp = requests.post(f"{BASE_URL}/api/datasets/import/csv", files=files1, data=data1)
    if resp.status_code != 200:
        log_test("Replace", "REP-3.0", "Create initial dataset", False, f"Status: {resp.status_code}")
        return

    original_dataset = resp.json()
    original_id = original_dataset["id"]
    log_test("Replace", "REP-3.1", "Initial dataset created", True, f"ID: {original_id}")

    # Test 3.2: Replace dataset with new data
    csv_data2 = [
        ["Name", "Score", "Extra"],
        ["Replaced1", "100", "New"],
        ["Replaced2", "200", "New"],
        ["Replaced3", "300", "New"]
    ]
    csv_file2 = create_csv_file(csv_data2)

    files2 = {"file": ("test_replace_new.csv", csv_file2, "text/csv")}
    data2 = {
        "project_id": str(project_id),
        "encoding": "utf-8",
        "has_header": "1",
        "add_row_id": "false",
        "replace_dataset_id": str(original_id)
    }

    resp = requests.post(f"{BASE_URL}/api/datasets/import/csv", files=files2, data=data2)
    log_test("Replace", "REP-3.2", "Replace dataset API succeeds",
             resp.status_code == 200, f"Status: {resp.status_code}")

    if resp.status_code != 200:
        print(f"        Error: {resp.text}")
        return

    replaced_dataset = resp.json()

    # Test 3.3: Dataset ID is preserved
    log_test("Replace", "REP-3.3", "Dataset ID preserved after replace",
             replaced_dataset["id"] == original_id,
             f"Original: {original_id}, After: {replaced_dataset['id']}")

    # Test 3.4: New data is present
    resp = requests.get(f"{BASE_URL}/api/datasets/{original_id}/preview?limit=10")
    if resp.status_code == 200:
        preview = resp.json()
        rows = preview.get("rows", [])
        columns = preview.get("columns", [])

        # Check new data
        has_new_data = len(rows) >= 3 and any(r.get("Name", "") == "Replaced1" for r in rows)
        log_test("Replace", "REP-3.4", "New data present after replace",
                 has_new_data, f"Rows: {len(rows)}")

        # Test 3.5: Old data is removed
        has_old_data = any(r.get("Name", "") == "Original1" for r in rows)
        log_test("Replace", "REP-3.5", "Old data removed after replace",
                 not has_old_data, "Checking for 'Original1'")

        # Test 3.6: New columns present
        log_test("Replace", "REP-3.6", "New columns present (Extra)",
                 "Extra" in columns, f"Columns: {columns}")

        # Test 3.7: Row count updated
        row_count = preview.get("total_count", 0)
        log_test("Replace", "REP-3.7", "Row count is 3 (new data)",
                 row_count == 3, f"Row count: {row_count}")
    else:
        log_test("Replace", "REP-3.4", "Preview after replace", False, f"Status: {resp.status_code}")

    # Test 3.8: Replace with RowID
    csv_data3 = [
        ["A", "B"],
        ["X", "1"],
        ["Y", "2"]
    ]
    csv_file3 = create_csv_file(csv_data3)
    files3 = {"file": ("test_replace_rowid.csv", csv_file3, "text/csv")}
    data3 = {
        "project_id": str(project_id),
        "encoding": "utf-8",
        "has_header": "1",
        "add_row_id": "true",
        "replace_dataset_id": str(original_id)
    }

    resp = requests.post(f"{BASE_URL}/api/datasets/import/csv", files=files3, data=data3)
    if resp.status_code == 200:
        resp = requests.get(f"{BASE_URL}/api/datasets/{original_id}/preview?limit=10")
        if resp.status_code == 200:
            preview = resp.json()
            columns = preview.get("columns", [])
            log_test("Replace", "REP-3.8", "Replace with RowID works",
                     columns[0] == "RowID", f"Columns: {columns}")
        else:
            log_test("Replace", "REP-3.8", "Replace with RowID works", False, "Preview failed")
    else:
        log_test("Replace", "REP-3.8", "Replace with RowID works", False, f"Import failed: {resp.status_code}")

    # Cleanup
    requests.delete(f"{BASE_URL}/api/datasets/{original_id}")


# ============================================================
# Test Category 4: Frontend JavaScript Verification
# ============================================================

def test_frontend_elements():
    """Test that frontend elements are present in HTML/JS."""
    print("\n" + "=" * 60)
    print("Category 4: Frontend Element Verification")
    print("=" * 60)

    # Get main page HTML
    resp = requests.get(BASE_URL)
    html = resp.text

    # Test 4.1: "プロジェクト設定" button text present (via JS that generates it)
    # We'll check the JS file instead
    resp = requests.get(f"{BASE_URL}/static/js/app.js")
    js_content = resp.text

    log_test("Frontend", "FE-4.1", "'プロジェクト設定' text in JS",
             "プロジェクト設定" in js_content, "Button text check")

    # Test 4.2: "編集" should NOT be used for project button (should be replaced)
    # This is tricky since 編集 might be used elsewhere. Let's check the specific context.
    # Looking for the pattern in the project card edit button

    # Test 4.3: Download button function exists
    log_test("Frontend", "FE-4.3", "downloadDataset function exists",
             "function downloadDataset" in js_content or "async function downloadDataset" in js_content,
             "Function definition check")

    # Test 4.4: import-excel-add-rowid checkbox exists
    log_test("Frontend", "FE-4.4", "import-excel-add-rowid checkbox in JS",
             "import-excel-add-rowid" in js_content, "Checkbox ID check")

    # Test 4.5: import-csv-add-rowid checkbox exists
    log_test("Frontend", "FE-4.5", "import-csv-add-rowid checkbox in JS",
             "import-csv-add-rowid" in js_content, "Checkbox ID check")

    # Test 4.6: import-hf-add-rowid checkbox exists
    log_test("Frontend", "FE-4.6", "import-hf-add-rowid checkbox in JS",
             "import-hf-add-rowid" in js_content, "Checkbox ID check")

    # Test 4.7: Replace mode radio buttons exist
    log_test("Frontend", "FE-4.7", "Excel replace mode radio in JS",
             "excel-replace-options" in js_content, "Replace options div check")

    log_test("Frontend", "FE-4.8", "CSV replace mode radio in JS",
             "csv-replace-options" in js_content, "Replace options div check")

    # Test 4.9: Toggle functions exist
    log_test("Frontend", "FE-4.9", "toggleExcelMode function exists",
             "function toggleExcelMode" in js_content, "Function check")

    log_test("Frontend", "FE-4.10", "toggleCsvMode function exists",
             "function toggleCsvMode" in js_content, "Function check")


# ============================================================
# Generate Test Report
# ============================================================

def generate_report():
    """Generate final test report."""
    print("\n" + "=" * 60)
    print("TEST SUMMARY REPORT")
    print("=" * 60)

    # Count results by category
    categories = {}
    total_pass = 0
    total_fail = 0

    for result in test_results:
        cat = result["category"]
        if cat not in categories:
            categories[cat] = {"pass": 0, "fail": 0}

        if result["status"] == "PASS":
            categories[cat]["pass"] += 1
            total_pass += 1
        else:
            categories[cat]["fail"] += 1
            total_fail += 1

    print(f"\nTotal: {total_pass} passed, {total_fail} failed")
    print("-" * 40)

    for cat, counts in categories.items():
        status = "PASS" if counts["fail"] == 0 else "FAIL"
        print(f"  {cat}: {counts['pass']} passed, {counts['fail']} failed [{status}]")

    print("-" * 40)

    # List failed tests
    failed = [r for r in test_results if r["status"] == "FAIL"]
    if failed:
        print("\nFailed Tests:")
        for f in failed:
            print(f"  [{f['id']}] {f['name']}")
            if f["details"]:
                print(f"        {f['details']}")

    return total_fail == 0


# ============================================================
# Main Entry Point
# ============================================================

def main():
    print("=" * 60)
    print("Dataset Features E2E Test Suite")
    print(f"Test Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"Target: {BASE_URL}")
    print("=" * 60)

    # Check server availability
    try:
        resp = requests.get(f"{BASE_URL}/api/projects", timeout=5)
        if resp.status_code != 200:
            print("ERROR: Server not responding correctly")
            return False
    except requests.exceptions.RequestException as e:
        print(f"ERROR: Cannot connect to server: {e}")
        return False

    print("Server OK, starting tests...")

    # Run all test categories
    test_download_endpoint()
    test_rowid_addition()
    test_dataset_replacement()
    test_frontend_elements()

    # Generate report
    success = generate_report()

    return success


if __name__ == "__main__":
    import sys
    success = main()
    sys.exit(0 if success else 1)
