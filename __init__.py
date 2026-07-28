"""
VFX Resolution Pipeline Nodes for ComfyUI
==========================================
Pixel-perfect roundtrip resolution for VFX workflows.

Two nodes that decide automatically whether the input fits the model's
working area or needs downscaling first:

  1. VFX Resolution (Prepare) -- pad or downscale+pad
  2. VFX Resolution (Restore) -- crop or crop+upscale

The decision is driven by the ``model_preset`` dropdown.  If the input
area is within the preset's ``max_area``, only asymmetric padding
(right + bottom) is applied (pixel-perfect).  Otherwise the image is
downscaled to fit, padded, and later upscaled back to the original
resolution.
"""

from __future__ import annotations

import torch
import torch.nn.functional as F


# ============================================================================
# Helpers
# ============================================================================

def _normalize_mask(mask: torch.Tensor, target_batch: int) -> torch.Tensor:
    """Ensure mask has shape [B, H, W] and matches target batch count."""
    if mask.dim() == 2:
        mask = mask.unsqueeze(0)
    if mask.shape[0] != target_batch:
        mask = mask.expand(target_batch, -1, -1)
    return mask.to(dtype=torch.float32)


def _fit_area(W: int, H: int, max_area: int | None, multiple: int) -> tuple[int, int, float]:
    """Return (new_W, new_H, scale_factor) to fit within max_area.

    Preserves aspect ratio.  Rounds both dimensions to the nearest
    multiple.  When max_area is None or the input already fits,
    scale_factor is 1.0.
    """
    if max_area is None or W * H <= max_area:
        return W, H, 1.0

    aspect = W / H
    scale = (max_area / (W * H)) ** 0.5
    target_H = max(multiple, round(H * scale / multiple) * multiple)
    target_W = max(multiple, round(target_H * aspect / multiple) * multiple)

    # Clamp if we overshot the area budget by more than 5 %
    if target_W * target_H > int(max_area * 1.05):
        target_W = max(multiple, round((target_W * 0.95) / multiple) * multiple)

    scale_factor = target_W / W
    return target_W, target_H, scale_factor


def _resample(tensor_4d: torch.Tensor, out_H: int, out_W: int, mode: str) -> torch.Tensor:
    """Resample [B, C, H, W] tensor to (out_H, out_W).

    mode ``auto`` uses area for downscale, bicubic for upscale.
    Skips filtering entirely when dimensions are within 5% (no-op).
    """
    _, _, H, W = tensor_4d.shape

    # No-op if dimensions are close enough
    if abs(out_H - H) <= max(1, int(H * 0.05)) and abs(out_W - W) <= max(1, int(W * 0.05)):
        if H == out_H and W == out_W:
            return tensor_4d
        return F.interpolate(tensor_4d, size=(out_H, out_W), mode="nearest")

    # --- auto: adaptive filter ---
    if mode == "auto":
        mode = "area" if out_H * out_W < H * W else "bicubic"

    # --- lanczos via torchvision ---
    if mode == "lanczos":
        try:
            from torchvision.transforms.functional import resize as tv_resize  # noqa: PLC0415
            return tv_resize(tensor_4d, [out_H, out_W], antialias=True)
        except ImportError:
            mode = "bicubic"

    antialias = True if mode == "bicubic" else False
    return F.interpolate(tensor_4d, size=(out_H, out_W), mode=mode, antialias=antialias)


# ============================================================================
# Model resolution presets
# ============================================================================

MODEL_PRESETS: dict[str, dict] = {
    "Wan 2.1": {
        "max_area": 832 * 480,
        "multiple": 16,
        "note": "832×480 (16:9) / 720×720 (1:1) / 480×832 (9:16)",
    },
    "Wan 2.2": {
        "max_area": 1280 * 720,
        "multiple": 16,
        "note": "1280×720 (16:9) / 960×960 (1:1) / 720×1280 (9:16)",
    },
    "Flux.1 / Flux2": {
        "max_area": 1024 * 1024,
        "multiple": 16,
        "note": "1024² / 1368×768 / 768×1368",
    },
    "Flux2Klein": {
        "max_area": 768 * 768,
        "multiple": 32,
        "note": "Variante destilada — 768² / 1024×576",
    },
    "LTX-2.3": {
        "max_area": 1024 * 576,
        "multiple": 32,
        "note": "1024×576 (16:9) / 768×768 (1:1) / 576×1024 (9:16)",
    },
    "LTX-2.3 + ICLORA": {
        "max_area": 1024 * 576,
        "multiple": 64,
        "note": "Multiplo 64 obligatorio — ControlNet UNION requiere latente par. 1280×768 / 1024×576 / 768×768",
    },
    "Custom (multiple 64)": {
        "max_area": None,
        "multiple": 64,
        "note": "Generico — multiplo de 64 sin limite de area. Para modelos + ControlNet UNION.",
    },
    "SD 1.5 / SDXL": {
        "max_area": 1024 * 1024,
        "multiple": 64,
        "note": "1024² (SDXL) / 512² (SD1.5)",
    },
    "Qwen-Image": {
        "max_area": 1024 * 1024,
        "multiple": 16,
        "note": "1024² optimo",
    },
    "Hunyuan Video": {
        "max_area": 960 * 544,
        "multiple": 16,
        "note": "960×544 (16:9) / 720×720 (1:1)",
    },
    "Pad Only (sin limite)": {
        "max_area": None,
        "multiple": 32,
        "note": "Solo padding a multiplo. Sin reduccion de area.",
    },
}


