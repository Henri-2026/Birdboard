# Birdboard — Nhật Ký Tiến Độ & Lộ Trình Phát Triển (`PROGRESS.md`)

Tài liệu này theo dõi chi tiết các cột mốc đã hoàn thành, kiến trúc đã triển khai và danh sách tính năng dự kiến cho các phiên bản tiếp theo của **Birdboard**.

---

## Phiên bản hiện tại: `v1.1.0` (Stack Group, Detail Stage & Pure `rpack` Optimal — Đã hoàn thành & Phát hành)

### Giai đoạn 0 — Nghiên cứu & Tuyển chọn Kiến trúc (`2026-11-18`)
- [x] Khảo sát hệ sinh thái mã nguồn mở thay thế PureRef trên GitHub (`BeeRef`, `PureRef-format`, `AnimRef`, `Allusion`).
- [x] Giải phẫu chi tiết mã nguồn `BeeRef` (`PyQt6`) và xác định chính xác 6 nguyên nhân gây giật lag, tràn RAM khi nạp trên 1.000 ảnh độ phân giải cao.
- [x] Chốt hướng phát triển độc lập dựa trên nền tảng Python + `PyQt6` + `QOpenGLWidget`, sử dụng định dạng dự án SQLite (`.bee` mở rộng bảng `lod_thumbs`) thay vì phụ thuộc vào định dạng nhị phân đóng `.pur`.

### Giai đoạn 1 — Định danh Thương hiệu & Lõi Chống Lag 1.000+ Hình (`2026-11-18`)
- [x] **Logo Birdboard:** Tách chuẩn phần vòng tròn và họa tiết chim bên trong (loại bỏ nền ngoài Alpha 100%, khử răng cưa không viền xám trên cả nền sáng/tối), xuất đủ bộ `logo.png` (`512×512`), `logo.ico` đa tầng (`16`→`256px`) và `logo.svg`.
- [x] **Tích hợp Windows Taskbar Icon:** Gắn `AppUserModelID` (`Birdboard.ReferenceBoard.1.0`) và hiển thị logo trên màn hình chờ `WelcomeOverlay`.
- [x] **Nạp ảnh đa luồng tốc độ cao:** Loại bỏ lệnh trễ `msleep(10)` của bản gốc; giải mã song song trên toàn bộ nhân CPU bằng C++ `QImageReader` (hỗ trợ DCT JPEG scaling + tự động xoay EXIF + đóng handle file ngay lập tức trên Windows).
- [x] **Engine 3-Tier Mipmap LOD & Async LRU Cache (`beeref/lod_cache.py`):**
  - Tầng 0 (`384px`) giữ sẵn trong RAM để bao quát hàng ngàn ảnh mượt >100 FPS.
  - Tầng 1 (`1280px`) và Tầng 2 (`Full-Res` gốc) giải mã ngầm bất đồng bộ khi zoom gần, tự động giải phóng RAM theo hạn mức LRU (`384 MB` / `768 MB`).
- [x] **GPU OpenGL Viewport & Tối ưu Scene $O(1)$:** Kích hoạt `QOpenGLWidget` (`4x MSAA`), đệm khung bao `itemsBoundingRect()`, gom lô `batch_update()` cho toàn bộ Undo/Redo, và bổ sung thuật toán xếp ảnh nhanh `_pack_large_masonry` ($O(N \log K)$) cho các bảng `> 300` ảnh.
- [x] **SQLite `.bee` Tốc độ cao:** Ghi 1 Transaction duy nhất với cơ chế staging file an toàn và bảng `lod_thumbs` giúp mở lại bảng 1.200+ hình chỉ trong ~1.1 giây.

