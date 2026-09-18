"""
COS — Standalone Validator (v2)
===============================

Tests the pure logic of ``cos/core.py`` (Comfy Output Standard, grammar
compatible with the studio pipeline) without ComfyUI, torch or network access.
The ComfyUI nodes are smoke-tested with a simulated ``folder_paths`` module.

Uso
---
    python validate_cos.py

Devuelve codigo de salida != 0 si hay fallos, util para CI/CD.
"""

from __future__ import annotations

import json
import sys
import tempfile
from contextlib import contextmanager
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


def sample_config() -> dict:
    return core.build_project_config(
        "TOTIE",
        fps=24,
        width=3840,
        height=2160,
        entities={
            "TOTIE_003_0030": {"entity_type": "shot"},
            "TOTIE_003_0010": {"entity_type": "shot"},
            "TOTIE_CHR_Totie": {"entity_type": "asset"},
        },
        root="A:/PROJECTS/COS",
    )


@contextmanager
def fake_comfy(output_dir):
    """Import the COS nodes with a simulated ``folder_paths`` module."""
    import importlib
    import types

    fake = types.ModuleType("folder_paths")
    fake.get_output_directory = lambda: str(output_dir)
    previous = sys.modules.get("folder_paths")
    sys.modules["folder_paths"] = fake
    try:
        import cos.nodes_project as nodes_project
        import cos.nodes_path as nodes_path

        importlib.reload(nodes_project)
        importlib.reload(nodes_path)
        yield types.SimpleNamespace(
            project=nodes_project, path=nodes_path,
            COSProject=nodes_project.COSProject,
            COSShot=nodes_path.COSShot,
            COSPath=nodes_path.COSPath,
            COSApprove=nodes_path.COSApprove,
        )
    finally:
        if previous is None:
            sys.modules.pop("folder_paths", None)
        else:
            sys.modules["folder_paths"] = previous


# ---------------------------------------------------------------------------
# Grammar
# ---------------------------------------------------------------------------

def test_versions(c: Checker) -> None:
    print("\n[test_versions]")
    c.eq(core.format_version(1), "v0001", "1 -> v0001 (4 digitos)")
    c.eq(core.format_version(25), "v0025", "25 -> v0025")
    c.eq(core.format_version(1234), "v1234", "1234 -> v1234")
    c.eq(core.parse_version("v0025"), 25, "v0025 -> 25")
    c.eq(core.parse_version("v0001"), 1, "v0001 -> 1")
    c.raises(ValueError, lambda: core.format_version(0), "version 0 invalida")
    c.raises(ValueError, lambda: core.parse_version("1"), "sin formato v####")
    c.raises(ValueError, lambda: core.parse_version("v1"), "v1 no es v####")


def test_validation(c: Checker) -> None:
    print("\n[test_validation]")
    c.eq(core.validate_project("TOTIE"), "TOTIE", "project valido")
    c.raises(ValueError, lambda: core.validate_project("TOT-IE"), "project con guion")
    c.raises(ValueError, lambda: core.validate_project(""), "project vacio")

    c.eq(core.validate_token("0030", "shot"), "0030", "token valido")
    c.raises(ValueError, lambda: core.validate_token("../etc", "shot"), "rechaza '..'")
    c.raises(ValueError, lambda: core.validate_token("a/b", "shot"), "rechaza '/'")
    c.raises(ValueError, lambda: core.validate_token("C:foo", "shot"), "rechaza ':'")
    c.raises(ValueError, lambda: core.validate_token("bad*", "shot"), "rechaza '*'")

    c.eq(core.normalize_task("I2V"), "i2v", "task a minusculas")
    c.eq(core.normalize_task("inpaint mask"), "inpaint_mask", "task con espacio")
    c.eq(core.normalize_description("Callao"), "Callao", "description valida")
    c.eq(core.normalize_description("  "), None, "description vacia -> None")
    c.eq(core.normalize_description(None), None, "description None -> None")

    c.eq(core.validate_artist("Ivan Cadenas"), "Ivan Cadenas", "artista con espacio")
    c.raises(ValueError, lambda: core.validate_artist("../x"), "artista con traversal")
    c.raises(ValueError, lambda: core.validate_artist(""), "artista vacio")


