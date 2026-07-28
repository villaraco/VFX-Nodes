"""
VFX Corrections — post-processing node for VFX pipelines.
==========================================================

Three optional correction stages (each toggleable):

1. **Geometric alignment** — SIFT homography + DIS optical flow.
   Corrects sub-pixel shifts introduced by the model.
2. **Colour matching** — Reinhard transfer in LAB space.
   Transfers colour statistics from reference to processed image.
3. **Seamless blending** — Poisson (cv2.seamlessClone) with
   alpha-blend fallback.

Requires ``opencv-contrib-python``.  Without it, the node is not
registered in ComfyUI (the parent ``__init__.py`` imports it
conditionally).
"""

from __future__ import annotations

import torch


class VFXCorrections:
    """Post-processing corrections to align model output with reference.

    Three optional stages, each toggleable:

    1. **Geometric alignment** (SIFT homography + DIS optical flow)
       corrects sub-pixel shifts the model may have introduced.
    2. **Color matching** (Reinhard transfer in LAB space)
       transfers the colour palette of the reference onto the
       processed image (background pixels only).
    3. **Seamless blending** (Poisson / alpha-blend fallback)
       softens the transition between generated and original zones.

    If a ``mask`` is connected, the mask's black pixels define the
    *background* (anchor for alignment and colour reference).
    Without a mask the entire image is treated as foreground.

    Requires ``opencv-contrib-python`` for alignment and blending.
    Colour matching works with plain ``opencv-python``.
    """

    DESCRIPTION = (
        "Correcciones de post-procesado para pipelines VFX. Tres etapas opcionales "
        "con switches independientes: (1) Alineación geométrica mediante SIFT + flujo "
        "óptico DIS para corregir desplazamientos sub-píxel que el modelo haya introducido. "
        "(2) Emparejado de color Reinhard en espacio LAB — transfiere la paleta cromática "
        "de la imagen original al resultado procesado usando solo los píxeles de fondo. "
        "(3) Mezcla seamless con Poisson blending y fallback alpha-blend para suavizar "
        "la frontera entre zonas generadas y originales. Requiere opencv-contrib-python."
    )

    _HAS_CV = None  # None = not checked yet, True/False = result

    @staticmethod
    def _check_cv() -> bool:
        if VFXCorrections._HAS_CV is not None:
            return VFXCorrections._HAS_CV
        try:
            import cv2  # noqa: F401
            VFXCorrections._HAS_CV = True
        except ImportError:
            VFXCorrections._HAS_CV = False
            print(
                "[VFX] Corrections: opencv not available. "
                "Install 'pip install opencv-contrib-python' for full functionality."
            )
        return VFXCorrections._HAS_CV

    @classmethod
    def INPUT_TYPES(s):
        return {
            "required": {
                "image": ("IMAGE",),
                "reference": ("IMAGE",),
                "enable_align": ("BOOLEAN", {"default": True}),
                "enable_color": ("BOOLEAN", {"default": True}),
                "enable_blend": ("BOOLEAN", {"default": False}),
                "color_strength": (
                    "FLOAT",
                    {"default": 1.0, "min": 0.0, "max": 1.0, "step": 0.05},
                ),
                "blend_feather": (
                    "INT",
                    {"default": 5, "min": 0, "max": 50, "step": 1},
                ),
            },
            "optional": {
                "mask": ("MASK",),
            },
        }

    RETURN_TYPES = ("IMAGE", "MASK")
    RETURN_NAMES = ("corrected_image", "diff_mask")
    FUNCTION = "correct"
    CATEGORY = "VFX"

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    def correct(
        self,
        image: torch.Tensor,
        reference: torch.Tensor,
        enable_align: bool,
        enable_color: bool,
        enable_blend: bool,
        color_strength: float,
        blend_feather: int,
        mask: torch.Tensor | None = None,
    ) -> tuple[torch.Tensor, torch.Tensor]:
        B, H, W, C = image.shape

        if not self._check_cv():
            return (
                image,
                torch.zeros(B, H, W, dtype=torch.float32, device=image.device),
            )

        result = image.clone()
        diff_mask = torch.zeros(B, H, W, dtype=torch.float32, device=image.device)

        for b in range(B):
            ref = reference[b] if reference.shape[0] == B else reference[0]
            msk = (
                mask[b]
                if mask is not None and mask.shape[0] == B
                else (mask[0] if mask is not None else None)
            )

            ref_np = self._to_numpy(ref)
            img_np = self._to_numpy(result[b])
            msk_np = self._to_numpy_mask(msk, H, W) if msk is not None else None

            # ---- Stage 1: Geometric alignment ----
            if enable_align:
                img_np, msk_np, align_diff = self._geo_align(img_np, ref_np, msk_np)
                if align_diff is not None:
                    diff_mask[b] = torch.from_numpy(
                        align_diff.astype("float32") / 255.0
                    ).to(image.device)

            # ---- Stage 2: Colour matching ----
            if enable_color and color_strength > 0:
                img_np = self._reinhard_match(img_np, ref_np, msk_np, color_strength)

            # ---- Stage 3: Seamless blending ----
            if enable_blend and msk_np is not None:
                img_np = self._seamless_blend(img_np, ref_np, msk_np, blend_feather)

            result[b] = torch.from_numpy(img_np.astype("float32") / 255.0).to(
                image.device
            )

        return (result, diff_mask)

    # ------------------------------------------------------------------
    # Helpers — conversion
    # ------------------------------------------------------------------

    @staticmethod
    def _to_numpy(t: torch.Tensor) -> "np.ndarray":
        return (t.cpu().numpy() * 255).clip(0, 255).astype("uint8")

    @staticmethod
    def _to_numpy_mask(m: torch.Tensor, H: int, W: int) -> "np.ndarray":
        if m.dim() == 2:
            m = m.unsqueeze(0)
        arr = m[0].cpu().numpy()
        if arr.shape[0] != H or arr.shape[1] != W:
            import cv2

            arr = cv2.resize(arr, (W, H), interpolation=cv2.INTER_NEAREST)
        return (arr * 255).clip(0, 255).astype("uint8")

    # ------------------------------------------------------------------
    # Stage 1 — Geometric alignment (SIFT + DIS)
    # ------------------------------------------------------------------

    def _geo_align(
        self,
        img: "np.ndarray",
        ref: "np.ndarray",
        msk: "np.ndarray | None",
    ) -> tuple["np.ndarray", "np.ndarray | None", "np.ndarray | None"]:
        """Align img to ref using SIFT homography, optionally refined with DIS flow.

        Returns (aligned_img, aligned_mask, diff_mask_uint8)."""
        import cv2
        import numpy as np

        diff = None

        # --- SIFT homography ---
        try:
            sift = cv2.SIFT_create()
        except Exception:
            print(
                "[VFX] SIFT not available (install opencv-contrib-python). "
                "Skipping alignment."
            )
            return img, msk, diff

        gray_ref = cv2.cvtColor(ref, cv2.COLOR_RGB2GRAY)
        gray_img = cv2.cvtColor(img, cv2.COLOR_RGB2GRAY)

        # Mask out foreground for feature detection (only align on background)
        if msk is not None and msk.any():
            bg_ref = cv2.bitwise_and(gray_ref, gray_ref, mask=cv2.bitwise_not(msk))
            bg_img = cv2.bitwise_and(gray_img, gray_img, mask=cv2.bitwise_not(msk))
        else:
            bg_ref, bg_img = gray_ref, gray_img

        kp1, des1 = sift.detectAndCompute(bg_ref, None)
        kp2, des2 = sift.detectAndCompute(bg_img, None)

        if des1 is None or des2 is None or len(kp1) < 8 or len(kp2) < 8:
            print("[VFX] SIFT: insufficient keypoints. Skipping alignment.")
            return img, msk, diff

        # FLANN matcher
        index_params = dict(algorithm=1, trees=5)
        search_params = dict(checks=50)
        flann = cv2.FlannBasedMatcher(index_params, search_params)
        matches = flann.knnMatch(des1, des2, k=2)

        good = [m for m, n in matches if m.distance < 0.7 * n.distance]
        if len(good) < 8:
            print(
                f"[VFX] SIFT: only {len(good)} good matches (need >= 8). "
                f"Skipping alignment."
            )
            return img, msk, diff

        src_pts = np.float32([kp2[m.trainIdx].pt for m in good]).reshape(-1, 1, 2)
        dst_pts = np.float32([kp1[m.queryIdx].pt for m in good]).reshape(-1, 1, 2)

        H_mat, _ = cv2.findHomography(src_pts, dst_pts, cv2.RANSAC, 3.0)
        if H_mat is None:
            print("[VFX] SIFT: homography failed. Skipping alignment.")
            return img, msk, diff

        img = cv2.warpPerspective(img, H_mat, (ref.shape[1], ref.shape[0]))
        if msk is not None:
            msk = cv2.warpPerspective(
                msk,
                H_mat,
                (ref.shape[1], ref.shape[0]),
                flags=cv2.INTER_NEAREST,
            )

        # --- DIS optical-flow refinement ---
        try:
            dis = cv2.DISOpticalFlow_create(cv2.DISOPTICAL_FLOW_PRESET_ULTRAFAST)
            flow = dis.calc(gray_ref, cv2.cvtColor(img, cv2.COLOR_RGB2GRAY), None)
            flow_map = np.dstack(
                np.meshgrid(np.arange(ref.shape[1]), np.arange(ref.shape[0]))
            ).astype("float32")
            flow_map += flow
            img = cv2.remap(
                img, flow_map[..., 0], flow_map[..., 1], cv2.INTER_LINEAR
            )
            if msk is not None:
                msk = cv2.remap(
                    msk,
                    flow_map[..., 0],
                    flow_map[..., 1],
                    cv2.INTER_NEAREST,
                )
        except Exception:
            pass  # DIS not available — homography alone is enough

        # Diff mask (where alignment changed things)
        diff = cv2.absdiff(ref, img)
        diff = cv2.cvtColor(diff, cv2.COLOR_RGB2GRAY)

        return img, msk, diff

    # ------------------------------------------------------------------
    # Stage 2 — Colour matching (Reinhard in LAB)
    # ------------------------------------------------------------------

    def _reinhard_match(
        self,
        img: "np.ndarray",
        ref: "np.ndarray",
        msk: "np.ndarray | None",
        strength: float,
    ) -> "np.ndarray":
        """Transfer colour statistics from ref to img (background pixels only)."""
        import cv2
        import numpy as np

        img_lab = cv2.cvtColor(img, cv2.COLOR_RGB2LAB).astype("float32")
        ref_lab = cv2.cvtColor(ref, cv2.COLOR_RGB2LAB).astype("float32")

        if msk is not None and msk.any():
            bg = (msk < 128).astype("float32")
        else:
            bg = np.ones(ref.shape[:2], dtype="float32")

        bg_count = int(bg.sum())
        if bg_count < 100:
            print("[VFX] Color match: too few background pixels (<100). Skipping.")
            return img

        ref_means, ref_stds = [], []
        img_means, img_stds = [], []
        for c in range(3):
            r_ch, i_ch = ref_lab[..., c], img_lab[..., c]
            ref_means.append((r_ch * bg).sum() / bg_count)
            img_means.append((i_ch * bg).sum() / bg_count)
            ref_stds.append(
                np.sqrt(((r_ch - ref_means[-1]) ** 2 * bg).sum() / bg_count) + 1e-6
            )
            img_stds.append(
                np.sqrt(((i_ch - img_means[-1]) ** 2 * bg).sum() / bg_count) + 1e-6
            )

        result_lab = img_lab.copy()
        for c in range(3):
            transferred = (
                (img_lab[..., c] - img_means[c]) / img_stds[c] * ref_stds[c]
                + ref_means[c]
            )
            result_lab[..., c] = (
                img_lab[..., c] * (1 - strength) + transferred * strength
            )

        result_lab = result_lab.clip(0, 255).astype("uint8")
        return cv2.cvtColor(result_lab, cv2.COLOR_LAB2RGB)

    # ------------------------------------------------------------------
    # Stage 3 — Seamless blending (Poisson / alpha-blend)
    # ------------------------------------------------------------------

    def _seamless_blend(
        self,
        img: "np.ndarray",
        ref: "np.ndarray",
        msk: "np.ndarray",
        feather: int,
    ) -> "np.ndarray":
        """Blend processed region into reference with soft edges."""
        import cv2
        import numpy as np

        if not msk.any():
            return img

        if feather > 0:
            ksize = feather * 2 + 1
            kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (ksize, ksize))
            msk_feathered = cv2.dilate(msk, kernel) if msk.max() > 0 else msk
            msk_blur = cv2.GaussianBlur(
                msk_feathered.astype("float32"), (ksize, ksize), feather
            )
            msk_blur = (msk_blur / 255.0).clip(0, 1)
        else:
            msk_blur = (msk / 255.0).clip(0, 1)

        # Try Poisson blending
        try:
            bin_mask = (msk > 128).astype("uint8") * 255
            if bin_mask.sum() > 0:
                bin_mask[0, :] = bin_mask[-1, :] = 0
                bin_mask[:, 0] = bin_mask[:, -1] = 0
                if bin_mask.sum() > 0:
                    center = (ref.shape[1] // 2, ref.shape[0] // 2)
                    return cv2.seamlessClone(
                        img, ref, bin_mask, center, cv2.NORMAL_CLONE
                    )
        except Exception:
            pass

        # Fallback: alpha blend
        msk_3ch = np.stack([msk_blur] * 3, axis=-1)
        return (img * msk_3ch + ref * (1 - msk_3ch)).astype("uint8")
