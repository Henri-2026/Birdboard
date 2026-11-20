<p align="center">
  <img src="beeref/assets/logo.png" width="128" height="128" alt="Birdboard Logo" />
</p>

<h1 align="center">Birdboard</h1>

<p align="center">
  <strong>Bảng tham chiếu vô cực (Infinite Reference Canvas) cá nhân hóa, hiệu năng cao trên nền GPU OpenGL.</strong>
</p>

---

## 1. Giới Thiệu

**Birdboard** là ứng dụng bảng tham chiếu hình ảnh (Moodboard & Reference Viewer) được thiết kế tối ưu cho việc nạp **hàng ngàn bức ảnh độ phân giải cao (1.000 – 5.000+ hình)** mượt mà không giật lag, kết hợp ngôn ngữ thiết kế **Studio Light / Penart Matte Dark** và hệ thống **Dropdown Kính Mờ Chuyển Động Quán Tính 120 FPS**.

---

## 2. Điểm Nổi Bật Của Birdboard `v1.1.0`

- **Nhóm Xếp Chồng Vật Lý (`Stack Group`), `Detail Stage View` & Tương Tác Chuẩn Xác (`v1.1.0`):**
  - Gom nhiều hình thành xấp bưu thiếp xếp so le hạt giống kèm độ nghiêng nhẹ `±1.0° .. ±2.8°` (`Ctrl + G` / tách `Ctrl + Shift + G`), hiển thị số lượng nét mỏng `[N]` góc phải trên và **Tên nhóm** lơ lửng bên dưới giống thư mục (`StackOverlayLabelItem` chuẩn HiDPI `1x/1.5x/2x`).
  - **Click đơn** chọn/di chuyển/resize nguyên khối với **khung chọn mảnh `1px` xám đen (`#3A3C42`) + 4 chấm tròn góc `4px`**, đổ bóng **9-patch Gaussian** mịn không đóng viền cứng, kéo chọn chính xác qua **khe hẹp** (`IntersectsItemShape`) và hiệu ứng **Hover Micro-Bounce** (`0% CPU` khi nghỉ).
  - **Nhấp đúp (`Double-Click`)** phủ màn mờ `Canvas Wash` (`80%`) và bung lưới bằng động cơ **Multi-Width Pure `rpack` Optimal** (`4×4` trên 16 ảnh dọc, `aspect ≈ 1.06` trên ảnh pha trộn, nhận diện nhóm nguyên khối khi bấm `Shift + O` ngoài bảng); hỗ trợ kéo tách ảnh (`Pull-Out`) tự dồn hàng (`Live Grid Reflow`) và `Undo/Redo` an toàn tuyệt đối.
  - **Màn hình Xem Chi Tiết (`Detail Stage View`):** Tích chọn Hình đại diện vàng `#FFDA12`, nhập `Tên nhóm...`, 5 ô màu chủ đạo `K-Means` (click copy HEX), `TÊN TỆP` sửa thông minh khóa nguyên đuôi `.jpg`/`.png`, `NGÀY TẠO` đủ năm 4 chữ số, và `Viết ghi chú...` ngay cột phải.
- **Lõi Hiển Thị Chống Lag Tuyệt Đối (>100 FPS ở 1.200+ ảnh):**
  - Kết xuất phần cứng qua **`QOpenGLWidget` (4x MSAA)**.
  - **Tháp độ phân giải 3 tầng (3-Tier Mipmap LOD) & Async LRU Cache:** Luôn giữ bản thu nhỏ `384px` siêu nhẹ khi xem toàn cảnh; tự động giải mã ngầm bản `1280px` và `Full-Res 1:1` khi zoom gần, tự động giải phóng RAM khi lướt sang vùng khác.
  - **Nạp ảnh song song đa nhân & Lưu/Mở tức thời:** Giải mã JPEG DCT trên toàn bộ nhân CPU, thuật toán xếp gạch *Masonry Packing* $O(N \log K)$ trong vài mili-giây cho bảng lớn, và lưu kèm bộ đệm `lod_thumbs` + toàn bộ metadata nhóm trong file `.bee` (SQLite).
- **Menu Chuột Phải Kính Mờ Penart (`penart-ui-craft`) & Dual-Theme DWM:**
  - Nền kính tối `rgba(28, 28, 34, 0.84)` làm nhòe thực vùng tranh bên dưới (`blur 20px` + `saturate 150%`), bo viền đồng tâm (`11px / 5px / 6px`) và quán tính **`480ms cubic-bezier(0.16, 1, 0.3, 1)`** ở 120 FPS.
  - Chuyển đổi tức thời giữa **Studio Light Mode (`#E9EAEC`)** và **Penart Dark Mode (`#1A1A1D`)** trên cửa sổ không viền Windows 11 DWM bo góc.

---

## 3. Cấu Trúc Thư Mục Dự Án

