# Birdboard v1.1.0 — Release Package (`RELEASE_NOTES.md`)

Gói phát hành chính thức của **Birdboard v1.1.0**, giới thiệu trọn bộ tính năng **Nhóm Xếp Chồng Vật Lý (`Stack Group`)**, **Màn hình Xem Chi Tiết (`Detail Stage View`)**, nâng cấp động cơ **Sắp Xếp Khối Vuông Thuần `rpack` (`Multi-Width Optimal Packing`)** dùng chung cho cả bảng chính lẫn bung lưới nhóm, cùng **bộ tài liệu hướng dẫn & quy tắc kỹ thuật chuyên sâu (`docs/`)**.

---

## 1. Điểm Mới Trọng Tâm Trong `Birdboard v1.1.0`

### A. Tính Năng Gom Nhóm Xếp Chồng (`Stack Group`) & Quy Tắc Nội Tại
- **Gom & Tách Nhóm tức thời (`Ctrl + G` / `Ctrl + Shift + G`):**
  - Chọn `>= 2` ảnh → thanh công cụ đảo màu `ContextualToolbar` trồi lên ở đáy (`Spring 260/24`) → gom về xấp bưu thiếp xếp chồng mượt mà ở `120 FPS` (`Spring place 300/30` + `pop 420/14`).
  - Hỗ trợ gộp thêm ảnh rời hoặc gộp nhiều nhóm cũ với nhau mà không bao giờ bỏ sót thẻ lớp sâu đang ẩn.
- **Quy tắc Hình Đại Diện (`Cover Priority`) & Xấp Collage Hạt Giống (`Seeded Collage Scatter`):**
  - Ảnh được chọn làm đại diện (`is_stack_cover = True`) **luôn đứng vị trí `#0` (`0°`, `zValue` cao nhất)** — không bao giờ bị thứ tự tên tệp ghi đè.
  - Hiển thị tối đa **12 thẻ lót (`MAX_VISIBLE_UNDERLAYS = 12`)** lấy mẫu đều đại diện trên toàn nhóm, rải lộ viền tự nhiên theo hạt giống cố định kèm góc nghiêng nhẹ **`±1.0° .. ±2.8°`** và chuẩn hóa diện tích $\sqrt{W \cdot H}$; tự động ẩn từ thẻ thứ 14 trở đi để giữ vững **`> 100 FPS`** cho bảng hàng ngàn ảnh.
- **Nhãn Số Lượng `[N]` & Tên Nhóm Lơ Lửng (`StackOverlayLabelItem` — Chuẩn HiDPI):**
  - Hiển thị số lượng ảnh nét mỏng `[N]` (`Be Vietnam Pro Light 11px`) ở góc phải trên và **Tên nhóm** (`Light 13px`) lơ lửng phía dưới giống tên thư mục.
  - Tách hoàn toàn khỏi `BeePixmapItem` (`shape()` rỗng, phi tương tác, chuẩn hóa `devicePixelRatioF()` trên màn `1x`/`1.5x`/`2x`, tự ẩn khi `< 24px` LOD) kết hợp bất biến `boundingRect()` cố định giúp chỉ mục `BspTreeIndex` của Qt6 ổn định tuyệt đối trên bảng lớn `> 160.000 px`.
- **Tương Tác Click Đơn / Nhấp Đúp / Kéo Tách (`Pull-Out`) & Undo An Toàn:**
  - **`Click đơn`:** Chọn, kéo di chuyển và Resize/Xoay trọn cả nhóm (đồng bộ cả thẻ ẩn, khóa tỷ lệ tối thiểu `>= 0.04`). `Ctrl + Click` bật/tắt chọn nguyên nhóm; `Ctrl + A` chỉ chọn thẻ đang hiển thị.
  - **`Nhấp đúp (Double-Click)`:** Phủ màn mờ **`Canvas Wash` (`α = 0.80`)** kèm khóa chống đóng nhầm 3rd-click `0.28s`, bung lưới bằng **động cơ `Optimal` (`Shift + O`)**.
  - **Kéo tách (`Pull-Out`):** Kéo 1 thẻ vượt biên lưới `±48px` kích hoạt các thẻ còn lại tự dồn hàng thời gian thực (`Live Grid Reflow`), tự chuyển Cover hoặc tự giải thể khi còn 1 ảnh.
  - **An toàn dữ liệu 100%:** `cancel_flights_for()` hủy mọi chuyển động bay dở trước các lệnh `Undo/Redo`, khôi phục trạng thái đầy đủ; lưu trọn 10 trường metadata nhóm & chi tiết vào file `.bee` (SQLite JSON).

### B. Màn Hình Xem Chi Tiết (`Detail Stage View`)
- **Cột trái:** Ô tròn tích chọn Hình đại diện vàng **`#FFDA12`**, ô nhập **`Tên nhóm...`** đồng bộ ra bảng chính, và **5 ô màu chủ đạo (`K-Means`, sáng → tối)** click để copy mã `HEX`.
- **Cột phải:** `KÍCH THƯỚC` (`W × H`), `TÊN TỆP` (**nhấp đúp sửa tên thông minh giữ nguyên đuôi `.jpg`/`.png`**), `NGÀY TẠO` (**đủ ngày, tháng, năm 4 chữ số**), và ô **`Viết ghi chú...`** đặt ngay bên dưới `NGÀY TẠO`.
- **Thanh Dark Toolbar đáy:** Nút `Điều chỉnh` (`sliders`, làm mờ vô hiệu hóa chờ phát triển sau), `Sao chép`, `Xuất ảnh`, `Xóa ảnh`.

