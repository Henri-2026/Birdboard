# Birdboard — Nhật Ký Tiến Độ & Lộ Trình Phát Triển (`PROGRESS.md`)

Tài liệu này theo dõi chi tiết các cột mốc đã hoàn thành, kiến trúc đã triển khai và danh sách tính năng dự kiến cho các phiên bản tiếp theo của **Birdboard**.

---

## Phiên bản hiện tại: `v1.0.0` (Đã hoàn thành & Push GitHub)

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

---

## Backlog Tiếp Theo (Dự kiến cho `v1.1` / `v2.0`)

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
