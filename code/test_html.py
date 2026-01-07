import json
import re
import time
import sys
import io
import glob
import os
from collections import defaultdict, Counter
from tree_sitter import Language, Parser

sys.setrecursionlimit(5000)

def collect_full_paths(data, prefix=""):
    paths = []
    if isinstance(data, dict):
        for key, value in data.items():
            full_key = f"{prefix}.{key}" if prefix else key
            if isinstance(value, (dict, list)):
                paths.extend(collect_full_paths(value, full_key))
            else:
                paths.append(full_key)
    elif isinstance(data, list):
        if all(not isinstance(item, (dict, list)) for item in data):
            if prefix:
                paths.append(prefix)
        else:
            for item in data:
                paths.extend(collect_full_paths(item, prefix))
    return paths


JAVASCRIPT_LANGUAGE = Language("build/my-languages.so", "javascript")
parser = Parser()
parser.set_language(JAVASCRIPT_LANGUAGE)


def extract_script_blocks(html_content):
    scripts = re.findall(r"<script[^>]*>([\s\S]*?)</script>", html_content, re.IGNORECASE)
    html_without_scripts = re.sub(r"<script[^>]*>[\s\S]*?</script>", "", html_content, flags=re.IGNORECASE)
    return scripts, html_without_scripts


def analyze_js_code(js_code, json_keys_set):
    js_bytes = js_code.encode()
    tree = parser.parse(js_bytes)
    root_node = tree.root_node

    matched_keys = set()
    match_details = []

    def extract_direct_lhs(node):
        if node.type == "member_expression":
            obj = node.child_by_field_name("object")
            if obj:
                return js_bytes[obj.start_byte:obj.end_byte].decode()
        return None

    def walk(node):
        # Check member_expression and subscript_expression
        if node.type in ("member_expression", "subscript_expression"):
            lhs = extract_direct_lhs(node)

            if node.type == "member_expression":
                prop = node.child_by_field_name("property")
                if prop and prop.type in ("property_identifier", "identifier"):
                    name = js_bytes[prop.start_byte:prop.end_byte].decode()
                    if name in json_keys_set:
                        matched_keys.add(name)
                        match_details.append({
                            "matched_key": name,
                            "code_snippet": js_bytes[node.start_byte:node.end_byte].decode(),
                            "lhs": lhs
                        })

            elif node.type == "subscript_expression":
                idx = node.child_by_field_name("index")
                if idx:
                    if idx.type == "string":
                        val = js_bytes[idx.start_byte:idx.end_byte].decode().strip("\"'")
                        if val in json_keys_set:
                            matched_keys.add(val)
                            match_details.append({
                                "matched_key": val,
                                "code_snippet": js_bytes[node.start_byte:node.end_byte].decode(),
                                "lhs": lhs
                            })
                    elif idx.type == "identifier":
                        val = js_bytes[idx.start_byte:idx.end_byte].decode()
                        if val in json_keys_set:
                            matched_keys.add(val)
                            match_details.append({
                                "matched_key": val,
                                "code_snippet": js_bytes[node.start_byte:node.end_byte].decode(),
                                "lhs": lhs
                            })

        for child in node.children:
            walk(child)

    walk(root_node)
    return matched_keys, match_details


def find_brace_snippets(content, key, context=30):
    braces = r"\{\{[^{}]*\b" + re.escape(key) + r"\b[^{}]*\}\}"
    matches = []
    for m in re.finditer(braces, content):
        start = max(0, m.start() - context)
        end = m.end() + context
        snippet = content[start:end]
        matches.append(snippet)
    return matches

# ----- main -----
target = sys.argv[2]
if sys.argv[1] == "-k":
    mode = ""
elif sys.argv[1] == "-s":
    mode = "_static"
elif sys.argv[1] == "-d":
    mode = "_dynamic"

# 1) Load JSON
with open(f"tests/{target}.json", "r", encoding="utf-8") as f_json:
    json_data = json.load(f_json)
    json_paths = list(set(collect_full_paths(json_data)))

