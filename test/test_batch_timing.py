"""Test batch execution timing fix.

This script tests that batch execution turnaround_ms reflects actual wall-clock time,
not the sum of individual LLM call times.
"""

import requests
import json
import time

BASE_URL = "http://localhost:9200"

def test_timing_comparison():
    """Compare timing for 1-item vs 3-item batch execution."""

    print("=" * 60)
    print("Batch Execution Timing Test")
    print("=" * 60)

    # Note: We're using project 1 and dataset 1
    # But dataset 1 has columns: question, context, expected_answer
    # And project 1 expects: text_WorkContentAndIssues, text_BusinessObjective, etc.
    # This mismatch will cause the batch to create jobs, but they may have
    # empty or mismatched parameters.

    # For this timing test, we'll just check that the timing calculation is correct
    # even if the actual LLM calls might fail due to parameter mismatch.

    print("\nNote: This test focuses on timing calculation correctness.")
    print("Parameter mismatch between project and dataset is expected.\n")

    # Test single execution first
    print("1. Testing single execution (1 repeat)...")
    single_start = time.time()

    single_response = requests.post(
        f"{BASE_URL}/api/run/single",
        json={
            "project_id": 1,
            "input_params": {
                "text_WorkContentAndIssues": "Test content",
                "text_BusinessObjective": "Test objective",
                "text_Hypothesis": "Test hypothesis",
                "text_HypothesisTest": "Test verification"
            },
            "repeat": 1,
            "model_name": "azure-gpt-4.1",
            "include_csv_header": True,
            "temperature": 0.7
        }
    )

    single_elapsed = time.time() - single_start

    if single_response.status_code == 200:
        single_result = single_response.json()
        single_turnaround = single_result["job"]["turnaround_ms"]
        print(f"✓ Single execution completed")
        print(f"  - Wall-clock time: {single_elapsed:.2f}s ({single_elapsed * 1000:.0f}ms)")
        print(f"  - Reported turnaround_ms: {single_turnaround}ms")
        print(f"  - Difference: {abs(single_turnaround - single_elapsed * 1000):.0f}ms")
    else:
        print(f"✗ Single execution failed: {single_response.status_code}")
        print(f"  {single_response.text}")
        return

    print("\n" + "-" * 60)

    # Test batch execution with 3 items
    print("\n2. Testing batch execution (3 items from dataset)...")
    batch_start = time.time()

    batch_response = requests.post(
        f"{BASE_URL}/api/run/batch",
        json={
            "project_id": 1,
            "dataset_id": 1,  # Has 3 rows
            "model_name": "azure-gpt-4.1",
            "include_csv_header": True,
            "temperature": 0.7
        }
    )

    batch_elapsed = time.time() - batch_start

    if batch_response.status_code == 200:
        batch_result = batch_response.json()
        batch_turnaround = batch_result["job"]["turnaround_ms"]
        item_count = len(batch_result["job"]["items"])

        print(f"✓ Batch execution completed")
        print(f"  - Items processed: {item_count}")
        print(f"  - Wall-clock time: {batch_elapsed:.2f}s ({batch_elapsed * 1000:.0f}ms)")
        print(f"  - Reported turnaround_ms: {batch_turnaround}ms")
        print(f"  - Difference: {abs(batch_turnaround - batch_elapsed * 1000):.0f}ms")

        # Calculate sum of individual item times
        item_times = [item["turnaround_ms"] for item in batch_result["job"]["items"] if item["turnaround_ms"]]
        if item_times:
            total_item_time = sum(item_times)
            print(f"\n  Individual item times: {item_times}")
            print(f"  Sum of individual times: {total_item_time}ms")
            print(f"  Ratio (sum/wall-clock): {total_item_time / batch_turnaround:.2f}x")
    else:
        print(f"✗ Batch execution failed: {batch_response.status_code}")
        print(f"  {batch_response.text}")
        return

    print("\n" + "=" * 60)
    print("Analysis:")
    print("=" * 60)

    print(f"\nExpected behavior (FIXED):")
    print(f"  - Job turnaround_ms should reflect wall-clock time")
    print(f"  - 3 items should take ~3x longer than 1 item (due to sequential execution)")
    print(f"  - Reported turnaround_ms should match actual elapsed time")

    print(f"\nOld behavior (BROKEN):")
    print(f"  - Job turnaround_ms was sum of individual item times")
    print(f"  - This was same as wall-clock time (1x)")
    print(f"  - But gave wrong impression that 3 items was faster than 1 item")

    print(f"\nActual results:")
    print(f"  - Single execution: {single_turnaround}ms (wall: {single_elapsed * 1000:.0f}ms)")
    print(f"  - Batch execution: {batch_turnaround}ms (wall: {batch_elapsed * 1000:.0f}ms)")
    print(f"  - Ratio: {batch_turnaround / single_turnaround:.2f}x")

    if abs(batch_turnaround - batch_elapsed * 1000) < 1000:  # Within 1 second
        print(f"\n✓ PASS: Timing calculation is correct!")
    else:
        print(f"\n✗ FAIL: Timing calculation is still incorrect!")

    print("\n" + "=" * 60)

if __name__ == "__main__":
    try:
        test_timing_comparison()
    except KeyboardInterrupt:
        print("\n\nTest interrupted by user")
    except Exception as e:
        print(f"\n✗ Test failed with error: {e}")
        import traceback
        traceback.print_exc()
