import os
import sys
import time
import requests
from urllib.parse import urlparse
from pathlib import Path
from playwright.sync_api import sync_playwright


def merge_ranges(ranges):
    """Merge overlapping or adjacent ranges."""
    if not ranges:
        return []

    ranges = sorted(ranges, key=lambda x: x[0])
    merged = [ranges[0]]

    for current in ranges[1:]:
        prev = merged[-1]
        if current[0] <= prev[1]:  # overlap or adjacent
            merged[-1] = (prev[0], max(prev[1], current[1]))
        else:
            merged.append(current)

    return merged


def run_config_commands(page, config_file):
    """Execute commands in the config file until TEST is found."""
    with open(config_file, "r", encoding="utf-8") as f:
        for raw in f:
            line = raw.strip()
            if not line or line.startswith("#"):
                continue

            # Stop executing at TEST
            if line.startswith("TEST"):
                print("[INFO] Reached TEST.")
                break

            # Explicitly ignore TARGET lines
            if line.startswith("TARGET "):
                print(f"[INFO] TARGET line: {line[7:].strip()}")
                continue

            if line.startswith("LOAD "):
                url = line[5:].strip()
                print(f"[LOAD] {url}")
                try:
                    page.goto(url, wait_until="load", timeout=60000)
                except Exception as e:
                    print(f"[ERROR] LOAD failed ({url}): {e}")
                    raise
            elif line.startswith("WAIT_LOCATE "):
                xpath = line[12:].strip()
                print(f"[WAIT_LOCATE] {xpath}")
                try:
                    page.wait_for_selector(f"xpath={xpath}", timeout=30000)
                except Exception as e:
                    print(f"[ERROR] WAIT_LOCATE failed ({xpath}): {e}")
                    raise
            elif line.startswith("INPUT "):
                rest = line[6:].strip()
                try:
                    xpath, content = rest.split(" ", 1)
                except ValueError:
                    xpath, content = rest, ""
                print(f"[INPUT] {xpath} <- {content}")
                try:
                    locator = page.locator(f"xpath={xpath}")
                    locator.fill(content)
                except Exception as e:
                    print(f"[ERROR] INPUT failed ({xpath}): {e}")
                    raise
            elif line.startswith("CLICK "):
                xpath = line[6:].strip()
                print(f"[CLICK] {xpath}")
                try:
                    page.locator(f"xpath={xpath}").first.click()
                except Exception as e:
                    print(f"[ERROR] CLICK failed ({xpath}): {e}")
                    raise
            elif line.startswith("HOVER "):
                xpath = line[6:].strip()
                print(f"[HOVER] {xpath}")
                try:
                    page.locator(f"xpath={xpath}").hover()
                except Exception as e:
                    print(f"[ERROR] HOVER failed ({xpath}): {e}")
                    raise
            elif line.startswith("SCROLL "):
                loc = line[7:].strip().upper()
                print(f"[SCROLL] {loc}")
                try:
                    if loc == "END":
                        page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                    elif loc == "PAGE":
                        page.evaluate("window.scrollBy(0, window.innerHeight)")
                    else:
                        # allow numeric scroll: SCROLL 500 -> scroll by 500px
                        try:
                            px = int(loc)
                            page.evaluate(f"window.scrollBy(0, {px})")
                        except Exception:
                            print(f"[WARN] Unknown SCROLL target: {loc}")
                except Exception as e:
                    print(f"[ERROR] SCROLL failed ({loc}): {e}")
                    raise
            elif line.startswith("SLEEP "):
                try:
                    sec = int(line[6:].strip())
                except Exception:
                    sec = 1
                print(f"[SLEEP] {sec}s")
                time.sleep(sec)
            else:
                # Unknown instruction: skip but log
                print(f"[WARN] Unknown command, skipping: {line}")


def get_js_coverage(config_file):
    """Run browser with coverage and execute config commands, return {js_url: merged_ranges}."""
    js_coverage = {}

    with sync_playwright() as p:
        # Headless Chromium suitable for server / docker
        browser = p.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-blink-features=AutomationControlled",
                "--disable-http2",
                "--disable-features=IsolateOrigins,site-per-process",
                "--ignore-certificate-errors",
                "--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0 Safari/537.36"
            ]
        )
        context = browser.new_context()
        page = context.new_page()

        # Start CDP precise coverage (V8)
        client = context.new_cdp_session(page)
        client.send("Profiler.enable")
        client.send("Profiler.startPreciseCoverage", {"callCount": True, "detailed": True})

        # Execute config commands
        run_config_commands(page, config_file)

        # Take coverage snapshot
        result = client.send("Profiler.takePreciseCoverage")
        client.send("Profiler.stopPreciseCoverage")
        client.send("Profiler.disable")
        browser.close()

        # Parse coverage result
        for entry in result.get("result", []):
            js_url = entry.get("url", "")
            if not js_url or not js_url.endswith(".js"):
                continue
            used_ranges = []
            for func in entry.get("functions", []):
                for r in func.get("ranges", []):
                    # r contains startOffset, endOffset, count
                    if r.get("count", 0) > 0:
                        used_ranges.append((r.get("startOffset", 0), r.get("endOffset", 0)))
            if used_ranges:
                js_coverage[js_url] = merge_ranges(used_ranges)

    return js_coverage


def save_executed_code(js_coverage, base_folder="js_executed"):
    """Download JS files and save only executed ranges (no comments)."""
    Path(base_folder).mkdir(parents=True, exist_ok=True)
    saved_any = False

    for url, ranges in js_coverage.items():
        try:
            response = requests.get(url, timeout=15)
            response.raise_for_status()
            code = response.text

            # Merge ranges again for safety
            ranges = merge_ranges(ranges)

            executed_parts = []
            for start, end in ranges:
                # clamp offsets to valid bounds
                s = max(0, min(len(code), start))
                e = max(0, min(len(code), end))
                if e > s:
                    #executed_parts.append(f"/* Executed range {s}-{e} */\n{code[s:e]}\n/* End range */")
                    executed_parts.append(code[s:e])
            trimmed_code = "\n".join(executed_parts)

            # Save with original domain/path
            parsed = urlparse(url)
            path = parsed.netloc + parsed.path
            if path.endswith("/") or not path.endswith(".js"):
                path += "index.js"
            full_path = os.path.join(base_folder, path.lstrip("/"))
            Path(os.path.dirname(full_path)).mkdir(parents=True, exist_ok=True)

            with open(full_path, "w", encoding="utf-8") as f:
                f.write(trimmed_code)

            print(f"[✓] Saved executed code: {full_path}")
            saved_any = True
        except Exception as e:
            print(f"[✗] Failed to save {url}: {e}")
    if not saved_any:
        print(f"[INFO] No JS files were saved. An empty directory was created at: {os.path.abspath(base_folder)}")


if __name__ == "__main__":
    target_name = sys.argv[2]

    # Replace with your config filename
    config_file = os.path.join("config", f"{target_name}.config")

    # Run coverage collection
    coverage = get_js_coverage(config_file)

    # Save executed parts of JS files
    save_executed_code(coverage, base_folder="js_files_" + target_name + "_dynamic")

