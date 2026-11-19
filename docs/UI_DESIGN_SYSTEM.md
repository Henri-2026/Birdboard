# Hệ Thống Thiết Kế Giao Diện & Chuyển Động (`UI_DESIGN_SYSTEM.md`)

Tài liệu này quy định hệ màu, hình học bo góc, vật lý chuyển động chuẩn **Penart (`penart-ui-craft`)** đã áp dụng trong **Birdboard**, cùng bản thiết kế chi tiết cho các thành phần UI tiếp theo.

---

## 1. Hệ Màu Dual-Theme (`Studio Light` & `Penart Matte Dark`)

Chuyển đổi trực tiếp không cần khởi động lại tại `Chuột phải -> Settings -> Settings -> Appearance & General -> Canvas Theme`:

| Token / Thành phần | **Light Mode** *(Mặc định)* | **Dark Mode** *(Penart)* |
| :--- | :--- | :--- |
| **Nền Canvas (`Scene:Canvas`)** | `#E9EAEC` (`rgb(233, 234, 236)`) | `#1A1A1D` (`rgb(26, 26, 29)`) |
| **Chữ ghi chú (`Scene:Text`)** | `#1C1C22` | `#F2F2F7` |
| **Khung & Tay nắm chọn (`Scene:Selection`)** | `#3A82F7` | `#3A82F7` |
| **Viền tách nền cửa sổ DWM (`1px`)** | `#C4C7CC` | `#34343C` |
| **Bóng đổ dưới chân tranh (khi zoom gần)** | `rgba(0, 0, 0, 28)` | `rgba(0, 0, 0, 28)` |

---

## 2. Bảng Dropdown Chuột Phải Chuẩn Penart (`beeref/widgets/penart_menu.py`)

Cố định chất liệu **Kính Mờ Đen chữ Trắng** cho cả hai chế độ Sáng và Tối để đảm bảo độ tương phản cao nhất trên mọi bức tranh:

- **Chất liệu Kính Mờ (`Frosted Glass`):**
  - Lấy mẫu trực tiếp vùng Canvas/tranh bên dưới menu → tăng độ bão hòa `150%` → làm mờ Gaussian thực `~20px` → phủ lớp tối `rgba(28, 28, 34, 0.84)`.
  - Viền phản quang ngoài: `1px rgba(255, 255, 255, 0.16)`.
  - Viền sáng mép trên bên trong: `1px rgba(255, 255, 255, 0.12)`.
  - Bóng đổ Gaussian không gợn bậc: `rgba(0, 0, 0, 0.48)`.
- **Hệ chữ & Trạng thái:**
  - Mục đang bật: `#F2F2F7` (khi hover sáng lên `#FFFFFF`).
  - Phím tắt & Mũi tên submenu `›`: `#9A9AA2` (khi hover `#D4D4DC`).
  - Mục đang khóa (Disabled): `#6C6C74`.
  - Huy hiệu tích chọn (`✓`): Nền xanh `#3A82F7` bo góc `4.2px`.
- **Bo Viền Đồng Tâm (`Concentric Corner Radius`):**
  $$R_{\text{outer}} (11\text{px}) = R_{\text{inner}} (6\text{px}) + \text{Padding} (5\text{px})$$
- **Vật Lý Hạ Dropdown Có Quán Tính (`480ms` @ `120 FPS`):**
  - Đường cong: `cubic-bezier(0.16, 1, 0.3, 1)`.
  - Quỹ đạo 3 mốc Keyframe quanh tâm góc trên:
    - `0%`: `opacity = 0.00`, `translateY = -18px`, `scaleY = 0.76`, `scaleX = 0.94`
    - `46%`: `opacity = 0.92`, `translateY = -3px`, `scaleY = 0.97`, `scaleX = 0.99`
    - `100%`: `opacity = 1.00`, `translateY = 0px`, `scaleY = 1.00`, `scaleX = 1.00`

---

## 3. Cửa Sổ DWM Không Viền & Cụm 3 Chấm Điều Khiển (`beeref/win_dwm.py`)

- Sử dụng `DwmSetWindowAttribute` trên `HWND` của riêng cửa sổ Birdboard:
  - Bo tròn 4 góc phần cứng (`DWMWCP_ROUND`).
  - Quầng bóng đổ sâu tự nhiên của Windows 11 DWM phủ lên các cửa sổ nền phía sau.
  - Kéo di chuyển cửa sổ mượt ở dải `28px` mép trên cùng và kéo giãn kích thước ở cả 8 cạnh/góc (`6px` border).
  - Cụm **3 chấm tròn** ở góc trái trên: Đỏ `#FF5F57` (Đóng), Vàng `#FEBC2E` (Thu nhỏ), Xanh `#28C840` (Phóng to / Khôi phục).

---

## 4. Thiết Kế Lưu Trữ Cho Giai Đoạn Tiếp Theo: "Bảng Đồng Hồ" (`Clock HUD Pill`)

*(Đã chốt ý tưởng từ ảnh mẫu tham chiếu, dành cho bản cập nhật tiếp theo)*:

- **Vị trí:** Nổi cố định trên không gian màn hình của Viewport (góc trái trên, bên dưới cụm 3 chấm điều khiển), giữ nguyên kích thước và vị trí khi người dùng Pan/Zoom ảnh.
- **Cấu trúc 3 phần trên một thẻ thuốc ngang (`Pill Card`):**
  1. **Trái:** Ô vuông bo góc đồng tâm nền tối chứa biểu tượng Thư mục / Bảng hiện tại.
  2. **Giữa:** Thứ trong tuần (chữ nhỏ màu phụ) xếp trên Ngày & Tháng tiếng Việt in đậm vừa (ví dụ: `Thứ Năm` / `19 tháng 11`).
  3. **Phải:** Đồng hồ số `HH:MM:SS` dùng phông chữ nét mảnh hiện đại (`Light / Thin tabular-nums`), cập nhật mỗi `1000ms`.
- **Màu sắc theo Theme:**
  - *Light Mode:* Thẻ trắng `#FFFFFF` nổi êm trên nền xám `#E9EAEC` với bóng đổ nhẹ `rgba(0,0,0,0.06)`.
  - *Dark Mode:* Thẻ tối `#242429` viền `1px rgba(255,255,255,0.10)` nổi trên nền `#1A1A1D`.