def test_grammar(c: Checker) -> None:
    print("\n[test_grammar]")
    c.eq(core.build_entity("TOTIE", "003", "0030"), "TOTIE_003_0030", "entity")
    c.eq(core.build_entity("TOTIE", "DZN", "0010"), "TOTIE_DZN_0010", "entity con secuencia alfanumerica")

    tokens = core.split_entity("TOTIE_003_0030")
    c.eq(tokens["project"], "TOTIE", "split project")
    c.eq(tokens["sequence"], "003", "split sequence")
    c.eq(tokens["shot"], "0030", "split shot")
    c.eq(core.split_entity("TOTIE_DZN_0010")["sequence"], "DZN", "split DZN")
    c.raises(ValueError, lambda: core.split_entity("TOTIE"), "entity incompleta")

    c.eq(core.build_group("TOTIE_003_0030", "i2v"), "TOTIE_003_0030_i2v", "group sin description")
    c.eq(
        core.build_group("TOTIE_003_0030", "i2v", "callao"),
        "TOTIE_003_0030_i2v_callao",
        "group con description",
    )
    c.eq(
        core.build_version_name("TOTIE_003_0030", "i2v", "v0001", "callao"),
        "TOTIE_003_0030_i2v_callao_v0001",
        "version name",
    )
    c.eq(
        core.build_version_name("TOTIE_003_0030", "upscale", "v0012"),
        "TOTIE_003_0030_upscale_v0012",
        "version name sin description",
    )
    c.raises(
        ValueError,
        lambda: core.build_version_name("TOTIE_003_0030", "i2v", "1"),
        "version sin formato v####",
    )


# ---------------------------------------------------------------------------
# Config + paths
# ---------------------------------------------------------------------------

def test_project_config(c: Checker) -> None:
    print("\n[test_project_config]")
    config = sample_config()
    c.eq(config["name"], "TOTIE", "name")
    c.eq(config["fps"], 24, "fps")
    c.eq(config["formats"][0]["width"], 3840, "width del formato")
    c.eq(config["masking_ratio"], {"name": "TOTIE", "width": 16, "height": 9}, "masking 16:9")
    c.eq(config["default_handles_in"], 8, "handles in")
    c.eq(config["directory"]["windows"], "A:/PROJECTS/COS/TOTIE", "directory")
    c.eq(list(config["entities"]), ["TOTIE_003_0030", "TOTIE_003_0010", "TOTIE_CHR_Totie"], "entidades")

    with tempfile.TemporaryDirectory() as tmp:
        path = core.write_project_config(tmp, config)
        c.ok(path.name == "TOTIE.json", "config escrito como <PROJECT>.json")
        loaded = core.load_project_config(path)
        c.eq(loaded["name"], "TOTIE", "roundtrip name")
        c.eq(len(core.list_projects(tmp)), 1, "list_projects encuentra 1")

        md = core.write_project_md(tmp, config)
        text = md.read_text(encoding="utf-8")
        c.ok("| TOTIE_003_0030 | shot | 003 | 0030 |" in text, "_PROJECT.md con la entidad")

    c.eq(core.parse_entities("TOTIE_003_0030, TOTIE_DZN_0010"), {
        "TOTIE_003_0030": {"entity_type": "shot"},
        "TOTIE_DZN_0010": {"entity_type": "shot"},
    }, "parse_entities")
    c.eq(
        core.parse_entities("TOTIE_CHR_Totie:asset")["TOTIE_CHR_Totie"]["entity_type"],
        "asset",
        "parse_entities con tipo",
    )
    c.raises(ValueError, lambda: core.parse_entities("TOTIE"), "entity incompleta")
    c.raises(ValueError, lambda: core.parse_entities("TOTIE_003_0030:nope"), "tipo invalido")


