"""
VFX Flux Batch — CLI Queue Script
=================================
Encola todas las combinaciones prompt x variacion via ComfyUI API.

Uso
---
    python queue_flux_batch.py workflow.json
    python queue_flux_batch.py workflow.json --dry-run
    python queue_flux_batch.py workflow.json --start-index 10 --start-variation 2
"""

from __future__ import annotations

import argparse
import copy
import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE))

from flux_batch import _parse_flux2_md  # noqa: E402


# ============================================================================
# Workflow format conversion (saved → API)
# ============================================================================

def convert_to_api(workflow: dict) -> dict:
    """Convert saved workflow format to ComfyUI /prompt API format.

    Saved format (v0.27.0):
        {"nodes": [{id, type, widgets_values, ...}], "links": [[...], ...], ...}

    API format:
        {"16": {"class_type": "CLIPTextEncode", "inputs": {...}}, ...}
    """
    nodes_array = workflow.get("nodes", [])
    links = workflow.get("links", [])

    # Step 1: build node_id → {class_type, inputs} dict
    api = {}
    node_type_map = {}  # node_id → node type name

    for nd in nodes_array:
        if not isinstance(nd, dict):
            continue
        nid = str(nd.get("id", ""))
        nt = nd.get("type", nd.get("class_type", ""))
        node_type_map[nid] = nt
        api[nid] = {"class_type": nt, "inputs": {}}

    # Step 2: populate widgets_values as named inputs
    for nd in nodes_array:
        if not isinstance(nd, dict):
            continue
        nid = str(nd.get("id", ""))
        nt = nd.get("type", nd.get("class_type", ""))
        wv = nd.get("widgets_values", [])
        if nid not in api:
            continue
        inputs = api[nid]["inputs"]
        _set_widget_inputs(nt, wv, inputs)

    # Step 3: apply links (connections between nodes)
    for link in links:
        if not isinstance(link, list) or len(link) < 6:
            continue
        _, from_id, from_slot, to_id, to_slot, _link_type = link[:6]
        from_id = str(from_id)
        to_id = str(to_id)
        if to_id not in api:
            continue
        nt = node_type_map.get(to_id, "")
        slot_name = _input_slot_name(nt, to_slot)
        if slot_name:
            api[to_id]["inputs"][slot_name] = [from_id, from_slot]

    # Step 4: remove empty inputs
    for nd in api.values():
        nd["inputs"] = {k: v for k, v in nd.get("inputs", {}).items() if v not in ("", None)}

    return api


# Known node I/O mappings (in INPUT_TYPES order)
_NODE_INPUTS: dict[str, list[str]] = {
    "VFXFluxBatchPrompts": ["file_path", "prompt_index", "variation", "variations", "base_seed"],
    "VFXPrepareResolution": ["image", "model_preset", "downscale_method", "pad_mode", "quality"],
    "VFXRestoreResolution": ["image", "orig_width", "orig_height", "scale_factor", "model_width", "model_height", "upscale_method", "external_upscale"],
    "VFXFitDimension": ["image", "target_width", "target_height", "method"],
    "VFXFramePad": ["image", "mode", "frames"],
    "CLIPTextEncode": ["clip", "text"],
    "EmptyLatentImage": ["width", "height", "batch_size"],
    "KSampler": ["model", "seed", "steps", "cfg", "sampler_name", "scheduler", "positive", "negative", "latent_image", "denoise"],
    "VAEDecode": ["samples", "vae"],
    "VAEEncode": ["pixels", "vae"],
    "SaveImage": ["images", "filename_prefix"],
    "LoadImage": ["image"],
}


def _set_widget_inputs(node_type: str, widgets_values: list, inputs: dict):
    """Populate inputs dict from widgets_values array."""
    names = _NODE_INPUTS.get(node_type)
    if not names:
        return
    for i, name in enumerate(names):
        if i < len(widgets_values) and name not in inputs:
            inputs[name] = widgets_values[i]


def _input_slot_name(node_type: str, slot: int) -> str | None:
    """Return the input name for a given slot index."""
    names = _NODE_INPUTS.get(node_type)
    if names and slot < len(names):
        return names[slot]
    return None


# ============================================================================
# API
# ============================================================================

def queue_prompt(prompt_workflow: dict, server: str = "127.0.0.1:8188") -> str | None:
    """Queue a workflow via ComfyUI API. Returns prompt_id or None."""
    payload = {"prompt": prompt_workflow, "client_id": "vfx-flux-batch"}
    data = json.dumps(payload).encode("utf-8")
    url = f"http://{server}/prompt"
    try:
        req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            result = json.loads(resp.read().decode("utf-8"))
            pid = result.get("prompt_id")
            if pid:
                return pid
            print(f"  [WARN] Unexpected response: {result}")
            return None
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        print(f"  [ERROR] HTTP {e.code}: {body[:200]}")
        return None
    except Exception as e:
        print(f"  [ERROR] {e}")
        return None