### Giai đoạn 2 — Giao diện Kính Mờ Penart, Light/Dark Mode & Cửa sổ DWM (`2026-11-19`)
- [x] **Dropdown Kính Mờ Đen chuẩn Penart (`beeref/widgets/penart_menu.py`):**
  - Khắc phục triệt để lỗi chữ xám mờ trên nền trắng của `QMenu` mặc định Windows 11.
  - Áp dụng nền kính tối `rgba(28, 28, 34, 0.84)` + làm nhòe thực vùng Canvas bên dưới (`20px blur`, `150% saturation`), chữ `#F2F2F7` sắc nét, bo viền đồng tâm `11px` / `5px` / `6px` và bóng đổ Gaussian mịn.
  - Vật lý chuyển động hạ menu có quán tính `480ms` theo đường cong `cubic-bezier(0.16, 1, 0.3, 1)` ở `120 FPS` cho cả menu gốc lẫn menu con.
- [x] **Chế độ Sáng / Tối (Dual-Theme):**
  - Mặc định nền **Studio Light Mode (`#E9EAEC`)** kèm bóng đổ nhẹ dưới chân tranh khi zoom gần.
  - Hỗ trợ chuyển trực tiếp tức thời sang **Penart Dark Mode (`#1A1A1D`)** ngay trong `Settings -> Appearance & General -> Canvas Theme`.
- [x] **Cửa sổ Không Viền DWM & Cụm 3 Chấm Điều Khiển (`beeref/win_dwm.py`):**
  - Bo tròn góc và phủ quầng bóng đổ sâu tự nhiên của Windows 11 DWM quanh viền cửa sổ (cô lập 100% trên `HWND` của Birdboard).
  - Thêm cụm 3 chấm điều khiển (Đóng / Thu nhỏ / Phóng to) ở góc trái trên, hỗ trợ kéo cửa sổ ở mép trên và kéo giãn 8 cạnh/góc.
- [x] **Định danh chính thức `Birdboard v1.0.0`** và phát hành lên `https://github.com/Henri-2026/Birdboard`.

### Giai đoạn 3 — Chuẩn hóa Không gian Dự án Độc lập (`2026-11-19`)
- [x] Thiết lập thư mục dự án chuẩn tại `D:\.Linh app\BIRDBOARD` với môi trường `.venv` độc lập.
- [x] Xây dựng đầy đủ hệ thống tài liệu quản trị dự án: `AGENT.md`, `README.md`, `PROGRESS.md` và bộ tài liệu kỹ thuật trong `docs/`.
- [x] Tải và tổ chức kho mã nguồn tham chiếu trong `reporef/` (`beeref`, `PureRef-format`, `AnimRef`).

