# Birdboard — AI Agent Operating Guide (`AGENT.md`)

Tài liệu này là quy chuẩn bắt buộc dành cho mọi AI Agent (Antigravity, Claude Code, Cursor, Codex...) khi làm việc trên dự án **Birdboard** tại `D:\.Linh app\BIRDBOARD`.

---

## 1. Định Danh Dự Án & Quy Tắc Cốt Lõi

- **Tên phần mềm chính thức:** `Birdboard` *(Tuyệt đối không dùng tên cũ `PureCanvas` hay `BeeRef` trên giao diện người dùng)*.
- **GitHub Repository:** https://github.com/Henri-2026/Birdboard
- **Thư mục gốc chuẩn:** `D:\.Linh app\BIRDBOARD`
- **Môi trường Python thực thi:** `D:\.Linh app\BIRDBOARD\.venv\Scripts\python.exe` (hoặc `pythonw.exe` khi chạy GUI không console).
- **Khởi chạy nhanh trên Windows:** `D:\.Linh app\BIRDBOARD\Run-Birdboard.bat`

### Quy trình làm việc bắt buộc cho Agent ở mỗi phiên mới
1. **Đọc trước khi sửa:** Luôn đọc `AGENT.md` và `PROGRESS.md` đầu tiên để nắm trạng thái hiện tại và các hạng mục đang chờ trong Backlog.
2. **Phân tích trước khi code (khi người dùng yêu cầu):** Trình bày rõ giải pháp kỹ thuật, thông số UI/UX và chờ xác nhận trước khi ghi đè mã nguồn.
3. **Cập nhật tiến độ:** Sau mỗi đợt nâng cấp hoặc bản phát hành mới, cập nhật ngay vào `PROGRESS.md` và tài liệu tương ứng trong `docs/`.
4. **Không đẩy `reporef/` và `.venv/` lên Git:** Thư mục `reporef/` chứa các mã nguồn tham chiếu độc lập (đã được loại trừ trong `.gitignore`), chỉ dùng để tra cứu thuật toán tại máy local.

---

## 2. Ba Bất Biến Kỹ Thuật Không Được Phá Vỡ (Core Invariants)

### Bất biến #1 — Hiệu năng chống lag tuyệt đối với > 1.000 – 5.000+ hình ảnh
Mọi tính năng thêm mới vào Canvas **không bao giờ** được làm giảm FPS khi lăn chuột zoom hoặc pan trên bảng có hàng ngàn ảnh độ phân giải cao:
- **GPU Viewport:** Luôn duy trì `QOpenGLWidget` (`4x MSAA`, `FullViewportUpdate`) trong `beeref/view.py`.
- **3-Tier Mipmap LOD & Async LRU Streaming (`beeref/lod_cache.py` & `beeref/items.py`):**
  - *Tier 0 (`<= 384px`):* Luôn sẵn trong RAM (~250 KB/ảnh) để vẽ toàn cảnh 1.000+ ảnh ở >100 FPS.
  - *Tier 1 (`<= 1280px`) & Tier 2 (`Full-Res 1:1`):* Bắt buộc giải mã **bất đồng bộ trên luồng nền (`ThreadPoolExecutor`)**, không bao giờ giải mã ảnh 4K đồng bộ trong hàm `paint()` khi người dùng đang lướt chuột, và tự động xả RAM theo hạn mức Byte-Budget LRU (`384 MB` cho Tier 1, `768 MB` cho Tier 2).
- **Độ phức tạp Scene $O(1)$ khi Zoom/Pan (`beeref/scene.py`):**
  - Giữ cơ chế cache `_cached_all_bounds` & `_cached_sel_bounds` cho `itemsBoundingRect()`.
  - Mọi thao tác chỉnh sửa hàng loạt (Insert, Delete, Move, Scale, Rotate, Arrange, Undo/Redo) bắt buộc bọc trong `with scene.batch_update():`.
  - Khi sắp xếp `Optimal` với số lượng ảnh `> 300`, dùng thuật toán `_pack_large_masonry` ($O(N \log K)$) thay vì `rpack` ($O(N^{2.5})$).
