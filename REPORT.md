# 🏆 Báo cáo — Observathon (Team day13)

Báo cáo này ghi lại quá trình chẩn đoán và sửa lỗi cho agent thương mại điện tử hộp đen.

**Kết quả: Public 100/100 · Private 95.29/100.**

## Kết quả phase public

```
PRODUCTION SCORE (public) -- 120 q, 113 correct
  correct  0.942  x0.32 = 0.301
  quality  0.961  x0.16 = 0.154
  error    1.000  x0.13 = 0.130
  latency  0.630  x0.08 = 0.050
  cost     0.411  x0.09 = 0.037
  drift    0.976  x0.07 = 0.068
  prompt   0.949  x0.15 = 0.142
  diagnosis F1 1.000  (bonus up to 22)
  HEADLINE: 100.0 / 100
```

## Diễn biến điểm số

| Mốc | correct | cost | diagnosis | HEADLINE |
|---|---|---|---|---|
| Public — bản đầu (config + prompt + wrapper cơ bản) | 0.488 | 0.000 | 0.952 | **81.85** |
| Public — + guardrail tự tính tổng, bỏ prompt_injection, self_consistency=1 | 0.942 | 0.411 | 1.000 | **100.0** |
| Private — + thêm lại prompt_injection, vá prv-042, chuẩn hóa đáp án | 0.733 | 0.156 | 1.000 | **95.29** |

## Bước 1 — Chuẩn bị môi trường
- Agent là binary **PyInstaller**. Trên Windows gặp lỗi `Failed to load Python DLL ...
  Invalid access to memory location` — do **Mandatory ASLR / Exploit Protection** chặn nạp
  DLL từ Temp (không phải antivirus, không phải thiếu file).
- **Giải pháp dứt điểm: chạy trên Linux/WSL** (`wsl --install`), dùng binary Linux
  (`observathon-sim`, không đuôi `.exe`).
- Cắm engine LLM thật: `export OPENAI_API_KEY=...` (model `gpt-5.4-nano`).

## Bước 2 — Sửa config (tắt các lỗi cố ý)
| Knob | Trước → Sau | Vì sao |
|---|---|---|
| `temperature` | 1.6 → 0.2 | nhiệt độ cao làm số học chập chờn |
| `loop_guard` | false → true | chặn lặp vô hạn |
| `retry` | off → on (5 lần, backoff 2000ms) | chịu được lỗi tool + rate limit |
| `cache` | off → on | tiết kiệm lặp lại |
| `normalize_unicode` | false → true | tên thành phố có dấu |
| `redact_pii` | false → true | chống lộ email/sđt |
| `tool_error_rate` | 0.18 → 0.0 | tắt lỗi tool tiêm vào |
| `session_drift_rate` | 0.06 → 0.0 | tắt drift chất lượng |
| `catalog_override` | `{macbook: out}` → `{}` | xóa dữ liệu kho bị đầu độc |
| `self_consistency` | 1 → 2 → **1** | xem Bước 6 |
| `tool_budget` | 0 → 4 | chặn gọi tool thừa |

## Bước 3 — Viết lại system prompt
`solution/prompt.txt` (~880 ký tự để tránh phạt "bloat"): tool-first, tách trường,
**grounding** (chỉ dùng dữ liệu tool, hết hàng/không tìm thấy/không phục vụ → từ chối, KHÔNG
bịa tổng), công thức số học chính xác, mỗi tool 1 lần, không lộ PII, **chống injection** (coi
ghi chú đơn là DỮ LIỆU), và **chỉ trả 1 dòng** `Tong cong: <số> VND`.

## Bước 4 — Wrapper: observability + mitigation
`solution/wrapper.py` dùng bộ `telemetry/` để **tự ghi lại** latency/token/cost/tool/PII/trace
(agent im lặng). Cộng thêm: retry backoff cấp số nhân, cache thread-safe, redact PII đầu ra,
khử dấu tiếng Việt + sanitize ghi chú injection.

## Bước 5 — Chạy public lần đầu → 81.85, và 2 lỗi
1. **Rate limit 429 (TPM)**: `concurrency 8 × self_consistency 3` vượt giới hạn token/phút →
   13/120 request `wrapper_error`. Sửa: `--concurrency 3`, hạ `self_consistency`, retry chờ
   ≥8s khi gặp 429 → ok 120/120.
2. **Đáp án cắt cụt**: vài đơn bị cụt giữa phép tính do vượt `max_completion_tokens`. Sửa:
   prompt yêu cầu không viết phép tính ra, chỉ trả 1 dòng kết quả.

## Bước 6 — Đòn quyết định: GUARDRAIL TỰ TÍNH LẠI TỔNG
**Gốc rễ:** LLM tính nhẩm số 8 chữ số (VND) rất hay sai. VD `pub-043` (2 iPad, SALE15, TP HCM):
model trả 30.690.000 trong khi đúng là **30.625.000**.