### C. Nâng Cấp Sắp Xếp Hình (`Multi-Width Pure rpack` & `Stack-Aware Arrange`) & Tinh Chỉnh Toàn Ứng Dụng
- **Động cơ Sắp Xếp Hợp Nhất (`scene.pack_optimal_sizes`):** Đánh giá 6 bề rộng khởi điểm kèm trần chiều cao `1.28×` và hàm chấm điểm diện tích + tỷ lệ vuông → tạo lưới **`4 × 4` chuẩn xác** cho 16 ảnh cùng tỷ lệ và tỷ lệ khung **`≈ 1.06`** cho tập ảnh hỗn hợp, căn tâm **`0.0px`** không trôi `gap/2`, tự chuyển sang `_pack_large_masonry` ($O(N \log K)$, `< 5ms`) khi `> 300` phần tử.
- **Sắp xếp nhận diện Nhóm (`Stack-Aware`):** Khi bấm `Shift + O`, `Shift + G` (`Arrange Gap`), `Horizontal`, `Vertical` hoặc `Square`, mỗi nhóm thu gọn được gom tính như **1 đơn vị nguyên khối** đo theo khung xấp xòe đầy đủ và dịch chuyển đồng bộ toàn bộ thẻ underlay & thẻ ẩn.
- **Hoàn thiện thị giác & cảm giác chuột:** Đổ bóng **9-patch Gaussian** mịn (`13.5px` blur), khung chọn mảnh gốc **`1px` màu xám đen (`#3A3C42`/`#A8AAB2`) + 4 chấm tròn góc `4px`**, kéo chọn chính xác qua **khe hẹp** (`IntersectsItemShape`, kể cả khoảng trống bên trong `MultiSelectItem`), và phản hồi **`Hover Micro-Bounce`** siêu nhẹ (`0% CPU` khi nghỉ).

---

## 2. Thành Phần Trong Thư Mục `release/`

- **`Birdboard-v1.1.0-Source-and-Docs.zip`**: Bản nén hoàn chỉnh chứa toàn bộ Source Code sạch + bộ tài liệu `docs/` mới nhất kèm hình ảnh minh họa.
- **`v1.1.0/source/`**: Mã nguồn sạch của Birdboard v1.1.0 (`beeref/`, `docs/`, `tests/`, `pyproject.toml`, `Birdboard.spec`, `Run-Birdboard.bat`, `AGENT.md`, `PROGRESS.md`, `README.md`, `LICENSE`).
- **`v1.1.0/docs/`**: Bộ tài liệu hướng dẫn & giải phẫu kỹ thuật đầy đủ:
  1. **`STACK_GROUP_AND_ARRANGEMENT_GUIDE.md`** *(Trọng tâm `v1.1.0`)*: Hướng dẫn sử dụng chi tiết + trọn bộ **8 quy tắc nội tại của Nhóm Xếp Chồng**, `Detail Stage View`, tương tác chuột/khung chọn, lưu trữ `.bee`, và thuật toán sắp xếp hình hợp nhất.
  2. **`ARRANGE_OPTIMAL_AND_GAP_GUIDE.md`** *(Cập nhật `v1.1.0`)*: Hướng dẫn & giải phẫu toán học Multi-Width Pure `rpack`, Masonry $O(N \log K)$, `Arrange Gap` (`Shift + G`), và `Stack-Aware Arrange`.
  3. **`ZERO_LAG_AND_ANTI_ALIASING_GUIDE.md`**: Kỹ thuật hiển thị >1.000 – 5.000+ ảnh `>100 FPS`, `QOpenGLWidget 4x MSAA`, 3-Tier Mipmap LOD & Async LRU Cache.
  4. **`CONTROLS_AND_SHORTCUTS.md`** *(Cập nhật `v1.1.0`)*: Bảng tra cứu đầy đủ phím tắt & thao tác chuột bao gồm toàn bộ thao tác Nhóm Xếp Chồng.
  5. **`STACK_GROUP_BIRDBOARD_SPEC.md`**, **`ARCHITECTURE.md`**, **`UI_DESIGN_SYSTEM.md`**, **`REFERENCE_ANALYSIS.md`**.

---

## 3. Hướng Dẫn Chạy Nhanh Từ Gói Source Code

```powershell
# Giải nén gói release và mở PowerShell tại thư mục source:
python -m venv .venv
.\.venv\Scripts\pip install -e .
.\Run-Birdboard.bat
```

---

## 4. Lịch Sử Phát Hành Trước Đó (`v1.0.0`)

- **`Birdboard-v1.0.0-Source-and-Docs.zip`** & **`v1.0.0/`**: Bản phát hành nền tảng với lõi chống lag >1.000 ảnh (`QOpenGLWidget 4x MSAA` + 3-Tier Mipmap LOD + SQLite `lod_thumbs`), menu chuột phải Kính Mờ Penart `480ms` @ `120 FPS`, hai chế độ Sáng/Tối DWM, thuật toán `Arrange -> Optimal` (`Shift + O`) và `Arrange Gap` (`Shift + G`).