def test_paths(c: Checker) -> None:
    print("\n[test_paths]")
    root = Path("A:/PROJECTS/COS")
    c.eq(
        core.entity_dir(root, "TOTIE", "shot", "TOTIE_003_0030").as_posix(),
        "A:/PROJECTS/COS/TOTIE/shot/TOTIE_003_0030",
        "entity_dir",
    )
    c.eq(
        core.work_dir(root, "TOTIE", "shot", "TOTIE_003_0030", "i2v", "Ivan Cadenas").as_posix(),
        "A:/PROJECTS/COS/TOTIE/shot/TOTIE_003_0030/work/i2v/Ivan Cadenas",
        "work_dir con artista",
    )
    c.eq(
        core.version_task_dir(root, "TOTIE", "shot", "TOTIE_003_0030", "i2v").as_posix(),
        "A:/PROJECTS/COS/TOTIE/shot/TOTIE_003_0030/version/i2v",
        "version_task_dir",
    )
    vpath = core.version_dir(
        root, "TOTIE", "shot", "TOTIE_003_0030", "i2v", "TOTIE_003_0030_i2v_v0001"
    )
    c.eq(
        vpath.as_posix(),
        "A:/PROJECTS/COS/TOTIE/shot/TOTIE_003_0030/version/i2v/TOTIE_003_0030_i2v_v0001",
        "version_dir",
    )
    c.eq(core.pack_dir(vpath, "exr").as_posix(), f"{vpath.as_posix()}/_exr", "pack_dir")
    c.eq(core.source_dir(vpath).name, "_source", "source_dir")
    c.eq(
        core.publish_task_dir(root, "TOTIE", "shot", "TOTIE_003_0030", "i2v").as_posix(),
        "A:/PROJECTS/COS/TOTIE/shot/TOTIE_003_0030/publish/i2v",
        "publish_task_dir",
    )
    c.raises(ValueError, lambda: core.pack_dir(vpath, "nope"), "pack desconocido")
    c.raises(ValueError, lambda: core.entity_dir(root, "TOTIE", "nope", "X_Y_Z"), "entity_type invalido")


def test_skeleton(c: Checker) -> None:
    print("\n[test_skeleton]")
    with tempfile.TemporaryDirectory() as tmp:
        config = sample_config()
        core.ensure_project(tmp, config)
        pdir = Path(tmp) / "TOTIE"
        c.ok(pdir.is_dir(), "carpeta del proyecto")
        for sub in ("work", "version", "publish"):
            c.ok((pdir / "shot" / "TOTIE_003_0030" / sub).is_dir(), f"shot/TOTIE_003_0030/{sub}")
        c.ok((pdir / "asset" / "TOTIE_CHR_Totie" / "version").is_dir(), "asset/TOTIE_CHR_Totie/version")

        before = sorted(str(p) for p in pdir.rglob("*"))
        core.ensure_project(tmp, config)
        after = sorted(str(p) for p in pdir.rglob("*"))
        c.ok(after == before, "ensure_project idempotente")

        core.ensure_entity(tmp, "TOTIE", "shot", "TOTIE_999_9999")
        c.ok((pdir / "shot" / "TOTIE_999_9999" / "work").is_dir(), "ensure_entity crea el arbol")


def test_versions_resolution(c: Checker) -> None:
    print("\n[test_versions_resolution]")
    with tempfile.TemporaryDirectory() as tmp:
        vtask = Path(tmp) / "version" / "i2v"
        vtask.mkdir(parents=True)
        c.eq(core.existing_versions(vtask), [], "sin versiones")
        c.eq(core.current_version(vtask), None, "current_version sin nada -> None")

        (vtask / "TOTIE_003_0030_i2v_v0001").mkdir()
        (vtask / "TOTIE_003_0030_i2v_v0002").mkdir()
        c.eq(core.existing_versions(vtask), [1, 2], "detecta v0001 y v0002")
        c.eq(core.current_version(vtask), "v0002", "current = la mas alta")
        c.ok(not (vtask / "TOTIE_003_0030_i2v_v0003").exists(), "current no crea nada")

        c.eq(core.resolve_version(vtask, "new"), "v0003", "new = max + 1")
        c.eq(core.resolve_version(vtask, "current"), "v0002", "current")
        c.raises(ValueError, lambda: core.resolve_version(vtask, "nope"), "modo invalido")

        empty = Path(tmp) / "version" / "upscale"
        empty.mkdir(parents=True)
        c.eq(core.resolve_version(empty, "current"), "v0001", "current sin versiones -> v0001")