# ============================================================================
# Node 1 — VFX Resolution (Prepare)
# ============================================================================

class VFXPrepareResolution:
    """Prepare an image for AI model processing.

    Decides automatically whether the input fits the model's working
    area or needs downscaling first, based on the selected preset.

    * Input within area  → asymmetric padding (pixel-perfect).
    * Input exceeds area → downscale + asymmetric padding.

    Always outputs 7 values so the companion ``VFXRestoreResolution``
    can reverse every transformation exactly.
    """

    DESCRIPTION = (
        "Prepara una imagen para su procesamiento con IA. "
        "Selecciona el modelo objetivo en el desplegable y el nodo decide automáticamente "
        "si la resolución de entrada cabe en el área de trabajo del modelo o necesita "
        "reducirse primero. Si cabe, solo añade padding asimétrico (derecha y abajo) "
        "hasta el múltiplo requerido — los píxeles originales no se tocan. "
        "Si no cabe, aplica un downscale de alta calidad + padding. "
        "Genera 7 salidas de metadatos para que el nodo Restore pueda revertir "
        "cada transformación de forma exacta."
    )

    @classmethod
    def INPUT_TYPES(s):
        return {
            "required": {
                "image": ("IMAGE", {"tooltip": "Input image or video sequence (any resolution)."}),
                "model_preset": (
                    list(MODEL_PRESETS.keys()),
                    {"default": "Flux.1 / Flux2", "tooltip": "Target AI model. Determines max working area and VAE multiple alignment."},
                ),
                "downscale_method": (
                    ["auto", "lanczos", "bicubic", "bilinear", "area"],
                    {"default": "auto", "tooltip": "Interpolation when reducing: auto = area for downscale, bicubic for upscale."},
                ),
                "pad_mode": (
                    ["replicate", "reflect", "constant", "debug_red"],
                    {"default": "replicate", "tooltip": "How padding pixels are generated. replicate extends edge (VFX default). debug_red fills with red for testing."},
                ),
                "quality": (
                    "FLOAT",
                    {"default": 1.0, "min": 0.5, "max": 3.0, "step": 0.1,
                     "tooltip": "Resolution quality multiplier. 1.0 = preset default. Increase to give the model more pixels (may hit VRAM limits). Does NOT affect the VAE multiple alignment."},
                ),
            },
            "optional": {
                "mask": ("MASK", {"tooltip": "Optional inpainting mask. Black = do not modify, white = generate."}),
            },
        }

    RETURN_TYPES = ("IMAGE", "MASK", "INT", "INT", "FLOAT", "INT", "INT")
    RETURN_NAMES = (
        "image_processed",
        "mask_processed",
        "orig_width",
        "orig_height",
        "scale_factor",
        "model_width",
        "model_height",
    )
    FUNCTION = "prepare"
    CATEGORY = "VFX"

    def prepare(
        self,
        image: torch.Tensor,
        model_preset: str,
        downscale_method: str,
        pad_mode: str,
        quality: float,
        mask: torch.Tensor | None = None,
    ) -> tuple[torch.Tensor, torch.Tensor, int, int, float, int, int]:
        B, orig_H, orig_W, C = image.shape
        preset = MODEL_PRESETS[model_preset]
        max_area = preset["max_area"]
        multiple = preset["multiple"]

        # ---- effective area (quality slider scales the preset's area budget) ----
        effective_area = None if max_area is None else int(max_area * quality)

        # ---- fit to model area ----
        fit_W, fit_H, scale = _fit_area(orig_W, orig_H, effective_area, multiple)

        # ---- downscale if the image exceeds the area budget ----
        if scale < 1.0:
            img_4d = image.permute(0, 3, 1, 2)
            image = _resample(img_4d, fit_H, fit_W, downscale_method).permute(0, 2, 3, 1)
        else:
            fit_W, fit_H = orig_W, orig_H

        # ---- mask (downscale with nearest to keep hard edges) ----
        mask_norm = _normalize_mask(mask, B) if mask is not None else None
        if scale < 1.0 and mask_norm is not None:
            mask_norm = _resample(mask_norm.unsqueeze(1), fit_H, fit_W, "nearest").squeeze(1)
        elif scale < 1.0:
            mask_norm = torch.zeros((B, fit_H, fit_W), dtype=torch.float32, device=image.device)

        # ---- asymmetric padding (right + bottom only → top-left anchor) ----
        W, H = fit_W, fit_H
        pad_w = (multiple - (W % multiple)) % multiple
        pad_h = (multiple - (H % multiple)) % multiple

        if pad_w == 0 and pad_h == 0:
            mask_out = (
                mask_norm
                if mask_norm is not None
                else torch.zeros((B, H, W), dtype=torch.float32, device=image.device)
            )
            return (image, mask_out, orig_W, orig_H, scale, W, H)

        img_4d = image.permute(0, 3, 1, 2)
        padded = F.pad(img_4d, (0, pad_w, 0, pad_h), mode=pad_mode if pad_mode != "debug_red" else "constant", value=0.0)
        if pad_mode == "debug_red":
            if pad_h > 0:
                padded[:, 0, -pad_h:, :] = 1.0    # red channel on bottom rows
            if pad_w > 0:
                padded[:, 0, :, -pad_w:] = 1.0    # red channel on right columns
        image_padded = padded.permute(0, 2, 3, 1)

        if mask_norm is not None:
            mask_out = F.pad(
                mask_norm.unsqueeze(1), (0, pad_w, 0, pad_h),
                mode="constant", value=0.0,
            ).squeeze(1)
        else:
            mask_out = torch.zeros(
                (B, H + pad_h, W + pad_w), dtype=torch.float32, device=image.device,
            )

        # model_w / model_h = pre-padding dimensions
        return (image_padded, mask_out, orig_W, orig_H, scale, W, H)


