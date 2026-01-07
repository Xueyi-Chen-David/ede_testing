from seleniumwire import webdriver
from seleniumwire.utils import decode
import time
import json
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.common.action_chains import ActionChains
import sys
import os


class Cacher:
    def __init__(self, config_file, firefox=False):

        # Setup browser
        if firefox:
            self.driver = webdriver.Firefox()
        else:
            chrome_options = webdriver.ChromeOptions()
            chrome_options.add_argument("--headless=new")   # 或 --headless
            chrome_options.add_argument("--no-sandbox")
            chrome_options.add_argument("--disable-dev-shm-usage")
            chrome_options.add_argument("--disable-gpu")
            chrome_options.add_argument("--remote-debugging-port=9222")
            chrome_options.add_argument("--disable-blink-features=AutomationControlled")

            self.driver = webdriver.Chrome(options=chrome_options)


        # Attach interceptor
        self.driver.response_interceptor = self.interceptor_resp

        self.wait = WebDriverWait(self.driver, 12)
        self.target = None
        self.cache = {}
        self.response = None
        self.config = []
        self.parse_config(config_file)

    # ----------------------------------------------------------------------
    # CONFIG PARSING
    # ----------------------------------------------------------------------
    def parse_config(self, config_text):
        for line in config_text.split("\n"):
            line = line.strip()
            if not line or line.startswith("#"):
                continue

            if line.startswith("TARGET "):
                self.target = line[7:]
                continue

            self.config.append(line)

    # ----------------------------------------------------------------------
    # SELENIUMWIRE INTERCEPTOR
    # ----------------------------------------------------------------------
    def interceptor_resp(self, request, response):
        try:
            body = decode(
                response.body,
                response.headers.get("Content-Encoding", "identity")
            )

            # Save everything into cache
            self.cache[request.url] = (
                {h: response.headers[h] for h in response.headers},
                body
            )

            # Match TARGET
            if self.target and self.target in request.url:
                try:
                    self.response = json.loads(body)
                    print("✓ Captured:", request.url)
                except:
                    pass

        except Exception as e:
            print("[Decode error]", e)

    # ----------------------------------------------------------------------
    # COMMAND EXECUTION
    # ----------------------------------------------------------------------
    def process_config(self, command):

        # LOAD
        if command.startswith("LOAD "):
            url = command[5:]
            print("→ LOAD:", url)
            self.driver.get(url)

        # COOKIE
        elif command.startswith("COOKIE "):
            cookie_string = command[7:]
            print("→ COOKIE:", cookie_string)
            for item in cookie_string.split(";"):
                key, value = item.strip().split("=", 1)
                self.driver.add_cookie({"name": key, "value": value})

        # WAIT_LOCATE
        elif command.startswith("WAIT_LOCATE "):
            xpath = command[12:]
            print("→ WAIT:", xpath)
            try:
                self.wait.until(
                    EC.presence_of_element_located((By.XPATH, xpath))
                )
            except:
                print("✗ Timeout:", xpath)

        # CLICK
        elif command.startswith("CLICK "):
            xpath = command[6:]
            print("→ CLICK:", xpath)
            btn = self.driver.find_element("xpath", xpath)
            ActionChains(self.driver).move_to_element(btn).perform()
            btn.click()

        # HOVER
        elif command.startswith("HOVER "):
            xpath = command[6:]
            print("→ HOVER:", xpath)
            ActionChains(self.driver).move_to_element(
                self.driver.find_element("xpath", xpath)
            ).perform()

        # INPUT
        elif command.startswith("INPUT "):
            rest = command[6:]
            xpath, content = rest.split(" ", 1)
            print("→ INPUT:", xpath, "=", content)
            elem = self.driver.find_element("xpath", xpath)
            elem.send_keys(Keys.CONTROL, "a")
            elem.send_keys(Keys.DELETE)
            elem.send_keys(content)

        # SCROLL
        elif command.startswith("SCROLL "):
            mode = command[7:].strip().upper()
            print("→ SCROLL:", mode)
            html = self.driver.find_element(By.TAG_NAME, "html")
            if mode == "END":
                html.send_keys(Keys.END)
            elif mode == "PAGE":
                html.send_keys(Keys.PAGE_DOWN)

        # SLEEP
        elif command.startswith("SLEEP "):
            sec = int(command[6:])
            print("→ SLEEP:", sec)
            time.sleep(sec)

        # TEST
        elif command.startswith("TEST "):
            print("→ TEST")

    # ----------------------------------------------------------------------
    def run(self):
        for cmd in self.config:
            self.process_config(cmd)

    def finish(self):
        self.driver.quit()

    def export_response(self):
        return self.response


# --------------------------------------------------------------------------
# MAIN EXECUTION
# --------------------------------------------------------------------------
if __name__ == "__main__":
    target = sys.argv[2]
    config_path = os.path.join("config", f"{target}.config")

    with open(config_path, "r", encoding="utf8") as f:
        config_text = f.read()

    c = Cacher(config_text)
    c.run()

    print("Waiting for network responses…")
    time.sleep(3)

    json_data = c.export_response()
    c.finish()

    output_path = os.path.join("tests", f"{target}.json")

    if json_data:
        os.makedirs("tests", exist_ok=True)
        with open(output_path, "w", encoding="utf8") as f:
            json.dump(json_data, f, ensure_ascii=False, indent=2)
        print("✓ Saved to tests")
    else:
        print("❌ No JSON captured (TARGET not matched?)")
