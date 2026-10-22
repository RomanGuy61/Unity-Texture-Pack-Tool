# Unity Game Texture Pack Tool

A Python tool for extracting, editing, creating, and applying texture packs for Unity games. It also supports audio extraction and replacement, texture identification, HTML texture galleries, and restoring original game assets.

## Features

- **Texture Extraction:** Extract textures from Unity `.assets` files as PNG images.
- **Audio Extraction:** Export audio clips from Unity assets for editing.
- **Texture Pack Creation:** Build ZIP-based texture packs from modified textures.
- **Audio Replacement:** Replace game audio using WAV files, with conversion to Ogg Vorbis through FFmpeg.
- **Pack Loading:** Apply texture and audio modifications directly to Unity game assets.
- **Automatic Backups:** Back up original game assets in a `CorePack` directory before applying modifications.
- **Asset Restoration:** Restore backed-up game assets.
- **HTML Texture Gallery:** Generate a browsable HTML gallery of extracted textures and their metadata.
- **Screenshot Detection:** Find potential matching textures by comparing a screenshot against extracted textures.
- **Texture Probing:** Replace selected textures with solid colors to help identify them in-game.
- **Graphical Interface:** Use a simple Tkinter GUI to extract, build, load, and restore texture packs.
- **Command-Line Interface:** Perform operations directly from a terminal.

## Requirements

