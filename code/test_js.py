import json
from collections import defaultdict, Counter
from tree_sitter import Language, Parser
import re
import glob
import time
import os
import io
import sys
sys.setrecursionlimit(5000)

# ----------------------------
# Setup Tree-sitter JavaScript
# ----------------------------
JAVASCRIPT_LANGUAGE = Language('build/my-languages.so', 'javascript')
parser = Parser()
parser.set_language(JAVASCRIPT_LANGUAGE)

# ----------------------------
# Load JSON and collect full key paths
# ----------------------------
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
            paths.append(prefix)
        else:
            for item in data:
                paths.extend(collect_full_paths(item, prefix))
    return paths

# Step 1: full paths from your previous logic
target = sys.argv[2]
if sys.argv[1] == "-k":
    mode = ""
elif sys.argv[1] == "-s":
    mode = "_static"
elif sys.argv[1] == "-d":
    mode = "_dynamic"

with open("tests/" + target + ".json", "r", encoding="utf-8") as f_json:
    json_data = json.load(f_json)
    json_paths = list(set(collect_full_paths(json_data)))

# Step 2: build child key patterns per parent path
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

# ----------------------------
# Parse JavaScript
# ----------------------------
def extract_direct_lhs(node, js_bytes):
    if node.type == "member_expression":
        object_node = node.child_by_field_name("object")
        if object_node:
            return js_bytes[object_node.start_byte:object_node.end_byte].decode()
    return None

js_folder = "js_files_" + target + mode
file_key_matches = defaultdict(set)
file_match_details = defaultdict(list)

all_js_files = glob.glob(f"{js_folder}/**/*.js", recursive=True)

for js_file in all_js_files:
    print(f"Processing {js_file}...")
    with open(js_file, "r", encoding="utf-8", errors="ignore") as f_js:
        js_code = f_js.read()
        js_bytes = js_code.encode()

    tree = parser.parse(js_bytes)
    root_node = tree.root_node

    def walk_with_parent(node):
        if node.type in ("member_expression", "subscript_expression"):
            lhs = extract_direct_lhs(node, js_bytes)

            if node.type == "member_expression":
                property_node = node.child_by_field_name("property")
                if property_node and property_node.type in ("property_identifier", "identifier"):
                    prop_name = js_bytes[property_node.start_byte:property_node.end_byte].decode()
                    if prop_name in json_keys_set:
                        file_key_matches[js_file].add(prop_name)
                        file_match_details[js_file].append({
                            "matched_key": prop_name,
                            "key_node_type": property_node.type,
                            "parent_node_type": node.type,
                            "code_snippet": js_bytes[node.start_byte:node.end_byte].decode(),
                            "lhs": lhs
                        })

            elif node.type == "subscript_expression":
                index_node = node.child_by_field_name("index")
                if index_node:
                    if index_node.type == "string":
                        value = js_bytes[index_node.start_byte:index_node.end_byte].decode().strip("\"'")
                        if value in json_keys_set:
                            file_key_matches[js_file].add(value)
                            file_match_details[js_file].append({
                                "matched_key": value,
                                "key_node_type": index_node.type,
                                "parent_node_type": node.type,
                                "code_snippet": js_bytes[node.start_byte:node.end_byte].decode(),
                                "lhs": lhs
                            })
                    elif index_node.type == "identifier":
                        var_name = js_bytes[index_node.start_byte:index_node.end_byte].decode()
                        if var_name in json_keys_set:
                            file_key_matches[js_file].add(var_name)
                            file_match_details[js_file].append({
                                "matched_key": var_name,
                                "key_node_type": index_node.type,
                                "parent_node_type": node.type,
                                "code_snippet": js_bytes[node.start_byte:node.end_byte].decode(),
                                "lhs": lhs
                            })

        for child in node.children:
            walk_with_parent(child)

    walk_with_parent(root_node)

# ----------------------------
# Find JS file with the most unique matched keys
# ----------------------------
if not file_key_matches:
    print("[!] No JSON keys matched in any JavaScript file.")
    exit(1)
most_matched_file = max(file_key_matches.items(), key=lambda x: len(x[1]))[0]
most_matched_keys = file_key_matches[most_matched_file]

# ----------------------------
# Determine the 2nd-level folder and collect all JS files under it
# ----------------------------
rel_path = os.path.relpath(most_matched_file, js_folder)
parts = rel_path.split(os.sep)

if len(parts) >= 2:
    second_level_folder = os.path.join(js_folder, parts[0], parts[1])
    if os.path.isfile(second_level_folder):
        second_level_folder = os.path.dirname(second_level_folder)
    same_level_js_files = glob.glob(f"{second_level_folder}/**/*.js", recursive=True)
else:
    second_level_folder = os.path.dirname(most_matched_file)
    same_level_js_files = [most_matched_file]

# ----------------------------
# Combine key matches from these JS files
# ----------------------------
combined_keys = set()
combined_details = []

for jsf in same_level_js_files:
    combined_keys |= file_key_matches.get(jsf, set())
    combined_details.extend(file_match_details.get(jsf, []))

# Use combined results for the next analysis
most_matched_keys = combined_keys
file_match_details_group = combined_details

# ----------------------------
# Write result paths for top-matching JS file
# ----------------------------
output_paths = set()
for key in most_matched_keys:
    if key in collapsed_key_to_paths:
        for parent_path, children in parent_to_child_keys.items():
            if parent_path.split(".")[-1] == key:
                matched_children = [child for child in children if child in most_matched_keys]
                if matched_children:
                    for child in matched_children:
                        full_path = parent_path + "." + child
                        output_paths.add(full_path)
                '''else:
                    for child in children:
                        full_path = parent_path + "." + child
                        output_paths.add(full_path)'''
                break
    else:
        for path in json_paths:
            if path.split(".")[-1].split("[")[0] == key:
                if all(path not in paths for paths in collapsed_key_to_paths.values()):
                    output_paths.add(path)

# ----------------------------
# Post-process output_paths to enforce flexible LHS consistency
# ----------------------------
key_to_lhs = defaultdict(set)
path_to_key = {}
key_to_root = defaultdict(set)

for match in file_match_details_group:
    matched_key = match['matched_key']
    lhs = match.get('lhs')
    key_to_lhs[matched_key].add(lhs)

# Determine key associated with each path (collapsed or leaf)
path_to_key_updates = []
for path in list(output_paths):
    parts = path.split(".")
    collapsed_matched = False
    '''for key, collapsed_paths in collapsed_key_to_paths.items():
        if path in collapsed_paths:
            path_to_key_updates.append((path, key))
            collapsed_matched = True
            break'''
    if not collapsed_matched:
        path_to_key_updates.append((path, parts[-1].split("[")[0]))

# Apply updates outside the loop to avoid RuntimeError
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

# Create StringIO buffer to capture print output
buffer = io.StringIO()
original_stdout = sys.stdout
sys.stdout = buffer  # Redirect print to buffer

# Filter paths based on flexible LHS condition
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

# Restore standard output
sys.stdout = original_stdout
output_file_path = "result" + mode + "/" + target + "_js_result.txt"
with open(output_file_path, "w", encoding="utf-8") as f_out:
    for path in sorted(final_paths):
        f_out.write(path + "\n")

print(f"[✓] Result JSON key paths written to: {output_file_path}")
