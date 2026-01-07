import os
import sys
import subprocess
from pathlib import Path
import time

target = sys.argv[2]

INPUT_DIR = "js_files_" + target
OUTPUT_DIR = "js_files_" + target + "_static"

# Ensure output root exists
if os.path.exists(INPUT_DIR):
    Path(OUTPUT_DIR).mkdir(parents=True, exist_ok=True)
else:
    print("Folder not found!")

# Path to Closure Compiler
CLOSURE_CMD = "google-closure-compiler"
COMPILATION_LEVEL = "SIMPLE"

def optimize_js_files(input_dir, output_dir):
    for root, _, files in os.walk(input_dir):
        for file in files:
            if file.endswith(".js"):
                input_path = os.path.join(root, file)

                # Preserve relative structure
                rel_path = os.path.relpath(input_path, input_dir)
                output_path = os.path.join(output_dir, rel_path)
                Path(os.path.dirname(output_path)).mkdir(parents=True, exist_ok=True)

                try:
                    print(f"[→] Optimizing: {input_path}")
                    subprocess.run(
                        [
                            *CLOSURE_CMD.split(),
                            f"--js={input_path}",
                            f"--js_output_file={output_path}",
                            f"--compilation_level={COMPILATION_LEVEL}"
                        ],
                        check=False,
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL
                    )
                    print(f"[✓] Saved: {output_path}")
                except subprocess.CalledProcessError as e:
                    print(f"[✗] Failed: {input_path} → {e}")

if __name__ == "__main__":
    optimize_js_files(INPUT_DIR, OUTPUT_DIR)
