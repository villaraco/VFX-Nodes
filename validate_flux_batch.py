"""
VFX Flux Batch — unit tests
============================
Prueba el parser de markdown y el nodo VFXFluxBatchPrompts.
No requiere ComfyUI corriendo.
"""

from __future__ import annotations

import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE))

from flux_batch import VFXFluxBatchPrompts, _parse_flux2_md, DEFAULT_NEGATIVE  # noqa: E402

PROMPTS_FILE = "E:/OpenCode/Proyecto-LAB/MIOPIA-HELP/prompts-flux2-totie.md"


def test_parser():
    """Verify the markdown parser extracts valid prompts."""
    prompts = _parse_flux2_md(PROMPTS_FILE)
    assert len(prompts) > 0, "No prompts parsed"
    assert len(prompts) < 110, f"Too many prompts: {len(prompts)} (expected ~95)"

    for p in prompts:
        assert isinstance(p["number"], int), f"Bad number: {p}"
        assert p["name"], f"Empty name: {p}"
        assert p["prompt"], f"Empty prompt: {p}"
        assert "[VIDEO" not in p["prompt"], f"VIDEO entry leaked: {p}"

    first = prompts[0]
    assert first["number"] == 1, f"First number: {first['number']}"
    assert "Totie" in first["name"], f"First name: {first['name']}"
    assert "studio product photography" in first["prompt"].lower()

    print(f"  [OK] Parser: {len(prompts)} prompts parsed, all valid")
    return len(prompts)


def test_node_output(total_prompts: int):
    """Verify VFXFluxBatchPrompts outputs correct values."""
    node = VFXFluxBatchPrompts()

    r = node.get_prompt(
        file_path=PROMPTS_FILE,
        prompt_index=0,
        variation=0,
        variations=5,
        base_seed=42,
        auto_queue=False,
    )

    data = r["result"]
    assert data[0].startswith("studio product photography"), f"Bad prompt: {data[0][:50]}"
    assert data[1] == DEFAULT_NEGATIVE, "Negative prompt mismatch"
    assert data[2] == 42, f"Bad seed: {data[2]}"
    assert "Totie" in data[3], f"Bad piece_name: {data[3]}"
    assert data[4] == 1, f"Bad piece_number: {data[4]}"
    assert data[5] == total_prompts, f"Bad total_prompts: {data[5]}"
    assert "PDM" in data[6], f"Bad section: {data[6]}"
    filename = data[7]
    assert "001" in filename, f"Bad filename_prefix: {filename}"
    assert "seed42" in filename, f"Bad filename_prefix: {filename}"

    print(f"  [OK] Node output (idx=0, var=0): #{data[4]} {data[3]} | seed={data[2]} | {data[5]} total | file={filename}")

    # Check UI metadata
    ui = r["ui"]
    assert ui.get("batch_total") == [total_prompts], f"Bad batch_total: {ui.get('batch_total')}"
    assert ui.get("batch_variations") == [5], f"Bad batch_variations: {ui.get('batch_variations')}"
    assert "AUTO-QUEUE" not in str(ui.get("vfx_info")), "auto_queue label should not appear when disabled"

    # With auto_queue=True
    r2 = node.get_prompt(
        file_path=PROMPTS_FILE,
        prompt_index=0,
        variation=0,
        variations=5,
        base_seed=42,
        auto_queue=True,
    )
    assert "AUTO-QUEUE ON" in r2["ui"]["vfx_info"][-1], "auto_queue label missing"
    print(f"  [OK] UI metadata: batch_total={ui['batch_total']}, batch_variations={ui['batch_variations']}")

    # Second prompt
    r = node.get_prompt(
        file_path=PROMPTS_FILE,
        prompt_index=1,
        variation=2,
        variations=5,
        base_seed=42,
        auto_queue=False,
    )
    data = r["result"]
    expected_seed = 42 + 1 * 5 + 2
    assert data[2] == expected_seed, f"Bad seed: {data[2]} != {expected_seed}"
    assert data[4] == 2, f"Bad piece_number: {data[4]}"
    print(f"  [OK] Node output (idx=1, var=2): #{data[4]} {data[3]} | seed={data[2]}")

    # Wrap-around
    r = node.get_prompt(
        file_path=PROMPTS_FILE,
        prompt_index=total_prompts + 5,
        variation=0,
        variations=5,
        base_seed=42,
        auto_queue=False,
    )
    assert r["result"][4] == 6, f"Wrap-around failed: got #{r['result'][4]}"
    print(f"  [OK] Wrap-around (idx={total_prompts + 5}): #{r['result'][4]} {r['result'][3]}")