def test_build_output(c: Checker) -> None:
    print("\n[test_build_output]")
    with tempfile.TemporaryDirectory() as tmp:
        config = sample_config()
        out = core.build_output(tmp, config, "TOTIE_003_0030", "i2v", "v0001", "callao")
        c.eq(out["version_name"], "TOTIE_003_0030_i2v_callao_v0001", "version_name")
        c.eq(out["group"], "TOTIE_003_0030_i2v_callao", "group")
        c.eq(
            out["prefixes"]["png"],
            "TOTIE/shot/TOTIE_003_0030/version/i2v/TOTIE_003_0030_i2v_callao_v0001/_png/"
            "TOTIE_003_0030_i2v_callao_v0001",
            "prefijo png",
        )
        c.eq(
            out["prefixes"]["mov"],
            "TOTIE/shot/TOTIE_003_0030/version/i2v/TOTIE_003_0030_i2v_callao_v0001/_mov/"
            "TOTIE_003_0030_i2v_callao_v0001",
            "prefijo mov",
        )
        c.ok("\\" not in out["prefixes"]["exr"], "prefijo con barras normales (ComfyUI)")
        c.ok(core.is_within(tmp, out["version_path"]), "version dentro del root")

        asset = core.build_output(tmp, config, "TOTIE_CHR_Totie", "t2i", "v0001", entity_type="asset")
        c.eq(
            asset["prefixes"]["exr"],
            "TOTIE/asset/TOTIE_CHR_Totie/version/t2i/TOTIE_CHR_Totie_t2i_v0001/_exr/"
            "TOTIE_CHR_Totie_t2i_v0001",
            "prefijo de asset",
        )
        c.raises(
            ValueError,
            lambda: core.build_output(tmp, config, "TOTIE_003_0030", "i2v", "1"),
            "version invalida",
        )


# ---------------------------------------------------------------------------
# Sidecars
# ---------------------------------------------------------------------------

def test_version_meta(c: Checker) -> None:
    print("\n[test_version_meta]")
    config = sample_config()
    meta = core.build_version_meta(
        config, "TOTIE_003_0030", "i2v", "v0025",
        entity_type="shot", description="callao", user="Mike",
        dependencies=["TOTIE_003_0030_i2i_gen_v0001"],
        comfy={"model": "minimaxh3", "seed": 87654321, "resolution": [3840, 2160]},
        date="2026/09/18 13:44:00",
    )
    keys = list(meta.keys())
    for key in ("date", "dependencies", "description", "entity", "entity_type",
                "episode", "group", "name", "project", "scene", "sequence",
                "task", "user", "version"):
        c.ok(key in meta, f"clave del pipeline: {key}")
    c.eq(keys[-1], "comfy", "el bloque comfy va al final")
    c.eq(meta["entity"], "TOTIE_003_0030", "entity")
    c.eq(meta["entity_type"], "shot", "entity_type")
    c.eq(meta["sequence"], "003", "sequence")
    c.eq(meta["scene"], "", "scene vacio")
    c.eq(meta["episode"], "", "episode vacio")
    c.eq(meta["group"], "TOTIE_003_0030_i2v_callao", "group")
    c.eq(meta["name"], "TOTIE_003_0030_i2v_callao_v0025", "name")
    c.eq(meta["version"], 25, "version como int")
    c.eq(meta["description"], "callao", "description")
    c.eq(meta["dependencies"], ["TOTIE_003_0030_i2i_gen_v0001"], "dependencies")
    c.eq(meta["comfy"]["seed"], 87654321, "bloque comfy")

    with tempfile.TemporaryDirectory() as tmp:
        path = core.write_version_meta(tmp, meta["name"], meta)
        c.ok(path.name == "TOTIE_003_0030_i2v_callao_v0025.json", "nombre del sidecar de version")
        c.eq(json.loads(path.read_text(encoding="utf-8"))["version"], 25, "sidecar releible")

        src = core.write_source_copy(tmp, meta["name"], {"nodes": []})
        c.eq(src.parent.name, "_source", "_source creado")
        c.ok(src.is_file(), "workflow copiado a _source")
        c.eq(core.write_source_copy(tmp, meta["name"], None), None, "sin workflow no escribe _source")


def test_output_meta(c: Checker) -> None:
    print("\n[test_output_meta]")
    config = sample_config()
    meta = core.build_output_meta("exr", "TOTIE_003_0030_i2v_v0001", config)
    c.eq(meta["name"], "exr", "nombre del pack")
    c.eq(meta["single"], False, "single")
    c.eq(meta["source"], "TOTIE_003_0030_i2v_v0001.json", "source")
    attrs = meta["attributes"]
    c.eq(attrs["ext"], "exr", "ext")
    c.eq(attrs["width"], 3840, "width del config")
    c.eq(attrs["height"], 2160, "height del config")
    c.eq(attrs["colorspace"], "ACES - ACEScg", "colorspace exr")
    c.eq(attrs["bit_depth"], 32, "bit depth exr")
    c.eq(attrs["software"], "comfyui", "software")
    c.ok("rgba.red" in attrs["channels"], "canales exr")

    mov = core.build_output_meta("mov", "V", config)["attributes"]
    c.eq(mov["codec"], "hevc", "codec del mov")
    c.eq(mov["ext"], "mp4", "ext del mov")
    c.raises(ValueError, lambda: core.build_output_meta("nope", "V", config), "pack desconocido")


