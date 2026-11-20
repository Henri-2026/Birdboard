# Đặc Tả Kỹ Thuật & UI/UX: Tính Năng Group - Xếp Chồng (Stack, Spread, Detail Stage, Cover Selector & Pull Out)
> **Tài liệu chuẩn hóa dành cho Tab Birdboard (`beeref` / PyQt6) & hệ thống Deskboard Design Skills.**
> Mọi thông số về bố cục, màu sắc, nhịp chuyển động (damped springs), cấu trúc dữ liệu, thứ tự ưu tiên Hình đại diện (`cover_item_id` — không xếp theo `filename`) và ánh xạ trực tiếp vào kiến trúc Birdboard (`items.py`, `scene.py`, `view.py`, `commands.py`, `fileio/sql.py`) đều đã được đóng gói hoàn chỉnh tại đây. Agent ở tab Birdboard có thể triển khai trực tiếp từ tài liệu này mà không cần phân tích lại từ đầu.

---

## 1. Tổng Quan Vòng Đời 5 Trạng Thái (5-State Lifecycle)

Tính năng **Group - Xếp chồng (`Stack Group`)** vận hành qua 5 trạng thái liên hoàn (tương ứng chính xác với Hình 1 và Hình 2):

1. **Multi-Select & Contextual Toolbar (Hình 1 - Khung 1 & 2):**
   - Quét chọn $\ge 2$ hình rời trên canvas → Thanh **Inverted Dark Toolbar** bật từ đáy lên (`Spring 260/24`), hiển thị 4 nút: `[Xếp chồng (Ctrl+S), Xếp lưới (Ctrl+G), Xuất (Ctrl+E), Xóa (Del)]`.
2. **Collapse into Stack / Gom thành Group Xếp chồng (Hình 1 - Khung 3):**
   - Bấm **Xếp chồng (`Stack`)** → Toàn bộ hình được chọn gom về tâm chung `(cx, cy)` (`Spring 300/30` + nhịp nảy `Spring pop 420/14`), dùng chung một `stack_id`.
   - **Hình đại diện (`cover_item_id`)** nằm trên cùng (`z_index` cao nhất, góc xoay `0°`, không lệch tâm); các hình bên dưới xoay nghiêng nhẹ (`±2°..5.5°`) và lệch tâm vài pixel tạo cảm giác xấp ảnh vật lý.
   - Nút đầu tiên trên Dark Toolbar tự động morph sang **Tách chồng (`Unstack`, `Ctrl+Shift+S`)**.
3. **Spread Stack / Bung lưới tạm thời trên nền mờ (Hình 2 - Khung 1):**
   - Click vào xấp Stack → Nền canvas và toàn bộ thẻ ngoài group bị phủ lớp mờ **`Canvas Wash` (`α = 0.80`, `0.30s`)**.
   - Các thẻ trong Stack bay tỏa ra thành **Lưới chuẩn (`Grid`, ví dụ 4×3 cho 12 hình)** trong `0.50s` (2 chặng: `unfold bezier` có `recoil` ở mốc `76%` → `ease-in-out` về vị trí nghỉ, góc xoay trả về `0°`).
4. **Detail Stage View + Chọn Hình Đại Diện Group (Hình 2 - Khung 2):**
   - Khi đang bung lưới (Spread), click vào **1 hình** → Mở màn hình **Detail Stage View** toàn khung:
     - **Góc trên trái:** Nút `←` (`Back`) quay lại lưới Spread.
     - **Bên trái bức hình:**
       1. **Ô tròn Tick chọn làm Hình đại diện Group (`Set as Group Cover` — Tính năng bổ sung):** Khi tick chọn, hình này được gán làm `cover_item_id` của Group và **đẩy lên trên cùng của xấp Stack** (bỏ qua thứ tự `sort_by_filename`).
       2. **Cột 5 Ô màu chủ đạo (`5 Color Swatches`):** Xếp dọc bên trái hình, trích xuất tự động từ ảnh, click để copy mã HEX.
     - **Chính giữa:** Khung hiển thị ảnh độ phân giải cao (`LOD Tier-2`).
     - **Bên phải bức hình:** Cột **Thông tin (`Metadata`)** gồm `DIMENSIONS / KÍCH THƯỚC` (`736 × 1104`), `FILENAME / NGUỒN`, `CREATED / NGÀY TẠO`.
     - **Bên dưới bức hình:** Ô nhập ghi chú **`Viết ghi chú...`** (`Write a note…`) căn lề trái theo bức hình + Thanh **Dark Toolbar** 4 nút (`[Adjust/Filters/Crop, Copy, Export, Delete]`).
