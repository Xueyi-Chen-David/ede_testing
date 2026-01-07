import os
import sys
import time
import subprocess
import requests
from bs4 import BeautifulSoup
from pathlib import Path
from urllib.parse import urlparse
from playwright.sync_api import sync_playwright


def load_config(target):
    config_path = os.path.join("config", f"{target}.config")
    config_data = {}

    with open(config_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            key, value = line.split(" ", 1)
            config_data[key] = value

    return config_data


def extract_inline_scripts_from_html(html):
    soup = BeautifulSoup(html, "html.parser")
    scripts = []
    idx = 0

    for tag in soup.find_all("script"):
        if tag.get("src"):
            continue
        idx += 1
        content = tag.string or ""
        if content is None:
            content = "".join(tag.strings) if tag.strings else ""
        scripts.append({
            "index": idx,
            "content": content,
            "length": len(content),
        })

    return scripts


def slice_utf16(code, start, end):
    try:
        b = code.encode("utf-16-le")
        byte_start = start * 2
        byte_end = end * 2
        sliced = b[byte_start:byte_end]
        return sliced.decode("utf-16-le", errors="ignore")
    except Exception:
        try:
            return code[start:end]
        except:
            return ""


def run_config_commands(page, config_file):
    with open(config_file, "r", encoding="utf-8") as f:
        for raw in f:
            line = raw.strip()
            if not line or line.startswith("#"):
                continue

            if line.startswith("TEST"):
                print("[INFO] Reached TEST.")
                break

            if line.startswith("LOAD "):
                url = line[5:].strip()
                print(f"[LOAD] {url}")
                page.goto(url, wait_until="load", timeout=60000)

            elif line.startswith("WAIT_LOCATE "):
                xpath = line[12:].strip()
                print(f"[WAIT_LOCATE] {xpath}")
                page.wait_for_selector(f"xpath={xpath}", timeout=30000)

            elif line.startswith("INPUT "):
                rest = line[6:].strip()
                try:
                    xpath, content = rest.split(" ", 1)
                except ValueError:
                    xpath, content = rest, ""
                print(f"[INPUT] {xpath} <- {content}")
                locator = page.locator(f"xpath={xpath}")
                locator.fill(content)

            elif line.startswith("CLICK "):
                xpath = line[6:].strip()
                print(f"[CLICK] {xpath}")
                page.locator(f"xpath={xpath}").first.click()

            elif line.startswith("HOVER "):
                xpath = line[6:].strip()
                print(f"[HOVER] {xpath}")
                page.locator(f"xpath={xpath}").hover()

            elif line.startswith("SCROLL "):
                loc = line[7:].strip().upper()
                print(f"[SCROLL] {loc}")
                if loc == "END":
                    page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                elif loc == "PAGE":
                    page.evaluate("window.scrollBy(0, window.innerHeight)")
                else:
                    try:
                        px = int(loc)
                        page.evaluate(f"window.scrollBy(0, {px})")
                    except:
                        print(f"[WARN] Unknown SCROLL: {loc}")

            elif line.startswith("SLEEP "):
                sec = int(line[6:].strip())
                print(f"[SLEEP] {sec}s")
                time.sleep(sec)

            else:
                print(f"[WARN] Unknown command: {line}")



def get_inline_coverage(config_file):
    inline_scripts = {}

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-blink-features=AutomationControlled",
                "--disable-http2",
                "--disable-features=IsolateOrigins,site-per-process",
                "--ignore-certificate-errors",
            ],
        )

        context = browser.new_context()
        page = context.new_page()

        client = context.new_cdp_session(page)
        client.send("Profiler.enable")
        client.send("Debugger.enable")
        client.send("Profiler.startPreciseCoverage",
                    {"callCount": True, "detailed": True})

        run_config_commands(page, config_file)

        html = page.content()

        coverage = client.send("Profiler.takePreciseCoverage")

        script_sources = {}
        for entry in coverage.get("result", []):
            sid = entry.get("scriptId")
            if not sid:
                continue

            try:
                resp = client.send("Debugger.getScriptSource", {"scriptId": sid})
                script_sources[sid] = resp.get("scriptSource", "")
            except:
                script_sources[sid] = ""

        browser.close()

    results = []

    for entry in coverage.get("result", []):
        if entry.get("url"):
            continue 

        sid = entry.get("scriptId")
        if not sid:
            continue

        src = script_sources.get(sid, "")
        if not src:
            continue

        ranges = []
        for func in entry.get("functions", []):
            for r in func.get("ranges", []):
                if r.get("count", 0) > 0:
                    ranges.append((r.get("startOffset", 0), r.get("endOffset", 0)))

        if not ranges:
            continue

        ranges = sorted(ranges)
        results.append({
            "scriptId": sid,
            "source": src,
            "ranges": ranges
        })

    return html, results


def optimize_static_js(input_dir, output_dir):
    CLOSURE_CMD = "google-closure-compiler"
    COMPILATION_LEVEL = "SIMPLE"

    for root, _, files in os.walk(input_dir):
        for file in files:
            if not file.endswith(".js"):
                continue

            input_path = os.path.join(root, file)
            rel_path = os.path.relpath(input_path, input_dir)
            output_path = os.path.join(output_dir, rel_path)

            Path(os.path.dirname(output_path)).mkdir(parents=True, exist_ok=True)

            print(f"[→] Closure Compiler: {input_path}")

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

            print(f"[✓] Saved optimized: {output_path}")


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: download_html.py <-d|-k|-s> <target>")
        sys.exit(1)

    mode = sys.argv[1]
    target = sys.argv[2]

    cfg = load_config(target)
    url = cfg.get("LOAD")
    if not url:
        raise ValueError("LOAD key not found in config file.")

    if mode == "-k":
        base_dir = f"html_files_{target}"
    elif mode == "-d":
        base_dir = f"html_files_{target}_dynamic"
    elif mode == "-s":
        base_dir = f"html_files_{target}_static"
    else:
        raise ValueError("Unknown mode")

    inline_dir = os.path.join(base_dir, "inline_scripts")
    Path(inline_dir).mkdir(parents=True, exist_ok=True)

    html_path = os.path.join(base_dir, "page.html")


    if mode == "-d":
        raw_html = requests.get(url, timeout=15).text
        with open(html_path, "w", encoding="utf-8") as f:
            f.write(raw_html)

        config_file = f"config/{target}.config"
        dynamic_html, inline_cov = get_inline_coverage(config_file)

        for item in inline_cov:
            sid = item["scriptId"]
            src = item["source"]
            parts = [slice_utf16(src, s, e) for s, e in item["ranges"]]
            out_file = os.path.join(inline_dir, f"inline_{sid}.js")

            with open(out_file, "w", encoding="utf-8") as f:
                f.write("\n".join(parts))

            print(f"[✓] Saved sliced inline: {out_file}")

        sys.exit(0)

    html = requests.get(url, timeout=15).text

    with open(html_path, "w", encoding="utf-8") as f:
        f.write(html)

    inline_raw = extract_inline_scripts_from_html(html)

    for item in inline_raw:
        idx = item["index"]
        content = item["content"]

        out_file = os.path.join(inline_dir, f"inline_{idx}.js")
        with open(out_file, "w", encoding="utf-8") as f:
            f.write(content)

        print(f"[✓] Saved inline script: {out_file}")

    if mode == "-s":
        optimize_static_js(inline_dir, inline_dir)

        print(f"[✓] Static optimized inline scripts saved in {inline_dir}")

    print("[✓] Done.")
