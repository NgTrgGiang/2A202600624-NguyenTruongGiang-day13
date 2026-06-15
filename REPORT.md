# 🏆 Báo cáo — Hành trình đạt 100/100 (Team day13)

Báo cáo này ghi lại quá trình chẩn đoán và sửa lỗi cho agent hộp đen, từ điểm đầu đến
**100.0 / 100** ở phase public.

## Kết quả cuối

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
| Bản đầu (sửa config + prompt + wrapper cơ bản) | 0.488 | 0.000 | 0.952 | **81.85** |
| + Guardrail tự tính tổng, bỏ prompt_injection, self_consistency=1 | 0.942 | 0.411 | 1.000 | **100.0** |

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

## Phase private — kết quả
- 80/80 request `ok`, không 429.
- **Phòng thủ injection hoạt động hoàn hảo**: guardrail kích hoạt 33/80, đè lại các tổng bị
  note tiêm giá giả lừa (vd model trả 660.827.500 → guardrail tính đúng 66.027.500 từ giá thật
  `check_stock`). Giá không bao giờ bị tiêm.
- Vá điểm yếu duy nhất (prv-042: model quên gọi `calc_shipping`) bằng cách ép prompt luôn gọi
  `calc_shipping` khi có địa điểm.

## Bài học
1. **Sửa file `solution/` thì PHẢI chạy lại `sim` rồi mới `score`** (score chỉ đọc
   `run_output.json`, không chạy lại agent).
2. **Đừng để LLM làm số học** — đọc dữ liệu tool và tự tính trong code (đòn bẩy lớn nhất:
   `correct` 0.488 → 0.942).
3. **Quan sát trước, sửa sau** — log `trace` để biết tool trả về gì, rồi mới viết guardrail.
4. **Hiểu thang điểm** — bỏ finding sai đáng +1đ; guardrail nâng cả `correct`/`quality`/`prompt`.
5. **Concurrency vừa phải** để tránh rate limit 429 (TPM).