5. **Pull Out / Kéo 1 hình ra ngoài Group Xếp chồng (Hình 2 - Khung 3):**
   - Khi đang ở chế độ **Spread (bung lưới)**, nhấn giữ và kéo 1 hình ra khỏi ranh giới khung lưới Spread → Hình đó tách khỏi Group (`stack_id = None`), các hình còn lại trong lưới (ví dụ 11 hình) lập tức tự động dồn hàng (`Live Grid Reflow` bằng `Spring 300/30`). Khi đóng chế độ Spread, 11 hình thu về lại thành Stack, còn hình vừa kéo ra đứng độc lập bên ngoài.

---

## 2. Cấu Trúc Dữ Liệu & Quy Tắc Sắp Xếp (Data Model & Cover Priority Rule)

### 2.1. Thuộc tính trên từng Item (`BeePixmapItem` / `CanvasItem`)
Mỗi item trong Birdboard (`beeref/items.py`) bổ sung 5 thuộc tính lưu vào `get_extra_save_data()` (tương thích 100% với JSON `data` trong bảng `items` của `.bee` SQLite mà không cần phá vỡ schema cũ):

```python
# Thuộc tính thêm vào BeeItemMixin / BeePixmapItem:
self.stack_id: str | None = None          # UUID của Group xếp chồng (None nếu là hình rời)
self.is_stack_cover: bool = False         # True nếu hình này được tick chọn làm Hình đại diện của Group
self.stack_order: int = 0                 # Thứ tự của hình trong Group (0, 1, 2...)
self.note: str = ""                       # Nội dung ghi chú ("Viết ghi chú...") ở màn hình Detail View
self.palette_hex: list[str] = []          # Cache 5 mã màu HEX chủ đạo (ví dụ ['#E5E0D8', '#BDB8B2', ...])
```

### 2.2. Quy tắc Sắp xếp Thành viên trong Group (TUYỆT ĐỐI KHÔNG ÉP SORT THEO NAME ĐÈ LÊN COVER)
Trong Birdboard hiện tại (`beeref/items.py`), hàm `sort_by_filename(items)` đang sắp xếp mọi item theo tên file (`x.filename`). Khi áp dụng cho **Group - Xếp chồng**, phải dùng hàm `sort_stack_members(items)` với quy tắc ưu tiên tuyệt đối cho **Hình đại diện (`is_stack_cover = True`)**:

```python
def sort_stack_members(items: list) -> list:
    """
    Sắp xếp các hình trong một Group Xếp chồng:
    1. Hình được tick chọn làm Hình đại diện (is_stack_cover=True) LUÔN được ưu tiên số 1
       (nằm ở mặt tiền cao nhất khi thu gọn Stack, và nằm ở ô đầu tiên khi bung lưới Spread).
    2. Các hình còn lại giữ nguyên thứ tự stack_order (hoặc thứ tự lúc gom nhóm),
       KHÔNG tự ý sort theo filename làm mất vị trí hình đại diện.
    """
    cover_items = [it for it in items if getattr(it, 'is_stack_cover', False)]
    other_items = [it for it in items if not getattr(it, 'is_stack_cover', False)]
    other_items.sort(key=lambda it: (getattr(it, 'stack_order', 0), getattr(it, 'save_id', 0) or 0))
    return cover_items + other_items
```