# 2) Build key / parent relationships
parent_to_child_keys = defaultdict(list)
for path in json_paths:
    parts = path.split(".")
    if len(parts) >= 2:
        parent = ".".join(parts[:-1])
        child = parts[-1].split("[")[0]
        parent_to_child_keys[parent].append(child)

child_key_patterns = Counter(tuple(sorted(children)) for children in parent_to_child_keys.values())

# Build json_keys_set + collapsed parent-to-path mapping
json_keys_set = set()
collapsed_key_to_paths = defaultdict(set)
leaf_key_to_paths = defaultdict(list)

for path in json_paths:
    parts = path.split(".")
    for part in parts:
        json_keys_set.add(part)
    if len(parts) > 1:
        parent = ".".join(parts[:-1])
        parent_key = parent.split(".")[-1]
        leaf_key = parts[-1].split("[")[0]

        # Track all paths sharing the same leaf key
        leaf_key_to_paths[leaf_key].append((parent_key, path))

        key_tuple = tuple(sorted(parent_to_child_keys.get(parent, [])))
        if child_key_patterns[key_tuple] > 1:
            collapsed_key_to_paths[parent_key].add(path)

# Now add leaf keys that appear in multiple places to collapsed_key_to_paths
for leaf_key, parent_path_pairs in leaf_key_to_paths.items():
    if len(parent_path_pairs) > 1:
        for parent_key, path in parent_path_pairs:
            collapsed_key_to_paths[parent_key].add(path)

# 3) Load HTML and inline script code
inline_js_dir = f"html_files_{target}{mode}/inline_scripts"
all_script_code = ""

js_files = sorted(glob.glob(os.path.join(inline_js_dir, "*.js")))

if not js_files:
    print(f"[!] No JS files found in {inline_js_dir}")
else:
    js_contents = []
    for js_path in js_files:
        try:
            with open(js_path, "r", encoding="utf-8") as f_js:
                js_contents.append(f_js.read())
        except Exception as e:
            print(f"[!] Failed to read {js_path}: {e}")

    all_script_code = "\n".join(js_contents)

html_path = f"html_files_{target}{mode}/page.html"
with open(html_path, "r", encoding="utf-8") as f_html:
    html_content = f_html.read()

script_blocks, html_without_scripts = extract_script_blocks(html_content)

# 4) Load existing JS result paths to skip
js_result_file = f"result{mode}/{target}_js_result.txt"
already_found_paths = set()
try:
    with open(js_result_file, "r", encoding="utf-8") as f_js:
        already_found_paths = {line.strip() for line in f_js if line.strip()}
except FileNotFoundError:
    print(f"[!] JS result file not found: {js_result_file} — skipping JS filtering")

# 5) Analyze the inline JS with Tree-sitter
js_keys = set()
js_details = []
if all_script_code.strip():
    js_keys, js_details = analyze_js_code(all_script_code, json_keys_set)
else:
    print("[!] No <script> blocks found in HTML.")

# 6) Build output_paths from js_keys using parent relationship logic (like earlier)
output_paths = set()
for key in js_keys:
    # skip numeric keys
    if key.isdigit():
        continue
    if key in collapsed_key_to_paths:
        # find parent_path(s) whose last part equals this key
        for parent_path, children in parent_to_child_keys.items():
            if parent_path.split(".")[-1] == key:
                matched_children = [child for child in children if child in js_keys]
                if matched_children:
                    for child in matched_children:
                        full_path = parent_path + "." + child
                        output_paths.add(full_path)
                # if no matched_children, original code commented out adding all children
                break
    else:
        # find any json_paths whose last segment equals key
        for path in json_paths:
            leaf = path.split(".")[-1].split("[")[0]
            if leaf == key:
                # ensure path not in any collapsed_key_to_paths values
                if all(path not in paths for paths in collapsed_key_to_paths.values()):
                    output_paths.add(path)

# 7) Post-process output_paths to enforce flexible LHS consistency (preserve debug prints)
# prepare structures
key_to_lhs = defaultdict(set)
path_to_key = {}
key_to_root = defaultdict(set)

# collect lhs from js_details (like file_match_details_group)
for match in js_details:
    matched_key = match.get('matched_key')
    lhs = match.get('lhs')
    key_to_lhs[matched_key].add(lhs)