# ============================================================================
# Main
# ============================================================================

def main():
    parser = argparse.ArgumentParser(description="Queue Flux2 prompt variations via ComfyUI API.")
    parser.add_argument("workflow", help="Path to ComfyUI workflow JSON file.")
    parser.add_argument("--prompts-file", default="E:\\OpenCode\\Proyecto-LAB\\MIOPIA-HELP\\prompts-flux2-totie.md")
    parser.add_argument("--base-seed", type=int, default=42)
    parser.add_argument("--variations", type=int, default=5)
    parser.add_argument("--server", default="127.0.0.1:8188")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--delay", type=float, default=0.1)
    parser.add_argument("--start-index", type=int, default=0)
    parser.add_argument("--start-variation", type=int, default=0)
    args = parser.parse_args()

    prompts = _parse_flux2_md(args.prompts_file)
    if not prompts:
        print(f"[ERROR] No prompts found in: {args.prompts_file}")
        return 1

    total_prompts = len(prompts)
    total_combos = total_prompts * args.variations
    print(f"File:        {args.prompts_file}")
    print(f"Prompts:     {total_prompts}")
    print(f"Variations:  {args.variations}")
    print(f"Base seed:   {args.base_seed}")
    print(f"Total jobs:  {total_combos}")
    print()

    # Load saved workflow
    try:
        with open(args.workflow, "r", encoding="utf-8") as f:
            saved = json.load(f)
    except Exception as e:
        print(f"[ERROR] Failed to load workflow: {e}")
        return 1

    # Find VFXFluxBatchPrompts node — handles both saved and API formats
    nodes_array = saved.get("nodes")
    flux_id = None

    if isinstance(nodes_array, list):
        # Saved format: nodes as array with widgets_values
        for nd in nodes_array:
            if isinstance(nd, dict) and nd.get("type", "") == "VFXFluxBatchPrompts":
                flux_id = str(nd.get("id", ""))
                wv = nd.get("widgets_values", [])
                if len(wv) >= 1:
                    wv[0] = args.prompts_file
                if len(wv) >= 4:
                    wv[3] = args.variations
                if len(wv) >= 5:
                    wv[4] = args.base_seed

                def update_indices(idx, var):
                    if len(wv) >= 2:
                        wv[1] = idx
                    if len(wv) >= 3:
                        wv[2] = var
                break
    else:
        # API format: dict of {node_id: {class_type, inputs}}
        for nid, nd in saved.items():
            if not isinstance(nd, dict):
                continue
            if nd.get("class_type", "") == "VFXFluxBatchPrompts":
                flux_id = str(nid)
                inputs = nd.setdefault("inputs", {})
                inputs["file_path"] = args.prompts_file
                inputs["base_seed"] = args.base_seed
                inputs["variations"] = args.variations

                def update_indices(idx, var):
                    inputs["prompt_index"] = idx
                    inputs["variation"] = var
                break

    if not flux_id:
        print("[ERROR] VFXFluxBatchPrompts node not found in workflow.")
        return 1

    # For saved format, convert to API; for API format, use as-is
    if isinstance(nodes_array, list):
        api_wf = convert_to_api(saved)
    else:
        api_wf = saved

    print(f"Starting from index={args.start_index}, variation={args.start_variation}")
    print()

    count = 0
    skipped = 0

    for prompt_idx in range(args.start_index, total_prompts):
        entry = prompts[prompt_idx]
        start_var = args.start_variation if prompt_idx == args.start_index else 0

        for var in range(start_var, args.variations):
            seed = args.base_seed + prompt_idx * args.variations + var
            update_indices(prompt_idx, var)

            label = f"#{entry['number']} {entry['name'][:40]}"
            print(f"  [{count + 1}/{total_combos}] seed={seed}  {label}  (idx={prompt_idx}, var={var})")

            if not args.dry_run:
                # For saved format, reconvert (widgets_values changed); for API, use in-place
                wf = convert_to_api(saved) if isinstance(nodes_array, list) else api_wf
                pid = queue_prompt(wf, args.server)
                if pid:
                    print(f"           -> queued: {pid}")
                    count += 1
                else:
                    skipped += 1
                time.sleep(args.delay)
            else:
                count += 1

    print()
    print(f"Done. Queued: {count}, Skipped: {skipped}")
    return 0 if skipped == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