- **Hiệu ứng trên từng ảnh (như đổ bóng Card Shadow):** Phải có điều kiện lọc theo LOD (`screen_max_edge > 150`), tự động bỏ qua khi zoom xa toàn cảnh và tuyệt đối không dùng `QGraphicsDropShadowEffect` (CPU-bound).

### Bất biến #2 — Quy chuẩn Giao diện & Vật lý Chuyển động Penart (`penart-ui-craft`)
- **Dropdown chuột phải & Submenu (`beeref/widgets/penart_menu.py`):**
  - Duy trì chất liệu **Kính Mờ Đen chữ Trắng** ở cả Light Mode lẫn Dark Mode: nền `rgba(28, 28, 34, 0.84)` kết hợp lấy mẫu làm nhòe thực vùng Canvas bên dưới (`blur ~20px` + `saturate 150%`), viền phản quang `1px rgba(255, 255, 255, 0.16)`, highlight mép trên `rgba(255, 255, 255, 0.12)`.
  - Phân cấp chữ sắc nét: `#F2F2F7` (chính), `#9A9AA2` (phím tắt & mũi tên `›`), `#6C6C74` (vô hiệu hóa), `#3A82F7` (tích chọn).
  - **Bo viền đồng tâm ($R_{\text{outer}} = R_{\text{inner}} + \text{Padding}$):** Khung ngoài `11px` — đệm `5px` — thanh hover bên trong `6px`.
  - **Vật lý hạ menu có quán tính (`Dropdown Inertia Unfurl`):** Thời lượng `480ms`, đường cong `cubic-bezier(0.16, 1, 0.3, 1)` ở `120 FPS` từ điểm neo góc trên.
- **Hệ màu Dual-Theme (`beeref/constants.py`):**
  - **Light Mode (Mặc định):** Nền Studio Light Gray `#E9EAEC` (`rgb(233, 234, 236)`), chữ ghi chú `#1C1C22`.
  - **Dark Mode:** Nền Penart Matte Dark `#1A1A1D` (`rgb(26, 26, 29)`), chữ ghi chú `#F2F2F7`.

### Bất biến #3 — Cô lập Cửa sổ An toàn trên Windows (`beeref/win_dwm.py`)
- Mọi lời gọi `dwmapi.dll` (`DwmSetWindowAttribute`, bo góc `DWMWCP_ROUND`, bóng đổ DWM, viền mảnh tách nền) chỉ được phép truyền vào `int(window.winId())` của riêng cửa sổ Birdboard.
- Tuyệt đối không ghi vào Windows Registry hệ thống, không hook tiến trình ngoài, không làm ảnh hưởng bất kỳ phần mềm nào khác trên máy.

---

## 3. Bản Đồ Kiến Trúc Thư Mục