### Giai đoạn 4 — Tính Năng Group - Xếp Chồng (`Stack Group`) & `Detail Stage View` (`2026-11-19`)
- [x] **Vòng đời 5 trạng thái Xếp chồng vật lý 120 FPS (`beeref/stack_manager.py`, `beeref/deskboard_motion.py`):**
  - **Multi-Select Toolbar (`ContextualToolbar`):** Khi chọn `>= 2` ảnh, thanh nổi đảo màu trồi lên ở đáy (`Spring present 260/24`) với `[Xếp chồng (Ctrl+G), Xếp lưới (Shift+O), Xuất, Xóa]`.
  - **Collapsed Physical Pile (`Ctrl + G`):** Gom ảnh về tâm chọn (`Spring place 300/30` + `Spring pop 420/14`). Hình đại diện (`is_stack_cover=True`) luôn đứng đầu `#0` (`0°`, `zValue` cao nhất qua `sort_stack_members`), tối đa 12 lớp dưới xếp so le hạt giống cố định kèm góc xoay nhẹ `±1.0° .. ±2.8°` (`Seeded Collage Scatter`, tự ẩn từ lớp 13 trở đi giữ vững `>100 FPS`). Bóng đổ mềm `_draw_soft_card_shadow` và biên `boundingRect()` cố định theo hệ tọa độ item (kẹp chặt trong vùng đệm `pad`) giúp chỉ số BSP của `QGraphicsScene` ổn định ở mọi mức zoom.
  - **Nhãn Số Lượng `[N]` & Tên Group Tách Rời (`StackOverlayLabelItem`):** Tách hoàn toàn nhãn `[N]` và `stack_name` (`Be Vietnam Pro Light 300`, `#1A1A1C` / `#EAEAF0`) sang `StackOverlayLabelItem` phi tương tác (`shape()` rỗng, `LOD < 24px` tự ẩn), không làm phình `boundingRect()` của thẻ ảnh; chuẩn hóa HiDPI (`devicePixelRatioF()`) cho cả `StackOverlayLabelItem` lẫn Cover badge `#FFDA12` để giữ kích thước 1:1 trên màn hình `1x`/`1.5x`/`2x` và tự đồng bộ tức thời khi di chuyển, xoay/resize, zoom, đổi theme hoặc Undo/Redo.
  - **Click Đơn Chọn/Di Chuyển/Resize — Nhấp Đúp Bung Lưới `rpack` Optimal (`Spread`):** Click đơn chọn gọn Group với **khung chọn mảnh `1px` (`#3A3C42`) + 4 chấm tròn góc `4px`** (`constants.py` & `selection.py`), hỗ trợ kéo & Resize an toàn (`factor >= 0.04`, `get_stack_center` luôn đọc tâm Cover thực tế chống văng tọa độ 100%). **Nhấp đúp (`Double-Click`)** phủ lớp mờ `CanvasWashItem` (`α = 0.80`, `0.30s`) kèm khóa chống đóng nhầm 3rd-click `0.28s` (`can_dismiss_spread_by_wash`), bung lưới bằng **`rpack.pack` Optimal Spread thuần** (loại bỏ vòng lặp bảng cứng, căn tâm chuẩn `0.0px` không lệch `gap/2`). Click ra ngoài hoặc bấm `Esc` để thu gọn (`0.24s`).
  - **Kéo Chọn Khe Hẹp, `Ctrl+Click` / `Ctrl+A` & `Hover Micro-Bounce`:** Dùng `IntersectsItemShape` khi kéo khung chọn qua các khe hẹp (kể cả khoảng trống bên trong khung `MultiSelectItem`), `Ctrl+Click` bật/tắt chọn nguyên nhóm thu gọn, `Ctrl+A` chỉ chọn các thẻ đang hiển thị (bỏ qua lớp ẩn); hiệu ứng nhún nhẹ `Hover Micro-Bounce` (`Spring lift 420/26`) kẹp gọn trong `pad`, tự tạm ngưng khi đang kéo/pan/zoom và dừng timer ở `0% CPU` khi nghỉ.
  - **Kéo Tách Khỏi Nhóm (`Pull-Out`) & Undo/Redo An Toàn (`cancel_flights_for`):** Kéo 1 thẻ trong lưới Spread ra ngoài `keep_zone` (`±48px`) kích hoạt các thẻ còn lại tự dồn hàng tức thời (`Spring place 300/30`). Bổ sung `cancel_flights_for` dọn animation đang bay và khôi phục tỷ lệ gốc trước các lệnh `CreateStack`, `Unstack`, `PullOut`, `DeleteItems`, `SetStackCover`, `ArrangeItems` để tránh mất hiển thị khi `Ctrl+Z` giữa chừng.
- [x] **Màn Hình Xem Chi Tiết `DetailStageOverlay` (`beeref/widgets/detail_stage.py`):**
  - **Cột trái:** Ô tròn Tick chọn **Hình đại diện Group** (`28×28px`, nền vàng `#FFDA12` khi active) + dòng nhập **Tên nhóm (`Tên nhóm...`)** nằm ngay bên dưới + **5 ô màu chủ đạo** (`K-Means` sắp từ sáng đến tối, click để copy mã HEX).
  - **Cột phải:** `KÍCH THƯỚC` (`W × H`), `TÊN TỆP` (**nhấp đúp sửa tên thông minh** chỉ bôi đen phần tên và giữ khóa nguyên phần đuôi `.jpg`/`.png`), `NGÀY TẠO` (**hiển thị đầy đủ ngày, tháng, năm**: `Tạo vào DD tháng MM, YYYY`), và ô **`Viết ghi chú...`** đặt ngay bên dưới `NGÀY TẠO`.
  - **Thanh Dark Toolbar đáy Stage:** Giữ nút `Điều chỉnh` (`sliders.svg`) ở trạng thái làm mờ (`opacity=0.28`, vô hiệu hóa chờ phát triển sau), cùng 3 nút `Sao chép`, `Xuất ảnh`, `Xóa ảnh`.