def test_output_sidecars(c: Checker) -> None:
    print("\n[test_output_sidecars]")
    with tempfile.TemporaryDirectory() as tmp:
        config = sample_config()
        vpath = Path(tmp) / "TOTIE_003_0030_i2v_v0001"
        name = "TOTIE_003_0030_i2v_v0001"
        (vpath / "_png").mkdir(parents=True)
        (vpath / "_mov").mkdir()
        (vpath / "_png" / f"{name}_00001_.png").write_text("png")
        (vpath / "_mov" / f"{name}_00001_.mp4").write_text("mp4")

        written = core.write_output_sidecars(vpath, name, config)
        names = sorted(p.name for p in written)
        c.eq(names, ["_mov.json", "_png.json"], "solo escribe sidecars de packs existentes")
        c.ok((vpath / "_png" / "_png.json").is_file(), "_png.json creado")
        c.ok(not (vpath / "_exr" / "_exr.json").exists(), "no inventa el pack exr")
        data = json.loads((vpath / "_mov" / "_mov.json").read_text(encoding="utf-8"))
        c.eq(data["attributes"]["codec"], "hevc", "atributos del mov")


def test_publish_version(c: Checker) -> None:
    print("\n[test_publish_version]")
    with tempfile.TemporaryDirectory() as tmp:
        vpath = Path(tmp) / "TOTIE_003_0030_i2v_v0001"
        (vpath / "_png").mkdir(parents=True)
        (vpath / "TOTIE_003_0030_i2v_v0001.json").write_text("{}")
        (vpath / "_png" / "TOTIE_003_0030_i2v_v0001_00001_.png").write_text("render")

        dest = Path(tmp) / "publish" / "i2v" / "TOTIE_003_0030_i2v_v0001"
        copied = core.publish_version(vpath, dest)
        c.eq(sorted(p.name for p in copied), ["TOTIE_003_0030_i2v_v0001.json", "_png"], "copia sidecar + pack")
        c.ok((dest / "_png" / "TOTIE_003_0030_i2v_v0001_00001_.png").is_file(), "render publicado")
        c.ok((vpath / "_png" / "TOTIE_003_0030_i2v_v0001_00001_.png").is_file(),
             "el original permanece (copy, no move)")
        c.raises(FileNotFoundError, lambda: core.publish_version(Path(tmp) / "nope", dest),
                 "version inexistente")


def test_dependencies_and_traversal(c: Checker) -> None:
    print("\n[test_dependencies_and_traversal]")
    c.eq(
        core.parse_dependencies("A_v0001, B_v0002\nC_v0003; D_v0004"),
        ["A_v0001", "B_v0002", "C_v0003", "D_v0004"],
        "parse_dependencies",
    )
    c.eq(core.parse_dependencies(""), [], "dependencies vacias")
    c.eq(core.parse_dependencies("   ,  "), [], "solo separadores")

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        core.ensure_project(root, sample_config())
        c.ok(core.is_within(root, root / "TOTIE" / "shot"), "ruta interna OK")
        c.ok(not core.is_within(root, root / ".." / "evil"), "ruta externa rechazada")
        c.ok(not core.is_within(root, Path(tmp).parent), "padre rechazado")


# ---------------------------------------------------------------------------
# Nodes (smoke, folder_paths simulado)
# ---------------------------------------------------------------------------

def test_cos_project_node(c: Checker) -> None:
    print("\n[test_cos_project_node]  (smoke, folder_paths simulado)")
    with tempfile.TemporaryDirectory() as tmp:
        with fake_comfy(tmp) as nodes:
            node = nodes.COSProject()
            config, cfg_path, info = node.run(
                "create", "TOTIE", 24, 3840, 2160, "TOTIE_003_0030,TOTIE_CHR_Totie:asset"
            )
        c.eq(config["name"], "TOTIE", "config creado")
        c.ok(Path(cfg_path).is_file(), "TOTIE.json escrito")
        c.ok((Path(tmp) / "TOTIE" / "shot" / "TOTIE_003_0030" / "work").is_dir(), "arbol del shot")
        c.ok((Path(tmp) / "TOTIE" / "asset" / "TOTIE_CHR_Totie" / "version").is_dir(), "arbol del asset")
        c.ok("2 entidades" in info, "info con el recuento")

        with fake_comfy(tmp) as nodes:
            loaded, _, info2 = nodes.COSProject().run(
                "load", "TOTIE", 24, 1920, 1080, "OTRO_X_Y"
            )
        c.eq(loaded["formats"][0]["width"], 3840, "load ignora los inputs y lee el config")
        c.ok("loaded" in info2, "info = loaded")