# Determine key associated with each path (collapsed or leaf)
path_to_key_updates = []
for path in list(output_paths):
    parts = path.split(".")
    collapsed_matched = False
    if not collapsed_matched:
        path_to_key_updates.append((path, parts[-1].split("[")[0]))

for path, key in path_to_key_updates:
    path_to_key[path] = key

# Group all relevant keys by root and add full paths to mid-keys
root_group_to_keys = defaultdict(set)
path_root_group = {}
for path, key in list(path_to_key.items()):
    parts = path.split(".")
    root = ".".join(parts[:-1])
    root_group_to_keys[root].add(key)
    path_root_group[path] = root

    for i in range(1, len(parts)):
        sub_path = ".".join(parts[:i+1])
        sub_root = ".".join(parts[:i])
        mid_key = parts[i]
        root_group_to_keys[sub_root].add(mid_key)
        path_to_key[sub_path] = mid_key

# Capture debug output into buffer
buffer = io.StringIO()
original_stdout = sys.stdout
sys.stdout = buffer  # redirect

# Filter paths based on flexible LHS condition (keeps debug prints)
final_paths = set()
for root, keys in root_group_to_keys.items():
    lhs_to_keys = defaultdict(set)
    for key in keys:
        for lhs in key_to_lhs.get(key, []):
            if lhs:
                lhs_to_keys[lhs].add(key)

    # Find lhs(s) with the maximum number of keys
    max_len = 0
    top_lhss = set()
    for lhs, ks in lhs_to_keys.items():
        if len(ks) > max_len:
            max_len = len(ks)
            top_lhss = {lhs}
        elif len(ks) == max_len:
            top_lhss.add(lhs)

    # Now only consider those top_lhss
    for path, key in list(path_to_key.items()):
        if path_root_group.get(path) == root:
            if len(keys) == 1:
                if path in output_paths:
                    final_paths.add(path)
            else:
                if any(key in lhs_to_keys[lhs] for lhs in top_lhss):
                    if path in output_paths:
                        final_paths.add(path)

# Restore stdout
sys.stdout = original_stdout
debug_buffer_content = buffer.getvalue()

# remove paths already found in external JS result file
final_paths = {p for p in final_paths if p not in already_found_paths}

# 8) Build found_snippets_js based on final_paths and js_details
# Map matched_key -> list of code_snippets
key_to_snips = defaultdict(list)
for d in js_details:
    key_to_snips[d['matched_key']].append((d.get('lhs'), d.get('code_snippet')))

found_snippets_js = {}
for path in sorted(final_paths):
    # path's last leaf is the key
    key = path.split(".")[-1].split("[")[0]
    snippets = []
    for lhs, cs in key_to_snips.get(key, []):
        snippets.append(f"[JS] LHS:{lhs} -> {cs}")
    if snippets:
        found_snippets_js[path] = snippets

# 9) Search remaining HTML using {{key}} pattern only (skip already_found_paths)
found_snippets_html = {}
for leaf_key, parent_path_pairs in leaf_key_to_paths.items():
    if leaf_key.isdigit():
        continue
    braces_pattern = r"\{\{[^{}]*\b" + re.escape(leaf_key) + r"\b[^{}]*\}\}"
    if re.search(braces_pattern, html_without_scripts):
        snippets = find_brace_snippets(html_without_scripts, leaf_key)
        if snippets:
            for _, full_path in parent_path_pairs:
                if full_path in already_found_paths:
                    continue
                # if JS already found the same path via final_paths, skip duplication
                if full_path in found_snippets_js:
                    continue
                found_snippets_html[full_path] = snippets

# 10) Combine results (JS final_paths + HTML template matches)
found_snippets = {}
found_snippets.update(found_snippets_html)
found_snippets.update(found_snippets_js)

# 11) Output result list and detailed snippets (and include debug buffer)
output_result = f"result{mode}/{target}_html_result.txt"
with open(output_result, "w", encoding="utf-8") as f_out:
    for path in sorted(found_snippets.keys()):
        f_out.write(path + "\n")