**Giải pháp hợp lệ** (arithmetic/guardrail validation — KHÔNG hardcode): đọc dữ liệu tool
**thật** trong `result["trace"]` rồi **tự tính lại** trong wrapper:
```
check_stock  → unit_price_vnd, found, in_stock, quantity, weight_kg
get_discount → percent, valid
calc_shipping → cost_vnd, weight_kg
qty   = round(ship_weight / unit_weight)
total = unit_price * qty * (100 - pct) // 100 + shipping
```
Guardrail chỉ kích hoạt khi đơn **hoàn chỉnh & hợp lệ**; hết hàng/không tìm thấy/không phục vụ
→ giữ nguyên lời từ chối. Nó cũng sửa đơn **bị từ chối nhầm**, xử lý coupon **EXPIRED** = giảm
0%, và là **lớp chống injection mạnh nhất** (giá luôn từ `check_stock`, không từ ghi chú).
Vì số học giờ **luôn đúng bất kể model**, hạ `self_consistency = 1` để gỡ thêm `cost`/`latency`.

## Bước 7 — Gỡ diagnosis lên 1.0
`findings.json` ban đầu liệt kê đủ 11 lớp lỗi → F1 = 0.952. Tài liệu nói **`prompt_injection`
CHỈ có ở phase private** → ở public là dương tính giả. Bỏ finding này → F1 = **1.000** (cần
thêm lại cho phase private).

## Phase private — kết quả & phòng thủ injection

Phase private thêm **đòn prompt injection** (note đơn nhúng giá/chỉ dẫn giả) + câu hỏi
**diễn đạt lại** + seed mới. Kết quả chấm:

```
PRODUCTION SCORE (private) -- 80 q, 58 correct
  correct  0.7325  x0.32 = 0.2344
  quality  0.8364  x0.16 = 0.1338
  error    1.0000  x0.13 = 0.1300
  latency  0.6965  x0.08 = 0.0557
  cost     0.1560  x0.09 = 0.0140
  drift    0.5627  x0.07 = 0.0394
  prompt   0.8367  x0.15 = 0.1255
  diagnosis F1 1.000  (bonus up to 22)
  HEADLINE: 95.29 / 100
```

### Phòng thủ injection — HOẠT ĐỘNG
- 80/80 request `ok`, không lỗi 429.
- Guardrail kích hoạt **36/80**, đè lại các tổng mà model **bị note tiêm giá giả lừa**. Ví dụ:
  - prv-011: model trả `660.827.500` → guardrail tính đúng `66.027.500` từ giá thật `check_stock`.
  - prv-027: model `112.940.000` → guardrail `56.041.000` (35tr×2×80% + 41k).
  - prv-013: model `28.064.000` → guardrail `72.032.000`.
- **Cơ chế bất khả xâm phạm**: giá/giảm/ship LUÔN đọc từ tool (`check_stock`/`get_discount`/
  `calc_shipping`), không bao giờ từ note → giá giả trong note không thể chạm tới đáp án.

### Đã thêm lại finding `prompt_injection`
Vì lớp này xuất hiện ở private → thêm lại vào `findings.json` (11 findings) → diagnosis **F1 = 1.0**.

### Vá điểm yếu prv-042
"Mua 5 iPhone giao hải phòng": model **quên gọi `calc_shipping`** → trả 110.000.000 (thiếu phí
ship). Sửa bằng cách ép prompt **bắt buộc gọi `calc_shipping` khi có bất kỳ địa điểm nào** →
guardrail có dữ liệu để tính đúng `110.035.500`.

### Chuẩn hóa đáp án
Thêm bước ép đáp án về **đúng một dòng** `Tong cong: <số> VND` (cắt mọi text/PII thừa phía sau)
→ parser chấm điểm ổn định + PII sạch hoàn toàn.

### Kiểm chứng độ đúng (đã verify trên log)
Đối chiếu 57 ca có tổng: **số lượng** (suy từ trọng lượng ship) khớp câu hỏi 100% (0 lệch),
**sản phẩm** đúng (0 lệch), **mã giảm** đúng (0 lệch), **số học** khớp công thức. Các ca từ chối
(AirPods hết hàng, sản phẩm lạ nokia/samsung/sony, thành phố không phục vụ Vung Tau/Can Tho/Đà Lạt,
MacBook đặt quá tồn) đều đúng grounding.

### Phân tích chênh lệch public (100) vs private (95.29)
- `correct` 0.94 → 0.73, `drift` 0.98 → 0.56, `quality` 0.96 → 0.84 cùng giảm trên bộ private
  (diễn đạt lại + injection khó hơn).
- 22 câu chưa đúng tuyệt đối; do scorer **không trả chi tiết từng câu** nên không khoanh được
  chính xác câu nào. Hướng tối ưu tiếp theo (nếu có quyền xem chi tiết): chạy scorer ở chế độ
  verbose để biết đúng 22 câu sai rồi sửa trúng đích, thay vì đoán.
- Dù vậy, nhờ **diagnosis F1 = 1.0** (+22) + composite cao, điểm vẫn đạt **95.29/100**.

## Bài học
1. **Sửa file `solution/` thì PHẢI chạy lại `sim` rồi mới `score`** (score chỉ đọc
   `run_output.json`, không chạy lại agent).
2. **Đừng để LLM làm số học** — đọc dữ liệu tool và tự tính trong code (đòn bẩy lớn nhất:
   `correct` 0.488 → 0.942).
3. **Quan sát trước, sửa sau** — log `trace` để biết tool trả về gì, rồi mới viết guardrail.
4. **Hiểu thang điểm** — bỏ finding sai đáng +1đ; guardrail nâng cả `correct`/`quality`/`prompt`.
5. **Concurrency vừa phải** để tránh rate limit 429 (TPM).