def test_cos_shot_node(c: Checker) -> None:
    print("\n[test_cos_shot_node]  (smoke, folder_paths simulado)")
    with tempfile.TemporaryDirectory() as tmp:
        with fake_comfy(tmp) as nodes:
            config, _, _ = nodes.COSProject().run("create", "TOTIE", 24, 3840, 2160, "TOTIE_003_0030")
            shot, shot_path, info = nodes.COSShot().run(config, "TOTIE_004_0010")
        c.eq(shot["entity"], "TOTIE_004_0010", "entity del COS_SHOT")
        c.eq(shot["sequence"], "004", "sequence")
        c.eq(shot["shot"], "0010", "shot")
        c.ok((Path(shot_path) / "version").is_dir(), "arbol creado")
        c.ok("registrado" in info, "avisa del registro")

        saved = core.load_project_config(core.project_config_path(tmp, "TOTIE"))
        c.ok("TOTIE_004_0010" in saved["entities"], "entidad registrada en el config")

        with fake_comfy(tmp) as nodes:
            shot2, _, info2 = nodes.COSShot().run(saved, "TOTIE_003_0030")
        c.eq(shot2["entity"], "TOTIE_003_0030", "entidad existente")
        c.ok("registrado" not in info2, "no re-registra")


def test_cos_path_node(c: Checker) -> None:
    print("\n[test_cos_path_node]  (smoke, folder_paths simulado)")
    with tempfile.TemporaryDirectory() as tmp:
        with fake_comfy(tmp) as nodes:
            config, _, _ = nodes.COSProject().run("create", "TOTIE", 24, 3840, 2160, "TOTIE_003_0030")
            shot, _, _ = nodes.COSShot().run(config, "TOTIE_003_0030")
            out = nodes.COSPath().run(
                config, "TOTIE_003_0030", "i2v", "new",
                shot=shot, description="callao", model="minimaxh3", seed=1234,
                artist="Mike", dependencies="TOTIE_003_0030_i2i_gen_v0001",
                prompt={"1": {"class_type": "KSampler"}},
                extra_pnginfo={"workflow": {"nodes": []}},
            )
        png, exr, mov, version, out_dir, info = out
        c.eq(version, "v0001", "primera version")
        c.eq(
            png,
            "TOTIE/shot/TOTIE_003_0030/version/i2v/TOTIE_003_0030_i2v_callao_v0001/_png/"
            "TOTIE_003_0030_i2v_callao_v0001",
            "prefijo png",
        )
        c.ok(exr.endswith("_exr/TOTIE_003_0030_i2v_callao_v0001"), "prefijo exr")
        c.ok(mov.endswith("_mov/TOTIE_003_0030_i2v_callao_v0001"), "prefijo mov")
        c.ok(Path(out_dir).is_dir(), "carpeta de version creada")

        meta_path = Path(out_dir) / "TOTIE_003_0030_i2v_callao_v0001.json"
        c.ok(meta_path.is_file(), "sidecar de version escrito")
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        c.eq(meta["name"], "TOTIE_003_0030_i2v_callao_v0001", "name del sidecar")
        c.eq(meta["entity"], "TOTIE_003_0030", "entity")
        c.eq(meta["task"], "i2v", "task")
        c.eq(meta["description"], "callao", "description")
        c.eq(meta["sequence"], "003", "sequence")
        c.eq(meta["user"], "Mike", "user")
        c.eq(meta["version"], 1, "version int")
        c.eq(meta["dependencies"], ["TOTIE_003_0030_i2i_gen_v0001"], "dependencies")
        c.eq(meta["comfy"]["model"], "minimaxh3", "modelo en comfy")
        c.eq(meta["comfy"]["seed"], 1234, "seed en comfy")
        c.eq(meta["comfy"]["resolution"], [3840, 2160], "resolucion del config")
        c.eq(meta["comfy"]["workflow"], {"nodes": []}, "workflow en comfy")

        workfile = Path(tmp) / "TOTIE" / "shot" / "TOTIE_003_0030" / "work" / "i2v" / "Mike"
        c.ok((workfile / "TOTIE_003_0030_i2v_callao_v0001.json").is_file(), "workfile guardado")
        c.ok((Path(out_dir) / "_source" / "TOTIE_003_0030_i2v_callao_v0001.json").is_file(),
             "copia en _source")

        with fake_comfy(tmp) as nodes:
            out2 = nodes.COSPath().run(config, "TOTIE_003_0030", "i2v", "new", description="callao")
        c.eq(out2[3], "v0002", "segunda pasada -> v0002")
        with fake_comfy(tmp) as nodes:
            out3 = nodes.COSPath().run(config, "TOTIE_003_0030", "i2v", "current", description="callao")
        c.eq(out3[3], "v0002", "current reusa la ultima")


