# Birdboard v1.0.0 — Release Package (`RELEASE_NOTES.md`)

Gói phát hành chính thức của **Birdboard v1.0.0**, bao gồm đầy đủ **Source Code** và **Bộ Tài Liệu Kỹ Thuật Chuyên Sâu (`docs/`)** về thuật toán xếp khối vuông tối ưu (`Arrange -> Optimal`), chỉnh khoảng cách khe hở (`Arrange Gap`), và kiến trúc hiển thị hàng ngàn hình ảnh không giật lag, không răng cưa.

---

## 1. Thành Phần Trong Thư Mục `release/`

- **`Birdboard-v1.0.0-Source-and-Docs.zip`**: Bản nén hoàn chỉnh chứa toàn bộ Source Code sạch + bộ tài liệu `docs/` kèm hình minh họa (dùng để lưu trữ, chia sẻ hoặc triển khai nhanh sang máy mới).
- **`v1.0.0/source/`**: Bản mã nguồn sạch của Birdboard (`beeref/`, `pyproject.toml`, `Birdboard.spec`, `Run-Birdboard.bat`, `AGENT.md`, `PROGRESS.md`, `README.md`, `LICENSE`).
- **`v1.0.0/docs/`**: Bộ tài liệu kỹ thuật & hướng dẫn sử dụng chi tiết được trích xuất riêng để tra cứu nhanh:
  1. **`ARRANGE_OPTIMAL_AND_GAP_GUIDE.md`** *(Trọng tâm #1)*:
     - Hướng dẫn sử dụng `Arrange -> Optimal` (`Shift + O`) gom hàng loạt hình thành khối vuông khít nhau.
     - Hai cách điều chỉnh khoảng cách khe hở giữa các hình (`Arrange Gap` từ `0 – 200 px`): Thanh kéo xem trước trực tiếp `Arrange -> Arrange Gap...` (`Shift + G`) và thiết lập cố định trong `Settings -> Images & Items -> Arrange Gap`.
     - Giải phẫu toán học & mã nguồn thuật toán lai 2 tầng: **Exact 2D Bin-Packing (`rpack`)** cho $\le 300$ hình và **Masonry Column Min-Heap ($O(N \log K)$)** dưới `5ms` cho $300 - 10.000+$ hình, kèm công thức bù lệch tọa độ khi ảnh đã Crop/Xoay.
  2. **`ZERO_LAG_AND_ANTI_ALIASING_GUIDE.md`** *(Trọng tâm #2)*:
     - Hướng dẫn vận hành và giải phẫu 4 cơ chế triệt tiêu giật lag & răng cưa khi nạp trên 1.000 – 5.000+ hình độ phân giải cao:
       - Kết xuất phần cứng **`QOpenGLWidget` (`4x MSAA`)** đạt >100 FPS.
       - **Tháp ảnh Mipmap 3 tầng (`384px` / `1280px` / `Full-Res 1:1`)** lọc vùng chống răng cưa trong C++ (`2x DCT` + `SmoothTransformation`) kết hợp giải mã ngầm bất đồng bộ và **Byte-Budget LRU Eviction**.
       - Khóa gom lô sự kiện `batch_update()` + đệm khung bao $O(1)$ + cây không gian `BSP Depth 12`.
       - Định dạng lưu trữ SQLite `.bee` nhúng bảng đệm `lod_thumbs` giúp mở lại dự án hàng ngàn ảnh trong ~1 giây.
  3. **`ARCHITECTURE.md`**: Sơ đồ tổng thể kiến trúc hệ thống Birdboard.
  4. **`UI_DESIGN_SYSTEM.md`**: Hệ màu Studio Light (`#E9EAEC`) / Penart Matte Dark (`#1A1A1D`), Dropdown Kính Mờ `480ms` @ `120 FPS`, và thiết kế lưu trữ cho Bảng Đồng Hồ.
  5. **`REFERENCE_ANALYSIS.md`** & **`CONTROLS_AND_SHORTCUTS.md`**.

---

## 2. Hướng Dẫn Chạy Nhanh Từ Gói Source Code

```powershell
# Giải nén gói release và mở PowerShell tại thư mục giải nén:
python -m venv .venv
.\.venv\Scripts\pip install -e .
.\Run-Birdboard.bat
```