```text
BIRDBOARD/
├── AGENT.md                  # Hướng dẫn kiến trúc & quy tắc bất biến dành cho AI Agent
├── README.md                 # Tài liệu tổng quan & hướng dẫn cài đặt, sử dụng
├── PROGRESS.md               # Nhật ký tiến độ các phiên bản & Backlog tính năng mới
├── Run-Birdboard.bat         # File nhấp đúp mở nhanh ứng dụng (không hiện cửa sổ đen)
├── Birdboard.spec            # Cấu hình xuất file Birdboard.exe độc lập (PyInstaller)
├── pyproject.toml            # Khai báo cấu hình gói Python & thư viện phụ thuộc
├── beeref/                   # Mã nguồn chính của ứng dụng Birdboard
├── docs/                     # Thư mục tài liệu kỹ thuật & thiết kế chi tiết
│   ├── STACK_GROUP_AND_ARRANGEMENT_GUIDE.md # Hướng dẫn & quy tắc Nhóm Xếp Chồng, Detail Stage & Optimal Packing
│   ├── ARRANGE_OPTIMAL_AND_GAP_GUIDE.md     # Thuật toán xếp khối vuông Optimal & khoảng cách Gap
│   ├── ZERO_LAG_AND_ANTI_ALIASING_GUIDE.md  # Kỹ thuật xem >1.000 hình không lag, không răng cưa
│   ├── STACK_GROUP_BIRDBOARD_SPEC.md        # Đặc tả gốc tính năng Group - Xếp chồng
│   ├── ARCHITECTURE.md       # Giải phẫu kiến trúc GPU, LOD Cache, Scene & SQLite
│   ├── UI_DESIGN_SYSTEM.md   # Hệ màu, vật lý chuyển động Penart & thiết kế Bảng Đồng Hồ
│   ├── REFERENCE_ANALYSIS.md # Phân tích đối chiếu các kho mã nguồn mẫu
│   └── CONTROLS_AND_SHORTCUTS.md # Hướng dẫn phím tắt & thao tác chuột
├── release/                  # Gói phát hành chính thức (Source code + Docs đóng gói)
├── reporef/                  # Các kho mã nguồn mở tham chiếu lưu tại local (gitignore)
│   ├── beeref/               # Nguồn gốc rbreu/beeref
│   ├── PureRef-format/       # Đặc tả đọc/ghi định dạng .pur của PureRef
│   └── AnimRef/              # Tham chiếu tính năng ảnh động GIF / Video
└── tests/                    # Bộ kiểm thử tự động
```

---

## 4. Cài Đặt & Khởi Chạy Nhanh (Windows)

### Mở sử dụng ngay
Nhấp đúp trực tiếp vào file **`Run-Birdboard.bat`** trong thư mục `D:\.Linh app\BIRDBOARD`.

### Thiết lập lại môi trường từ đầu (nếu sang máy mới)
```powershell
git clone https://github.com/Henri-2026/Birdboard.git
cd Birdboard
python -m venv .venv
.\.venv\Scripts\pip install -e .
.\Run-Birdboard.bat
```

---

## 5. Tài Liệu Chi Tiết

- **[Hướng Dẫn Toàn Tập: Nhóm Xếp Chồng (`Stack Group`), Quy Tắc Bên Trong & Sắp Xếp Hình (`Optimal`)](docs/STACK_GROUP_AND_ARRANGEMENT_GUIDE.md)** *(Mới ở `v1.1.0`)*
- **[Thuật toán Xếp Khối Vuông (`Arrange -> Optimal`) & Khoảng Cách (`Arrange Gap`)](docs/ARRANGE_OPTIMAL_AND_GAP_GUIDE.md)**
- **[Kỹ thuật Hiển thị >1.000 Hình Không Lag & Không Răng Cưa](docs/ZERO_LAG_AND_ANTI_ALIASING_GUIDE.md)**
- [Hướng dẫn dành cho AI Agent (`AGENT.md`)](AGENT.md)
- [Nhật ký tiến độ & Lộ trình (`PROGRESS.md`)](PROGRESS.md)
- [Kiến trúc hệ thống tổng thể (`docs/ARCHITECTURE.md`)](docs/ARCHITECTURE.md)
- [Hệ thống thiết kế UI & Chuyển động (`docs/UI_DESIGN_SYSTEM.md`)](docs/UI_DESIGN_SYSTEM.md)
- [Phân tích các Repo tham chiếu (`docs/REFERENCE_ANALYSIS.md`)](docs/REFERENCE_ANALYSIS.md)
- [Bảng phím tắt & Thao tác chuột (`docs/CONTROLS_AND_SHORTCUTS.md`)](docs/CONTROLS_AND_SHORTCUTS.md)

---

## 6. Giấy Phép & Ghi Công

**Birdboard** được phát triển tùy biến từ dự án mã nguồn mở [BeeRef](https://github.com/rbreu/beeref) (tác giả Rebecca Breu) theo giấy phép **GNU General Public License v3.0 (GPL-3.0)**.