def test_cos_approve_node(c: Checker) -> None:
    print("\n[test_cos_approve_node]  (smoke, folder_paths simulado)")
    with tempfile.TemporaryDirectory() as tmp:
        with fake_comfy(tmp) as nodes:
            config, _, _ = nodes.COSProject().run("create", "TOTIE", 24, 3840, 2160, "TOTIE_003_0030")
            shot, _, _ = nodes.COSShot().run(config, "TOTIE_003_0030")
            _, _, _, version, out_dir, _ = nodes.COSPath().run(
                config, "TOTIE_003_0030", "i2v", "new", shot=shot, description="callao",
                extra_pnginfo={"workflow": {"nodes": []}},
            )
            vpath = Path(out_dir)
            (vpath / "_png").mkdir(parents=True, exist_ok=True)
            (vpath / "_mov").mkdir(exist_ok=True)
            (vpath / "_png" / f"TOTIE_003_0030_i2v_callao_{version}_00001_.png").write_text("still")
            (vpath / "_mov" / f"TOTIE_003_0030_i2v_callao_{version}_00001_.mp4").write_text("mov")

            published, count, info = nodes.COSApprove().run(
                "i2v", shot=shot, version="current", description="callao"
            )
        names = published.splitlines()
        c.eq(count, 4, "publica sidecar + _source + _png + _mov")
        c.ok("TOTIE_003_0030_i2v_callao_v0001.json" in names, "sidecar de version publicado")
        c.ok("_png" in names, "pack png publicado")

        dest = Path(tmp) / "TOTIE" / "shot" / "TOTIE_003_0030" / "publish" / "i2v" / "TOTIE_003_0030_i2v_callao_v0001"
        c.ok((dest / "_png" / "TOTIE_003_0030_i2v_callao_v0001_00001_.png").is_file(), "render en publish")
        c.ok((dest / "_png" / "_png.json").is_file(), "sidecar de salida en publish")
        c.ok((vpath / "_png" / "TOTIE_003_0030_i2v_callao_v0001_00001_.png").is_file(),
             "el original permanece")
        c.ok("publish" in info, "info legible")

        with fake_comfy(tmp) as nodes:
            c.raises(
                ValueError,
                lambda: nodes.COSApprove().run("i2v", shot_path=str(Path(tmp) / "nope" / "shot" / "X_Y_Z")),
                "entidad sin versiones -> ValueError",
            )
            c.raises(ValueError, lambda: nodes.COSApprove().run("i2v"), "sin shot ni shot_path")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    c = Checker()

    print("=" * 70)
    print("COS — Validator v2 (gramatica compatible con el pipeline)")
    print("=" * 70)

    test_versions(c)
    test_validation(c)
    test_grammar(c)
    test_project_config(c)
    test_paths(c)
    test_skeleton(c)
    test_versions_resolution(c)
    test_build_output(c)
    test_version_meta(c)
    test_output_meta(c)
    test_output_sidecars(c)
    test_publish_version(c)
    test_dependencies_and_traversal(c)
    test_cos_project_node(c)
    test_cos_shot_node(c)
    test_cos_path_node(c)
    test_cos_approve_node(c)

    print("\n" + "=" * 70)
    if c.failures == 0:
        print("TODOS LOS TESTS PASARON — COS core v2 OK")
        print("=" * 70)
        return 0
    print(f"{c.failures} FALLOS detectados — revisar arriba")
    print("=" * 70)
    return 1


if __name__ == "__main__":
    sys.exit(main())
