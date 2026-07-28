# VFX-Nodes: Custom Nodes de Resolucion para ComfyUI VFX

Custom nodes para ComfyUI que garantizan resolucion de salida identica a la de entrada
en cualquier pipeline VFX, independientemente del modelo AI utilizado.

## Nodos

### VFXPrepareResolution
Prepara una imagen para procesamiento con IA. Segun el preset de modelo seleccionado,
decide si la imagen cabe en el area de trabajo o necesita downscale. Aplica padding
asimetrico (derecha + abajo) para alineacion a multiplos del VAE sin tocar pixeles
originales.

### VFXRestoreResolution
Restaura la resolucion original tras el modelo. Recorta el padding y aplica upscale
uniforme si hubo downscale. Soporta modelos que cambian dimensiones internamente
(adaptativo, sin crash).

### VFXFitDimension
Ajusta una imagen a dimensiones exactas sin distorsion de aspecto. Escala uniforme
+ center-crop. Util entre upscalers externos (SeedVR2, ESRGAN) y la salida final.

### VFXCorrections (opcional, requiere opencv-contrib-python)
Post-procesado VFX con 3 etapas toggleables:
1. Alineacion geometrica (SIFT + DIS optical flow)
2. Emparejado de color Reinhard (espacio LAB)
3. Mezcla seamless (Poisson blending + alpha-blend fallback)

## Presets de Modelo

| Preset | Max Area | Multiple |
|---|---|---|
| Wan 2.1 | 832x480 | 16 |
| Wan 2.2 | 1280x720 | 16 |
| Flux.1 / Flux2 | 1024x1024 | 16 |
| Flux2Klein | 768x768 | 32 |
| LTX-2.3 | 1024x576 | 32 |
| LTX-2.3 + ICLORA | 1024x576 | 64 |
| Custom (multiple 64) | sin limite | 64 |
| SD 1.5 / SDXL | 1024x1024 | 64 |
| Qwen-Image | 1024x1024 | 16 |
| Hunyuan Video | 960x544 | 16 |
| Pad Only (sin limite) | sin limite | 32 |

## Instalacion

```bash
# Copiar a custom_nodes de ComfyUI
cp -r VFX-Nodes/ /path/to/ComfyUI/custom_nodes/VFX_Nodes/

# Requisitos
pip install -r requirements.txt
```

## Tests

```bash
# Todos los tests
python validate_roundtrip.py

# Solo resoluciones especificas
python validate_roundtrip.py --resolutions 1920x1080,3840x2160

# Solo presets de padding (pixel-perfect)
python validate_roundtrip.py --presets
```

Tests incluidos:
- Roundtrip pixel-perfect (padding)
- Roundtrip con downscale+upscale (todos los presets)
- ICLORA + ControlNet UNION (latente par)
- Restore adaptativo (modelo cambia dimensiones)
- Fit Dimension (escala sin distorsion)

## Licencia

Open-source. Usar y modificar libremente.