- **Khi thu gọn thành Xấp (`Collapsed Stack`):**
  - Danh sách `ordered = sort_stack_members(members)`.
  - **`ordered[0]` (Hình đại diện / Cover Image)** được gán **`zValue` cao nhất** trong cả nhóm (`top_z`), đặt tại đúng tâm `(cx, cy)` với **`rotation = 0.0°`**, hiển thị rõ ràng 100% ở mặt trước của xấp.
  - Các hình `ordered[1..N-1]` xếp lớp lần lượt phía dưới (`top_z - i * Z_STEP`).
- **Khi chưa có hình nào được người dùng tick chọn thủ công:**
  - Lúc mới tạo Group (`Stack`), hình đang nằm ở đầu danh sách (hoặc hình có `zValue` cao nhất lúc quét chọn) được tự động gán `is_stack_cover = True` làm hình đại diện mặc định.
- **Khi người dùng tick chọn một hình mới làm Hình đại diện:**
  - Đặt `it.is_stack_cover = (it is chosen_item)` cho toàn bộ thành viên trong `stack_id`, cập nhật lại `zValue` và render mặt tiền của Stack ngay lập tức.

---

## 3. Thuật Toán Hình Học & Bố Cục 3 Chế Độ (Layout Geometry)

### 3.1. Chế độ 1: Thu gọn thành Xấp Vật Lý (`Collapsed Physical Pile`)
Khi $N$ hình ($N \ge 2$) được gom thành một Stack tại tâm `(cx, cy)`:

1. **Hình đại diện (`index = 0`, mặt trên cùng):**
   - Vị trí tâm: `(cx, cy)` (độ lệch `\Delta x = 0, \Delta y = 0`).
   - Góc xoay hiển thị: `0.0°` (luôn ngay ngắn để dễ nhận diện nội dung Group).
   - Bóng đổ: `shadow α = 0.10, blur = 12px, offset_y = 4px` (khi hover cả xấp: nhấc `+3 screen px`, `α = 0.16, blur = 16px`).
2. **Các hình nằm dưới (`index = 1 .. N-1`):**
   - Để tạo hiệu ứng xấp ảnh tự nhiên như Hình 1 (Khung 3) mà không tốn GPU vẽ hàng trăm thẻ đè lên nhau:
     - Chỉ hiển thị tối đa **$K = \min(N - 1, 4)$ lớp thẻ đại diện ngay bên dưới** thẻ mặt tiền; các thẻ từ `index >= 5` đặt trùng vị trí tâm `(cx, cy)` và ẩn (`setVisible(False)` hoặc không vẽ trong khi Stack đang đóng) để giữ 120 FPS.
     - Công thức độ nghiêng (`tilt_deg`) và độ lệch tâm (`dx, dy` tính theo đơn vị scene, tỉ lệ theo kích thước thẻ đại diện $W_0, H_0$) cho 4 lớp dưới cùng:
       ```python
       STACK_UNDERLAY_OFFSETS = [
           # (dx_ratio, dy_ratio, tilt_deg)
           (-0.035, -0.020, -4.2),   # Lớp dưới 1: lệch nhẹ trái-trên, nghiêng -4.2°
           ( 0.040,  0.025,  3.6),   # Lớp dưới 2: lệch nhẹ phải-dưới, nghiêng +3.6°
           (-0.025,  0.035, -2.4),   # Lớp dưới 3: lệch nhẹ trái-dưới, nghiêng -2.4°
           ( 0.030, -0.025,  4.8),   # Lớp dưới 4: lệch nhẹ phải-trên, nghiêng +4.8°
       ]
       ```
     - Nếu các thẻ dưới có kích thước gốc quá lớn so với thẻ đại diện (`W_i > 1.05 * W_0` hoặc `H_i > 1.05 * H_0`), khi đang ở trạng thái **Collapsed Stack**, tạm thời co nhẹ `display_scale` của thẻ dưới sao cho kích thước hiển thị không vượt quá $1.04 \times (W_0, H_0)$ (và khôi phục `scale` thật khi bung lưới `Spread` hoặc `Unstack`). Nhờ vậy mép giấy lấp ló xung quanh thẻ đại diện luôn đều, đẹp như một xấp bưu thiếp thật.

