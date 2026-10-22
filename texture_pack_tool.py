#!/usr/bin/env python3
"""Texture Pack Editor & Loader for Unity Game (Unity)."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
import zipfile
from io import BytesIO
from pathlib import Path
from typing import Dict, List, Optional

try:
    import UnityPy
except Exception as e:  # pragma: no cover
    raise SystemExit(f"UnityPy is required: {e}")

try:
    import cv2
    _CV2_OK = True
except Exception:
    _CV2_OK = False

from PIL import Image

GAME_DATA_DIRNAME = None  # auto-detect any *_Data folder
CORE_PACK_DIRNAME = "CorePack"
DEFAULT_EXTRACT_DIR = "ExtractedTextures"
PACK_MANIFEST_NAME = "manifest.json"


def sanitize(name: str) -> str:
    keep = []
    for ch in name:
        if ch.isalnum() or ch in "._-":
            keep.append(ch)
        else:
            keep.append("_")
    s = "".join(keep).strip("._")
    return s or "texture"


def find_game_dir(user: Optional[str] = None) -> Path:
    def is_data_dir(p: Path) -> bool:
        return p.is_dir() and (list(p.glob("*.assets")) or (p / "globalgamemanagers").is_file())

    if user:
        p = Path(user)
        if is_data_dir(p):
            return p.resolve()
        # search inside provided path
        for c in p.iterdir() if p.is_dir() else []:
            if is_data_dir(c):
                return c.resolve()
        # maybe user passed game root with a *_Data folder
        for c in (p.glob("*_Data") if p.is_dir() else []):
            if is_data_dir(c):
                return c.resolve()
        raise SystemExit(f"Game data directory not found: {user}")

    cwd = Path.cwd()
    if is_data_dir(cwd):
        return cwd.resolve()
    # search cwd for a *_Data folder
    for p in sorted(cwd.iterdir()):
        if p.is_dir() and (p.name.endswith("_Data") or is_data_dir(p)):
            if is_data_dir(p):
                return p.resolve()
    # search one level deeper
    for p in cwd.iterdir():
        if p.is_dir():
            for c in p.iterdir():
                if c.is_dir() and is_data_dir(c):
                    return c.resolve()
    raise SystemExit(
        "Could not find a Unity game data folder (*_Data with *.assets). "
        "Run from the game folder or pass --game-dir."
    )


def core_pack_dir(game_dir: Path) -> Path:
    return game_dir.parent / CORE_PACK_DIRNAME


def sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def extract_textures(game_dir: Path, out_dir: Path, verbose: bool = True) -> Path:
    out_dir = out_dir.resolve()
    tex_root = out_dir / "textures"
    audio_root = out_dir / "audio"
    if tex_root.exists():
        shutil.rmtree(tex_root)
    if audio_root.exists():
        shutil.rmtree(audio_root)
    tex_root.mkdir(parents=True, exist_ok=True)
    audio_root.mkdir(parents=True, exist_ok=True)

    manifest = {
        "game": "Unity Game",
        "version": 2,
        "source_game_data": str(game_dir),
        "entries": [],
    }

    asset_files = sorted(game_dir.glob("*.assets"))
    total_tex = 0
    total_aud = 0
    # Pass 1: textures (separate pass to avoid corrupting audio extraction)
    for asset_path in asset_files:
        if verbose:
            print(f"[extract] {asset_path.name}")
        try:
            env = UnityPy.load(str(asset_path))
        except Exception as e:
            print(f"  ! failed to load {asset_path.name}: {e}")
            continue
        for o in env.objects:
            if getattr(o.type, "name", "") != "Texture2D":
                continue
            try:
                d = o.read()
            except Exception as e:
                print(f"  ! read failed path_id={o.path_id}: {e}")
                continue
            if not getattr(d, "m_Width", 0) or not getattr(d, "m_Height", 0):
                continue
            name = getattr(d, "m_Name", "") or f"texture_{o.path_id}"
            safe = sanitize(name)
            rel = Path(asset_path.stem) / f"{safe}_{o.path_id}.png"
            file_path = tex_root / rel
            file_path.parent.mkdir(parents=True, exist_ok=True)
            try:
                img = d.image
                img.save(file_path, compress_level=1)
            except Exception as e:
                print(f"  ! export failed {name} ({o.path_id}): {e}")
                continue
            entry = {
                "type": "texture",
                "id": f"{asset_path.name}::{o.path_id}",
                "name": name,
                "asset": asset_path.name,
                "path_id": o.path_id,
                "width": int(d.m_Width),
                "height": int(d.m_Height),
                "format": int(d.m_TextureFormat),
                "file": str(Path("textures") / rel).replace(os.sep, "/"),
                "original_sha256": sha256_file(file_path),
            }
            manifest["entries"].append(entry)
            total_tex += 1

    # Pass 2: audio (fresh load to avoid fmod state corruption)
    for asset_path in asset_files:
        if verbose:
            print(f"[extract audio] {asset_path.name}")
        try:
            env = UnityPy.load(str(asset_path))
        except Exception as e:
            print(f"  ! failed to load {asset_path.name}: {e}")
            continue
        for o in env.objects:
            if getattr(o.type, "name", "") != "AudioClip":
                continue
            try:
                d = o.read()
            except Exception as e:
                print(f"  ! read failed path_id={o.path_id}: {e}")
                continue
            name = getattr(d, "m_Name", "") or f"audio_{o.path_id}"
            try:
                samples = d.samples
            except Exception as e:
                print(f"  ! audio extract failed {name} ({o.path_id}): {e}")
                continue
            if not samples:
                continue
            for sname, data in samples.items():
                safe = sanitize(sname)
                rel = Path(asset_path.stem) / f"{safe}_{o.path_id}{Path(sname).suffix or '.wav'}"
                file_path = audio_root / rel
                file_path.parent.mkdir(parents=True, exist_ok=True)
                file_path.write_bytes(data)
                entry = {
                    "type": "audio",
                    "id": f"{asset_path.name}::{o.path_id}",
                    "name": name,
                    "asset": asset_path.name,
                    "path_id": o.path_id,
                    "channels": int(d.m_Channels or 0),
                    "frequency": int(d.m_Frequency or 0),
                    "bits": int(d.m_BitsPerSample or 0),
                    "length": float(d.m_Length or 0),
                    "compression": int(d.m_CompressionFormat or 0),
                    "file": str(Path("audio") / rel).replace(os.sep, "/"),
                    "original_sha256": sha256_file(file_path),
                }
                manifest["entries"].append(entry)
                total_aud += 1
                break

    man_path = out_dir / PACK_MANIFEST_NAME
    with open(man_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)
    if verbose:
        print(f"[extract] exported {total_tex} textures and {total_aud} audio clips to {out_dir}")
    return out_dir

def load_manifest(directory: Path) -> dict:
    p = directory / PACK_MANIFEST_NAME
    if not p.is_file():
        raise SystemExit(f"Manifest not found: {p}")
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def build_pack(source_dir: Path, out_zip: Path, include_all: bool = False, verbose: bool = True) -> Path:
    source_dir = source_dir.resolve()
    manifest = load_manifest(source_dir)
    entries = manifest.get("entries", manifest.get("textures", []))
    chosen = []
    for t in entries:
        fpath = source_dir / t["file"]
        if not fpath.is_file():
            continue
        if include_all:
            chosen.append(t)
        else:
            if t.get("original_sha256") and sha256_file(fpath) != t["original_sha256"]:
                chosen.append(t)
            elif not t.get("original_sha256"):
                chosen.append(t)
    if not chosen:
        raise SystemExit("No changed textures found. Edit some PNGs or use --all.")

    out_zip = out_zip.resolve()
    out_zip.parent.mkdir(parents=True, exist_ok=True)
    if out_zip.exists():
        out_zip.unlink()

    pack_manifest = {
        "game": manifest.get("game", "Unity Game"),
        "version": 1,
        "base_manifest": manifest.get("source_game_data", ""),
        "entries": [],
    }
    with zipfile.ZipFile(out_zip, "w", zipfile.ZIP_DEFLATED) as z:
        for t in chosen:
            fpath = source_dir / t["file"]
            arc = t["file"]
            z.write(fpath, arc)
            e = {
                "id": t["id"],
                "name": t["name"],
                "asset": t["asset"],
                "path_id": t["path_id"],
                "type": t.get("type", "texture"),
                "file": arc,
            }
            if t.get("type", "texture") == "texture":
                e.update({"width": t.get("width"), "height": t.get("height"), "format": t.get("format")})
            else:
                e.update({"channels": t.get("channels"), "frequency": t.get("frequency"),
                          "bits": t.get("bits"), "length": t.get("length"),
                          "compression": t.get("compression")})
            pack_manifest["entries"].append(e)
        z.writestr(PACK_MANIFEST_NAME, json.dumps(pack_manifest, indent=2))

    if verbose:
        print(f"[build] packed {len(chosen)} entries -> {out_zip}")
    return out_zip


def backup_core(game_dir: Path, verbose: bool = True) -> Path:
    core_dir = core_pack_dir(game_dir)
    if core_dir.exists() and any(core_dir.iterdir()):
        if verbose:
            print(f"[core] existing core pack found: {core_dir}")
        return core_dir
    core_dir.mkdir(parents=True, exist_ok=True)
    patterns = ["*.assets", "*.assets.resS", "*.resource"]
    count = 0
    for pat in patterns:
        for p in game_dir.glob(pat):
            shutil.copy2(p, core_dir / p.name)
            count += 1
    if verbose:
        print(f"[core] backed up {count} files to {core_dir}")
    return core_dir


def restore_core(game_dir: Path, verbose: bool = True) -> None:
    core_dir = core_pack_dir(game_dir)
    if not core_dir.exists() or not any(core_dir.iterdir()):
        raise SystemExit(f"Core pack not found: {core_dir}")
    count = 0
    for p in core_dir.iterdir():
        if p.is_file():
            shutil.copy2(p, game_dir / p.name)
            count += 1
    marker = game_dir.parent / "ActiveTexturePack.txt"
    if marker.exists():
        marker.unlink()
    if verbose:
        print(f"[restore] restored {count} core files")


def apply_pack(game_dir: Path, pack_zip: Path, verbose: bool = True) -> None:
    backup_core(game_dir, verbose=verbose)
    restore_core(game_dir, verbose=False)

    pack_zip = pack_zip.resolve()
    with zipfile.ZipFile(pack_zip, "r") as z:
        manifest = json.loads(z.read(PACK_MANIFEST_NAME))
        entries = manifest.get("entries", manifest.get("textures", []))
        if not entries:
            raise SystemExit("Pack contains no entries.")
        entries_by_asset: Dict[str, List[dict]] = {}
        data_cache: Dict[str, bytes] = {}
        for t in entries:
            data_cache[t["id"]] = z.read(t["file"])
            entries_by_asset.setdefault(t["asset"], []).append(t)

    changed_assets = 0
    applied = 0
    for asset_name, entries in entries_by_asset.items():
        asset_path = game_dir / asset_name
        if not asset_path.is_file():
            print(f"[load] ! asset not found: {asset_name}")
            continue
        try:
            env = UnityPy.load(str(asset_path))
        except Exception as e:
            print(f"[load] ! failed to load {asset_name}: {e}")
            continue
        obj_map = {}
        for o in env.objects:
            if getattr(o.type, "name", "") in ("Texture2D", "AudioClip"):
                obj_map[o.path_id] = o
        name_map = {}
        for o in env.objects:
            if getattr(o.type, "name", "") in ("Texture2D", "AudioClip"):
                try:
                    name_map.setdefault(o.read().m_Name, o)
                except Exception:
                    pass

        asset_changed = False
        for t in entries:
            o = obj_map.get(t["path_id"])
            if o is None:
                o = name_map.get(t["name"])
            if o is None:
                print(f"[load] ! texture not found: {t['name']} ({t['path_id']}) in {asset_name}")
                continue
            try:
                d = o.read()
                etype = t.get("type", "texture")
                if etype == "audio":
                    import wave
                    wav_bytes = data_cache[t["id"]]
                    import wave, subprocess, tempfile
                    with wave.open(BytesIO(wav_bytes), "rb") as w:
                        ch = w.getnchannels()
                        rate = w.getframerate()
                        bits = w.getsampwidth() * 8
                        frames = w.getnframes()
                        dur = frames / rate if rate else 0.0
                    # Convert WAV to Ogg Vorbis via ffmpeg for Unity compatibility.
                    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as wf:
                        wf.write(wav_bytes); wav_path = wf.name
                    ogg_path = wav_path + ".ogg"
                    subprocess.run(
                        ["ffmpeg", "-y", "-i", wav_path, "-c:a", "libvorbis", "-q:a", "4", ogg_path],
                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True,
                    )
                    ogg_bytes = Path(ogg_path).read_bytes()
                    os.unlink(wav_path); os.unlink(ogg_path)

                    res_name = d.m_Resource.m_Source if (d.m_Resource and d.m_Resource.m_Source) else f"{asset_name.replace('.assets','.resource')}"
                    res_path = game_dir / res_name
                    if not res_path.is_file():
                        res_path = game_dir / asset_name.replace(".assets", ".resource")
                    res_bytes = bytearray(res_path.read_bytes()) if res_path.is_file() else bytearray()
                    orig_offset = d.m_Resource.m_Offset if d.m_Resource else 0
                    orig_size = d.m_Resource.m_Size if d.m_Resource else 0
                    new_size = len(ogg_bytes)
                    if new_size <= orig_size and orig_size > 0:
                        off = orig_offset
                        res_bytes[off:off+new_size] = ogg_bytes
                        for i in range(off+new_size, off+orig_size):
                            res_bytes[i] = 0
                    else:
                        off = len(res_bytes)
                        res_bytes += ogg_bytes
                    res_path.write_bytes(res_bytes)
                    from UnityPy.classes.generated import StreamedResource
                    d.m_Channels = ch
                    d.m_Frequency = rate
                    d.m_BitsPerSample = bits
                    d.m_Length = dur
                    d.m_CompressionFormat = 1  # Vorbis
                    d.m_LoadType = 0
                    d.m_PreloadAudioData = True
                    d.m_AudioData = None
                    d.m_Resource = StreamedResource(off, new_size, res_name)
                    d.save()
                    asset_changed = True
                    applied += 1
                    if verbose:
                        print(f"[load] applied audio {t['name']} ({t['path_id']})")
                else:
                    img = Image.open(BytesIO(data_cache[t["id"]]))
                    if img.mode not in ("RGB", "RGBA", "L", "LA"):
                        img = img.convert("RGBA")
                    d.set_image(img, target_format=4)  # TextureFormat.RGBA32
                    d.save()
                    asset_changed = True
                    applied += 1
                    if verbose:
                        print(f"[load] applied {t['name']} ({t['path_id']})")
            except Exception as e:
                print(f"[load] ! failed {t['name']}: {e}")

        if asset_changed:
            try:
                if hasattr(env, "file") and env.file is not None:
                    env.file.mark_changed()
                # Serialize fully to bytes first, then atomically replace the
                # file. Writing directly to the source path truncates it before
                # UnityPy finishes reading the remaining object data.
                data = env.file.save()
                tmp_path = asset_path.with_name(asset_path.name + ".tmp")
                tmp_path.write_bytes(data)
                os.replace(tmp_path, asset_path)
                changed_assets += 1
            except Exception as e:
                print(f"[load] ! save failed {asset_name}: {e}")

    marker = game_dir.parent / "ActiveTexturePack.txt"
    marker.write_text(str(pack_zip), encoding="utf-8")
    if verbose:
        print(f"[load] applied {applied} textures across {changed_assets} assets")
        print(f"[load] active pack: {pack_zip}")


def generate_gallery(extract_dir: Path, out_html: Path = None, verbose: bool = True) -> Path:
    extract_dir = extract_dir.resolve()
    manifest = load_manifest(extract_dir)
    entries = manifest.get("entries", manifest.get("textures", []))
    textures = [e for e in entries if e.get("type", "texture") == "texture"]
    if out_html is None:
        out_html = extract_dir / "gallery.html"
    out_html = out_html.resolve()
    rows = []
    for t in textures:
        img_rel = t["file"]
        rows.append(
            f'<div class="card"><img src="{img_rel}" loading="lazy"><div class="meta">'
            f'<b>{t["name"]}</b><br>id: {t["id"]}<br>asset: {t["asset"]}<br>'
            f'path_id: {t["path_id"]}<br>{t["width"]}x{t["height"]} fmt {t["format"]}</div></div>'
        )
    html = (
        "<!DOCTYPE html><html><head><meta charset='utf-8'><title>Texture Gallery</title>"
        "<style>body{font-family:sans-serif;background:#111;color:#eee}"
        ".grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(220px,1fr));gap:12px;padding:12px}"
        ".card{background:#222;border-radius:8px;padding:8px}.card img{width:100%;height:160px;object-fit:contain;background:#000;border-radius:4px}"
        ".meta{font-size:12px;margin-top:6px;line-height:1.4;word-break:break-all}</style></head>"
        "<body><h1>Unity Game Texture Gallery</h1><div class='grid'>" + "".join(rows) + "</div></body></html>"
    )
    out_html.write_text(html, encoding="utf-8")
    if verbose:
        print(f"[gallery] wrote {len(textures)} entries to {out_html}")
    return out_html


def detect_texture(screenshot: Path, extract_dir: Path, top: int = 8, verbose: bool = True) -> None:
    if not _CV2_OK:
        raise SystemExit("opencv-python (cv2) is required for detect.")
    extract_dir = extract_dir.resolve()
    manifest = load_manifest(extract_dir)
    entries = manifest.get("entries", manifest.get("textures", []))
    textures = [e for e in entries if e.get("type", "texture") == "texture"]

    img = cv2.imread(str(screenshot))
    if img is None:
        raise SystemExit(f"Could not read screenshot: {screenshot}")
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    # downscale very large screenshots for speed
    h, w = gray.shape
    if max(h, w) > 1280:
        scale = 1280 / max(h, w)
        gray = cv2.resize(gray, (int(w * scale), int(h * scale)))
    orb = cv2.ORB_create(nfeatures=3000)
    kp1, des1 = orb.detectAndCompute(gray, None)
    if des1 is None:
        raise SystemExit("No features found in screenshot.")

    bf = cv2.BFMatcher(cv2.NORM_HAMMING, crossCheck=True)
    results = []
    for t in textures:
        tex_path = extract_dir / t["file"]
        tex = cv2.imread(str(tex_path), cv2.IMREAD_GRAYSCALE)
        if tex is None:
            continue
        # downscale texture to reasonable size
        th, tw = tex.shape
        if max(th, tw) > 512:
            scale = 512 / max(th, tw)
            tex = cv2.resize(tex, (int(tw * scale), int(th * scale)))
        kp2, des2 = orb.detectAndCompute(tex, None)
        if des2 is None or len(des2) < 5:
            continue
        try:
            matches = bf.match(des1, des2)
        except Exception:
            continue
        if not matches:
            continue
        matches = sorted(matches, key=lambda m: m.distance)
        good = [m for m in matches if m.distance < 45]
        if len(good) == 0:
            continue
        results.append((len(good), t, matches[0].distance))

    results.sort(key=lambda r: (-r[0], r[2]))
    if verbose:
        print(f"[detect] screenshot features: {len(des1)}, candidate textures: {len(textures)}")
        print(f"[detect] top {min(top, len(results))} matches:")
    for score, t, dist in results[:top]:
        print(f"  score={score:4d}  dist={dist:3d}  {t['id']}  ({t['name']})  {t['file']}")
    if not results:
        print("[detect] no matches found.")


def probe_textures(extract_dir: Path, ids: List[str], color: str = "#FF00FF", out_pack: Path = None, apply: bool = False, game_dir: Optional[str] = None, verbose: bool = True) -> None:
    extract_dir = extract_dir.resolve()
    manifest = load_manifest(extract_dir)
    by_id = {t["id"]: t for t in manifest.get("entries", manifest.get("textures", []))}
    chosen = []
    for tid in ids:
        if tid not in by_id:
            print(f"[probe] ! unknown id: {tid}")
            continue
        chosen.append(by_id[tid])
    if not chosen:
        raise SystemExit("No valid texture ids to probe.")
    # parse color
    color = color.lstrip("#")
    if len(color) == 3:
        color = "".join(c * 2 for c in color)
    r = int(color[0:2], 16); g = int(color[2:4], 16); b = int(color[4:6], 16)

    outdir = Path("/tmp/scratchpad/probe_pack") if False else (extract_dir.parent / "_probe_pack")
    # use a temp dir in scratchpad to avoid cluttering extract dir
    outdir = Path("/home/Roman-Fedora/scratchpad/_probe_pack")
    if outdir.exists():
        shutil.rmtree(outdir)
    (outdir / "textures").mkdir(parents=True)
    probe_manifest = {"game": manifest.get("game", "Unity Game"), "version": 1, "textures": []}
    from PIL import Image
    for t in chosen:
        img = Image.new("RGBA", (t["width"], t["height"]), (r, g, b, 255))
        rel = t["file"]
        (outdir / rel).parent.mkdir(parents=True, exist_ok=True)
        img.save(outdir / rel)
        probe_manifest["textures"].append({
            "id": t["id"], "name": t["name"], "asset": t["asset"],
            "path_id": t["path_id"], "width": t["width"], "height": t["height"],
            "format": t["format"], "file": rel,
        })
    (outdir / PACK_MANIFEST_NAME).write_text(json.dumps(probe_manifest), encoding="utf-8")

    if out_pack is None:
        out_pack = Path("ProbePack.zip")
    out_pack = out_pack.resolve()
    build_pack(outdir, out_pack, include_all=True, verbose=False)
    if verbose:
        print(f"[probe] replaced {len(chosen)} texture(s) with color #{color}")
        for t in chosen:
            print(f"  {t['id']}  ({t['name']})  {t['width']}x{t['height']}")
        print(f"[probe] pack: {out_pack}")
    if apply:
        gd = find_game_dir(game_dir) if game_dir else find_game_dir()
        apply_pack(gd, out_pack)
    # cleanup
    shutil.rmtree(outdir, ignore_errors=True)


def migrate_manifest(extract_dir: Path, game_dir: Optional[str] = None, verbose: bool = True) -> None:
    extract_dir = extract_dir.resolve()
    manifest = load_manifest(extract_dir)
    gd = find_game_dir(game_dir) if game_dir else find_game_dir(manifest.get("source_game_data"))
    # Convert old "textures" list to entries
    if "entries" not in manifest:
        old = manifest.pop("textures", [])
        manifest["entries"] = []
        for t in old:
            t = dict(t)
            t.setdefault("type", "texture")
            manifest["entries"].append(t)
    existing_ids = {e["id"] for e in manifest["entries"]}
    # Extract audio entries from game (without clobbering edited files)
    import tempfile
    asset_files = sorted(gd.glob("*.assets"))
    added = 0
    for asset_path in asset_files:
        try:
            env = UnityPy.load(str(asset_path))
        except Exception:
            continue
        for o in env.objects:
            if getattr(o.type, "name", "") != "AudioClip":
                continue
            try:
                d = o.read()
                samples = d.samples
            except Exception:
                continue
            if not samples:
                continue
            eid = f"{asset_path.name}::{o.path_id}"
            if eid in existing_ids:
                continue
            for sname, data in samples.items():
                safe = sanitize(sname)
                rel = Path(asset_path.stem) / f"{safe}_{o.path_id}{Path(sname).suffix or '.wav'}"
                dest = extract_dir / "audio" / rel
                dest.parent.mkdir(parents=True, exist_ok=True)
                # original hash from game data
                orig_hash = hashlib.sha256(data).hexdigest()
                if not dest.exists():
                    dest.write_bytes(data)
                entry = {
                    "type": "audio",
                    "id": eid,
                    "name": getattr(d, "m_Name", "") or f"audio_{o.path_id}",
                    "asset": asset_path.name,
                    "path_id": o.path_id,
                    "channels": int(d.m_Channels or 0),
                    "frequency": int(d.m_Frequency or 0),
                    "bits": int(d.m_BitsPerSample or 0),
                    "length": float(d.m_Length or 0),
                    "compression": int(d.m_CompressionFormat or 0),
                    "file": str(Path("audio") / rel).replace(os.sep, "/"),
                    "original_sha256": orig_hash,
                }
                manifest["entries"].append(entry)
                existing_ids.add(eid)
                added += 1
                break
    manifest["version"] = 2
    with open(extract_dir / PACK_MANIFEST_NAME, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)
    if verbose:
        print(f"[migrate] added {added} audio entries; total entries {len(manifest['entries'])}")


def list_packs(directory: Path = Path(".")) -> None:
    directory = directory.resolve()
    packs = sorted(directory.glob("*.zip"))
    if not packs:
        print("No .zip packs found in", directory)
        return
    for p in packs:
        try:
            with zipfile.ZipFile(p) as z:
                m = json.loads(z.read(PACK_MANIFEST_NAME))
                n = len(m.get("textures", []))
            print(f"{p.name}: {n} textures")
        except Exception:
            print(f"{p.name}: (not a texture pack)")


def run_gui() -> None:
    import tkinter as tk
    from tkinter import filedialog, messagebox, ttk

    root = tk.Tk()
    root.title("Unity Game Texture Pack Tool")
    root.geometry("760x460")

    try:
        default_gd = str(find_game_dir())
    except SystemExit:
        default_gd = ""
    game_dir_var = tk.StringVar(value=default_gd)
    extract_var = tk.StringVar(value=DEFAULT_EXTRACT_DIR)
    pack_var = tk.StringVar(value="MyPack.zip")

    frm = ttk.Frame(root, padding=10)
    frm.pack(fill="both", expand=True)

    ttk.Label(frm, text="Game data dir:").grid(row=0, column=0, sticky="w")
    ttk.Entry(frm, textvariable=game_dir_var, width=62).grid(row=0, column=1, sticky="we")
    ttk.Button(frm, text="Browse", command=lambda: game_dir_var.set(filedialog.askdirectory() or game_dir_var.get())).grid(row=0, column=2)

    ttk.Label(frm, text="Extract dir:").grid(row=1, column=0, sticky="w")
    ttk.Entry(frm, textvariable=extract_var, width=62).grid(row=1, column=1, sticky="we")
    ttk.Button(frm, text="Browse", command=lambda: extract_var.set(filedialog.askdirectory() or extract_var.get())).grid(row=1, column=2)

    ttk.Label(frm, text="Pack zip:").grid(row=2, column=0, sticky="w")
    ttk.Entry(frm, textvariable=pack_var, width=62).grid(row=2, column=1, sticky="we")
    ttk.Button(frm, text="Browse", command=lambda: pack_var.set(filedialog.asksaveasfilename(defaultextension=".zip", filetypes=[("Zip", "*.zip")]) or pack_var.get())).grid(row=2, column=2)

    log = tk.Text(frm, height=18, wrap="word")
    log.grid(row=4, column=0, columnspan=3, sticky="nsew", pady=10)

    def append(msg):
        log.insert("end", msg + "\n")
        log.see("end")
        root.update_idletasks()

    def gd():
        return find_game_dir(game_dir_var.get()) if game_dir_var.get() else find_game_dir()

    def do_extract():
        try:
            g = gd()
            extract_textures(g, Path(extract_var.get()))
            append("Extract complete.")
        except Exception as e:
            messagebox.showerror("Error", str(e))
            append(f"ERROR: {e}")

    def do_build(changed_only=True):
        try:
            src = Path(extract_var.get())
            out = Path(pack_var.get())
            build_pack(src, out, include_all=not changed_only)
            append("Build complete.")
        except Exception as e:
            messagebox.showerror("Error", str(e))
            append(f"ERROR: {e}")

    def do_load():
        try:
            g = gd()
            apply_pack(g, Path(pack_var.get()))
            append("Load complete.")
        except Exception as e:
            messagebox.showerror("Error", str(e))
            append(f"ERROR: {e}")

    def do_restore():
        try:
            g = gd()
            restore_core(g)
            append("Restore complete.")
        except Exception as e:
            messagebox.showerror("Error", str(e))
            append(f"ERROR: {e}")

    btns = ttk.Frame(frm)
    btns.grid(row=3, column=0, columnspan=3, pady=5)
    ttk.Button(btns, text="Extract", command=do_extract).pack(side="left", padx=3)
    ttk.Button(btns, text="Build (changed)", command=lambda: do_build(True)).pack(side="left", padx=3)
    ttk.Button(btns, text="Build (all)", command=lambda: do_build(False)).pack(side="left", padx=3)
    ttk.Button(btns, text="Load Pack", command=do_load).pack(side="left", padx=3)
    ttk.Button(btns, text="Restore Core", command=do_restore).pack(side="left", padx=3)

    frm.columnconfigure(1, weight=1)
    frm.rowconfigure(4, weight=1)
    root.mainloop()


def main() -> None:
    parser = argparse.ArgumentParser(description="Unity Game texture pack editor & loader")
    parser.add_argument("--game-dir", help="Path to Unity Game_Data or game root")
    sub = parser.add_subparsers(dest="cmd")

    p_ext = sub.add_parser("extract", help="Extract textures from game assets")
    p_ext.add_argument("out", nargs="?", default=DEFAULT_EXTRACT_DIR, help="Output directory")

    p_build = sub.add_parser("build", help="Build a texture pack zip from an extracted dir")
    p_build.add_argument("source", nargs="?", default=DEFAULT_EXTRACT_DIR)
    p_build.add_argument("output", nargs="?", default="MyPack.zip")
    p_build.add_argument("--all", action="store_true", help="Include all textures, not just changed")

    p_load = sub.add_parser("load", help="Apply a texture pack zip to the game")
    p_load.add_argument("pack", help="Pack zip path")
    p_load.add_argument("--game-dir", dest="game_dir2", help="Game data dir")

    p_restore = sub.add_parser("restore", help="Restore original core assets")
    p_restore.add_argument("--game-dir", dest="game_dir3", help="Game data dir")

    sub.add_parser("list", help="List .zip packs in current dir")
    p_gal = sub.add_parser("gallery", help="Generate an HTML gallery of extracted textures")
    p_gal.add_argument("source", nargs="?", default=DEFAULT_EXTRACT_DIR)
    p_gal.add_argument("output", nargs="?", default=None)
    p_det = sub.add_parser("detect", help="Detect which texture a screenshot shows")
    p_det.add_argument("screenshot", help="Path to screenshot image")
    p_det.add_argument("source", nargs="?", default=DEFAULT_EXTRACT_DIR)
    p_det.add_argument("--top", type=int, default=8)
    p_mig = sub.add_parser("migrate", help="Update an old extracted folder to include audio entries")
    p_mig.add_argument("source", nargs="?", default=DEFAULT_EXTRACT_DIR)
    p_mig.add_argument("--game-dir", dest="game_dir5", help="Game data dir")
    p_probe = sub.add_parser("probe", help="Replace texture(s) with a solid color to identify them in-game")
    p_probe.add_argument("--id", action="append", required=True, help="Texture id to probe (repeatable)")
    p_probe.add_argument("--color", default="#FF00FF", help="Hex color (default magenta)")
    p_probe.add_argument("--output", default="ProbePack.zip")
    p_probe.add_argument("--apply", action="store_true", help="Apply the probe pack immediately")
    p_probe.add_argument("--game-dir", dest="game_dir4", help="Game data dir")
    sub.add_parser("gui", help="Launch graphical interface")

    args = parser.parse_args()

    game_dir_arg = args.game_dir
    if args.cmd == "load" and getattr(args, "game_dir2", None):
        game_dir_arg = args.game_dir2
    if args.cmd == "restore" and getattr(args, "game_dir3", None):
        game_dir_arg = args.game_dir3

    if args.cmd is None or args.cmd == "gui":
        run_gui()
        return
    if args.cmd == "extract":
        g = find_game_dir(game_dir_arg)
        extract_textures(g, Path(args.out))
        return
    if args.cmd == "build":
        build_pack(Path(args.source), Path(args.output), include_all=args.all)
        return
    if args.cmd == "load":
        g = find_game_dir(game_dir_arg)
        apply_pack(g, Path(args.pack))
        return
    if args.cmd == "restore":
        g = find_game_dir(game_dir_arg)
        restore_core(g)
        return
    if args.cmd == "list":
        list_packs(Path("."))
        return
    if args.cmd == "gallery":
        src = Path(args.source)
        out = Path(args.output) if args.output else None
        generate_gallery(src, out)
        return
    if args.cmd == "detect":
        detect_texture(Path(args.screenshot), Path(args.source), top=args.top)
        return
    if args.cmd == "migrate":
        gd = getattr(args, "game_dir5", None)
        migrate_manifest(Path(args.source), game_dir=gd)
        return
    if args.cmd == "probe":
        gd = getattr(args, "game_dir4", None)
        probe_textures(Path(args.source), args.id, color=args.color, out_pack=Path(args.output), apply=args.apply, game_dir=gd)
        return


if __name__ == "__main__":
    main()
