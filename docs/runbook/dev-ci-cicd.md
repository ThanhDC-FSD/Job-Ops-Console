# CICD & Dev Interop Runbook

## Vấn đề hiện tại
- Các script chạy frontend/backendan trong môi trường địa phương (`run_job_ops_frontend.bat` / `run_job_ops_backend.bat`) sử dụng cổng 5182 và 8102, nhưng CORS chỉ mở với 5180 nên khi mở cả hai server cùng lúc sẽ xảy ra lỗi `NetworkError: Backend offline`.
- CI/CD và các bước kiểm tra cần một bản sao chia riêng dữ liệu crawl và schema xử lý cho backend/CD để tránh khóa file (`database is locked`) mỗi khi cả pipeline thu thập dữ liệu lẫn API ghi log/automation cùng truy cập.
- Tài liệu chưa ghi lại rõ ràng các bước khởi động và bất kỳ thay đổi cấu hình nào nên khó tái tạo lại môi trường “dev + CD”.

## Workaround + start cả hai server FE + BE
1. **Chuẩn bị môi trường**: đảm bảo `.venv` đã cài, `npm install` trong `apps/frontend`. Cập nhật biến môi trường trong `.env` nếu cần (mặc định mới: `BACKEND_PORT=8102`, `FRONTEND_ORIGIN=http://127.0.0.1:5182`).
2. **Chạy cả hai cùng lúc**: 
   - Dùng script tổng `scripts\bat\run_job_ops_all.bat start all` để dừng phiên trước, khởi động backend rồi frontend, không cần mở nhiều cửa sổ thủ công.
   - Hoặc lần lượt gọi `scripts\bat\run_job_ops_backend.bat` và `scripts\bat\run_job_ops_frontend.bat`.
3. **Xác thực**:
   - Backend: `curl http://127.0.0.1:8102/health` (phải trả về `{"status":"ok",...}`).
   - Frontend: mở `http://127.0.0.1:5182` và kiểm tra xem các request `/api/*` không báo lỗi CORS.
4. **CORS đã được mở rộng**: FastAPI giờ cho phép `FRONTEND_ORIGIN` từ `.env` và thêm các origin `http://127.0.0.1:5180`, `http://127.0.0.1:5182`, `http://localhost:5180`, `http://localhost:5182` thay vì chỉ 5180.

## Thông tin các server sau khi fix
- **Backend API**: `127.0.0.1:8102`, entry point `scripts\bat\run_job_ops_backend.bat`, `uvicorn app.main:app`.
- **Frontend UI**: `127.0.0.1:5182`, `npm run dev -- --host 127.0.0.1 --port 5182` (được gọi bởi `run_job_ops_frontend.bat` hoặc `run_job_ops_all.bat`).
- **Môi trường/biến quan trọng**:
  - `BACKEND_PORT`: 8102 (có thể ghi đè trong `.env` để phù hợp CD).
  - `FRONTEND_ORIGIN`: `http://127.0.0.1:5182` (FastAPI sẽ cho phép origin này cùng danh sách localhost/127.0.0.1:5180/5182).
  - `JOB_DB_PATH`: đường dẫn đến SQLite backend (mặc định `input/crawled_job/linkedin_jobs_jd.sqlite`, có thể trỏ tới bản sao riêng cho CI).

## Tách riêng hai database theo schema
1. **Tạo bản sao schema riêng**: dùng script mới `scripts/python/clone_job_db.py` để copy dữ liệu crawl sang file khác, ví dụ:
   ```bat
   .venv\Scripts\python.exe scripts\python\clone_job_db.py --target apps\backend\app\job_ops_schema.sqlite --force
   ```
   Tùy chọn `--vacuum` để rebuild nếu cần.
2. **Chỉ backend/CD viết vào bản sao**: trong CI hoặc quy trình automation, thiết lập `JOB_DB_PATH` cục bộ (trong `.env` hoặc biến môi trường hệ thống) trỏ tới `apps/backend/app/job_ops_schema.sqlite`. Dữ liệu crawl gốc (`input/crawled_job/linkedin_jobs_jd.sqlite`) có thể giữ nguyên chỉ để đọc hoặc để restart pipeline riêng biệt.
3. **Tính toán schema riêng trong CI**: trước khi chạy test/automation, gọi script clone với `--force` để đảm bảo bản sao sạch sẽ, rồi chạy backend + frontend như phía trên.
4. **Cập nhật `.env` hoặc pipeline script** để `JOB_DB_PATH` trỏ tới bản sao riêng, tránh lock file khi crawler/automation song song.

## Kiểm tra CI/CD
- Để kiểm tra pipeline loạt, khởi động backend/front-end như trên rồi chạy:
  1. `pip install -r requirements.txt` từ root (đảm bảo `.venv` cập nhật).
  2. `npm run build` trong `apps/frontend` để xác thực trình biên dịch Vite.
  3. Nếu cần mô phỏng CI, clone DB mới, bật `RUN_STARTUP_BOOTSTRAP_ACTIONS=1` rồi gọi `scripts\bat\run_job_ops_backend.bat`.
- Ghi lại lỗi (logs ở `apps/backend/app/logs`) nếu có, mô tả cổng/phiên bản backend + frontend trong Jira hoặc ghi chú CICD.

## Ghi chú
- Các script `run_job_ops_*` giữ nguyên logic start/stop nhưng giờ backend + frontend chia rõ cổng/biến để tránh xung đột CORS.
- Giữ thói quen dùng `run_job_ops_all` để tránh việc chạy nhiều cửa sổ `npm`/`uvicorn` gây “port already in use”.
- Nếu CD cần môi trường khác (ví dụ `0.0.0.0`), chỉ cần override `BACKEND_HOST`/`BACKEND_PORT` trong pipeline và đảm bảo tương ứng `VITE_API_BASE` được cung cấp khi build.

## Logging & diagnostics
- Backend ghi log chi tiết cho các hành động API (list jobs, chi tiết/jobs, priority/manual review updates, delete) trong `apps/backend/app/logs/backend.log` và `backend.error.log`. Khi cần theo dõi bước automation/CI, xem thêm `apps/backend/app/logs/etl_runs/automation_run_*.log` và bật `DIAGNOSTICS=1` trong `.env` để ghi thêm payload cho POST/PATCH.
- Frontend giờ log từng request/response có tiền tố `[api]` trong developer console (Chrome/Edge: F12 → Console; nhớ bật `Verbose` nếu cần). Khi lỗi xảy ra, chuỗi console sẽ hiển thị `network failure`, `response error`, cùng status/body. Tìm dòng như `[api] request start GET http://127.0.0.1:8102/api/jobs?...` để song hành với backend.
- Khi chạy CI, đảm bảo capture cả `apps/backend/app/logs/backend.log` + `logs/etl_runs/*.log` trong pipeline artifacts và ghi rõ cổng/biến môi trường (từ phần “Thông tin các server…” phía trên) để dễ đối chiếu. Dùng script `scripts/python/clone_job_db.py` trước mỗi run trong CI để khởi tạo lại schema copy và tránh khóa file.
