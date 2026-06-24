"""
Subprocess entry point — executed via VS_Code/.venv/Scripts/python.exe.

Usage:
    python topology_pipeline/runner.py <image_path> <dataset_dir> [model_path]

stdout protocol:
    LOG:<message>       progress line (displayed in GUI progress window)
    RESULT:<json>       final result JSON  { nodes, links, devices_csv, links_csv }
    ERROR:<message>     fatal error message
"""
import os
import sys
import io

# Force UTF-8 stdout/stderr so Korean Windows (CP949) doesn't break the pipe
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

# Set env var before any ML imports
os.environ.setdefault("FLAGS_use_mkldnn", "0")

# Ensure Network_Dev/ is on the path so 'topology_pipeline' resolves as a package
_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)


def _log(msg: str) -> None:
    print(f"LOG:{msg}", flush=True)


def main() -> None:
    if len(sys.argv) < 3:
        print("ERROR:Usage: runner.py <image_path> <dataset_dir> [model_path]", flush=True)
        sys.exit(1)

    image_path  = sys.argv[1]
    dataset_dir = sys.argv[2]
    model_path  = sys.argv[3] if len(sys.argv) > 3 else None

    try:
        from topology_pipeline import pipeline
        result = pipeline.run(
            image_path=image_path,
            dataset_dir=dataset_dir,
            model_path=model_path,
            progress_cb=_log,
        )

        import json
        out = {
            "nodes":       len(result["nodes"]),
            "links":       len(result["links"]),
            "devices_csv": result["devices_csv"],
            "links_csv":   result["links_csv"],
            "mode":        result.get("mode", "yolo"),
        }
        print(f"RESULT:{json.dumps(out)}", flush=True)

    except Exception as exc:
        import traceback
        print(f"ERROR:{exc}", flush=True)
        traceback.print_exc(file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