- [x] **Lưu/Mở trọn vẹn trong file dự án `.bee` (SQLite JSON) & Full Undo/Redo** cho mọi thao tác nhóm.
- [x] **Tài liệu hướng dẫn chuyên sâu & Đóng gói phát hành `Birdboard v1.1.0` (`2026-11-20`):**
  - Hoàn thiện bộ hướng dẫn chuyên sâu [docs/STACK_GROUP_AND_ARRANGEMENT_GUIDE.md](docs/STACK_GROUP_AND_ARRANGEMENT_GUIDE.md), cập nhật [docs/ARRANGE_OPTIMAL_AND_GAP_GUIDE.md](docs/ARRANGE_OPTIMAL_AND_GAP_GUIDE.md) & [docs/CONTROLS_AND_SHORTCUTS.md](docs/CONTROLS_AND_SHORTCUTS.md).
  - Đóng gói `release/v1.1.0/` + `release/Birdboard-v1.1.0-Source-and-Docs.zip` và phát hành GitHub Release `v1.1.0`.

---

## Backlog Tiếp Theo (Dự kiến cho `v1.2` / `v2.0`)

### 1. Bảng Đồng Hồ Nổi — *Floating Clock HUD Pill* (Ưu tiên hàng đầu ở Round kế tiếp)
- [ ] Thiết kế thẻ thuốc nổi cố định ở góc trái trên của khung nhìn (không bị trôi khi Pan/Zoom ảnh trên Canvas):
  - **Cụm trái:** Huy hiệu vuông bo góc đồng tâm chứa icon Bảng / Thư mục.
  - **Cụm giữa:** Thứ trong tuần + Ngày tháng tiếng Việt xếp gọn 2 dòng (ví dụ: `Thứ Năm` / `19 tháng 11`).
  - **Cụm phải:** Đồng hồ số nét mảnh thanh thoát (`HH:MM:SS`) cập nhật mỗi giây bằng `QTimer` nhẹ (`0% CPU`).
  - **Thích ứng giao diện:** Tự động đổi chất liệu thẻ sáng (`#FFFFFF` trên nền `#E9EAEC`) hoặc thẻ tối (`#242429` / kính mờ trên nền `#1A1A1D`), có tùy chọn ẩn/hiện nhanh.

### 2. Cụm Nút Tiện Ích Nổi Góc Màn Hình (Tùy chọn mở rộng)
- [ ] Nút gạt nhanh Light/Dark Mode & Cài đặt nhanh ở góc dưới bên trái.
- [ ] Nút thêm ảnh nhanh (`+`), đếm tổng số ảnh trên bảng hoặc tìm kiếm nhanh theo tên file ở góc phải.

### 3. Công Cụ Tham Chiếu Nâng Cao (Tham chiếu từ `reporef/`)
- [ ] **Chế độ Overlay Xuyên Chuột (`Click-Through Mode`):** Khóa bảng, giảm độ đục cửa sổ và cho phép vẽ xuyên chuột xuống phần mềm bên dưới.
- [ ] **Hỗ trợ Ảnh động GIF & Video ngắn** (tham chiếu cơ chế điều khiển frame từ `reporef/AnimRef`).
- [ ] **Vẽ đánh dấu nhanh trên bảng (`Annotation Strokes`)** & **Nhập file `.pur` cũ** (tham chiếu `reporef/PureRef-format` nếu phát sinh nhu cầu).
- [ ] **Xuất bản gói `Birdboard.exe` Portable** đóng gói hoàn chỉnh kèm trình tạo Shortcut ra Desktop.
