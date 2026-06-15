# Observathon — Bộ công cụ cho Học viên

🇻🇳 Tiếng Việt | [🇬🇧 English](README_en.md)

Bạn được giao một agent thương mại điện tử **hộp đen, im lặng, đầy lỗi** (dạng binary) chạy
trên một **LLM thật**. Nó không cho bạn biết gì cả. Nhiệm vụ của bạn: **gắn quan sát, chẩn
đoán lỗi, và sửa chúng** — bằng cách sửa config, **viết lại system prompt của agent**, và thêm
một lớp wrapper giảm thiểu lỗi.

## Cài đặt (bắt buộc có một LLM thật)
```bash
# 1. chọn một engine:
export OPENAI_API_KEY=sk-...        # đám mây (model mặc định gpt-5.4-nano), HOẶC
#    local miễn phí: chạy Ollama / llama.cpp (tương thích OpenAI), đặt provider:"local" + LOCAL_BASE_URL trong config.json

# 2. kiểm tra khung bài nộp (chỉ stdlib, không cần key)
python harness/selfcheck.py

# 3. chạy binary mô phỏng giai đoạn PRACTICE (trong bin/practice/)
./bin/practice/observathon-sim --config solution/config.json --wrapper solution/wrapper.py \
    --out run_output.json --concurrency 8
#   macOS lần đầu: xattr -dr com.apple.quarantine bin/practice/observathon-sim
#   Windows:      bin\practice\observathon-sim.exe ...
```
Agent **không phát ra gì cả** và `run_output.json` **cố tình tối giản** — mỗi dòng chỉ có
`answer` + `status` (không có latency, tokens, lời gọi tool, hay trace). Cách DUY NHẤT để thấy
latency, chi phí, số lần gọi tool, vòng lặp, drift và PII là **gắn quan sát trong
`solution/wrapper.py`**: `call_next()` trả về kết quả ĐẦY ĐỦ (gồm `meta` + `trace`) cho BẠN —
hãy ghi lại bằng bộ `telemetry/` đã học ở Ngày 13. (Sim cũng ghi một khối `sealed` đã ký dành
cho việc chấm điểm — đó không phải phần quan sát của bạn.)

## Bạn tối ưu cái gì (đòn bẩy v6)
Agent **điều khiển bằng prompt** và được giao kèm một system prompt **cố tình tệ** (nó bịa ra
tổng tiền, tính sai, gọi tool dư thừa, lặp lại email/sđt của khách, và **làm theo chỉ dẫn ẩn
trong ghi chú đơn hàng**). **Hãy viết lại `solution/prompt.txt`** — đây là cách sửa có đòn bẩy
cao nhất và là một thành phần điểm **`prompt` chiếm 15%**. Xem
**[`docs/PROMPT_OPTIMIZATION.md`](docs/PROMPT_OPTIMIZATION.md)**.

| Bạn chỉnh | Tác dụng |
|---|---|
| `solution/config.json` | các knob (provider/model, temperature, retry, cache, normalize, redact, `self_consistency`, `tool_budget`, `planner`, …) |
| `solution/prompt.txt` | **system prompt** của agent — viết lại nó |
| `solution/examples.json` | few-shot (tùy chọn) |
| `solution/wrapper.py` | `mitigate()` — quan sát + retry/cache/route/redact/sanitize + định tuyến prompt theo từng request |
| `solution/findings.json` | chẩn đoán (loại lỗi + bằng chứng + nguyên nhân gốc) |

## Chọn binary cho HĐH của bạn (`bin/<phase>/`)
| HĐH / kiến trúc | tệp |
|---|---|
| macOS (Apple Silicon, M1+) | `observathon-sim` / `observathon-score` (arm64) |
| Windows | `observathon-sim.exe` / `observathon-score.exe` |
| Linux | `observathon-sim` / `observathon-score` (x86_64) |

(macOS Intel không có sẵn binary — trên Intel hãy chạy từ mã nguồn với Python + `openai`.)
macOS lần đầu (Gatekeeper): `xattr -dr com.apple.quarantine bin/<phase>/*`. Lịch phát hành:
`practice` ngay từ đầu · public **sim** ở 1h, **score** ở 2h · private **sim** ở 3h, **score** ở 3.5h.

## Tạo lưu lượng thực tế (tự chọn mức tải)
```bash
# 200 người dùng x 12 lượt = 2400 request trải trên một khoảng thời gian mô phỏng
./bin/practice/observathon-sim --users 200 --turns 12 --concurrency 12 \
    --config solution/config.json --wrapper solution/wrapper.py --out run_output.json
```
- `--users N` số người dùng · `--turns K` request mỗi người (K lớn → quality-drift rõ hơn) · `--rps` tốc độ đến · `--concurrency` số request song song.
- **Lưu lượng practice NGẪU NHIÊN mỗi lần** (in ra `random run seed = …`; truyền `--seed <giá trị>` để tái hiện). Việc chấm điểm luôn dùng bộ public/private **cố định**, nên mọi đội được xếp hạng trên cùng lưu lượng.

## Cách chấm điểm
`100 × (0.32·correct + 0.16·quality + 0.13·error + 0.08·latency + 0.09·cost + 0.07·drift +
0.15·prompt) + tối đa 22 × diagnosis-F1`. Quality = LLM judge (`gpt-5.4-mini`, có offline dự
phòng). `prompt` dựa trên **kết quả thực tế** (grounding/số học/tiết kiệm tool/PII/chống
injection trừ đi phần prompt quá dài).

## Bạn nộp gì (git push `solution/` + `run_output.json` + `score.json`)
`config.json` · `prompt.txt` · `examples.json` (tùy chọn) · `wrapper.py` · `findings.json`.

## Các giai đoạn
- **Bây giờ → 1h**: chẩn đoán bằng binary practice; viết lại prompt + config.
- **1h** public **sim** · **2h** public **score** → commit, push, leo bảng.
- **3h** private **sim** (bộ giữ kín + diễn đạt lại + đòn **injection**) · **3.5h** private **score** → push (lần cuối).

Xem `docs/FAULT_CLASSES.md`, `docs/PROMPT_OPTIMIZATION.md`, `docs/WRAPPER_API.md`, `docs/SUBMIT.md`. Luật: `../RULES.md`.

---

# 🏆 Hành trình đạt 100/100 (Team day13)

Phần này ghi lại quá trình chẩn đoán và sửa lỗi cho agent hộp đen, từ điểm đầu đến
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

## Bài học
1. **Sửa file `solution/` thì PHẢI chạy lại `sim` rồi mới `score`** (score chỉ đọc
   `run_output.json`, không chạy lại agent).
2. **Đừng để LLM làm số học** — đọc dữ liệu tool và tự tính trong code (đòn bẩy lớn nhất:
   `correct` 0.488 → 0.942).
3. **Quan sát trước, sửa sau** — log `trace` để biết tool trả về gì, rồi mới viết guardrail.
4. **Hiểu thang điểm** — bỏ finding sai đáng +1đ; guardrail nâng cả `correct`/`quality`/`prompt`.
5. **Concurrency vừa phải** để tránh rate limit 429 (TPM).
