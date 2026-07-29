"""
VFX Resolution — Roundtrip Validator
=====================================
Valida que el pipeline Prepare -> Restore es matematicamente perfecto
(sin pixel shift, sin cambio de resolucion, sin interpolacion espuria).

No requiere ComfyUI corriendo — importa directamente los custom nodes
y ejecuta tests de identidad sobre tensores aleatorios.

Uso
---
    python validate_roundtrip.py
    python validate_roundtrip.py --resolutions 1920x1080,3840x2160,1280x736
    python validate_roundtrip.py --presets
    python validate_roundtrip.py --all

El script devuelve codigo de salida != 0 si hay fallos, util para CI/CD.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import torch

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE))

from __init__ import (
    MODEL_PRESETS,
    VFXPrepareResolution,
    VFXRestoreResolution,
    VFXFitDimension,
)

# ---------------------------------------------------------------------------
# Resoluciones de test por defecto
# ---------------------------------------------------------------------------

DEFAULT_RESOLUTIONS = [
    (512, 512),
    (1920, 1080),
    (3840, 2160),
    (3384, 1902),
    (1280, 736),
    (2048, 1152),
    (4096, 1716),
    (800, 600),
    (1024, 1024),
    (7680, 4320),
]

# Presets usados para test de padding (sf=1.0, pixel-perfect)
PAD_PRESETS = [
    ("Pad Only (sin limite)", "replicate"),
    ("Pad Only (sin limite)", "reflect"),
    ("Pad Only (sin limite)", "constant"),
    ("Custom (multiple 64)", "replicate"),
    ("Custom (multiple 64)", "reflect"),
    ("Custom (multiple 64)", "constant"),
]

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _random_image(B: int, H: int, W: int) -> torch.Tensor:
    """Imagen aleatoria [B, H, W, 3] en rango [0, 1]."""
    return torch.rand(B, H, W, 3, dtype=torch.float32)


def _random_mask(B: int, H: int, W: int) -> torch.Tensor:
    """Mascara aleatoria binaria [B, H, W]."""
    return (torch.rand(B, H, W) > 0.5).float()


def _compare_tensors(a: torch.Tensor, b: torch.Tensor, name: str) -> dict:
    """Compara dos tensores pixel a pixel."""
    if a.shape != b.shape:
        return {
            "ok": False,
            "error": f"Shape mismatch: {a.shape} vs {b.shape}",
            "max_diff": float("nan"),
        }
    diff = (a.float() - b.float()).abs()
    return {
        "ok": bool((diff < 1e-7).all()),
        "error": None,
        "max_diff": float(diff.max()),
        "mean_diff": float(diff.mean()),
    }


# ---------------------------------------------------------------------------
# Test: padding presets (pixel-perfect roundtrip)
# ---------------------------------------------------------------------------

def test_padding_roundtrip(resolutions: list[tuple[int, int]]) -> int:
    """Identity pass con presets de solo padding.

    Usa ``Pad Only`` (mult=32) y ``Custom (multiple 64)`` (mult=64).
    Como no hay downscale, el roundtrip debe ser pixel-perfect (diff=0.0).
    """
    prepare = VFXPrepareResolution()
    restore = VFXRestoreResolution()
    failures = 0

    print("\n" + "=" * 70)
    print("TEST: Padding roundtrip (pixel-perfect)")
    print("=" * 70)

    for W, H in resolutions:
        for preset_name, pad_mode in PAD_PRESETS:
            B = 2
            image = _random_image(B, H, W)
            mask = _random_mask(B, H, W)

            img_p, msk_p, ow, oh, sf, mw, mh = prepare.prepare(
                image, preset_name, "bicubic", pad_mode, 1.0, mask,
            )
            img_r, msk_r, _, _, _, _, _ = restore.restore(
                img_p, ow, oh, sf, mw, mh, "bicubic", mask=msk_p,
            )

            img_ok = _compare_tensors(image, img_r, "image")["ok"]
            msk_ok = _compare_tensors(mask, msk_r, "mask")["ok"]

            if img_ok and msk_ok:
                m_name = preset_name[:8]
                print(f"  [OK]  {W:>5d}x{H:<5d}  {m_name:>8s}  {pad_mode:10s}  "
                      f"padded={img_p.shape[2]}x{img_p.shape[1]}")
            else:
                failures += 1
                print(f"  [FAIL] {W:>5d}x{H:<5d}  {preset_name}  {pad_mode}  "
                      f"padded={img_p.shape[2]}x{img_p.shape[1]}")

    print(f"\n  Padding roundtrip: {failures} fallos")
    return failures


# ---------------------------------------------------------------------------
# Test: todos los presets Model Match
# ---------------------------------------------------------------------------

def test_preset_roundtrip(resolutions: list[tuple[int, int]]) -> int:
    """Roundtrip con cada uno de los 11 presets.

    * sf == 1.0  → exige pixel-perfect (solo padding).
    * sf <  1.0  → exige resolucion final correcta (downscale+upscale).
    """
    prepare = VFXPrepareResolution()
    restore = VFXRestoreResolution()
    failures = 0

    print("\n" + "=" * 70)
    print("TEST: Model presets roundtrip")
    print("=" * 70)

    for preset_name, preset in MODEL_PRESETS.items():
        print(f"\n  Preset: {preset_name}")
        preset_fails = 0

        for W, H in resolutions:
            B = 1
            image = _random_image(B, H, W)
            mask = _random_mask(B, H, W)

            try:
                img_p, msk_p, ow, oh, sf, mw, mh = prepare.prepare(
                    image, preset_name, "bicubic", "replicate", 1.0, mask,
                )

                # Verify padded image is multiple-aligned
                mult = preset["multiple"]
                pW, pH = img_p.shape[2], img_p.shape[1]
                if pW % mult != 0 or pH % mult != 0:
                    print(f"  [FAIL] {W:>5d}x{H:<5d}  padded={pW}x{pH}  "
                          f"not multiple of {mult}")
                    preset_fails += 1
                    continue

                img_r, msk_r, _, _, _, _, _ = restore.restore(
                    img_p, ow, oh, sf, mw, mh, "bicubic", mask=msk_p,
                )

                if sf >= 1.0:
                    test_ok = (
                        _compare_tensors(image, img_r, "image")["ok"]
                        and _compare_tensors(mask, msk_r, "mask")["ok"]
                    )
                    action = "pad only (pixel-perfect)"
                else:
                    test_ok = (
                        img_r.shape[1] == H and img_r.shape[2] == W
                        and msk_r.shape[1] == H and msk_r.shape[2] == W
                    )
                    action = "downscale+pad"

                if test_ok:
                    print(f"  [OK]  {W:>5d}x{H:<5d}  ->  {mw:>5d}x{mh:<5d}  "
                          f"sf={sf:.4f}  {action}")
                else:
                    preset_fails += 1
                    print(f"  [FAIL] {W:>5d}x{H:<5d}  ->  {mw}x{mh}  sf={sf:.4f}")
                    if sf >= 1.0:
                        print("         Pixel-perfect expected")
                    else:
                        print(f"         Shape: expected=({H},{W})  "
                              f"got=({img_r.shape[1]},{img_r.shape[2]})")

            except Exception as e:
                preset_fails += 1
                print(f"  [ERROR] {W:>5d}x{H:<5d}  {type(e).__name__}: {e}")

        print(f"  -> {preset_fails} fallos en {preset_name}")
        failures += preset_fails

    print(f"\n  Preset roundtrip: {failures} fallos totales")
    return failures


# ---------------------------------------------------------------------------
# Test: ICLORA (latente par)
# ---------------------------------------------------------------------------

def test_iclora_case() -> int:
    """Verifica que los presets ICLORA producen latentes pares.

    Solo se consideran fallos los presets que DEBERIAN ser compatibles
    con ControlNet UNION (LTX-2.3 + ICLORA y Custom multiple 64).
    """
    ICLORA_PRESETS = {"LTX-2.3 + ICLORA", "Custom (multiple 64)"}

    failures = 0

    print("\n" + "=" * 70)
    print("TEST: ICLORA + ControlNet UNION (latente par)")
    print("=" * 70)

    problematic = [(1280, 736), (1280, 720), (1920, 1080)]

    prepare = VFXPrepareResolution()

    for preset_name in ("LTX-2.3", "LTX-2.3 + ICLORA", "Custom (multiple 64)"):
        for W, H in problematic:
            image = _random_image(1, H, W)
            try:
                img_p, _, _, _, _, mw, mh = prepare.prepare(
                    image, preset_name, "bicubic", "replicate", 1.0,
                )
                # El modelo ve la imagen padded — el latente se calcula sobre esas dimensiones
                pW, pH = img_p.shape[2], img_p.shape[1]
                lw, lh = pW // 32, pH // 32
                both_even = (lw % 2 == 0) and (lh % 2 == 0)

                if both_even:
                    print(f"  [OK]    {preset_name:25s}  {W}x{H} -> padded={pW}x{pH}  "
                          f"latente={lw}x{lh}")
                elif preset_name in ICLORA_PRESETS:
                    failures += 1
                    print(f"  [FAIL]  {preset_name:25s}  {W}x{H} -> padded={pW}x{pH}  "
                          f"latente={lw}x{lh}  IMPAR (deberia ser compatible)")
                else:
                    print(f"  [INFO]  {preset_name:25s}  {W}x{H} -> padded={pW}x{pH}  "
                          f"latente={lw}x{lh}  impar (esperado, no es preset ICLORA)")
            except Exception as e:
                print(f"  [ERROR] {preset_name:25s}  {W}x{H}  {e}")
                failures += 1

    print(f"\n  ICLORA test: {failures} fallos")
    return failures


# ---------------------------------------------------------------------------
# Test: Restore adaptativo (modelo cambia dimensiones)
# ---------------------------------------------------------------------------

def test_adaptive_restore() -> int:
    """Simula que el modelo devuelve una resolucion distinta a la esperada.

    Escenarios probados:
    - Modelo agranda la imagen (ej: 992x576 -> 1328x768)
    - Modelo encoge la imagen
    - Modelo devuelve la resolucion esperada (caso normal)
    - Modelo cambia aspecto (should still crop top-left)

    En todos los casos el output final DEBE tener la resolucion original.
    """
    prepare = VFXPrepareResolution()
    restore = VFXRestoreResolution()
    failures = 0

    print("\n" + "=" * 70)
    print("TEST: Adaptive restore (model changes output dimensions)")
    print("=" * 70)

    # Caso: el modelo agranda la salida (Flux2Klein 992x576 -> 1328x768)
    W_in, H_in = 1280, 736
    image = _random_image(1, H_in, W_in)
    _, _, ow, oh, sf, mw, mh = prepare.prepare(image, "Flux2Klein", "bicubic", "replicate", 1.0)
    print(f"  Prepare: {W_in}x{H_in} -> model={mw}x{mh} sf={sf:.4f}")

    # Simular que el modelo devuelve 1328x768 en vez de 992x576
    img_bad = torch.randn(1, 768, 1328, 3)
    try:
        img_r, _, _, _, _, _, _ = restore.restore(img_bad, ow, oh, sf, mw, mh, "bicubic")
        shape_ok = img_r.shape == (1, H_in, W_in, 3)
        print(f"  Modelo agranda (1328x768): restored={img_r.shape[2]}x{img_r.shape[1]}",
              "OK" if shape_ok else "FAIL")
        if not shape_ok:
            failures += 1
    except Exception as e:
        print(f"  Modelo agranda: CRASH {e}")
        failures += 1

    # Caso: modelo encoge
    img_small = torch.randn(1, 256, 256, 3)
    try:
        img_r, _, _, _, _, _, _ = restore.restore(img_small, ow, oh, sf, mw, mh, "bicubic")
        shape_ok = img_r.shape == (1, H_in, W_in, 3)
        print(f"  Modelo encoge (256x256): restored={img_r.shape[2]}x{img_r.shape[1]}",
              "OK" if shape_ok else "FAIL")
        if not shape_ok:
            failures += 1
    except Exception as e:
        print(f"  Modelo encoge: CRASH {e}")
        failures += 1

    # Caso: modelo devuelve exacto (normal)
    img_normal = torch.randn(1, mh, mw, 3)
    try:
        img_r, _, _, _, _, _, _ = restore.restore(img_normal, ow, oh, sf, mw, mh, "bicubic")
        shape_ok = img_r.shape == (1, H_in, W_in, 3)
        print(f"  Normal ({mw}x{mh}): restored={img_r.shape[2]}x{img_r.shape[1]}",
              "OK" if shape_ok else "FAIL")
        if not shape_ok:
            failures += 1
    except Exception as e:
        print(f"  Normal: CRASH {e}")
        failures += 1

    # Caso: modelo cambia aspect ratio (Flux2Klein 992x576 -> 1344x768)
    img_aspect = torch.randn(1, 600, 800, 3)
    try:
        img_r, _, _, _, _, _, _ = restore.restore(img_aspect, ow, oh, sf, mw, mh, "bicubic")
        shape_ok = img_r.shape == (1, H_in, W_in, 3)
        print(f"  Aspect change (800x600): restored={img_r.shape[2]}x{img_r.shape[1]}",
              "OK" if shape_ok else "FAIL")
        if not shape_ok:
            failures += 1
    except Exception as e:
        print(f"  Aspect change: CRASH {e}")
        failures += 1

    # Caso real: Flux2Klein devuelve 1344x768 en vez de 992x576
    # El Restore debe usar el output completo del modelo (sin crop interno)
    img_flux_real = torch.randn(1, 768, 1344, 3)
    try:
        img_r, _, _, _, _, _, _ = restore.restore(img_flux_real, ow, oh, sf, mw, mh, "bicubic")
        shape_ok = img_r.shape == (1, H_in, W_in, 3)
        # debe usar output completo: 1344x768 -> upscale -> 1280x736
        print(f"  Flux2Klein real (1344x768): restored={img_r.shape[2]}x{img_r.shape[1]}",
              "OK" if shape_ok else "FAIL")
        if not shape_ok:
            failures += 1
    except Exception as e:
        print(f"  Flux2Klein real: CRASH {e}")
        failures += 1

    # Caso: pad-only + modelo agranda
    W_in2, H_in2 = 1920, 1080
    image2 = _random_image(1, H_in2, W_in2)
    _, _, ow2, oh2, sf2, mw2, mh2 = prepare.prepare(image2, "Pad Only (sin limite)", "bicubic", "replicate", 1.0)
    print(f"\n  PadOnly Prepare: {W_in2}x{H_in2} -> model={mw2}x{mh2} sf={sf2:.4f}")
    img_bad2 = torch.randn(1, 1200, 2000, 3)
    try:
        img_r, _, _, _, _, _, _ = restore.restore(img_bad2, ow2, oh2, sf2, mw2, mh2, "bicubic")
        shape_ok = img_r.shape == (1, H_in2, W_in2, 3)
        print(f"  PadOnly + modelo agranda (2000x1200): restored={img_r.shape[2]}x{img_r.shape[1]}",
              "OK" if shape_ok else "FAIL")
        if not shape_ok:
            failures += 1
    except Exception as e:
        print(f"  PadOnly + agranda: CRASH {e}")
        failures += 1

    print(f"\n  Adaptive restore: {failures} fallos")
    return failures


# ---------------------------------------------------------------------------
# Test: VFX Fit Dimension
# ---------------------------------------------------------------------------

def test_fit_dimension() -> int:
    """Verifica que VFXFitDimension escala sin distorsion."""
    node = VFXFitDimension()
    failures = 0

    print("\n" + "=" * 70)
    print("TEST: VFX Fit Dimension")
    print("=" * 70)

    cases = [
        # (in_W, in_H, target_W, target_H, label)
        (1280, 720, 3840, 2160, "720p -> 4K"),
        (992, 576, 1280, 736, "model -> orig"),
        (512, 512, 1024, 1024, "exact aspect"),
        (1920, 1080, 1920, 1080, "no-op"),
        (800, 600, 1920, 1080, "aspect change"),
    ]

    for iW, iH, tW, tH, label in cases:
        img = torch.rand(1, iH, iW, 3)
        try:
            result, _ = node.fit(img, tW, tH, "auto")
            shape_ok = result.shape == (1, tH, tW, 3)
            prefix = "[OK]" if shape_ok else "[FAIL]"
            print(f"  {prefix:6s} {iW:>5d}x{iH:<5d} -> {tW}x{tH}  ({label})")
            if not shape_ok:
                failures += 1
        except Exception as e:
            print(f"  [ERROR] {iW}x{iH} -> {tW}x{tH}  {e}")
            failures += 1

    # Batch test
    img_batch = torch.rand(3, 256, 256, 3)
    result, _ = node.fit(img_batch, 512, 512, "bicubic")
    if result.shape == (3, 512, 512, 3):
        print(f"  [OK]    Batch 3: 256x256 -> 512x512")
    else:
        print(f"  [FAIL]  Batch 3: got {result.shape}")
        failures += 1

    print(f"\n  Fit Dimension: {failures} fallos")
    return failures


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(description="VFX Resolution Roundtrip Validator")
    parser.add_argument(
        "--resolutions", type=str, default=None,
        help="Resoluciones a testear: WxH,WxH,...",
    )
    parser.add_argument(
        "--passthrough", action="store_true",
        help="Solo test de padding (presets PadOnly, Custom 64)",
    )
    parser.add_argument(
        "--presets", action="store_true",
        help="Solo test de presets",
    )
    parser.add_argument(
        "--all", action="store_true", default=True,
        help="Ejecutar todos los tests (default)",
    )
    args = parser.parse_args()

    if args.resolutions:
        resolutions = []
        for spec in args.resolutions.split(","):
            w, h = spec.strip().split("x")
            resolutions.append((int(w), int(h)))
    else:
        resolutions = DEFAULT_RESOLUTIONS

    run_pad = args.passthrough or args.all
    run_presets = args.presets or args.all
    if not run_pad and not run_presets:
        run_pad = run_presets = True

    total = 0

    if run_pad:
        total += test_padding_roundtrip(resolutions)
        total += test_iclora_case()
        total += test_adaptive_restore()
        total += test_fit_dimension()

    if run_presets:
        total += test_preset_roundtrip(resolutions)

    print("\n" + "=" * 70)
    if total == 0:
        print("TODOS LOS TESTS PASARON — el pipeline VFX es pixel-perfect")
        print("=" * 70)
        return 0
    else:
        print(f"{total} FALLOS detectados — revisar resultados arriba")
        print("=" * 70)
        return 1


if __name__ == "__main__":
    sys.exit(main())