# ============================================================================
# Node 2 — VFX Resolution (Restore)
# ============================================================================

class VFXRestoreResolution:
    """Restore the original resolution after model processing.

    Always receives metadata from ``VFXPrepareResolution``.

    Adaptive crop: if the model returned a different resolution than
    expected (some architectures rebucket or upscale internally), the
    node clips to the available area (top-left) and adjusts the upscale
    accordingly instead of crashing.  A warning is printed to the
    ComfyUI console so the user knows a size mismatch occurred.

    Set ``upscale_method`` to ``passthrough`` to skip internal upscaling
    and connect the output to an external upscaler (SeedVR2, RTX VSR).
    """

    DESCRIPTION = (
        "Restaura la resolucion original de la imagen tras el procesamiento del modelo. "
        "Recibe los metadatos del nodo Prepare mediante cables directos. "
        "Primero recorta la zona de padding añadida por Prepare (crop anclado top-left, "
        "cero interpolacion). Si la imagen fue reducida antes del modelo, aplica un "
        "upscale uniforme de alta calidad para devolverla a su resolucion original exacta. "
        "7 salidas: imagen y mascara restauradas, imagen y mascara cropeadas "
        "(sin upscale), max_resolution (para SeedVR2), y target_width/target_height "
        "(para RTX VSR y Fit Dimension). "
        "Usa image_cropped + target_width/height para conectar directamente a RTX VSR "
        "sin necesidad del nodo Fit Dimension."
    )

    @classmethod
    def INPUT_TYPES(s):
        return {
            "required": {
                "image": ("IMAGE", {"tooltip": "Processed image from VAE Decode (may have different dimensions than expected)."}),
                "orig_width": ("INT", {"forceInput": True, "tooltip": "Original input width. Connect from Prepare's orig_width output."}),
                "orig_height": ("INT", {"forceInput": True, "tooltip": "Original input height. Connect from Prepare's orig_height output."}),
                "scale_factor": ("FLOAT", {"forceInput": True, "tooltip": "Scale factor applied by Prepare (1.0 = no downscale, <1.0 = downscaled)."}),
                "model_width": ("INT", {"forceInput": True, "tooltip": "Pre-padding width (crop target). Connect from Prepare's model_width output."}),
                "model_height": ("INT", {"forceInput": True, "tooltip": "Pre-padding height (crop target). Connect from Prepare's model_height output."}),
                "upscale_method": (
                    ["auto", "lanczos", "bicubic", "bilinear", "nearest", "passthrough"],
                    {"default": "lanczos", "tooltip": "Upscale method. passthrough = no upscale (use image_cropped output for external upscaler like SeedVR2)."},
                ),
            },
            "optional": {
                "mask": ("MASK", {"tooltip": "Optional processed mask for inpainting workflows."}),
            },
        }

    RETURN_TYPES = ("IMAGE", "MASK", "IMAGE", "MASK", "INT", "INT", "INT")
    RETURN_NAMES = ("image_restored", "mask_restored", "image_cropped", "mask_cropped", "max_resolution", "target_width", "target_height")
    FUNCTION = "restore"
    CATEGORY = "VFX"

    def restore(
        self,
        image: torch.Tensor,
        orig_width: int,
        orig_height: int,
        scale_factor: float,
        model_width: int,
        model_height: int,
        upscale_method: str,
        mask: torch.Tensor | None = None,
    ) -> tuple[torch.Tensor, torch.Tensor]:
        B, H, W, C = image.shape

        # ---- crop / adjust to model dimensions ----
        if H == model_height and W == model_width:
            # Exact match -> pixel-perfect
            crop_H, crop_W = H, W
            off_H, off_W = 0, 0

        elif H < model_height or W < model_width:
            # Model shrank -> use available area
            crop_H, crop_W = H, W
            off_H, off_W = 0, 0
            print(
                f"[VFX] WARNING: processed image ({W}x{H}) is SMALLER "
                f"than expected ({model_width}x{model_height}). "
                f"Using available area."
            )

        else:
            # Padding or model changed size -> top-left crop to expected
            crop_H = min(H, model_height)
            crop_W = min(W, model_width)
            off_H, off_W = 0, 0
            if H > model_height + 128 or W > model_width + 128:
                print(
                    f"[VFX] WARNING: model significantly changed dimensions "
                    f"({W}x{H} vs expected {model_width}x{model_height})."
                )

        cropped = image[:, off_H:off_H + crop_H, off_W:off_W + crop_W, :]

        # ---- uniform-scale upscale (zero aspect distortion) ----
        needs_upscale = (
            (crop_H != orig_height or crop_W != orig_width)
            and upscale_method != "passthrough"
        )
        if needs_upscale:
            # Calculate a UNIFORM scale factor so both dimensions scale equally
            scale_w = orig_width / crop_W
            scale_h = orig_height / crop_H
            scale = max(scale_w, scale_h)  # ensure target is fully covered
            temp_W = max(orig_width, round(crop_W * scale))
            temp_H = max(orig_height, round(crop_H * scale))

            img_4d = cropped.permute(0, 3, 1, 2)
            upscaled = _resample(img_4d, temp_H, temp_W, upscale_method)

            # Center-crop to exact target dimensions
            trim_w = (temp_W - orig_width) // 2
            trim_h = (temp_H - orig_height) // 2
            restored_image = upscaled[:, :, trim_h:trim_h + orig_height, trim_w:trim_w + orig_width].permute(0, 2, 3, 1)
        else:
            restored_image = cropped

        # ---- mask ----
        if mask is not None:
            mask = _normalize_mask(mask, B)
            raw_mask_cropped = mask[:, off_H:off_H + crop_H, off_W:off_W + crop_W]
            if needs_upscale:
                mask_4d = raw_mask_cropped.unsqueeze(1)
                mask_up = _resample(mask_4d, temp_H, temp_W, "nearest")
                restored_mask = mask_up[:, :, trim_h:trim_h + orig_height, trim_w:trim_w + orig_width].squeeze(1)
            else:
                restored_mask = raw_mask_cropped
        else:
            raw_mask_cropped = torch.zeros(
                (B, crop_H, crop_W), dtype=torch.float32, device=image.device,
            )
            restored_mask = torch.zeros(
                (B, orig_height, orig_width), dtype=torch.float32, device=image.device,
            )

        return (restored_image, restored_mask, cropped, raw_mask_cropped, max(orig_width, orig_height), orig_width, orig_height)