### 3.2. Chế độ 2: Bung Lưới Tạm Thời (`Spread Grid Session`)
Khi click mở một Stack có $N$ thành viên:

1. **Tính số cột và hàng của lưới (`Grid Columns & Rows`):**
   - Với $N$ hình:
     $$\text{cols} = \lceil \sqrt{N \times 1.15} \rceil \quad (\text{ví dụ } N = 12 \Rightarrow \text{cols} = 4, \text{rows} = 3)$$
   - Khoảng cách giữa các ô: `gap = 18px` (theo chuẩn `gridGap: 18` của `deskboard-tokens`).
2. **Kích thước ô lưới đồng nhất hoặc giữ nguyên tỷ lệ:**
   - Trong chế độ Spread, mỗi hình giữ nguyên tỷ lệ khung hình thật (`True Aspect Ratio`), được căn giữa trong ô `(cell_w, cell_h)` hoặc đóng gói theo hàng có cùng chiều cao chuẩn (`row_height`) để tạo thành khối chữ nhật gọn gàng như Hình 2 (Khung 1 & 3).
   - Tâm của toàn bộ lưới Spread đặt tại tâm `(cx, cy)` của Stack (hoặc dịch nhẹ vào trong khung nhìn `viewport` nếu Stack nằm sát mép cửa sổ).
3. **Lớp phủ mờ nền (`Canvas Wash Scrim`):**
   - Vẽ một lớp phủ màu nền canvas (`#E9EAEC` ở Light mode / `#1B1C1E` ở Dark mode) với độ đục **`α = 0.80`** nằm ngay **dưới** các thẻ của Stack đang Spread (`zValue = spread_base_z - 0.5`), nhưng nằm **trên** toàn bộ các thẻ khác trên canvas.
   - Nhờ đó, toàn bộ các thẻ khác ngoài Group bị làm mờ đi 80% (như cụm thẻ bên trái ở Hình 2 - Khung 1 & 3), giúp mắt tập trung tuyệt đối vào các thẻ đang bung ra.
4. **Huy hiệu Ô tròn Tick chọn Đại diện ngay trên lưới Spread (Tùy chọn nhanh):**
   - Khi rê chuột (hover) lên một hình trong lưới Spread, ở góc trên-trái của hình đó hiện nhẹ ô tròn tick đại diện (`24×24px`); riêng hình đang là **Hình đại diện (`is_stack_cover = True`)** luôn hiện chấm/tích vàng `#FFDA12` ở góc trên-trái để người dùng biết ngay hình nào đang là bìa của Group.

### 3.3. Chế độ 3: Kéo 1 Hình Ra Ngoài Group (`Pull Out Interaction`)
Khi đang ở chế độ **Spread Grid**:

1. **Ngưỡng tách khỏi Group (`Pull-Out Boundary`):**
   - Gọi `grid_rect` là khung bao (`QRectF`) của toàn bộ lưới Spread hiện tại.
   - Vùng giữ thẻ trong Group là `keep_zone = grid_rect.adjusted(-48, -48, +48, +48)`.
2. **Hành vi khi kéo 1 thẻ (`dragged_item`):**
   - Nếu tâm của `dragged_item` vẫn nằm trong `keep_zone`: cho phép đổi vị trí thứ tự (`reorder`) giữa các ô trong lưới Spread.
   - Ngay khi tâm của `dragged_item` vượt ra ngoài `keep_zone`:
     - Đánh dấu `dragged_item` ở trạng thái **`pulled_out_preview`**: các thẻ còn lại ($N - 1$ thẻ) trong lưới Spread **lập tức chạy animation `Spring place (300/30)` dồn hàng lại** để lấp kín ô trống (như Hình 2 - Khung 3: 11 hình dồn thành 2 hàng 4 + 1 hàng 3, hình thứ 12 nằm rời bên phải).
   - Khi người dùng **thả chuột (`mouseReleaseEvent`)** ở ngoài `keep_zone`:
     - Thực thi lệnh Undoable `PullOutFromStackCommand`:
       - Xóa `stack_id` của `dragged_item` (`dragged_item.stack_id = None`, `dragged_item.is_stack_cover = False`).
       - Nếu `dragged_item` trước đó là Hình đại diện (`is_stack_cover`), tự động gán `is_stack_cover = True` cho hình đầu tiên còn lại trong Group.
       - Nếu Group chỉ còn lại 1 hình duy nhất (`len(remaining) < 2`), tự động giải tán Group (`Unstack`).

