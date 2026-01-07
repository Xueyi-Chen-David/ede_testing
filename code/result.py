import json
import sys
from pathlib import Path
from collections import OrderedDict

# Files
TARGET = sys.argv[2]

if sys.argv[1] == "-k":
    MODE = ""
elif sys.argv[1] == "-s":
    MODE = "_static"
elif sys.argv[1] == "-d":
    MODE = "_dynamic"

JSON_FILE = Path(f'tests/{TARGET}.json')
SMALL_JS = Path(f'result{MODE}/{TARGET}_js_result.txt')
SMALL_HTML = Path(f'result{MODE}/{TARGET}_html_result.txt')
OUT_HTML = Path(f'result{MODE}/{TARGET}_flagged.html')

def parse_smallfile(text):
    s = set()
    for line in text.splitlines():
        line = line.strip()
        if line:
            s.add(line.strip(' "\''))
    return s

def make_html_from_obj(obj, present_keys, parent_key="", indent=0):
    spaces = "  " * indent
    html = []

    if isinstance(obj, dict):
        html.append(spaces + "{")
        for k, v in obj.items():
            full_key = f"{parent_key}.{k}" if parent_key else k
            cls = "present" if full_key in present_keys else "missing"
            if isinstance(v, (dict, list)):
                html.append(f'{spaces}  <span class="{cls}">"{k}": </span>' + make_html_from_obj(v, present_keys, full_key, indent + 1))
            else:
                html.append(f'{spaces}  <span class="{cls}">"{k}": "{v}"</span>,')
        html.append(spaces + "}")
    elif isinstance(obj, list):
        html.append(spaces + "[")
        for item in obj:
            html.append(make_html_from_obj(item, present_keys, parent_key, indent + 1) + ",")
        html.append(spaces + "]")
    else:
        html.append(spaces + str(obj))
    return "\n".join(html)

def make_html(data, present_keys):
    html = []
    html.append("<!DOCTYPE html>")
    html.append("<html>")
    html.append("<head>")
    html.append('  <meta charset="utf-8">')
    html.append("  <style>")
    html.append("    .present { color: black; }")
    html.append("    .missing { color: red; }")
    html.append("    pre { font-family: monospace; }")
    html.append("  </style>")
    html.append("</head>")
    html.append("<body>")
    html.append("<pre>")
    html.append(make_html_from_obj(data, present_keys))
    html.append("</pre>")
    html.append("</body>")
    html.append("</html>")
    return "\n".join(html)

def main():
    data = json.loads(Path(JSON_FILE).read_text(encoding="utf-8"), object_pairs_hook=OrderedDict)

    small_keys = set()
    if SMALL_JS.exists():
        small_keys |= parse_smallfile(SMALL_JS.read_text(encoding="utf-8"))
    if SMALL_HTML.exists():
        small_keys |= parse_smallfile(SMALL_HTML.read_text(encoding="utf-8"))

    html = make_html(data, small_keys)
    OUT_HTML.write_text(html, encoding="utf-8")
    print("Wrote", OUT_HTML)

if __name__ == "__main__":
    main()