```text
D:\.Linh app\BIRDBOARD\
├── AGENT.md                    # Quy chuẩn vận hành & bất biến kỹ thuật cho AI Agent
├── README.md                   # Tổng quan dự án, cài đặt và hướng dẫn sử dụng
├── PROGRESS.md                 # Nhật ký phiên bản đã hoàn thành & Backlog tính năng tiếp theo
├── Run-Birdboard.bat           # Trình khởi chạy nhanh 1-click (ẩn console)
├── Birdboard.spec              # Cấu hình đóng gói file Birdboard.exe độc lập (PyInstaller)
├── pyproject.toml              # Khai báo metadata gói Birdboard & dependencies
├── docs/                       # Tài liệu kỹ thuật chuyên sâu
│   ├── ARCHITECTURE.md         # Kiến trúc Engine GPU, 3-Tier LOD, Scene O(1) & SQLite I/O
│   ├── UI_DESIGN_SYSTEM.md     # Quy chuẩn màu sắc, Penart Dropdown, DWM & thiết kế Bảng Đồng Hồ
│   ├── REFERENCE_ANALYSIS.md   # Phân tích đối chiếu các repo mẫu trong reporef/
│   └── CONTROLS_AND_SHORTCUTS.md # Bảng tra cứu thao tác chuột & phím tắt
├── reporef/                    # Kho mã nguồn tham chiếu tại máy local (đã gitignore)
│   ├── README.md               # Chỉ mục các repo tham chiếu
│   ├── beeref/                 # Bản gốc rbreu/beeref (đối chiếu diff & core Qt)
│   ├── PureRef-format/         # FyorDev/PureRef-format (đặc tả nhị phân đọc/ghi file .pur)
│   └── AnimRef/                # lettucegoblin/AnimRef (tham chiếu tính năng GIF/Video/Loop)
├── beeref/                     # Gói mã nguồn lõi của Birdboard
│   ├── __main__.py             # Điểm vào ứng dụng, AppUserModelID, khởi tạo MainWindow
│   ├── constants.py            # Định danh Birdboard & Token màu Light/Dark Mode
│   ├── view.py                 # Khung nhìn QOpenGLWidget, Pan/Zoom, gọi Penart Menu & DWM
│   ├── scene.py                # Canvas vô cực, BSP-12, O(1) bounds cache, Masonry Packer
│   ├── items.py                # BeePixmapItem (3-Tier LOD + Card Shadow) & BeeTextItem
│   ├── lod_cache.py            # Bộ quản lý Mipmap LOD & giải mã đa luồng LRU Cache
│   ├── win_dwm.py              # Bo góc, đổ bóng Windows 11 DWM, Resize 8 hướng & nút 3 chấm
│   ├── selection.py            # Khung chọn, tay nắm Scale/Rotate/Flip (#3A82F7)
│   ├── commands.py             # Hệ thống Undo/Redo gom lô (batch_update)
│   ├── actions/                # Định nghĩa lệnh, phím tắt & cây menu chuột phải
│   ├── config/                 # Quản lý cài đặt người dùng (.ini) & sự kiện đổi Theme
│   ├── fileio/                 # Nạp ảnh song song DCT & đọc/ghi SQLite (.bee + lod_thumbs)
│   ├── widgets/
│   │   ├── penart_menu.py      # Hệ thống Dropdown Kính Mờ Penart 120 FPS
│   │   ├── welcome_overlay.py  # Màn hình chờ hiển thị logo tròn & file gần đây
│   │   └── settings.py         # Hộp thoại Cài đặt (bao gồm chuyển đổi Light/Dark Mode)
│   └── assets/                 # Logo tròn Birdboard (PNG, multi-size ICO, SVG) & con trỏ
└── tests/                      # Bộ kiểm thử tự động
```

---

## 4. Các Lệnh Thường Dùng Dành Cho Agent

- **Chạy ứng dụng chế độ GUI sạch (không hiện console):**
  ```powershell
  Start-Process -FilePath "d:\.Linh app\BIRDBOARD\.venv\Scripts\pythonw.exe" -ArgumentList "-m", "beeref" -WorkingDirectory "d:\.Linh app\BIRDBOARD"
  ```
- **Chạy kiểm tra log trực tiếp trên terminal khi debug:**
  ```powershell
  & "d:\.Linh app\BIRDBOARD\.venv\Scripts\python.exe" -m beeref -l DEBUG
  ```
- **Đóng gói ra file thực thi `.exe` độc lập (khi cần phát hành bản Portable):**
  ```powershell
  & "d:\.Linh app\BIRDBOARD\.venv\Scripts\pip.exe" install pyinstaller
  & "d:\.Linh app\BIRDBOARD\.venv\Scripts\pyinstaller.exe" Birdboard.spec
  ```