---

## 4. Đặc Tả Màn Hình Xem Chi Tiết 1 Hình (`Detail Stage View`) & Ô Tròn Tick Hình Đại Diện

Khi Group đang bung lưới (`Spread`), **click đơn vào 1 hình** (mà không kéo chuột) sẽ mở **Detail Stage View** (Hình 2 - Khung 2):

```
┌──────────────────────────────────────────────────────────────────────────────────┐
│  (←)                                                                             │  ← Nút Back (42×42 pill, inset 24px)
│                                                                                  │
│                  ┌───────────────────────────┐                                   │
│             (✓)  │                           │   KÍCH THƯỚC                      │  ← (✓) Ô tròn Tick chọn làm
│                  │                           │   736 × 1104                      │    Hình đại diện Group (28×28px)
│             (●)  │                           │                                   │
│             (●)  │                           │   NGUỒN / TÊN TỆP                 │  ← 5 Ô màu chủ đạo (28×28px, gap 10px)
│             (●)  │       HÌNH ẢNH CHI TIẾT   │   illustration_04.jpg             │    xếp dọc bên trái hình
│             (●)  │        (Full-Res LOD)     │                                   │
│             (●)  │                           │   NGÀY                            │
│                  │                           │   Tạo vào 19 tháng 11, 2026       │
│                  │                           │                                   │
│                  └───────────────────────────┘                                   │
│                  Viết ghi chú...                                                 │  ← Chỗ ghi Note (14px, căn trái theo ảnh)
│                                                                                  │
│                              ┌───────────────────┐                               │
│                              │   slider  ⧉  ↓  🗑 │                               │  ← Dark Toolbar (cao 58px, r 23px)
│                              └───────────────────┘                               │
└──────────────────────────────────────────────────────────────────────────────────┘
```

### 4.1. Chi tiết từng thành phần trên Detail Stage View
1. **Nền Stage (`Stage Backdrop`):**
   - Phủ toàn bộ vùng viewport bằng màu `--card-solid` (`#FFFFFF` ở Light mode / `#1B1C1E` ở Dark mode), fade-in `0.25s`.
   - Khung ảnh chính phóng mượt từ vị trí ô lưới lên giữa màn hình bằng **`Spring open (230 / 28)`** trong `0.55s` (khi đóng: thu về ô lưới bằng **`Spring close (320 / 34)`** trong `0.40s`).
2. **Ô Tròn Tick Chọn Làm Hình Đại Diện Group (`Group Cover Radio-Checkbox` — Bên trái bức hình):**
   - **Vị trí:** Đặt ở cột bên trái bức hình (cách mép trái bức hình `24px`, căn ngang với mép trên bức hình, nằm ngay phía trên 5 ô màu chủ đạo với khoảng cách `18px`).
   - **Kích thước:** Hình tròn đường kính **`28×28px`** (`border-radius: 50%`).
   - **Trạng thái & Tương tác:**
     - **Chưa chọn (`is_stack_cover == False`):**
       - Nền `--chrome` (`#FFFFFF` / dark `#2C2D30`), viền `1.5px solid rgba(26, 26, 28, 0.25)`, giữa có icon dấu tích mờ (`opacity: 0.25`).
       - Khi hover: phóng nhẹ `scale(1.08)` (`Spring 420/30`), viền đậm lên, hiện tooltip pill: **`Đặt làm hình đại diện nhóm`** (*"Khi chọn, hình này sẽ được đẩy lên mặt trên cùng của nhóm xếp chồng"*).
     - **Đã chọn (`is_stack_cover == True`):**
       - Nền vàng đặc trưng **`--sticky` (`#FFDA12`)**, viền `1.5px solid #E5C100`, dấu tích đậm màu `#1A1A1C` (`stroke-width: 2.2px, round cap/join`).
       - Khi click kích hoạt:
         1. Chạy animation nảy **`Spring pop (420 / 14)`** (`scale: 1.18 → 1.0`).
         2. Cập nhật `chosen_item.is_stack_cover = True` (và đặt `False` cho các hình khác trong cùng `stack_id`).
         3. Đưa `chosen_item` lên vị trí số 0 của `sort_stack_members` và gán `zValue` cao nhất trong Group (bỏ qua mọi thứ tự theo tên file).
         4. Hiện Toast xác nhận ở đáy màn hình (`bottom: 110px`): **`Đã đặt làm hình đại diện nhóm`**.
