import sys
import os
import requests
from urllib.parse import urlparse
from pathlib import Path
from playwright.sync_api import sync_playwright

def get_top_level_js_files(url):
    js_files = set()

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        #context = browser.new_context()
        context = browser.new_context(user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/112.0.0.0 Safari/537.36")
        page = context.new_page()

        def log_request(request):
            if request.resource_type == "script":
                js_files.add(request.url)

        page.on("request", log_request)
        try:
            page.goto(url, wait_until="load", timeout=60000)
            page.wait_for_timeout(5000)
        except Exception as e:
            print(f"[!] Timeout or load error for {url}: {e}")

        browser.close()

    return list(js_files)

def save_with_original_structure(js_urls, base_folder="js_files"):
    for url in js_urls:
        try:
            response = requests.get(url, timeout=10)
            response.raise_for_status()

            parsed = urlparse(url)
            path = parsed.netloc + parsed.path  # domain + path
            if path.endswith('/') or not path.endswith('.js'):
                path += 'index.js'  # fallback filename

            full_path = os.path.join(base_folder, path.lstrip('/'))
            Path(os.path.dirname(full_path)).mkdir(parents=True, exist_ok=True)

            with open(full_path, 'wb') as f:
                f.write(response.content)
            print(f"[✓] Saved: {full_path}")
        except Exception as e:
            print(f"[✗] Failed to download {url}: {e}")

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


if __name__ == "__main__":
    target = sys.argv[2]
    cfg = load_config(target)
    url = cfg.get("LOAD")
    if not url:
        raise ValueError("LOAD key not found in config file.")

    base_folder = f"js_files_{target}"

    js_list = get_top_level_js_files(url)
    save_with_original_structure(js_list, base_folder=base_folder)
