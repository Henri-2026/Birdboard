# Phân Tích Đối Chiếu Các Kho Mã Nguồn Tham Chiếu (`REFERENCE_ANALYSIS.md`)

Tài liệu này tổng hợp kết quả khảo sát kỹ thuật từ các kho mã nguồn mở lưu trong `reporef/` và giải thích những gì **Birdboard** kế thừa, cải tiến hoặc dự phòng cho tương lai.

---

## 1. Bảng Đối Chiếu Tổng Quan

| Tiêu chí | PureRef *(Đóng mã nguồn)* | `reporef/beeref` *(Gốc mở)* | `reporef/PureRef-format` | `reporef/AnimRef` | **Birdboard `v1.0.0`** |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **Ngôn ngữ / UI** | C++ / Qt | Python / PyQt6 | Python (CLI/Lib) | JS / Electron | **Python / PyQt6 + OpenGL** |
| **Kết xuất đồ họa** | GPU Custom | CPU Raster `QWidget` | Không có GUI | Chromium Canvas | **GPU `QOpenGLWidget` 4x MSAA** |
| **Quản lý RAM >1.000 ảnh** | Mipmap / Streaming | Giữ 100% `QPixmap` gốc (Lag/Tràn RAM) | Không áp dụng | Nặng RAM do Electron | **3-Tier LOD + Async LRU Cache** |
| **Xếp ảnh >1.000 tấm** | Nhanh | Treo lâu do `rpack` $O(N^{2.5})$ | Xếp tĩnh khi tạo file | Cơ bản | **Lai `rpack` + Masonry $O(N \log K)$ (<5ms)** |
| **Định dạng lưu trữ** | Nhị phân đóng `.pur` | SQLite `.bee` (`sqlar`) | Đọc/Ghi `.pur` | JSON / Local | **SQLite `.bee` + bảng đệm `lod_thumbs`** |
| **Menu chuột phải** | Context menu tối giản | `QMenu` hệ thống (Lỗi chữ mờ Win11) | Không có | HTML Menu | **Penart Frosted Glass 120 FPS** |

---

## 2. Chi Tiết Giá Trị Khai Thác Từ Từng Repo Trong `reporef/`

### 2.1. `reporef/beeref` (`rbreu/beeref`)
- **Phần giữ lại & kế thừa:**
  - Cấu trúc hướng đối tượng sạch giữa `Scene`, `View`, `SelectableMixin`, `QUndoStack` và các công cụ biến đổi không phá hủy ảnh gốc (Crop, Flip, Rotate, Scale, Grayscale, Sample Color, Exporters).
  - Ý tưởng dùng cơ sở dữ liệu SQLite chuẩn `sqlar` đóng gói gọn toàn bộ bảng tham chiếu thành 1 file duy nhất.
- **Phần đã thay thế hoàn toàn trong Birdboard:**
  - Thay bộ nạp tuần tự có `msleep(10)` bằng `ThreadPoolExecutor` + C++ DCT scaling.
  - Thay `QPixmap` đơn tầng bằng `LODCacheManager` 3 tầng.
  - Thay `QMenu` hệ thống bằng `PenartMenuController`.
  - Thay cửa sổ mặc định bằng cửa sổ không viền bo góc + bóng đổ Windows 11 DWM.

### 2.2. `reporef/PureRef-format` (`FyorDev/PureRef-format`)
- **Kết luận khảo sát:** Chỉ chứa bộ đọc/ghi nhị phân cho file `.pur` (`pur.hexpat` và module Python), không có giao diện hay bộ dựng hình nên không cần nhúng vào lõi Birdboard ở v1.0.
- **Ứng dụng tương lai:** Nếu cần công cụ chuyển đổi các bảng `.pur` cũ sang định dạng của Birdboard, có thể gọi trực tiếp parser trong `reporef/PureRef-format` để đọc tọa độ ma trận `x, y, z, scale, rotation, crop` và trích xuất luồng PNG sang bảng SQLite của Birdboard.

### 2.3. `reporef/AnimRef` (`lettucegoblin/AnimRef`)
- **Ứng dụng tương lai:** Tham khảo cách thiết kế thanh timeline mini dưới chân đối tượng Video/GIF (Play/Pause, lăn chuột tiến/lùi từng frame để học chuyển động Animation) khi bổ sung `BeeVideoItem` / `BeeGifItem` cho Birdboard ở các phiên bản tới.