3. **Cột 5 Ô Màu Chủ Đạo (`5 Dominant Color Swatches` — Bên trái bức hình):**
   - Nằm ngay dưới ô tròn tick đại diện, gồm **5 hình tròn đường kính `28×28px`**, khoảng cách dọc `10px`.
   - **Thuật toán trích xuất màu siêu tốc (`extract_dominant_palette`):**
     - Scale `thumb_pixmap` về ảnh `48×48px`, gom nhóm màu bằng quantization / K-Means ($k = 5$), sắp xếp 5 màu tìm được theo độ sáng cảm nhận (luminance $Y = 0.2126 R + 0.7152 G + 0.0722 B$) từ **cao xuống thấp** (sáng ở trên, tối ở dưới — giống hệt Hình 2 Khung 2).
   - **Tương tác:** Hover lên ô màu → phóng nhẹ `scale(1.12)` + hiện tooltip mã HEX (`#E5E0D8`). Click vào ô màu → copy mã HEX vào `QApplication.clipboard()` + hiện Toast **`Đã sao chép #E5E0D8`**.
4. **Cột Thông Tin Bên Phải (`Metadata Column`):**
   - Cách mép phải bức hình `28px`, căn đỉnh theo mép trên bức hình, chiều rộng `200px`.
   - Gồm 3 mục (khoảng cách giữa các mục `18px`):
     - **`KÍCH THƯỚC` (`DIMENSIONS`):** `f"{item._orig_width} × {item._orig_height}"` (font `Be Vietnam Pro 600`, `13px`, `tabular-nums`).
     - **`NGUỒN / TỆP` (`SOURCE`):** Tên file gốc (`os.path.basename(item.filename)` hoặc `"Clipboard Image"`), có hỗ trợ `word-wrap` / `elide`.
     - **`NGÀY` (`DATE`):** Ngày tạo/nhập hình (`"Tạo vào DD tháng MM, YYYY"`).
5. **Chỗ Ghi Note Bên Dưới Bức Hình (`Note / Caption Field`):**
   - Đặt ngay dưới cạnh đáy của bức hình (`16px`), căn thẳng mép trái với bức hình, chiều rộng bằng chiều rộng bức hình (tối소 `280px`).
   - Font `Be Vietnam Pro 400`, `14px`, màu `--text` (`#1A1A1C` / `#EDEDEF`), placeholder màu `--text-3` (`#B3B4B8`): **`Viết ghi chú...`**.
   - Tự động lưu vào `item.note` khi người dùng gõ hoặc khi đóng Detail View (hỗ trợ Undo/Redo qua `EditItemNoteCommand`).
6. **Thanh Contextual Dark Toolbar ở đáy (`bottom: 32px`):**
   - Cao `58px`, bo góc `23px`, nền `#16181A` (dark mode đảo màu `#F5F6F7`), bóng `--sh-toolbar`.
   - 4 nút (`56×44px`, slot `62px`):
     1. **Điều chỉnh / Bộ lọc (`sliders.svg`)**: Bật/tắt Grayscale, chỉnh Opacity, hoặc vào chế độ Crop.
     2. **Sao chép (`duplicate.svg`)**: Copy hình vào clipboard.
     3. **Xuất ảnh (`download.svg`)**: Lưu/xuất hình ra máy.
     4. **Xóa (`trash.svg`)**: Xóa hình hiện tại (kèm Toast hoàn tác).

