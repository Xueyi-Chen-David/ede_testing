import sys
import subprocess

if len(sys.argv) < 3:
    print("Usage:")
    print("  python3 edetest.py -k TARGET")
    print("  python3 edetest.py -s TARGET")
    print("  python3 edetest.py -d TARGET")
    sys.exit(1)

mode = sys.argv[1]
target = sys.argv[2]

modes = {
    "-k": ["code/download_json.py", "code/download_js.py", "code/download_html.py", "code/test_js.py", "code/test_html.py", "code/result.py"],
    "-s": ["code/download_json.py", "code/download_js.py", "code/download_html.py", "code/slice_static.py", "code/test_js.py", "code/test_html.py", "code/result.py"],
    "-d": ["code/download_json.py", "code/download_js.py", "code/download_html.py", "code/slice_dynamic.py", "code/test_js.py", "code/test_html.py", "code/result.py"],
}

if mode not in modes:
    print(f"Unknown mode: {mode}")
    sys.exit(1)

scripts = modes[mode]

for script in scripts:
    print(f"Running: python3 {script} {mode} {target}")
    subprocess.run(["python3", script, mode, target])