def test_seed_formula():
    """Verify seed = base_seed + prompt_index * variations + variation."""
    node = VFXFluxBatchPrompts()
    for pi in [0, 0, 1, 2, 10]:
        for v in [0, 2, 4]:
            r = node.get_prompt(
                file_path=PROMPTS_FILE,
                prompt_index=pi, variation=v,
                variations=5, base_seed=42, auto_queue=False,
            )
            expected = 42 + pi * 5 + v
            assert r["result"][2] == expected, f"Seed mismatch: idx={pi} var={v}"
    print(f"  [OK] Seed formula correct for all tested combinations")


def test_empty_file():
    """Graceful handling of missing file."""
    node = VFXFluxBatchPrompts()
    r = node.get_prompt(
        file_path="nonexistent_file.md",
        prompt_index=0, variation=0, variations=5, base_seed=42,
        auto_queue=False,
    )
    assert r["result"][0] == "", "Expected empty prompt"
    assert r["result"][5] == 0, "Expected 0 total"
    assert r["result"][7] == "", "Expected empty filename"
    print(f"  [OK] Empty file: returns empty prompt, total=0")


def test_filename_prefix():
    """Verify filename_prefix format."""
    node = VFXFluxBatchPrompts()
    r = node.get_prompt(
        file_path=PROMPTS_FILE,
        prompt_index=0, variation=0, variations=5, base_seed=42,
        auto_queue=False,
    )
    filename = r["result"][7]
    # Should be: "001_Totie_gesto_OK_seed42"
    assert filename.startswith("001_"), f"Bad prefix: {filename}"
    assert "Totie_gesto_OK" in filename, f"Name not in filename: {filename}"
    assert "seed42" in filename, f"Seed not in filename: {filename}"
    assert ":" not in filename, f"Invalid chars: {filename}"
    print(f"  [OK] filename_prefix: {filename}")


def test_suffix_and_anatomy():
    """Verify prompt_suffix concatenation and anatomy negative prompt."""
    node = VFXFluxBatchPrompts()
    from flux_batch import DEFAULT_NEGATIVE as neg

    # Anatomy terms in negative
    assert "visible legs" in neg, "Missing anatomy term in negative"
    assert "paws separated from body" in neg, "Missing anatomy term in negative"
    print("  [OK] Anatomy terms present in DEFAULT_NEGATIVE")

    # Without suffix (empty string)
    r = node.get_prompt(
        file_path=PROMPTS_FILE,
        prompt_index=0, variation=0, variations=5, base_seed=42,
        auto_queue=False, prompt_suffix="",
    )
    data = r["result"]
    assert data[0] == _parse_flux2_md(PROMPTS_FILE)[0]["prompt"], "Empty suffix should not modify prompt"
    assert "[suffix" not in str(r["ui"]["vfx_info"]), "No suffix indicator when empty"
    print("  [OK] Empty suffix: prompt unchanged, no indicator")

    # With suffix
    test_suffix = "tack sharp, vibrant colors, studio lighting"
    r = node.get_prompt(
        file_path=PROMPTS_FILE,
        prompt_index=0, variation=0, variations=5, base_seed=42,
        auto_queue=False, prompt_suffix=test_suffix,
    )
    data = r["result"]
    assert data[0].endswith(test_suffix), f"Suffix not appended: {data[0][-50:]}"
    assert data[0].startswith("studio product photography"), f"Prompt start lost: {data[0][:50]}"
    assert "[suffix" in str(r["ui"]["vfx_info"]), "Suffix indicator missing in vfx_info"
    print(f"  [OK] Suffix appended correctly, indicator shown")

    # Suffix with extra whitespace (stripped)
    r = node.get_prompt(
        file_path=PROMPTS_FILE,
        prompt_index=0, variation=0, variations=5, base_seed=42,
        auto_queue=False, prompt_suffix="  tack sharp  ",
    )
    assert r["result"][0].endswith("tack sharp"), f"Whitespace not stripped: {r['result'][0][-20:]}"
    print("  [OK] Suffix whitespace stripped correctly")


def main():
    print("=" * 50)
    print("VFX Flux Batch — Unit Tests")
    print("=" * 50)
    print()

    failures = 0
    total = _parse_flux2_md(PROMPTS_FILE)
    total_count = len(total)

    tests = [
        ("Parser", test_parser),
        ("Node output + UI metadata", lambda: test_node_output(total_count)),
        ("Seed formula", test_seed_formula),
        ("Empty file", test_empty_file),
        ("filename_prefix", test_filename_prefix),
        ("Suffix + anatomy", test_suffix_and_anatomy),
    ]

    for name, fn in tests:
        try:
            fn()
        except Exception as e:
            print(f"  [FAIL] {name}: {e}")
            failures += 1

    print()
    print("=" * 50)
    if failures == 0:
        print("ALL TESTS PASSED")
    else:
        print(f"{failures} TEST(S) FAILED")
    print("=" * 50)
    return failures


if __name__ == "__main__":
    sys.exit(main())