---

## 5. Bảng Thông Số Animation & Nhịp Chuyển Động (Motion & Spring Reference)

Toàn bộ chuyển động tuân thủ hệ phương trình lò xo tắt dần của `deskboard-motion` (`mass = 1, v0 = 0`, $\zeta = \frac{c}{2\sqrt{k}}$):

| Chuyển động | Tham số Spring / Bezier | Thời lượng ổn định | Mô tả chi tiết |
| :--- | :--- | :---: | :--- |
| **Gom vào Stack / Xếp lưới (`place`)** | **Spring `300 / 30`** ($\zeta = 0.87$) | `~0.50s` | Dùng khi gom các hình vào tâm Stack, khi xếp lưới `Ctrl+G`, và khi các hình còn lại tự dồn hàng lúc kéo 1 hình ra ngoài (`Pull Out`). |
| **Nhịp nảy khi Stack nhận hình (`pop`)** | **Spring `420 / 14`** ($\zeta = 0.34$) | `~0.45s` (`scale 1.06 → 1.0`) | Dùng khi xấp Stack vừa gom xong, khi thả thêm hình vào Stack, và khi tick chọn **Ô tròn Hình đại diện**. |
| **Hover nhấc thẻ / xấp (`lift`)** | **Spring `420 / 30`** ($\zeta = 0.73$) | `~0.48s` | Nhấc lên `+3 screen px` (`scale = 1 + 3 / zoom / width`), bóng đổ tăng từ `α .08 (blur 10)` lên `α .14 (blur 14)`. |
| **Bung xấp ra lưới (`Spread flight`)** | **2-segment Bezier** `[0, 0.76, 1]` | `0.50s` (thu lại: `0.24s`) | Chặng 1 (`0→0.76`): `cubic-bezier(0.16, 0.65, 0.28, 1)` vươn tới đỉnh có `recoil = min(3/zoom, 1.5% travel)`. Chặng 2 (`0.76→1`): `ease-in-out` về tâm ô lưới. |
| **Phủ mờ nền (`Canvas Wash`)** | `cubic-bezier(0.25, 0.1, 0.25, 1)` | `0.30s` | Lớp phủ màu canvas tăng độ đục từ `0 → 0.80` khi Spread Stack. |
| **Mở / Đóng Detail Stage (`open` / `close`)** | **Spring `230 / 28`** (mở) · **`320 / 34`** (đóng) | `0.55s` / `0.40s` | Phóng hình từ lưới Spread lên giữa màn hình Detail View và thu về lại ô lưới khi bấm `←` hoặc `Esc`. |
| **Toolbar bật lên (`present`) & co giãn (`soft`)** | **Spring `260 / 24`** · **`170 / 25`** | `0.49s` / `0.60s` | Thanh Dark Toolbar trồi lên từ `bottom + 60px → 0`; morph chiều rộng êm không rung. |

---

## 6. Kế Hoạch Triển Khai Trực Tiếp Cho Tab Birdboard (`D:\.Linh app\PureCanvas`)

Để tab Birdboard tích hợp nhanh, sạch và không xung đột với kiến trúc LOD hiện có, thực hiện theo 5 bước sau:

1. **`beeref/items.py`**:
   - Thêm các thuộc tính `stack_id`, `is_stack_cover`, `stack_order`, `note`, `palette_hex` vào `BeeItemMixin` / `BeePixmapItem`.
   - Lưu và khôi phục các trường này trong `get_extra_save_data()` và `create_from_data()` (tự động lưu vào cột JSON `data` của bảng SQLite `items` trong `.bee` mà không cần sửa cấu trúc bảng SQL).
   - Thêm hàm `sort_stack_members(items)` đặt cạnh `sort_by_filename(items)`: luôn đưa item có `is_stack_cover == True` lên đầu tiên.
   - Trong `BeePixmapItem.paint()`: khi item là `is_stack_cover` của một Stack đang thu gọn (`collapsed`), vẽ thêm hiệu ứng mép thẻ lấp ló hoặc badge số lượng thẻ nhỏ nếu cần, còn khi ở chế độ `Spread` thì hiển thị huy hiệu dấu tích vàng `#FFDA12` ở góc trên-trái của hình đại diện.
