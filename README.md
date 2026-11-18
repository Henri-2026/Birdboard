<p align="center">
  <img src="beeref/assets/logo.png" width="128" height="128" alt="Birdboard Logo" />
</p>

<h1 align="center">Birdboard v1.0.0</h1>

<p align="center">
  <strong>High-performance personalized infinite reference canvas for artists &amp; creators.</strong>
</p>

---

## Key Features in Birdboard v1.0.0

- **Zero-Lag 1,000+ High-Resolution Image Engine**
  - **GPU Hardware Compositing (`QOpenGLWidget`, 4x MSAA)** delivering >100 FPS smooth panning and zooming across massive moodboards.
  - **3-Tier Mipmap LOD Pyramid & Async LRU Streaming**: Always-resident lightweight `384px` thumbnails for full-board overviews, with non-blocking background upgrades to `1280px` and `1:1` full resolution on close zoom.
  - **Multi-Core Parallel Loader & Instant `.bee` Cache**: Hardware DCT-accelerated JPEG decoding across all CPU cores, batched $O(1)$ scene updates, $O(N \log K)$ masonry packing for >300 images, and embedded `lod_thumbs` SQLite startup cache.
- **Penart Frosted Glass Dropdown UI**
  - Dark Frosted Glass (`rgba(28, 28, 34, 0.84)` + real `20px` backdrop blur & `150%` saturation boost).
  - Concentric corner geometry (`11px` outer card / `5px` padding / `6px` inner hover pill) with zero-banding Gaussian drop shadow.
  - **480ms Dropdown Inertia Unfurl** (`cubic-bezier(0.16, 1, 0.3, 1)`) at 120 FPS across root and nested submenus.
- **Studio Light (`#E9EAEC`) & Penart Matte Dark (`#1A1A1D`) Themes**
  - Live instant theme switching via `Settings -> Appearance & General -> Canvas Theme`.
- **Frameless DWM Window with Native Shadow & Compact Controls**
  - Windows 11 DWM rounded corners, deep window elevation shadow, 8-edge native resize, and compact 3-dot top-left window controls.

---

## Quick Start (Windows)

```powershell
python -m venv .venv
.\.venv\Scripts\pip install -e .
.\Run-Birdboard.bat
```

---

## License & Attribution

Birdboard is customized and extended from the open-source [BeeRef](https://github.com/rbreu/beeref) project by Rebecca Breu, licensed under the **GNU General Public License v3.0 (GPL-3.0)**.