- Python 3.10 or newer recommended
- A Unity game with accessible game data files
- [UnityPy](https://github.com/K0lb3/UnityPy)
- [Pillow](https://python-pillow.org/)
- [OpenCV for Python](https://pypi.org/project/opencv-python/) for screenshot-based texture detection
- [FFmpeg](https://ffmpeg.org/) for audio replacement

## Installation

1. Clone or download this repository.

   ```bash
   git clone <your-repository-url>
   cd <repository-folder>
   ```

2. Install the required Python packages.

   ```bash
   python -m pip install UnityPy Pillow
   ```

3. Install OpenCV if you want to use screenshot detection.

   ```bash
   python -m pip install opencv-python
   ```

4. Install FFmpeg and ensure it is available in your system's `PATH` if you want to replace audio.

   On Fedora Linux:

   ```bash
   sudo dnf install ffmpeg
   ```

   If FFmpeg is unavailable in your enabled repositories, you may need to enable a suitable third-party repository first.

## Getting Started

### 1. Launch the graphical interface

Run the script without arguments:

```bash
python texture_pack_tool.py
```

Or explicitly launch the GUI:

```bash
python texture_pack_tool.py gui
```

The interface lets you select your Unity game data directory, choose an extraction directory, specify a ZIP output path, and perform common operations using buttons.

### 2. Extract game textures and audio

```bash
python texture_pack_tool.py --game-dir "/path/to/Game_Data" extract ExtractedTextures
```

Replace `/path/to/Game_Data` with the actual path to your game's data directory.

The tool exports textures as PNG files and audio clips into separate directories. It also creates a `manifest.json` file containing asset names, IDs, dimensions, audio metadata, and original file hashes.

Example output structure:

```text
ExtractedTextures/
├── manifest.json
├── textures/
│   ├── sharedassets0.assets/
│   │   ├── ExampleTexture_123.png
│   │   └── AnotherTexture_456.png
│   └── ...
└── audio/
    └── ...
```

The exact filenames and directory names depend on the game's assets.

### 3. Edit the textures

Open the extracted PNG files in your preferred image editor. Edit the textures you want to replace, keeping the original filenames and directory structure intact.

You can also edit the extracted WAV audio files with compatible audio software.

### 4. Build a texture pack

Create a ZIP containing only the modified assets:

```bash
python texture_pack_tool.py build ExtractedTextures MyPack.zip
```

To include every available entry instead of only modified entries, use:

```bash
python texture_pack_tool.py build ExtractedTextures MyPack.zip --all
```

The tool compares file hashes against the manifest to identify modified files.

### 5. Apply the pack

```bash
python texture_pack_tool.py --game-dir "/path/to/Game_Data" load MyPack.zip
```

The tool backs up the original core assets before applying the pack and records the active pack path in `ActiveTexturePack.txt`.

**Important:** Close the game before modifying its files. Always keep an independent backup of your game data.

### 6. Restore original assets

```bash
python texture_pack_tool.py --game-dir "/path/to/Game_Data" restore
```

This restores files from the `CorePack` backup and removes the active pack marker.

## Command Reference

| Command | Description |
| --- | --- |
| `gui` | Launch the graphical interface. |
| `extract [OUT]` | Extract textures and audio. |
| `build [SOURCE] [OUTPUT]` | Create a ZIP texture pack from extracted assets. |
| `load PACK` | Apply a texture pack to the game. |
| `restore` | Restore backed-up original assets. |
| `list` | List ZIP files in the current directory. |
| `gallery [SOURCE] [OUTPUT]` | Generate an HTML texture gallery. |
| `detect SCREENSHOT [SOURCE]` | Search for textures that may appear in a screenshot. |
| `migrate [SOURCE]` | Update an older manifest and add audio entries. |
| `probe --id ID` | Generate a solid-color replacement pack for a selected texture. |

Use `--help` to see the available command-line arguments:

```bash
python texture_pack_tool.py --help
```

For command-specific options, use commands such as:

```bash
python texture_pack_tool.py build --help
python texture_pack_tool.py detect --help
python texture_pack_tool.py probe --help
```

## Additional Tools

### HTML Texture Gallery

Generate a visual gallery of extracted textures:

```bash
python texture_pack_tool.py gallery ExtractedTextures
```

Open the generated `gallery.html` file in your browser to browse texture previews and their associated metadata.

### Screenshot Texture Detection

Find possible matches between a screenshot and the extracted textures:

```bash
python texture_pack_tool.py detect screenshot.png ExtractedTextures --top 8
```

This uses OpenCV's ORB feature detection and descriptor matching. Results are suggestions, not guaranteed identifications, and may be less accurate for heavily transformed, low-detail, or partially visible textures.

### Texture Probing

Replace a texture with a solid magenta color to help locate it in-game:

```bash
python texture_pack_tool.py probe --id "sharedassets0.assets::123" --color "#FF00FF"
```

Replace the example ID with the actual texture ID shown in `manifest.json`.

To apply the probe pack immediately:

```bash
python texture_pack_tool.py probe --id "sharedassets0.assets::123" --color "#FF00FF" --apply --game-dir "/path/to/Game_Data"
```

The tool generates a temporary probe pack and removes its intermediate working directory after building it.

### Migrating an Older Extraction

Update an older extracted directory to the current manifest format and add audio entries:

```bash
python texture_pack_tool.py migrate ExtractedTextures --game-dir "/path/to/Game_Data"
```

## Important Notes

- **Back up your game files.** Modifying Unity assets can prevent a game from launching correctly.
- **Game compatibility varies.** Not every Unity version, asset type, or texture format is guaranteed to work.
- **Keep the manifest.** The `manifest.json` file is necessary for building packs and mapping replacements to their original assets.
- **Use the correct game directory.** The tool can automatically search for a Unity `*_Data` directory in some situations, but passing `--game-dir` is more reliable.
- **Audio replacement requires FFmpeg.** The current implementation converts replacement WAV files to Ogg Vorbis.
- **Screenshot detection requires OpenCV.** Without it, the extraction, pack-building, and other supported operations can still be used.
- **Restoration depends on backups.** The `CorePack` directory contains the files used by the restore command. Keep it safe.
- **Test on a copy first.** Applying packs directly modifies the game's asset files.

## How It Works

1. UnityPy reads Unity asset files and identifies textures and audio clips.
2. Textures are exported as PNG images, while supported audio samples are exported as audio files.
3. A JSON manifest records asset identifiers and metadata.
4. Modified files are collected into a ZIP texture pack.
5. When a pack is applied, the tool matches entries to Unity assets and serializes the modified assets back to disk.

## Contributing

Suggestions, bug reports, and contributions are welcome. If you encounter a compatibility issue, please include your operating system, Unity version if known, the command you ran, and any relevant error messages.

## Disclaimer

This tool is intended for personal modding, experimentation, and asset customization. You are responsible for complying with the game's terms of service, applicable laws, and the rights of the original developers.

This project is not affiliated with or endorsed by Unity Technologies.