2. **`beeref/commands.py`**:
   - Thêm các lệnh `QUndoCommand` chuẩn để mọi thao tác đều `Ctrl+Z` / `Ctrl+Y` được:
     - `CreateStackCommand(scene, items, stack_id, center)`
     - `UnstackCommand(scene, stack_id)`
     - `SetStackCoverCommand(scene, stack_id, new_cover_item)` (đổi hình đại diện & đẩy `zValue` lên đỉnh Stack)
     - `PullOutFromStackCommand(scene, stack_id, item, new_pos)`
     - `EditItemNoteCommand(item, old_note, new_note)`
3. **`beeref/scene.py`**:
   - Quản lý trạng thái `active_spread_stack_id: str | None`.
   - Khi `active_spread_stack_id is None` (Stack đang đóng):
     - Click/kéo vào bất kỳ thẻ nào của Stack sẽ chọn và di chuyển đồng bộ cả `stack_id` như một group thống nhất.
     - Click đơn nhả tại chỗ (di chuyển $< 3\text{ screen px}$) hoặc double-click vào Stack → Gọi `spread_stack(stack_id)`: bật lớp phủ `CanvasWashItem(opacity=0.80)` và chạy animation bung các thành viên ra lưới 4×3.
   - Khi `active_spread_stack_id is not None` (Stack đang bung lưới):
     - Kéo 1 thẻ ra khỏi `keep_zone` → tách thẻ khỏi Stack (`Pull Out`) và reflow các thẻ còn lại trong lưới bằng `Spring 300/30`.
     - Click đơn vào 1 thẻ trong lưới → Mở `DetailStageOverlay` cho thẻ đó.
     - Click vào vùng trống (trên lớp `CanvasWashItem`) hoặc bấm `Esc` → Gọi `collapse_spread_stack()`, thu các thẻ về lại tâm `(cx, cy)` với `cover_item` nằm trên cùng (`zValue` cao nhất, góc xoay `0°`).
4. **Widget mới `beeref/widgets/detail_stage.py` & `beeref/widgets/contextual_toolbar.py`**:
   - **`ContextualToolbar`** (floating ở đáy giữa màn hình, `bottom: 32px`, cao `58px`, bo góc `23px`, đảo màu `#16181A` / `#F5F6F7`):
     - Hiện khi chọn $\ge 2$ hình rời (`[Xếp chồng, Xếp lưới, Xuất, Xóa]`) hoặc khi chọn 1 Stack (`[Tách chồng, Bung lưới, Xuất, Xóa]`).
   - **`DetailStageOverlay`** (overlay phủ lên `BeeGraphicsView` khi mở xem 1 hình):
     - Bên trái ảnh: **Ô tròn Tick chọn Hình đại diện (`28×28px`, màu vàng `#FFDA12` khi active)** + **5 Ô màu chủ đạo (`28×28px`)**.
     - Giữa: Ảnh full-res.
     - Bên phải ảnh: Cột thông tin (`KÍCH THƯỚC`, `TÊN TỆP`, `NGÀY`).
     - Dưới ảnh: Ô `QLineEdit` / `QTextEdit` không viền với placeholder **`Viết ghi chú...`** + Thanh Dark Toolbar 4 nút ở đáy.
5. **Phím tắt & Menu (`beeref/actions/actions.py` & `beeref/widgets/penart_menu.py`)**:
   - Thêm hành động **Xếp chồng (`Stack`)** (`Ctrl+S` hoặc `Ctrl+G` tùy cấu hình tránh đụng Save, hoặc thêm vào menu chuột phải & thanh Dark Toolbar dưới đáy) và **Tách chồng (`Unstack`)** (`Ctrl+Shift+S`).
