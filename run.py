"""
Quick runner for AI Test Case Generator.

Usage:
    # 1. Set your API key (required):
    set TESTGEN_API_KEY=your-api-key-here        (Windows)
    export TESTGEN_API_KEY=your-api-key-here      (Linux/macOS)

    # 2. Generate tests for all functions in sample.py:
    python run.py

    # 3. Generate tests for a specific function:
    python run.py calculate_discount

    # 4. Generate tests for any other python file:
    python run.py path/to/your_file.py

    # 5. Optionally set a fallback key:
    set TESTGEN_FALLBACK_KEY=your-fallback-key    (Windows)
"""

import os
import sys
from pathlib import Path

# Add engine to path
ENGINE_DIR = Path(__file__).resolve().parent / "engine"
sys.path.insert(0, str(ENGINE_DIR))

from main import run


def main():
    # ── Resolve API keys from environment variables ───────────
    api_key = os.environ.get("TESTGEN_API_KEY", "")
    fallback_key = os.environ.get("TESTGEN_FALLBACK_KEY", "")

    if not api_key:
        print(
            "Error: No API key found.\n"
            "  Set the TESTGEN_API_KEY environment variable:\n"
            "    Windows:     set TESTGEN_API_KEY=your-key-here\n"
            "    Linux/macOS: export TESTGEN_API_KEY=your-key-here\n",
            file=sys.stderr,
        )
        sys.exit(1)

    # Combine keys for fallback if secondary exists
    all_keys = f"{api_key},{fallback_key}" if fallback_key else api_key

    # ── Parse CLI arguments ───────────────────────────────────
    target_file = "examples/sample.py"
    target_func = None

    args = sys.argv[1:]
    if len(args) == 1:
        if args[0].endswith(".py"):
            target_file = args[0]
        else:
            target_func = args[0]
    elif len(args) >= 2:
        target_file = args[0]
        target_func = args[1]

    print(f"Target file:     {target_file}")
    if target_func:
        print(f"Target function: {target_func}")
    else:
        print(f"Target function: [All functions]")
    print(f"AI Model:        gemini-2.5-flash")
    print("-" * 50)

    result = run(
        file_path=target_file,
        api_key=all_keys,
        output_dir="generated_tests",
        function_name=target_func,
        base_url="https://generativelanguage.googleapis.com/v1beta/openai",
        model="gemini-2.5-flash",
    )

    print("-" * 50)
    print(f"Done! Successfully generated {result['success']}/{result['total']} test files.")
    print(f"Check your tests inside folder: {result['output_dir']}")


if __name__ == "__main__":
    main()
