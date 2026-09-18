"""
COS — Standalone Validator
==========================

Tests the pure logic of ``cos/core.py`` (Comfy Output Standard) without
ComfyUI, torch or network access.

Uso
---
    python validate_cos.py

Devuelve codigo de salida != 0 si hay fallos, util para CI/CD.
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE))

from cos import core  # noqa: E402


# ---------------------------------------------------------------------------
# Harness
# ---------------------------------------------------------------------------

class Checker:
    def __init__(self) -> None:
        self.failures = 0

    def ok(self, cond: bool, msg: str) -> None:
        if cond:
            print(f"  [OK]   {msg}")
        else:
            self.failures += 1
            print(f"  [FAIL] {msg}")

    def eq(self, got, expected, msg: str) -> None:
        self.ok(got == expected, f"{msg}  (got={got!r})")

    def raises(self, exc, fn, msg: str) -> None:
        try:
            fn()
        except exc:
            print(f"  [OK]   {msg}")
        except Exception as e:  # noqa: BLE001
            self.failures += 1
            print(f"  [FAIL] {msg} (wrong exception {type(e).__name__}: {e})")
        else:
            self.failures += 1
            print(f"  [FAIL] {msg} (no exception raised)")


def sample_project() -> dict:
    return {
        "schema": 1,
        "show": "tot",
        "project": "Totie",
        "slug": "TOT_Totie",
        "root": "E:/COMFY_OUTPUT",
        "artist": "mio",
        "fps": 24,
        "created": "2026-09-10",
        "updated": "2026-09-10",
        "sequences": {
            "cine": {
                "resolution": [3840, 2160],
                "variants": {},
                "shots": {"0010": "cine"},
            },
            "pant": {
                "variants": {
                    "gen": {"resolution": [1920, 1080], "aspect": "16:9"},
                    "callao": {"resolution": [1080, 1080], "aspect": "1:1"},
                    "granvia": {"resolution": [1440, 1080], "aspect": "4:3"},
                },
                "shots": {"0010": "boca", "0020": "oreja", "0030": "despedida"},
            },
        },
    }


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_slug(c: Checker) -> None:
    print("\n[test_slug]")
    c.eq(core.make_slug("tot", "Totie"), "TOT_Totie", "slug simple")
    c.eq(core.make_slug("mag", "Magerit V2"), "MAG_Magerit_V2", "espacios -> guion bajo")
    c.raises(ValueError, lambda: core.make_slug("TOOLONG", "X"), "show invalido (no 3 letras)")
    c.raises(ValueError, lambda: core.make_slug("tot", "  "), "project vacio")


def test_build_filename(c: Checker) -> None:
    print("\n[test_build_filename]")
    c.eq(
        core.build_base("tot", "pant", "0010", "i2v", "v001", variant="gen"),
        "tot_pant_gen_0010_i2v_v001",
        "base con variante",
    )
    c.eq(
        core.build_base("tot", "cine", "0010", "upscale", "v012"),
        "tot_cine_0010_upscale_v012",
        "base sin variante",
    )
    c.eq(core.build_base("tot", "cine", "0010", "I2V", "v001"), "tot_cine_0010_i2v_v001",
         "task normalizada a minusculas")
    c.raises(ValueError, lambda: core.build_base("tot", "cine", "0010", "i2v", "1"),
             "version sin formato v###")
    c.raises(ValueError, lambda: core.build_base("tot", "../x", "0010", "i2v", "v001"),
             "seq con traversal")


def test_validate_component(c: Checker) -> None:
    print("\n[test_validate_component]")
    c.eq(core.validate_component("0010_boca"), "0010_boca", "componente valido")
    c.raises(ValueError, lambda: core.validate_component("../etc"), "rechaza '..'")
    c.raises(ValueError, lambda: core.validate_component("a/b"), "rechaza '/'")
    c.raises(ValueError, lambda: core.validate_component("C:foo"), "rechaza ':'")
    c.raises(ValueError, lambda: core.validate_component("bad*"), "rechaza '*'")
    c.raises(ValueError, lambda: core.validate_component(""), "rechaza vacio")


def test_skeleton(c: Checker) -> None:
    print("\n[test_skeleton]")
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        project = sample_project()
        core.build_skeleton(root, project)

        for d in core.ROOT_DIRS:
            c.ok((root / d).is_dir(), f"root dir {d}/")

        pdir = root / "PROJECTS" / "TOT_Totie"
        c.ok((pdir / "project.json").parent.is_dir() or pdir.is_dir(), "proyecto creado")
        c.ok((pdir / "_WORKFLOWS").is_dir(), "_WORKFLOWS/")

        cine = pdir / "cine" / "0010_cine"
        for sub in core.SHOT_SUBDIRS:
            c.ok((cine / sub).is_dir(), f"cine/0010_cine/{sub}")
        c.ok((cine / "_NOTES.md").is_file(), "cine/0010_cine/_NOTES.md")

        c.ok((pdir / "pant" / "gen" / "0010_boca" / "02_WORK").is_dir(), "pant/gen/0010_boca/02_WORK")
        c.ok((pdir / "pant" / "callao" / "0030_despedida" / "03_PUBLISH").is_dir(),
             "pant/callao/0030_despedida/03_PUBLISH")

        # idempotente
        before = sorted(str(p) for p in pdir.rglob("*"))
        core.build_skeleton(root, project)
        after = sorted(str(p) for p in pdir.rglob("*"))
        c.ok(after == before, "skeleton idempotente")


def test_version_current(c: Checker) -> None:
    print("\n[test_version_current]")
    with tempfile.TemporaryDirectory() as tmp:
        shot = Path(tmp) / "0010_boca"
        (shot / "02_WORK").mkdir(parents=True)

        c.eq(core.resolve_version(shot, "current"), "v001", "sin estado -> v001")
        c.ok((shot / "02_WORK" / "v001").is_dir(), "carpeta v001 creada")

        # version existente sin estado -> la toma
        shot2 = Path(tmp) / "0020_oreja"
        (shot2 / "02_WORK" / "v003").mkdir(parents=True)
        c.eq(core.resolve_version(shot2, "current"), "v003", "max(existentes) -> v003")


def test_version_new(c: Checker) -> None:
    print("\n[test_version_new]")
    with tempfile.TemporaryDirectory() as tmp:
        shot = Path(tmp) / "0010_boca"
        (shot / "02_WORK").mkdir(parents=True)

        c.eq(core.resolve_version(shot, "new"), "v001", "primera pasada -> v001")
        c.eq(core.resolve_version(shot, "new"), "v002", "segunda pasada -> v002")
        c.eq(core.resolve_version(shot, "current"), "v002", "current tras new -> v002")
        c.ok((shot / "02_WORK" / "v002").is_dir(), "carpeta v002 creada")
        c.eq(core.existing_versions(shot), [1, 2], "versiones detectadas [1, 2]")

        state = core.load_state(shot)
        c.eq(state["current_version"], "v002", "state.current_version = v002")
        c.eq([h["version"] for h in state["history"]], ["v001", "v002"], "history completa")


def test_state_idempotent(c: Checker) -> None:
    print("\n[test_state_idempotent]")
    with tempfile.TemporaryDirectory() as tmp:
        shot = Path(tmp) / "0010_boca"
        (shot / "02_WORK").mkdir(parents=True)

        v1 = core.resolve_version(shot, "current")
        v2 = core.resolve_version(shot, "current")
        c.eq(v1, v2, "current repetido devuelve lo mismo")
        c.eq(len(core.load_state(shot)["history"]), 1, "history sin duplicados")

        core.register_task(shot, v1, "i2v")
        core.register_task(shot, v1, "i2v")
        tasks = core.load_state(shot)["history"][0]["tasks"]
        c.eq(tasks, ["i2v"], "register_task sin duplicados")


def test_sidecar(c: Checker) -> None:
    print("\n[test_sidecar]")
    with tempfile.TemporaryDirectory() as tmp:
        project = sample_project()
        base = core.build_base("tot", "pant", "0010", "i2v", "v001", variant="gen")
        meta = core.build_meta(
            project, "pant", "0010", "boca", "i2v", "v001",
            model="minimaxh3", seed=87654321, resolution=[1080, 1080], fps=24,
            variant="gen", workflow={"nodes": []}, prompt={"1": {}},
        )
        path = core.write_meta(tmp, base, meta)
        c.eq(path.name, "tot_pant_gen_0010_i2v_v001_meta.json", "nombre del sidecar")

        data = json.loads(path.read_text(encoding="utf-8"))
        keys = list(data.keys())
        c.eq(keys[0], "schema", "primer campo = schema")
        c.eq(keys[-1], "prompt", "ultimo campo = prompt")
        c.eq(data["seed"], 87654321, "seed persistida")
        c.eq(data["model"], "minimaxh3", "modelo persistido")
        c.eq(data["resolution"], [1080, 1080], "resolucion persistida")
        c.eq(data["shot_name"], "boca", "shot_name persistido")
        c.eq(data["workflow"], {"nodes": []}, "workflow persistido")


def test_project_json_roundtrip(c: Checker) -> None:
    print("\n[test_project_json_roundtrip]")
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        project = sample_project()
        path = core.write_project(root, project)
        c.ok(path.is_file(), "project.json escrito")

        loaded = core.load_project(path)
        c.eq(loaded["slug"], "TOT_Totie", "slug conservado")
        c.eq(loaded["sequences"]["pant"]["shots"]["0010"], "boca", "shots conservados")
        c.eq(loaded["updated"], core._today(), "updated refrescado")

        projects = core.list_projects(root)
        c.eq(len(projects), 1, "list_projects encuentra 1")


def test_approve_copy(c: Checker) -> None:
    print("\n[test_approve_copy]")
    with tempfile.TemporaryDirectory() as tmp:
        shot = Path(tmp) / "0010_boca"
        vdir = shot / "02_WORK" / "v001"
        vdir.mkdir(parents=True)

        (vdir / "tot_pant_gen_0010_i2v_v001_00001_.mp4").write_text("render-i2v")
        (vdir / "tot_pant_gen_0010_i2v_v001_meta.json").write_text("{}")
        (vdir / "tot_pant_gen_0010_i2i_v001_00001_.png").write_text("render-i2i")

        copied = core.approve_copy(shot, "i2v", "v001")
        names = sorted(p.name for p in copied)
        c.eq(
            names,
            ["tot_pant_gen_0010_i2v_v001_00001_.mp4", "tot_pant_gen_0010_i2v_v001_meta.json"],
            "copia solo los archivos de la task i2v",
        )
        c.ok((shot / "03_PUBLISH" / "tot_pant_gen_0010_i2v_v001_00001_.mp4").is_file(),
             "render publicado")
        c.ok((vdir / "tot_pant_gen_0010_i2v_v001_00001_.mp4").is_file(),
             "original permanece (copy, no move)")
        c.ok(not (shot / "03_PUBLISH" / "tot_pant_gen_0010_i2i_v001_00001_.png").exists(),
             "no publica otras tasks")

        c.raises(FileNotFoundError, lambda: core.approve_copy(shot, "i2v", "v009"),
                 "version inexistente lanza FileNotFoundError")


def test_traversal(c: Checker) -> None:
    print("\n[test_traversal]")
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        core.ensure_root(root)
        c.ok(core.is_within(root, root / "PROJECTS" / "TOT_Totie"), "ruta interna OK")
        c.ok(not core.is_within(root, root / ".." / "evil"), "ruta externa rechazada")
        c.ok(not core.is_within(root, Path(tmp).parent), "padre rechazado")


def test_render_project_md(c: Checker) -> None:
    print("\n[test_render_project_md]")
    md = core.render_project_md(sample_project())
    c.ok("| cine | - | 0010 | cine | 3840x2160 |" in md, "fila cine")
    c.ok("| pant | gen | 0010 | boca | 1920x1080 |" in md, "fila pant/gen")
    c.ok("| pant | granvia | 0030 | despedida | 1440x1080 |" in md, "fila pant/granvia")


def test_parse_inputs(c: Checker) -> None:
    print("\n[test_parse_inputs]")
    seqs = core.parse_sequences("cine,pant")
    c.eq(seqs, ["cine", "pant"], "parse_sequences")

    c.eq(
        core.parse_variants(";gen,callao,granvia", seqs),
        {"cine": [], "pant": ["gen", "callao", "granvia"]},
        "parse_variants posicional",
    )
    c.eq(
        core.parse_variants("gen,callao;", seqs),
        {"cine": ["gen", "callao"], "pant": []},
        "parse_variants invertido",
    )

    shots = core.parse_shots("cine:0010_cine;pant:0010_boca,0020_oreja,0030_despedida")
    c.eq(shots["cine"], {"0010": "cine"}, "parse_shots cine")
    c.eq(shots["pant"], {"0010": "boca", "0020": "oreja", "0030": "despedida"}, "parse_shots pant")


def test_build_project_dict(c: Checker) -> None:
    print("\n[test_build_project_dict]")
    p = core.build_project_dict(
        "tot", "Totie", "mio", 24,
        "cine,pant", ";gen,callao,granvia",
        "cine:0010_cine;pant:0010_boca,0020_oreja,0030_despedida",
        root="E:/COMFY_OUTPUT",
    )
    c.eq(p["slug"], "TOT_Totie", "slug generado")
    c.eq(p["sequences"]["cine"]["variants"], {}, "cine sin variantes")
    c.eq(list(p["sequences"]["pant"]["variants"].keys()), ["gen", "callao", "granvia"], "pant variantes")
    c.eq(p["sequences"]["pant"]["shots"]["0010"], "boca", "shot boca")
    c.eq(p["fps"], 24, "fps")
    c.eq(p["root"], "E:/COMFY_OUTPUT", "root registrado")
    c.eq(p["created"], p["updated"], "created == updated al crear")

    p2 = core.build_project_dict(
        "tot", "Totie", "mio", 24, "pant", "gen", "pant:0010_boca",
        config_extra='{"sequences": {"pant": {"variants": {"gen": {"resolution": [1920, 1080]}}}}}',
    )
    c.eq(p2["sequences"]["pant"]["variants"]["gen"]["resolution"], [1920, 1080], "config_extra fusionado")

    p3 = core.build_project_dict("tot", "Totie", "mio", 24, "cine", "", "cine:0010_cine",
                                 created="2020-01-01")
    c.eq(p3["created"], "2020-01-01", "created preservado")

    c.raises(ValueError, lambda: core.build_project_dict("tot", "X", "m", 24, "", ""),
             "sin secuencias lanza ValueError")
    c.raises(ValueError, lambda: core.build_project_dict(
        "tot", "X", "m", 24, "cine", "", "cine:0010_cine", config_extra="{bad json"),
        "config_extra invalido lanza ValueError")

    with tempfile.TemporaryDirectory() as tmp:
        core.build_skeleton(tmp, p)
        md = core.write_project_md(tmp, p)
        c.ok(md.is_file() and md.name == "_PROJECT.md", "write_project_md crea _PROJECT.md")
        c.ok("| pant | gen | 0010 | boca |" in md.read_text(encoding="utf-8"), "contenido _PROJECT.md")


def test_resolve_shot_dir(c: Checker) -> None:
    print("\n[test_resolve_shot_dir]")
    project = sample_project()
    root = Path("E:/COMFY_OUTPUT")

    cine = core.resolve_shot_dir(root, project, "cine", "0010")
    c.eq(cine.name, "0010_cine", "plano cine sin variante")
    c.ok(cine.parent.name == "cine", "cine cuelga de la secuencia")

    boca = core.resolve_shot_dir(root, project, "pant", "0010", variant="gen")
    c.eq(boca.as_posix(), "E:/COMFY_OUTPUT/PROJECTS/TOT_Totie/pant/gen/0010_boca",
         "plano pant/gen con variante")

    unknown = core.resolve_shot_dir(root, project, "pant", "9999", variant="gen")
    c.eq(unknown.name, "9999_9999", "shot desconocido usa el id como nombre")

    c.raises(ValueError, lambda: core.resolve_shot_dir(root, project, "../x", "0010"),
             "seq con traversal")


def test_resolve_resolution(c: Checker) -> None:
    print("\n[test_resolve_resolution]")
    project = sample_project()
    c.eq(core.resolve_resolution(project, "cine"), [3840, 2160], "cine -> resolucion de secuencia")
    c.eq(core.resolve_resolution(project, "pant", "gen"), [1920, 1080], "pant/gen -> de la variante")
    c.eq(core.resolve_resolution(project, "pant", "callao"), [1080, 1080], "pant/callao -> de la variante")
    c.eq(core.resolve_resolution(project, "nope"), None, "secuencia inexistente -> None")


def test_build_output(c: Checker) -> None:
    print("\n[test_build_output]")
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        project = sample_project()
        out = core.build_output(root, project, "pant", "0010", "i2v", "v001", variant="gen")

        c.eq(out["base"], "tot_pant_gen_0010_i2v_v001", "base corta")
        c.eq(
            out["prefix"],
            "PROJECTS/TOT_Totie/pant/gen/0010_boca/02_WORK/v001/tot_pant_gen_0010_i2v_v001",
            "prefijo relativo con barras normales",
        )
        c.ok(out["out_dir"].is_absolute(), "out_dir absoluto")
        c.ok(core.is_within(root, out["out_dir"]), "out_dir dentro del root")
        c.ok("\\" not in out["prefix"], "prefijo sin backslashes (ComfyUI)")

        cine = core.build_output(root, project, "cine", "0010", "upscale", "v012")
        c.eq(
            cine["prefix"],
            "PROJECTS/TOT_Totie/cine/0010_cine/02_WORK/v012/tot_cine_0010_upscale_v012",
            "prefijo sin variante",
        )

        c.raises(ValueError, lambda: core.build_output(root, project, "cine", "0010", "i2v", "1"),
                 "version invalida")


def test_ensure_shot_dirs(c: Checker) -> None:
    print("\n[test_ensure_shot_dirs]")
    with tempfile.TemporaryDirectory() as tmp:
        shot = Path(tmp) / "0010_boca"
        core.ensure_shot_dirs(shot)
        for sub in core.SHOT_SUBDIRS:
            c.ok((shot / sub).is_dir(), f"ensure_shot_dirs crea {sub}")
        c.ok((shot / "_NOTES.md").is_file(), "ensure_shot_dirs crea _NOTES.md")


def test_cos_path_node(c: Checker) -> None:
    print("\n[test_cos_path_node]  (smoke, folder_paths simulado)")
    import importlib
    import types

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        project = sample_project()
        core.build_skeleton(root, project)
        core.write_project(root, project)

        fake = types.ModuleType("folder_paths")
        fake.get_output_directory = lambda: str(root)
        previous = sys.modules.get("folder_paths")
        sys.modules["folder_paths"] = fake
        try:
            import cos.nodes_path as nodes_path

            importlib.reload(nodes_path)
            node = nodes_path.COSPath()
            out = node.run(
                project, "pant", "0010", "i2v", "new",
                variant="gen", model="minimaxh3", seed=1234,
                prompt={"1": {"class_type": "KSampler"}},
                extra_pnginfo={"workflow": {"nodes": []}},
            )
        finally:
            if previous is None:
                sys.modules.pop("folder_paths", None)
            else:
                sys.modules["folder_paths"] = previous

        exr, video, png, version, out_dir, info = out
        c.eq(
            exr,
            "PROJECTS/TOT_Totie/pant/gen/0010_boca/02_WORK/v001/tot_pant_gen_0010_i2v_v001",
            "prefijo EXR",
        )
        c.eq(video, exr, "video_prefix = exr_prefix")
        c.eq(png, exr, "png_prefix = exr_prefix")
        c.eq(version, "v001", "version nueva")
        c.ok(Path(out_dir).is_dir(), "carpeta de salida creada")

        meta_file = Path(out_dir) / "tot_pant_gen_0010_i2v_v001_meta.json"
        c.ok(meta_file.is_file(), "sidecar escrito")
        meta = json.loads(meta_file.read_text(encoding="utf-8"))
        c.eq(meta["seed"], 1234, "seed en el sidecar")
        c.eq(meta["model"], "minimaxh3", "modelo en el sidecar")
        c.eq(meta["resolution"], [1920, 1080], "resolucion desde project.json")
        c.eq(meta["variant"], "gen", "variante en el sidecar")
        c.eq(meta["task"], "i2v", "task en el sidecar")
        c.eq(meta["workflow"], {"nodes": []}, "workflow embebido")
        c.eq(meta["prompt"], {"1": {"class_type": "KSampler"}}, "prompt embebido")
        c.ok("tot_pant_gen_0010_i2v_v001" in info, "info legible")

        state = core.load_state(Path(out_dir).parent.parent)
        c.eq(state["current_version"], "v001", "_state.json actualizado")
        c.eq(state["history"][0]["tasks"], ["i2v"], "task registrada en el historial")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    c = Checker()

    print("=" * 70)
    print("COS — Validator (Fases 0-2: core, COS Project, COS Path)")
    print("=" * 70)

    test_slug(c)
    test_build_filename(c)
    test_validate_component(c)
    test_skeleton(c)
    test_version_current(c)
    test_version_new(c)
    test_state_idempotent(c)
    test_sidecar(c)
    test_project_json_roundtrip(c)
    test_approve_copy(c)
    test_traversal(c)
    test_render_project_md(c)
    test_parse_inputs(c)
    test_build_project_dict(c)
    test_resolve_shot_dir(c)
    test_resolve_resolution(c)
    test_build_output(c)
    test_ensure_shot_dirs(c)
    test_cos_path_node(c)

    print("\n" + "=" * 70)
    if c.failures == 0:
        print("TODOS LOS TESTS PASARON — COS core OK")
        print("=" * 70)
        return 0
    print(f"{c.failures} FALLOS detectados — revisar arriba")
    print("=" * 70)
    return 1


if __name__ == "__main__":
    sys.exit(main())
