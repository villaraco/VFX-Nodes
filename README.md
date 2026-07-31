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

### VFXFramePad
Nodo utilitario para manipular frames en batches de video. Dos modos:

- **prepend_first**: Repite el primer frame N veces al inicio del batch. Util para darle
  al modelo frames extra de "settling" y eliminar parpadeos de luminancia
  (problema conocido de LTX-2.3, Wan, etc.).
- **trim_start**: Recorta los primeros N frames. Util para eliminar los frames
  de settling anadidos y restaurar la duracion original.

Entradas: `image` (IMAGE), `mode` (prepend_first/trim_start), `frames` (INT, 0-1000).
Salidas: `image` (IMAGE), `mask` (MASK), `frame_count` (INT).

### VFXCorrections (opcional, requiere opencv-contrib-python)
Post-procesado VFX con 3 etapas toggleables:
1. Alineacion geometrica (SIFT + DIS optical flow)
2. Emparejado de color Reinhard (espacio LAB)
3. Mezcla seamless (Poisson blending + alpha-blend fallback)

## Guia de uso: VFXFramePad

El caso principal es eliminar parpadeos de luminancia en LTX-2.3 / Wan / Hunyuan.
El problema: los primeros frames generados por el modelo sufren un "settling"
(ajuste gradual de brillo/color) que arruina el inicio del clip. La solucion
consiste en darle frames extra al modelo y luego descartarlos.

### Workflow tipico (LTX-2.3)

```
[Load Video] 121 frames                     [Output final] 121 frames
     │                                              ▲
     ▼                                              │
[VFXFramePad] prepend_first, frames=3     [VFXFramePad] trim_start, frames=3
     │ 124 frames                                   ▲
     ▼                                              │
[EmptyLTXVLatentVideo] length=124 ──────────────────┘
     │
     ▼
[LTXVAddGuide] control con frame_idx=0
     │
     ▼
[Sampler] → [VAE Decode] 124 frames
```

1. **Antes del modelo** — `VFXFramePad (prepend_first, frames=3)`:
   El video de 121 frames pasa a 124. Los primeros 3 frames son copias del frame 0.
   El modelo genera 124 frames, usando los 3 primeros como "calentamiento".

2. **Despues del modelo** — `VFXFramePad (trim_start, frames=3)`:
   Se descartan los 3 frames de settling, recuperando los 121 frames originales
   con luminancia estable desde el frame 1.

| Etapa | Batch | Accion |
|-------|-------|--------|
| Video original | 121 frames | — |
| Prepend | 124 frames | +3 copias del frame 0 al inicio |
| Modelo genera | 124 frames | Frames 0-2: settling. Frames 3-123: contenido real |
| Trim | 121 frames | -3 frames iniciales descartados |

### Otros usos

- **Extender clip con hold**: `prepend_first, frames=5` — el video empieza con
  medio segundo de frame congelado antes del movimiento.
- **Recortar intro no deseada**: `trim_start, frames=12` — elimina el primer
  medio segundo (a 24fps) de un clip.

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
- Frame Pad (prepend, trim, roundtrip, bypass, device)

## Licencia

Open-source. Usar y modificar libremente.