# ============================================================================
# Node 3 — VFX Fit Dimension (uniform scale + center-crop to exact size)
# ============================================================================

class VFXFitDimension:
    """Fit an image (and optional mask) to exact target dimensions.

    Uniformly scales the input so it fully covers the target, then
    center-crops to the exact ``target_width`` × ``target_height``.
    No aspect distortion — the same scale factor is used for both axes.

    Use this between any AI upscaler (SeedVR2, ESRGAN, RTX VSR) and
    the final output when the upscaler does not guarantee exact
    output dimensions.

    If a mask is connected, it receives the same geometric transform
    (nearest-neighbour interpolation to preserve hard edges).
    """

    DESCRIPTION = (
        "Ajusta una imagen a dimensiones exactas sin distorsion de aspecto. "
        "Ideal para colocar entre un upscaler AI (SeedVR2, ESRGAN) y la salida final. "
        "No es necesario para RTX VSR (acepta width/height exactos desde Restore). "
        "Aplica una escala uniforme (mismo factor en ancho y alto) para cubrir "
        "completamente las dimensiones objetivo, luego recorta el exceso con un "
        "center-crop. Cero deformacion geometrica. Acepta mascara opcional."
    )

    @classmethod
    def INPUT_TYPES(s):
        return {
            "required": {
                "image": ("IMAGE", {"tooltip": "Image from an external upscaler (SeedVR2, ESRGAN) at any resolution."}),
                "target_width": ("INT", {"default": 1920, "min": 1, "max": 16384, "forceInput": True, "tooltip": "Exact output width. Connect from Prepare's orig_width."}),
                "target_height": ("INT", {"default": 1080, "min": 1, "max": 16384, "forceInput": True, "tooltip": "Exact output height. Connect from Prepare's orig_height."}),
                "method": (
                    ["auto", "lanczos", "bicubic", "bilinear", "nearest"],
                    {"default": "auto", "tooltip": "Resampling method. auto = area for downscale, bicubic for upscale."},
                ),
            },
            "optional": {
                "mask": ("MASK", {"tooltip": "Optional mask. Receives the same geometric transform (nearest interpolation)."}),
            },
        }

    RETURN_TYPES = ("IMAGE", "MASK")
    RETURN_NAMES = ("image", "mask")
    FUNCTION = "fit"
    CATEGORY = "VFX"

    def fit(
        self,
        image: torch.Tensor,
        target_width: int,
        target_height: int,
        method: str,
        mask: torch.Tensor | None = None,
    ) -> tuple[torch.Tensor, torch.Tensor]:
        _, H, W, _ = image.shape

        if H == target_height and W == target_width:
            m = mask if mask is not None else torch.zeros(
                image.shape[0], H, W, dtype=torch.float32, device=image.device,
            )
            return (image, m)

        # Uniform scale to cover target, then center-crop
        scale = max(target_width / W, target_height / H)
        temp_W = max(target_width, round(W * scale))
        temp_H = max(target_height, round(H * scale))
        trim_w = (temp_W - target_width) // 2
        trim_h = (temp_H - target_height) // 2

        # Image
        img_4d = image.permute(0, 3, 1, 2)
        upscaled = _resample(img_4d, temp_H, temp_W, method)
        result_img = upscaled[:, :, trim_h:trim_h + target_height, trim_w:trim_w + target_width]
        result_img = result_img.permute(0, 2, 3, 1)

        # Mask
        if mask is not None:
            mask = _normalize_mask(mask, image.shape[0])
            msk_4d = mask.unsqueeze(1)
            msk_up = _resample(msk_4d, temp_H, temp_W, "nearest")
            result_msk = msk_up[:, :, trim_h:trim_h + target_height, trim_w:trim_w + target_width].squeeze(1)
        else:
            result_msk = torch.zeros(
                (image.shape[0], target_height, target_width),
                dtype=torch.float32, device=image.device,
            )

        return (result_img, result_msk)


# ------------------------------------------------------------------
# Category colors
# ------------------------------------------------------------------

CATEGORY_COLORS = {
    "VFX": "#FF8C00",
}

# ============================================================================
# Registration
# ============================================================================

NODE_CLASS_MAPPINGS = {
    "VFXPrepareResolution": VFXPrepareResolution,
    "VFXRestoreResolution": VFXRestoreResolution,
    "VFXFitDimension": VFXFitDimension,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "VFXPrepareResolution": "🔶 VFX Resolution (Prepare)",
    "VFXRestoreResolution": "🔶 VFX Resolution (Restore)",
    "VFXFitDimension": "🔶 VFX Fit Dimension",
}

# ------------------------------------------------------------------
# Optional: VFX Corrections (requires opencv-contrib-python)
# ------------------------------------------------------------------
try:
    from .corrections import VFXCorrections  # noqa: F811

    NODE_CLASS_MAPPINGS["VFXCorrections"] = VFXCorrections
    NODE_DISPLAY_NAME_MAPPINGS["VFXCorrections"] = "🔶 VFX Corrections (Align+Color+Blend)"
except ImportError:
    pass
