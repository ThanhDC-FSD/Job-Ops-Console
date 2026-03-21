# Học Tập và Ôn Luyện Chuyên Sâu

## 1. Python / Concurrency
- **Sách/ tài liệu:** _Fluent Python_ (generator, iterator, context manager); _Python Concurrency with asyncio_ (pattern async/await).  
- **Thực hành:** bài tập thread/async trên Exercism.io hoặc LeetCode (chọn tagged `asyncio`, `concurrency`, `multithreading`).  
- **Tự đánh giá:** viết script nhỏ để so sánh kết quả sync/async và ghi lại các lỗi thường gặp.

## Python / Concurrency – Top Questions
### Question 1: When should I prefer asyncio over threads, and how do I profile the difference?
**Answer:** Choose asyncio for I/O-bound workloads that can yield (HTTP/DB/network) and profile via `asyncio.get_running_loop().time()` around tasks or `time.perf_counter()` for sync code.

**Explanation:** Threads still incur OS scheduling and GIL contention for CPU work, so for many concurrent I/O calls, a single event loop keeps context-switching cheap. Measure the wall time of paired sync/async implementations and monitor thread counts to confirm the async version stays faster.

**Example:** Wrap `requests.get` in `asyncio.to_thread` to compare with `httpx.AsyncClient.get` so you see how the loop remains responsive while the blocking call waits.

### Question 2: How does the GIL affect async vs multithreaded Python code?
**Answer:** The Global Interpreter Lock blocks true parallel CPU execution in threads, so asyncio avoids it by multiplexing a single thread, and multithreading only helps I/O-bound tasks.

**Explanation:** CPU-heavy code still runs sequentially inside the GIL, meaning threads fight for the lock. Async tasks cooperate by yielding at `await`, so the GIL is released naturally during blocking I/O. For CPU workloads, prefer multiprocessing or offloading to C extensions.

**Example:** A CPU loop inside a thread (e.g., counting to a million) delays other threads, whereas the same code in `run_in_executor` keeps the event loop free.

### Question 3: How do I detect and fix race conditions in async code?
**Answer:** Use `asyncio.Lock` or `asyncio.Semaphore` around shared state, and log `Task.current_task()` plus `await asyncio.sleep(0)` when debugging.

**Explanation:** Concurrency hazards happen when multiple coroutines mutate the same resource without coordination. Protect the critical sections by awaiting a lock before mutation, and release afterward. Instrument the code to see when tasks overlap or to reproduce the issue with repeated runs.

**Example:** Protect a shared dictionary with `async with lock:` before incrementing counters in multiple coroutines.

### Question 4: What’s the right way to cancel long-running async tasks?
**Answer:** Call `task.cancel()` and ensure the coroutine catches `asyncio.CancelledError` to perform cleanup before re-raising.

**Explanation:** Cancellation in asyncio is cooperative: you signal by cancelling the `Task`, but the coroutine must reach an `await` and handle the exception. Use `try/except asyncio.CancelledError` in loops to release resources (files, DB sessions) and optionally re-raise for upstream awareness.

**Example:** Wrap a polling loop with `try:`/`finally:` so `db_session.close()` still runs even when the task gets cancelled.

### Question 5: How do I coordinate multiple async steps and gather their results safely?
**Answer:** Use `await asyncio.gather()` for parallelism and `asyncio.wait()`/`as_completed()` when you need partial results or timeout handling.

**Explanation:** `gather` collects all results and propagates the first exception, so wrap it in `try/except` if you expect failures. Combine it with `return_exceptions=True` when you want to inspect each coroutine’s error without stopping the rest.

**Example:** Run API enrichment tasks concurrently using `await asyncio.gather(*jobs, return_exceptions=True)` and then filter out exceptions before persisting.

### Question 6: How can I safely share data between async tasks and synchronous threads?
**Answer:** Use producer/consumer queues (`asyncio.Queue` for coroutines, `queue.Queue` for threads) plus locks when crossing boundaries, and transfer data via `asyncio.run_coroutine_threadsafe`.

**Explanation:** Shared mutable state must be protected both in async and thread contexts. Pass objects through queues rather than direct mutation, and wrap access with locks to prevent races while keeping the event loop responsive.

**Example:** Threads can call `asyncio.run_coroutine_threadsafe(queue.put(item), loop)` while consumers `await queue.get()` inside coroutines.

### Question 7: What’s the right pattern for offloading CPU-heavy work from an async service?
**Answer:** Run CPU tasks in a `ProcessPoolExecutor` (or `ThreadPoolExecutor` for thread-safe code) via `loop.run_in_executor` or `asyncio.to_thread`.

**Explanation:** Async loops should only handle I/O. CPU-bound work blocks the loop, so delegate it to separate processes which avoid GIL contention and keep the main event loop free for other tasks.

**Example:** `result = await loop.run_in_executor(ProcessPoolExecutor(), heavy_compute, payload)`

### Question 8: How do I protect producers from overwhelming consumers?
**Answer:** Limit concurrency with semaphores or bounded queues and await availability before enqueuing more work.

**Explanation:** Without backpressure, tasks pile up and exhaust memory. Use `asyncio.BoundedSemaphore` or `Queue(maxsize=...)`, and have producers `await queue.put()` which blocks once the queue is full until consumers free space.

**Example:** Wrap task production with `async with semaphore:` so only a fixed number of concurrent tasks run.

### Question 9: How do I regain control during shutdown of long-running async services?
**Answer:** Track created tasks, cancel them on shutdown signals, and await their cleanup to release resources cleanly.

**Explanation:** Background workers should catch `CancelledError`, perform cleanup, and re-raise. Register shutdown handlers that cancel each task and `await asyncio.gather(*tasks, return_exceptions=True)`.

**Example:** 
```
task = asyncio.create_task(worker())
...
for t in tasks: t.cancel()
await asyncio.gather(*tasks, return_exceptions=True)
```

### Question 10: When should I use `await asyncio.sleep(0)` inside loops?
**Answer:** Insert it in tight polling loops to yield control to other coroutines, preventing starvation.

**Explanation:** Busy loops hog the event loop. A zero-second sleep acts as a cooperative yield so other scheduled tasks can run without waiting for heavy computation to finish.

**Example:** `while not ready: await asyncio.sleep(0.01)` before rechecking a condition.

### Question 11: How can I batch multiple async calls without overwhelming the event loop?
**Answer:** Use `asyncio.Semaphore` to cap concurrency and schedule tasks in chunks.

**Explanation:** Creating thousands of tasks at once can flood the loop and consume memory. Semaphore ensures only a fixed number run in parallel while others await their turn.

**Example:** 
```
sem = asyncio.Semaphore(10)
async def limited(job):
    async with sem:
        await job()
```

### Question 12: How do I debug order-of-execution issues in async code?
**Answer:** Log timestamped markers around awaits and use `asyncio.Task.get_name()`/`current_task()` to trace execution flow.

**Explanation:** Mixed awaits can appear out-of-order. Adding logs before/after awaits helps ded ded interleaving; optionally name tasks for readability.

**Example:**
```
task = asyncio.create_task(handle(), name="handler")
```

### Question 13: What patterns help coordinate retries with async requests?
**Answer:** Implement exponential backoff via helper that `await asyncio.sleep()` between attempts and keeps track of retries.

**Explanation:** Avoid hammering services by sleeping longer after each failure and aborting after max retries; wrap logic in a reusable decorator/helper.

**Example:**
```
for attempt in range(max_retries):
    try: return await call()
    except: await asyncio.sleep(backoff * attempt)
```

### Question 14: When juggling multiple event loops (tests/server), how do I avoid conflicts?
**Answer:** Create separate loops per thread/process and never share tasks across loops; use `asyncio.new_event_loop()` and `asyncio.set_event_loop()` explicitly.

**Explanation:** Each thread needs its own loop; reusing a loop in another thread raises `RuntimeError`. Keep loop management localized (tests vs app) and close loops when done.

**Example:** In pytest, `loop = asyncio.new_event_loop(); asyncio.set_event_loop(loop)` before running async fixtures.

### Question 15: How do I monitor event loop health in production?
**Answer:** Track loop delays using `loop.time()` diff or `loop.slow_callback_duration` and log when callbacks exceed thresholds.

**Explanation:** Delays indicate blocking operations. Starvation detection helps catch regressions; use metrics exporters to send to monitoring dashboards.

**Example:** 
```
loop = asyncio.get_running_loop()
delay = loop.time() - monotonic_reference
if delay > 0.1: log.warning("event loop blocked")
```

### Question 16: How do I detect blocking third-party libraries inside the event loop?
**Answer:** Use `loop.slow_callback_duration` and monitor `asyncio.get_running_loop().time()` spans around suspected calls; replace sync calls with async equivalents or run them in executors.

**Explanation:** Blocking callbacks delay the loop even if they aren’t your code. Setting `loop.slow_callback_duration` logs warnings and helps pinpoint offending libraries, so you can wrap them in `run_in_executor`.

**Example:** 
```
loop = asyncio.get_event_loop()
loop.set_debug(True)
loop.slow_callback_duration = 0.05
```

### Question 17: How do I chain dependent async operations safely?
**Answer:** Await each step sequentially or use `asyncio.create_task` for independent parts; handle exceptions per stage.

**Explanation:** When future B depends on A, await A before starting B. For independent branches, launch tasks and `await gather`. Wrap each stage in try/except to provide context-specific recovery.

**Example:** 
```
data = await fetch_config()
result = await process_data(data)
```

### Question 18: What’s the best way to propagate exceptions from `asyncio.gather()`?
**Answer:** Keep `return_exceptions=False` (default) and wrap in try/except to catch the first exception; use `return_exceptions=True` when you need all outcomes.

**Explanation:** With default behavior, a single failure cancels the rest and re-raises. If you expect partial results, inspect the returned list and log/exclude exceptions manually.

**Example:** 
```
try:
    await asyncio.gather(*jobs)
except Exception as exc:
    log.warning("child failed", exc_info=exc)
```

### Question 19: How do I automatically restart failed async workers?
**Answer:** Supervise tasks in a loop: await `task`, catch exceptions, log, and recreate a new task while applying backoff.

**Explanation:** Wrap worker logic in a supervisor coroutine that continuously spins tasks, catching `CancelledError` separately to exit politely.

**Example:** 
```
while True:
    task = asyncio.create_task(worker())
    try:
        await task
    except Exception:
        await asyncio.sleep(backoff)
```

### Question 20: How do I integrate synchronous libraries safely in async tests?
**Answer:** Use `pytest.mark.asyncio` with `loop.run_in_executor` or wrap the sync call in `asyncio.to_thread`.

**Explanation:** Tests mimic production concurrency; wrap blocking libs so the event loop isn’t blocked during test runs.

**Example:** `await asyncio.to_thread(sync_client.fetch, url)`

### Question 21: How do I avoid deadlocks when mixing `threading.Lock` and `asyncio.Lock`?
**Answer:** Keep thread locks in synchronous code and async locks in coroutine code, and never `await` while holding a thread lock.

**Explanation:** Deadlocks often happen when a thread waits on the loop while the loop is blocked by that same thread-owned lock. Isolate cross-boundary communication through queues whenever possible.

**Example:** Hold `threading.Lock` only inside `asyncio.to_thread(...)` work, then pass the result back to the event loop.

### Question 22: When should I use `asyncio.as_completed()` instead of `gather()`?
**Answer:** Use `as_completed()` when you want to process results as each task finishes rather than waiting for the whole batch.

**Explanation:** This is useful for progress reporting, streaming partial success, and long-tail workloads where one slow task should not block everything else.

**Example:** Persist completed API responses one by one while the slowest request is still running.

### Question 23: How do I cap concurrency against rate-limited APIs?
**Answer:** Combine a semaphore with sleep/backoff logic so you control both parallelism and request pacing.

**Explanation:** Many APIs break under bursts, not just under high totals. Concurrency caps plus paced retries keep clients stable and predictable.

**Example:** Use `async with semaphore:` around each request and insert short sleeps between retry waves.

### Question 24: What is a clean async worker-pool pattern?
**Answer:** Feed an `asyncio.Queue`, start a fixed number of workers, and stop them with sentinel values or cancellation.

**Explanation:** Worker pools are easier to monitor than spawning unbounded tasks and make shutdown behavior much cleaner.

**Example:** Push one `None` sentinel into the queue for each worker you want to stop.

### Question 25: How do I deduplicate concurrent work for the same resource?
**Answer:** Track in-flight tasks by key and reuse the same task until it completes.

**Explanation:** This prevents duplicate network requests and keeps multiple callers from doing the same expensive work at once.

**Example:** Store `inflight[user_id] = asyncio.create_task(load_user(user_id))`.

### Question 26: How do I add safe timeouts to async operations?
**Answer:** Wrap awaited calls with `asyncio.wait_for()` and handle timeout exceptions explicitly.

**Explanation:** Timeouts stop hung tasks from occupying concurrency slots forever. Decide per operation whether timeout should trigger retry, cancellation, or fallback behavior.

**Example:** `await asyncio.wait_for(fetch_profile(), timeout=5)`

### Question 27: When is `asyncio.shield()` useful?
**Answer:** Use it for critical final steps that should finish even if the parent task gets cancelled.

**Explanation:** Shielding is appropriate for cleanup, commit, or durable write stages, but should be used sparingly because it changes shutdown behavior.

**Example:** Shield a final state-save step before returning from a worker.

### Question 28: How do I keep logs readable in concurrent async systems?
**Answer:** Add correlation IDs such as `request_id`, `job_id`, or task names to every log message.

**Explanation:** Async logs interleave heavily under load. Context-rich structured logs let you trace one workflow without guessing which line belongs to which task.

**Example:** Include `job_id` in logger context before spawning child tasks.

### Question 29: How do I choose between thread executors and process executors?
**Answer:** Use thread executors for blocking I/O wrappers and process executors for CPU-heavy work.

**Explanation:** Threads are cheaper and share memory, but CPU-heavy thread work still contends on the GIL. Processes cost more but enable real CPU parallelism.

**Example:** File uploads may fit a thread pool, while heavy scoring logic fits a process pool.

### Question 30: How should I test retry logic in async code?
**Answer:** Mock failure sequences, use tiny backoff values, and assert both retry count and final outcome.

**Explanation:** Good retry tests prove not just that retries happen, but that they stop under the right conditions.

**Example:** Simulate two failures and one success, then assert the call happened three times.

### Question 31: How do I handle partial failure in fan-out workflows?
**Answer:** Collect successes and failures separately, then retry or skip only the failed subset.

**Explanation:** Treating every single child failure as fatal can reduce throughput unnecessarily in large concurrent jobs.

**Example:** Persist successful API responses first and queue failed IDs for a later retry pass.

### Question 32: How do I prevent memory growth in long-running async services?
**Answer:** Bound queues, remove completed tasks from registries, and avoid storing large result lists longer than necessary.

**Explanation:** Long-running services leak memory when task references, cached payloads, or retry registries are never cleaned up.

**Example:** Register a done callback that removes finished tasks from an `inflight` map.

### Question 33: What should I do if an async SDK still blocks internally?
**Answer:** Benchmark it under load, monitor loop lag, and wrap or replace it if it blocks the event loop.

**Explanation:** Some libraries expose async-looking APIs while still doing sync file or network work inside. Loop-lag metrics reveal this quickly.

**Example:** Move the SDK call into `asyncio.to_thread(...)` while evaluating alternatives.

### Question 34: What metrics make async services easier to operate?
**Answer:** Track queue depth, active task count, retry count, loop lag, error rate, and tail latency.

**Explanation:** These metrics tell you both system pressure and user-visible responsiveness, which is more useful than request count alone.

**Example:** Alert if loop lag stays above 100 ms for several minutes.

### Question 35: How do I protect downstream systems from retry storms?
**Answer:** Add exponential backoff with jitter, cap retries, and pause traffic after repeated failures.

**Explanation:** Without jitter, many workers retry in sync and can worsen outages. Spreading retry timing reduces cascade risk.

**Example:** Sleep for `base * 2**attempt + random_jitter`.

### Question 36: When is batching better than raw concurrency?
**Answer:** Batch when the remote system supports bulk operations or when per-request setup cost is high.

**Explanation:** Hundreds of small concurrent requests can still be slower and more fragile than a few efficient batch calls.

**Example:** Send 100 IDs in one bulk request instead of 100 separate fetches.

### Question 37: How do I design cancellation boundaries in pipelines?
**Answer:** Mark which stages are safe to cancel, which must complete, and which can be retried later.

**Explanation:** Clear cancellation boundaries prevent half-written state during shutdown and make recovery logic simpler.

**Example:** Let fetch stages cancel freely but protect final commit stages.

### Question 38: How do I make async writes idempotent?
**Answer:** Use stable unique keys, upserts, and retry-safe transaction patterns.

**Explanation:** Retries and restarts are normal in concurrent systems. Idempotent writes make those failures survivable instead of destructive.

**Example:** Upsert rows by external job ID instead of blindly inserting duplicates.

### Question 39: Which metrics matter most for event-loop health?
**Answer:** Loop lag, task backlog, queue wait time, error rate, and p95/p99 latency.

**Explanation:** Together these show whether the loop is overloaded, blocked, or simply slow at the edges.

**Example:** Compare queue wait time against processing time to see where pressure actually lives.

### Question 40: How do I separate orchestration from unit-of-work logic?
**Answer:** Put retries, throttling, and coordination in one layer, and keep worker functions focused on one small task.

**Explanation:** This separation reduces complexity and makes both testing and debugging much easier.

**Example:** A scheduler manages queueing while a worker only fetches and parses one record.

### Question 41: When should I use async generators?
**Answer:** Use them when results arrive incrementally and consumers benefit from streaming rather than waiting for a full list.

**Explanation:** Async generators reduce memory usage and naturally support backpressure through iteration.

**Example:** Yield parsed crawl results one row at a time.

### Question 42: How do I manage pooled resources in async code?
**Answer:** Limit access through pool objects or semaphores and always release resources in `finally`.

**Explanation:** Connection, session, and browser-page leaks often appear only under concurrency spikes, so defensive release logic matters.

**Example:** Return a borrowed DB session to the pool even when the query fails.

### Question 43: How do I keep async code maintainable as the project grows?
**Answer:** Standardize timeouts, retries, logging, and shutdown rules through shared helpers and conventions.

**Explanation:** Concurrency bugs multiply when every module invents its own lifecycle behavior. Shared patterns reduce drift and confusion.

**Example:** Reuse one retry helper across crawler and API modules.

### Question 44: How do I debug race bugs that only appear under load?
**Answer:** Run controlled stress tests, add correlation IDs, and lower concurrency gradually until the failure pattern becomes reproducible.

**Explanation:** Load-only bugs often depend on timing, so structured reproduction is more useful than random guessing.

**Example:** Repeat the same workload at concurrency 50, then 10, then 2 to isolate the trigger.

### Question 45: What short rule of thumb summarizes Python concurrency choices?
**Answer:** Use asyncio for high-concurrency I/O, threads for blocking I/O wrappers, and processes for CPU-bound work.

**Explanation:** That rule is not perfect, but it is accurate enough to guide most designs and interview answers.

**Example:** Crawling fits asyncio, legacy SDK calls fit threads, and heavy computation fits processes.

### Python / Concurrency – Phiên bản tiếng Việt
1. **Câu hỏi:** Khi nào chọn asyncio thay vì thread và cách đo hiệu năng?
   - **Trả lời:** Dùng asyncio cho các tác vụ I/O-bound, đo bằng `asyncio.get_running_loop().time()` hoặc `time.perf_counter()` để so sánh sync/async.
2. **Câu hỏi:** GIL ảnh hưởng thế nào đến asyncio và multithread?
   - **Trả lời:** GIL ngăn threads chạy song song CPU, nên asyncio (trên một thread) vẫn hiệu quả cho I/O; CPU-heavy cần multiprocessing.
3. **Câu hỏi:** Làm sao tìm và sửa race condition trong async?
   - **Trả lời:** Dùng `asyncio.Lock`/`Semaphore` quanh vùng chia sẻ và ghi log để biết khi nào các coroutine trùng nhau.
4. **Câu hỏi:** Cách hủy task dài hạn?
   - **Trả lời:** Gọi `task.cancel()`, bắt `CancelledError`, giải phóng tài nguyên trong `finally`.
5. **Câu hỏi:** Cách kết hợp nhiều bước async?
   - **Trả lời:** Dùng `await asyncio.gather()` hoặc `asyncio.wait()` + `return_exceptions` nếu cần kết quả một phần.
6. **Câu hỏi:** Làm sao chia sẻ an toàn giữa async và thread?
   - **Trả lời:** Trao đổi qua queue và khóa, dùng `asyncio.run_coroutine_threadsafe` để push từ thread.
7. **Câu hỏi:** Cách chuyển công việc CPU ra khỏi event loop?
   - **Trả lời:** Dùng `ProcessPoolExecutor`/`to_thread` để thực thi CPU-bound bên ngoài loop chính.
8. **Câu hỏi:** Làm sao kiểm soát tốc độ producer?
   - **Trả lời:** Dùng semaphore hoặc queue có kích thước cố định để tạo backpressure.
9. **Câu hỏi:** Cách tắt dịch vụ async khi shutdown?
   - **Trả lời:** Cancel tất cả task, đợi `asyncio.gather(..., return_exceptions=True)` và release resource.
10. **Câu hỏi:** Khi nào phải `await asyncio.sleep(0)`?
   - **Trả lời:** Trong vòng lặp polling để nhường luồng lại cho các coroutine khác.
11. **Câu hỏi:** Làm sao chạy nhiều async mà không overload?
   - **Trả lời:** Dùng semaphore để giới hạn số task đang chạy.
12. **Câu hỏi:** Cách debug trình tự await?
   - **Trả lời:** Ghi log trước/sau mỗi `await` và đặt tên cho task.
13. **Câu hỏi:** Cách retry với backoff?
   - **Trả lời:** Sleep tăng dần giữa mỗi lần thử, dừng sau số lần tối đa.
14. **Câu hỏi:** Xử lý nhiều event loop?
   - **Trả lời:** Tạo loop mới mỗi thread và không chia sẻ task, gọi `set_event_loop`.
15. **Câu hỏi:** Giám sát vòng lặp?
   - **Trả lời:** Đo delay (`loop.time()`) hoặc kích hoạt `slow_callback_duration`.
16. **Câu hỏi:** Nhận diện thư viện chặn loop?
   - **Trả lời:** Bật chế độ debug và `slow_callback_duration`, thay chúng bằng async hoặc executor.
17. **Câu hỏi:** Xâu chuỗi các bước phụ thuộc?
   - **Trả lời:** Await từng bước tuần tự, xử lý lỗi riêng.
18. **Câu hỏi:** Lấy ngoại lệ từ `gather`?
   - **Trả lời:** Đặt `try/except` quanh `gather` (mặc định re-raise) hoặc `return_exceptions=True`.
19. **Câu hỏi:** Restart worker thất bại?
   - **Trả lời:** Chạy supervisor loop, bắt lỗi và khởi lại task với backoff.
20. **Câu hỏi:** Dùng lib sync trong test?
   - **Trả lời:** Bao quanh bằng `asyncio.to_thread` hoặc `run_in_executor`.
21. **Câu hỏi:** Tránh deadlock giữa lock sync và async?
   - **Trả lời:** Không `await` khi đang giữ `threading.Lock`, và tách lock sync/async rõ ràng.
22. **Câu hỏi:** Khi nào dùng `as_completed()`?
   - **Trả lời:** Khi cần xử lý kết quả ngay khi từng task xong thay vì đợi cả lô.
23. **Câu hỏi:** Giới hạn API rate-limited?
   - **Trả lời:** Dùng semaphore kết hợp sleep/backoff để kiểm soát song song và tần suất gọi.
24. **Câu hỏi:** Worker pool async nên làm sao?
   - **Trả lời:** Dùng `asyncio.Queue` với số worker cố định và sentinel/cancel để dừng.
25. **Câu hỏi:** Tránh trùng việc theo key?
   - **Trả lời:** Lưu map task đang chạy theo key và tái dùng task đó.
26. **Câu hỏi:** Timeout an toàn?
   - **Trả lời:** Bọc bằng `asyncio.wait_for()` và xử lý timeout riêng.
27. **Câu hỏi:** Khi nào dùng `asyncio.shield()`?
   - **Trả lời:** Khi bước dọn dẹp/ghi cuối phải hoàn tất dù parent bị cancel.
28. **Câu hỏi:** Log async dễ đọc?
   - **Trả lời:** Gắn `request_id`, `job_id`, hoặc tên task vào từng log.
29. **Câu hỏi:** Chọn thread pool hay process pool?
   - **Trả lời:** Thread pool cho I/O block, process pool cho CPU nặng.
30. **Câu hỏi:** Test retry logic?
   - **Trả lời:** Mock chuỗi lỗi có kiểm soát và kiểm tra số lần retry.
31. **Câu hỏi:** Xử lý lỗi một phần?
   - **Trả lời:** Tách thành công/thất bại rồi retry riêng phần thất bại.
32. **Câu hỏi:** Tránh tăng memory ở service dài hạn?
   - **Trả lời:** Bound queue, xoá task hoàn tất khỏi registry, không giữ payload lâu.
33. **Câu hỏi:** Async SDK nhưng vẫn block?
   - **Trả lời:** Đo loop lag, benchmark tải, rồi bọc executor hoặc thay thư viện.
34. **Câu hỏi:** Metric vận hành quan trọng?
   - **Trả lời:** Queue depth, active task, retries, loop lag, error rate, tail latency.
35. **Câu hỏi:** Tránh retry storm?
   - **Trả lời:** Dùng backoff có jitter, giới hạn retry, và pause sau nhiều lỗi.
36. **Câu hỏi:** Khi nào batching tốt hơn concurrency thô?
   - **Trả lời:** Khi API có bulk endpoint hoặc chi phí từng request quá lớn.
37. **Câu hỏi:** Thiết kế ranh giới cancel?
   - **Trả lời:** Xác định bước nào cancel được, bước nào phải hoàn tất, bước nào retry sau.
38. **Câu hỏi:** Ghi dữ liệu idempotent?
   - **Trả lời:** Dùng khóa duy nhất, upsert, transaction retry-safe.
39. **Câu hỏi:** Metric quan trọng cho event loop?
   - **Trả lời:** Loop lag, backlog, queue wait time, error rate, p95/p99 latency.
40. **Câu hỏi:** Tách orchestration và unit-of-work?
   - **Trả lời:** Một lớp điều phối retry/throttle, một lớp chỉ làm tác vụ nhỏ.
41. **Câu hỏi:** Khi nào dùng async generator?
   - **Trả lời:** Khi cần stream kết quả dần thay vì đợi cả danh sách.
42. **Câu hỏi:** Quản lý pool tài nguyên?
   - **Trả lời:** Giới hạn bằng pool/semaphore và release trong `finally`.
43. **Câu hỏi:** Giữ code async dễ bảo trì?
   - **Trả lời:** Chuẩn hoá timeout, retry, logging, shutdown bằng helper chung.
44. **Câu hỏi:** Debug race chỉ xuất hiện khi tải cao?
   - **Trả lời:** Stress test có kiểm soát, thêm correlation ID, giảm dần concurrency.
45. **Câu hỏi:** Quy tắc nhớ nhanh?
   - **Trả lời:** Asyncio cho I/O nhiều, thread cho I/O block cũ, process cho CPU-bound.

## 2. FastAPI
- **Nguồn chính:** docs.fastapi.tiangolo.com (dependency injection, background tasks, security).  
- **Mini project:** xây API quản lý user với các endpoint tạo, đọc, cập nhật, xóa; kết nối async DB (SQLAlchemy/Databases + PostgreSQL).  
- **Bổ sung:** luyện các tình huống xử lý phụ thuộc (Depends), xử lý background job, bảo mật token.

## FastAPI – Top Questions
### Question 1: How do I structure dependency injection for DB sessions and still support background tasks?
**Answer:** Define a dependency that yields the session, use it within the request, and pass the session object explicitly to any `BackgroundTasks` callback.

**Explanation:** Dependencies with `yield` handle enter/exit logic centrally. Within the endpoint, call the dependency and feed its result into the background task to reuse the same session or client rather than creating another.

**Example:**
```
async def get_db():
    async with AsyncSession() as session:
        yield session

@app.post("/jobs")
async def create_job(background_tasks: BackgroundTasks, db=Depends(get_db)):
    background_tasks.add_task(process_job, db)
    return {"status": "queued"}
```

### Question 2: What are the best practices for async DB calls in FastAPI?
**Answer:** Use an async ORM like SQLAlchemy 1.4+ with `async_session`, keep queries small, and avoid reusing synchronous clients inside async endpoints.

**Explanation:** Mixing sync DB drivers with async routes blocks the event loop. Stick to async-aware drivers, release sessions promptly (using `async with` or `yield`), and batch writes/reads to minimize round trips.

**Example:** Fetch records via `await session.execute(select(...))` instead of calling a blocking helper.

### Question 3: How should I secure endpoints with OAuth2 tokens?
**Answer:** Use `OAuth2PasswordBearer` or `HTTPBearer` dependencies and verify tokens before executing sensitive logic.

**Explanation:** Define a reusable dependency that extracts and validates the token, raises `HTTPException(status_code=401)` on failure, and returns the authenticated user or claims for downstream logic.

**Example:**
```
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/token")

async def get_current_user(token: str = Depends(oauth2_scheme)):
    payload = verify_token(token)
    return await load_user(payload["sub"])
```

### Question 4: How do I monitor request latency and instrumentation per endpoint?
**Answer:** Add middleware that records `start = time.monotonic()` before `await call_next()` and logs differences plus relevant headers or tags.

**Explanation:** Collecting latencies per route helps spot slow dependencies. Keep instrumentation light and sample judiciously to avoid affecting throughput.

**Example:** A `@app.middleware("http")` that logs `duration_ms` and request path after the response is produced.

### Question 5: What’s the right way to handle validation errors and custom responses?
**Answer:** Use Pydantic models for payload validation, override `request validation_exception_handler`, and return structured JSON for clients.

**Explanation:** FastAPI automatically validates request/query/body data, but you can customize the exception handler to include extra context or error codes.

**Example:** Attach a handler that logs `exc.errors()` and returns `{"detail": "Invalid input", "errors": ...}`.

### Question 6: How do I return streaming responses from FastAPI?
**Answer:** Use `StreamingResponse` with an async generator or iterator and ensure cleanup occurs after streaming completes.

**Explanation:** Streaming prevents large payload buffering. Yield chunks lazily and close any resources afterward via `try/finally`.

**Example:** `return StreamingResponse(stream_logs(), media_type="text/plain")`.

### Question 7: What’s the best way to validate deeply nested payloads?
**Answer:** Compose nested Pydantic models and use them as field types to delegate validation to each submodel.

**Explanation:** Each nested model encapsulates its own rules; FastAPI assembles them automatically and reports precise errors.

**Example:** 
```
class Address(BaseModel):
    city: str

class User(BaseModel):
    name: str
    address: Address
```

### Question 8: How should I implement pagination safely in FastAPI?
**Answer:** Accept validated `limit`/`offset` query parameters, cap maximum values, and pass them to parameterized DB queries.

**Explanation:** This prevents clients from requesting huge pages. Return metadata like `total`, `page`, and `next_cursor` to guide navigation.

**Example:** 
```
@app.get("/items")
async def list_items(limit: int = Query(20, le=100), offset: int = 0):
    items = await fetch_items(limit, offset)
    return {"items": items, "limit": limit, "offset": offset}
```

### Question 9: How do I test FastAPI endpoints that rely on dependencies?
**Answer:** Use `TestClient` plus `app.dependency_overrides` to inject mocks for dependencies.

**Explanation:** Override IO-heavy or DB dependencies with lightweight fixtures to keep tests fast and deterministic.

**Example:** 
```
app.dependency_overrides[get_db] = lambda: test_session
client = TestClient(app)
```

### Question 10: How do I configure CORS for multiple frontend origins?
**Answer:** Mount `CORSMiddleware` with the allowed origins list, set `allow_credentials`, and permit required headers/methods.

**Explanation:** Proper CORS prevents browser blocks. Define the whitelist once and reuse the same middleware in all deployments.

**Example:** 
```
app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://one.example.com","https://two.example.com"],
    allow_methods=["*"],
    allow_headers=["*"],
    allow_credentials=True,
)
```

### Question 11: How do I handle file uploads efficiently in FastAPI?
**Answer:** Accept `UploadFile` objects, stream them to disk or object storage, and avoid reading the entire file into memory.

**Explanation:** `UploadFile` uses `SpooledTemporaryFile` so you can stream content. Process or forward chunks inside an async loop rather than `.read()` the whole file.

**Example:** 
```
async def upload(file: UploadFile):
    async with aiofiles.open(dest, "wb") as out:
        while chunk := await file.read(1024):
            await out.write(chunk)
```

### Question 12: What’s the best way to version API responses?
**Answer:** Use route prefixes (e.g., `/v1/items`) combined with dependency-driven serializers per version.

**Explanation:** Explicit versioning keeps clients stable. Keep shared logic in helpers while wiring in version-specific serializers or response models.

**Example:** 
```
router_v1 = APIRouter(prefix="/v1")
@router_v1.get("/items", response_model=ItemV1)
```

### Question 13: How do I enforce rate limiting per user?
**Answer:** Implement a dependency that checks a cache/store (Redis) counter per token/IP and raises HTTP 429 when limits breach.

**Explanation:** Rate limiting is cross-cutting; dependencies allow easy reuse. Use TTL-based counters to reset limits after the period.

**Example:** 
```
if cache.incr(key) > limit: raise HTTPException(429)
```

### Question 14: How do I log structured request/response data without leaking secrets?
**Answer:** Build middleware that redacts sensitive fields (passwords/tokens) before logging, and use structured loggers (JSON) for observability.

**Explanation:** Middleware wraps every request/response. Inspect body/headers but mask secrets, and log user/context metadata to trace issues.

**Example:** 
```
request_data = mask_sensitive(await request.json())
```

### Question 15: How can I use dependency overrides during testing to simulate failure modes?
**Answer:** Replace dependencies with mocks that raise exceptions or return error states, then assert handler retries or returns expected responses.

**Explanation:** Overriding is lightweight and allows testing error paths without hitting real infrastructure.

**Example:** 
```
app.dependency_overrides[get_db] = lambda: raise_forbidden()
```

### Question 16: How do I handle WebSocket connections in FastAPI?
**Answer:** Use `WebSocket` routes (`@app.websocket`) and accept connections via `await websocket.accept()`, then send/receive with `await websocket.send_json(...)`.

**Explanation:** WebSockets share the same ASGI infrastructure; keep long-lived connections non-blocking and handle disconnects with try/except for `WebSocketDisconnect`.

**Example:** 
```
@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket):
    await ws.accept()
    await ws.send_text("connected")
```

### Question 17: How do I memoize heavy dependencies?
**Answer:** Set `Depends` to `use_cache=True` (default) and ensure the dependency’s return value is reused per request rather than recreated.

**Explanation:** FastAPI caches dependency results per request by default; avoid calling costly constructors outside dependencies. For cross-request caching, use global singletons or cache decorators.

**Example:** 
```
async def get_client():
    client = AsyncHTTPClient()
    yield client
```

### Question 18: How do I customize the OpenAPI docs per endpoint?
**Answer:** Pass `summary`, `description`, `responses`, and extra metadata to the route decorator and `response_model`.

**Explanation:** Fine-grained metadata ensures accurate docs and helps consumers. Use `response_model_exclude_none` to control output as well.

**Example:** 
```
@app.post("/items", summary="Create item", response_description="The created item")
```

### Question 19: How do I validate repeated query parameters or arrays?
**Answer:** Use `Query(..., alias="tags[]")` with `List[str]` types and `Query` validators (`min_items`, `max_items`).

**Explanation:** FastAPI parses repeated parameters into lists automatically; use query models to enforce constraints or defaults.

**Example:** 
```
async def search(tags: List[str] = Query(default=[], min_items=1)):
```

### Question 20: How do I monitor background task health?
**Answer:** Track future/task state in a shared registry and log start/stop/exception events.

**Explanation:** BackgroundTasks execute asynchronously; store `task = asyncio.create_task(...)`, log metadata, and add callbacks to capture failures.

**Example:** 
```
task = asyncio.create_task(run_job(job_id))
task.add_done_callback(log_result)
```

### Question 21: How do I structure large FastAPI projects cleanly?
**Answer:** Split routes, schemas, services, repositories, and dependencies into separate modules with clear ownership.

**Explanation:** A flat `main.py` becomes hard to maintain quickly. Layered modules make testing easier and reduce tight coupling.

**Example:** Keep API routers in `routers/`, data models in `schemas/`, and DB logic in `repositories/`.

### Question 22: How do I return consistent error payloads across the API?
**Answer:** Define shared exception handlers and one response shape for validation, auth, and domain errors.

**Explanation:** Consistency helps frontend code and observability. Include stable fields like `code`, `message`, and `details`.

**Example:** Return `{"code":"permission_denied","message":"..."}` for every 403.

### Question 23: When should I use lifespan events instead of startup/shutdown decorators?
**Answer:** Prefer lifespan when you want one explicit place to initialize and clean up shared app resources.

**Explanation:** Lifespan keeps setup and teardown closer together and is easier to reason about in newer FastAPI/Starlette patterns.

**Example:** Open shared clients in lifespan and close them in the `finally` block.

### Question 24: How do I reuse service objects across requests safely?
**Answer:** Reuse stateless services freely, but create per-request stateful resources like DB sessions via dependencies.

**Explanation:** Shared mutable state across requests is risky unless you protect it carefully. Favor stateless service classes plus injected request-scoped resources.

**Example:** A shared config service is fine; a DB session should be request-scoped.

### Question 25: How do I handle long-running jobs without blocking HTTP clients?
**Answer:** Queue the work, return a job ID immediately, and expose a status endpoint for polling.

**Explanation:** Long jobs should not hold open normal request-response cycles. This pattern is easier to scale and retry.

**Example:** `POST /jobs` returns `{job_id, status:"queued"}`, then `GET /jobs/{id}` reports progress.

### Question 26: How do I design response models that are stable for clients?
**Answer:** Separate internal ORM models from external response schemas and version breaking changes explicitly.

**Explanation:** Exposing database shapes directly ties clients to backend internals. Response models should be deliberate contracts.

**Example:** Use `UserResponse` even if the ORM entity has extra internal fields.

### Question 27: How do I prevent N+1 query problems in FastAPI endpoints?
**Answer:** Shape queries up front with joins, eager loading, or batch fetches before building the response.

**Explanation:** The HTTP framework is not the issue here, but endpoints often trigger ORM lazy loading accidentally. Fix the data access pattern before serialization.

**Example:** Use `selectinload` when returning users with related roles.

### Question 28: How do I handle idempotent POST requests?
**Answer:** Accept an idempotency key and store request outcomes so retries do not create duplicates.

**Explanation:** This matters for payments, job creation, or any client that may retry after timeouts.

**Example:** Store an `Idempotency-Key` header and return the original result for the same key.

### Question 29: How do I secure internal admin endpoints differently from public ones?
**Answer:** Apply stricter dependencies, scopes, network restrictions, and auditing on admin routers.

**Explanation:** Not every endpoint should share the same auth policy. Split routers by trust level and keep authorization checks explicit.

**Example:** Mount `/admin` with a dependency that enforces admin claims.

### Question 30: What is a good strategy for request tracing?
**Answer:** Generate or propagate a request ID in middleware and attach it to logs, responses, and downstream calls.

**Explanation:** Request tracing helps connect one user action across multiple services and background tasks.

**Example:** Forward `X-Request-ID` to downstream APIs and include it in logs.

### Question 31: How do I validate business rules that depend on the database?
**Answer:** Keep shape validation in Pydantic and enforce DB-backed rules in service or domain layers.

**Explanation:** Pydantic should validate structure, not reach into storage. Business validation usually needs transactions and repository access.

**Example:** Check username uniqueness in a service before insert, not inside the schema.

### Question 32: How do I avoid leaking internal exceptions to clients?
**Answer:** Catch unexpected errors centrally, log full details internally, and return generic 500 responses externally.

**Explanation:** Raw stack traces can leak implementation details or secrets. Central handlers keep output clean and safe.

**Example:** Log exception context server-side and return `{"detail":"Internal server error"}`.

### Question 33: When should I prefer dependency injection over middleware?
**Answer:** Use middleware for cross-cutting HTTP concerns and dependencies for route-level resources or auth context.

**Explanation:** Middleware runs for every request; dependencies are more precise when only some routes need the behavior.

**Example:** Use middleware for timing/logging, but dependency injection for `current_user`.

### Question 34: How do I expose health checks that are actually useful?
**Answer:** Provide a cheap liveness check and a deeper readiness check that verifies critical dependencies.

**Explanation:** Health checks should distinguish “process is alive” from “service can actually do useful work.”

**Example:** `/health/live` returns quickly; `/health/ready` checks DB and cache connectivity.

### Question 35: How do I handle schema migrations safely with FastAPI apps?
**Answer:** Run migrations outside request handling and deploy code that is compatible with both old and new schemas during rollout.

**Explanation:** Tight coupling between deploy and schema change causes downtime risk. Expand-and-contract migrations are safer.

**Example:** Add nullable column first, deploy code, backfill data, then enforce not-null later.

### Question 36: How do I reduce serialization overhead in large responses?
**Answer:** Return only needed fields, paginate aggressively, and avoid building deeply nested payloads by default.

**Explanation:** Serialization cost can become significant even when DB time is fine. Response shape matters.

**Example:** Offer summary endpoints separate from detail endpoints.

### Question 37: How do I implement role-based authorization cleanly?
**Answer:** Encode roles/scopes in auth dependencies and keep authorization checks close to the route or service entry point.

**Explanation:** Authorization logic becomes brittle when scattered across the codebase. Centralized helpers reduce mistakes.

**Example:** `Depends(require_scope("jobs:write"))`.

### Question 38: How do I handle partial updates with PATCH correctly?
**Answer:** Use optional fields in update schemas and apply only provided fields to the stored record.

**Explanation:** PATCH should not overwrite unspecified fields with null unless the client explicitly sends null.

**Example:** Use `payload.model_dump(exclude_unset=True)` before updating.

### Question 39: How do I keep FastAPI tests fast?
**Answer:** Mock external systems, isolate database state, and test most business logic below the HTTP layer.

**Explanation:** Route tests are important, but not every rule needs a full HTTP round trip in tests.

**Example:** Unit test services directly and keep only key endpoint tests at the API level.

### Question 40: How do I handle file-download endpoints safely?
**Answer:** Stream files, validate file ownership, and set explicit content types and filenames.

**Explanation:** Download endpoints can leak data or exhaust memory if they read too much at once or skip authorization checks.

**Example:** Return `FileResponse` only after confirming the current user can access the file.

### Question 41: When should I use routers with prefixes and tags?
**Answer:** Use them to group related endpoints, keep docs readable, and make large APIs easier to navigate.

**Explanation:** Good router boundaries also help ownership and testing because related routes stay together.

**Example:** Put all job endpoints under `APIRouter(prefix="/jobs", tags=["jobs"])`.

### Question 42: How do I keep background work observable after the request ends?
**Answer:** Persist job metadata, emit structured logs, and expose status endpoints or dashboards.

**Explanation:** Once the request finishes, you still need visibility into success, failure, and timing for the background job.

**Example:** Save `started_at`, `finished_at`, and `error` fields for each async job.

### Question 43: How do I avoid overusing `BackgroundTasks`?
**Answer:** Use it for small post-response tasks, but move durable or long-running jobs to a proper queue system when needed.

**Explanation:** `BackgroundTasks` is convenient but still tied to the app process and lifecycle. It is not a full job platform.

**Example:** Send one email in `BackgroundTasks`, but use a queue for bulk document generation.

### Question 44: How do I make FastAPI docs more useful for frontend teammates?
**Answer:** Add examples, stable error shapes, clear summaries, and realistic response models.

**Explanation:** Good docs reduce Slack questions and make frontend integration much faster.

**Example:** Include sample payloads for success, validation error, and auth error cases.

### Question 45: What short rule of thumb summarizes good FastAPI design?
**Answer:** Keep routes thin, dependencies explicit, business logic outside handlers, and long-running work off the request path.

**Explanation:** That rule captures most of the maintainability and performance wins teams need in practice.

**Example:** Route validates input, service does work, repository handles storage, and background queue handles slow tasks.

### FastAPI – Phiên bản tiếng Việt
1. **Câu hỏi:** Sắp xếp dependency cho DB và background task?
   - **Trả lời:** Dùng dependency `yield` và truyền session vào `BackgroundTasks`.
2. **Câu hỏi:** Thực hành async DB?
   - **Trả lời:** Dùng async ORM/driver, giữ truy vấn nhỏ và tránh sync client.
3. **Câu hỏi:** Bảo mật OAuth2?
   - **Trả lời:** Dùng `OAuth2PasswordBearer`/`HTTPBearer`, validate token rồi trả HTTP 401 khi sai.
4. **Câu hỏi:** Giám sát latency?
   - **Trả lời:** Middleware đo `time.monotonic()` trước/sau `call_next`.
5. **Câu hỏi:** Xử lý validation error?
   - **Trả lời:** Dùng Pydantic để validate, override handler để trả payload có cấu trúc.
6. **Câu hỏi:** Streaming response?
   - **Trả lời:** Trả về `StreamingResponse` từ generator/iterator và cleanup tài nguyên.
7. **Câu hỏi:** Validate payload lồng nhau?
   - **Trả lời:** Dùng mô hình Pydantic lồng nhau (nested models).
8. **Câu hỏi:** Pagination an toàn?
   - **Trả lời:** Accept `limit/offset` có validation, limit tối đa, trả metadata.
9. **Câu hỏi:** Test route phụ thuộc?
   - **Trả lời:** Dùng `TestClient` và `dependency_overrides`.
10. **Câu hỏi:** CORS multi origin?
   - **Trả lời:** Dùng `CORSMiddleware` với danh sách domain và `allow_credentials`.
11. **Câu hỏi:** Upload file hiệu quả?
   - **Trả lời:** Dùng `UploadFile`, stream chunks bằng `aiofiles`.
12. **Câu hỏi:** Version API?
   - **Trả lời:** Dùng prefix (ví dụ `/v1`) và response_model riêng biệt.
13. **Câu hỏi:** Rate limiting?
   - **Trả lời:** Dependency kiểm tra counter Redis và raise HTTP 429 nếu vượt.
14. **Câu hỏi:** Log có cấu trúc?
   - **Trả lời:** Middleware làm sạch trường nhạy cảm và log JSON.
15. **Câu hỏi:** Override dependency lỗi?
   - **Trả lời:** Thay bằng mock trả lỗi hoặc trạng thái đặc biệt.
16. **Câu hỏi:** WebSocket?
   - **Trả lời:** Dùng route `@app.websocket`, `await websocket.accept()` và xử lý disconnect.
17. **Câu hỏi:** Memo dependency?
   - **Trả lời:** FastAPI cache dependency theo request nên reuse tự động.
18. **Câu hỏi:** Tùy chỉnh OpenAPI?
   - **Trả lời:** Truyền `summary`, `responses`, `response_description` vào decorator.
19. **Câu hỏi:** Validate query list?
   - **Trả lời:** Dùng `List[str]` với `Query` và tham số `min_items`.
20. **Câu hỏi:** Giám sát background task?
   - **Trả lời:** Lưu task reference, log sự kiện start/finish/exceptions.
21. **Câu hỏi:** Tổ chức project FastAPI lớn?
   - **Trả lời:** Tách router, schema, service, repository, dependency thành module riêng.
22. **Câu hỏi:** Payload lỗi thống nhất?
   - **Trả lời:** Dùng exception handler chung với shape lỗi cố định.
23. **Câu hỏi:** Khi nào dùng lifespan?
   - **Trả lời:** Khi muốn gom setup/cleanup tài nguyên app vào một chỗ rõ ràng.
24. **Câu hỏi:** Reuse service object an toàn?
   - **Trả lời:** Reuse service stateless, còn resource có state thì tạo theo request.
25. **Câu hỏi:** Job chạy lâu thì xử lý sao?
   - **Trả lời:** Queue công việc, trả `job_id` ngay và có endpoint tra cứu trạng thái.
26. **Câu hỏi:** Response model ổn định cho client?
   - **Trả lời:** Tách schema trả về khỏi ORM nội bộ và version khi có breaking change.
27. **Câu hỏi:** Tránh N+1 query?
   - **Trả lời:** Dùng join, eager loading, hoặc batch fetch trước khi serialize.
28. **Câu hỏi:** POST idempotent?
   - **Trả lời:** Dùng idempotency key để retry không tạo bản ghi trùng.
29. **Câu hỏi:** Bảo vệ endpoint admin?
   - **Trả lời:** Tách router admin và áp policy auth/scope nghiêm ngặt hơn.
30. **Câu hỏi:** Request tracing?
   - **Trả lời:** Sinh hoặc nhận `request_id` từ middleware rồi gắn vào log và downstream call.
31. **Câu hỏi:** Validate business rule phụ thuộc DB?
   - **Trả lời:** Để Pydantic kiểm tra shape, còn rule nghiệp vụ thì đặt ở service/domain layer.
32. **Câu hỏi:** Tránh lộ exception nội bộ?
   - **Trả lời:** Log chi tiết ở server nhưng trả 500 generic cho client.
33. **Câu hỏi:** Dependency hay middleware?
   - **Trả lời:** Middleware cho concern toàn request; dependency cho auth/resource theo route.
34. **Câu hỏi:** Health check hữu ích?
   - **Trả lời:** Tách liveness nhẹ và readiness kiểm tra dependency quan trọng.
35. **Câu hỏi:** Migration an toàn?
   - **Trả lời:** Chạy migration ngoài request path và dùng chiến lược expand-contract.
36. **Câu hỏi:** Giảm chi phí serialize response lớn?
   - **Trả lời:** Chỉ trả field cần thiết, paginate, tránh payload lồng quá sâu mặc định.
37. **Câu hỏi:** Role-based authorization sạch?
   - **Trả lời:** Gom logic scope/role vào dependency/helper dùng lại.
38. **Câu hỏi:** PATCH đúng cách?
   - **Trả lời:** Chỉ cập nhật field client thực sự gửi lên bằng `exclude_unset`.
39. **Câu hỏi:** Giữ test FastAPI chạy nhanh?
   - **Trả lời:** Mock hệ ngoài, cô lập DB, test nhiều logic ở tầng service.
40. **Câu hỏi:** Download file an toàn?
   - **Trả lời:** Stream file, kiểm tra quyền truy cập, set content type rõ ràng.
41. **Câu hỏi:** Khi nào dùng router prefix/tag?
   - **Trả lời:** Khi muốn nhóm endpoint rõ ràng và làm docs dễ đọc hơn.
42. **Câu hỏi:** Quan sát background job sau khi request xong?
   - **Trả lời:** Persist metadata job, log có cấu trúc, có endpoint trạng thái.
43. **Câu hỏi:** Tránh lạm dụng `BackgroundTasks`?
   - **Trả lời:** Chỉ dùng cho việc nhỏ sau response; job bền lâu nên đưa vào queue riêng.
44. **Câu hỏi:** Docs hữu ích cho frontend?
   - **Trả lời:** Thêm example, shape lỗi ổn định, summary rõ, response thực tế.
45. **Câu hỏi:** Quy tắc nhớ nhanh cho FastAPI?
   - **Trả lời:** Route mỏng, dependency rõ, business logic tách khỏi handler, việc chậm ra ngoài request path.

## 3. React
- **Tài liệu:** React docs (hooks, context, concurrent mode).  
- **Thực hành:** tái tạo component nhỏ dùng `useReducer`, `useMemo`, Context và Suspense để hiểu state flow và tối ưu re-render.  
- **Check:** kiểm tra DevTools Profiler để đo tái render và tần suất hooks được gọi.

## React – Top Questions
### Question 1: How do I prevent unnecessary re-renders in function components?
**Answer:** Wrap props with `useMemo`/`useCallback`, split components, and rely on `React.memo` for pure subtrees.

**Explanation:** Re-renders happen whenever parent props change, even if the child doesn’t need the new value. Memoization keeps referential equality, while component splitting isolates heavy render work.

**Example:** Provide a memoized handler `const handleClick = useCallback(() => setCount(c => c + 1), [])` before passing it deep.

### Question 2: When should I use `useReducer` instead of `useState`?
**Answer:** Use `useReducer` for complex state transitions that involve multiple related values or when you need to centralize update logic.

**Explanation:** `useReducer` keeps update logic in a single reducer function, which improves readability when state updates depend on the action type.

**Example:** Manage form state with `{loading, data, error}` via reducer actions `FETCH_START`, `FETCH_SUCCESS`, `FETCH_ERROR`.

### Question 3: How do Context and hooks interact without causing nested re-renders?
**Answer:** Provide granular contexts and consume only the values needed; split complex contexts so components avoid subscribing to frequently changing data.

**Explanation:** When a context value changes, all consumers re-render. Keep each context focused (e.g., `AuthContext`, `ThemeContext`) and memoize provider values to avoid re-renders from new references.

**Example:** Memoize context value: `const authValue = useMemo(() => ({ user, login }), [user, login]);`.

### Question 4: How can I measure React performance and spot bottlenecks?
**Answer:** Use React DevTools Profiler to capture interactions, look for “wasted” renders, and inspect flame charts for heavy components.

**Explanation:** Profiling reveals which components render frequently and how long they take, guiding where to add memoization or split logic.

**Example:** Profile during user interactions (typing, navigation) and note components with high render count/time.

### Question 5: What’s the best way to handle derived state?
**Answer:** Compute derived values inside `useMemo` or selectors and avoid duplicating state.

**Explanation:** Derived state should depend on other state/props, so calculating it lazily prevents stale values and extra updates.

**Example:** `const visibleItems = useMemo(() => items.filter(...), [items, filter]);`.

### Question 6: How do I prevent memory leaks from async data fetching?
**Answer:** Cancel fetches with `AbortController` or check a mounted flag before calling `setState`.

**Explanation:** React warns when you call `setState` after unmount. Signal the fetch to abort in the cleanup function or skip updates if the component is no longer mounted.

**Example:** 
```
const controller = new AbortController();
fetch(url, { signal: controller.signal }).then(...);
return () => controller.abort();
```

### Question 7: When should I lift state up versus using context?
**Answer:** Lift state to the nearest common ancestor for a few components; use context when many deep components share it to avoid prop drilling.

**Explanation:** Context adds global subscription cost, so keep it scoped. Use props for localized sharing.

**Example:** Keep form state inside the form component but provide theme via `ThemeContext`.

### Question 8: How do I integrate imperative third-party libraries safely?
**Answer:** Use `useRef` for DOM nodes and `useEffect` for initializing/tearing down the library.

**Explanation:** Hooks ensure the library sees stable refs and cleans up resources when the component unmounts.

**Example:** 
```
const containerRef = useRef(null);
useEffect(() => {
  const chart = createChart(containerRef.current);
  return () => chart.destroy();
}, []);
```

### Question 9: What patterns help manage complex forms?
**Answer:** Use `useReducer` or form libraries (like `react-hook-form`) to centralize state transitions and validation.

**Explanation:** Complex forms involve multiple fields and validation logic; a reducer keeps updates predictable and testable.

**Example:** Combine action types like `SET_FIELD`, `VALIDATE_FIELD`, and `RESET_FORM` inside a reducer.

### Question 10: How do I memoize selectors deriving from Redux/context?
**Answer:** Use `useMemo` or libraries like Reselect to compute derived data only when dependencies change.

**Explanation:** Derived objects/arrays break referential equality, so memoization keeps props stable and prevents needless renders.

**Example:** `const filteredItems = useMemo(() => items.filter(...), [items, filter]);`.

### Question 11: How do I handle global errors in React apps?
**Answer:** Use an Error Boundary component to catch render-time errors and fallback UI, while logging the error to monitoring services.

**Explanation:** Error boundaries wrap child components and catch rendering errors, preventing the whole app from crashing. Combine with analytics to alert developers.

**Example:** 
```
<ErrorBoundary fallback={<ErrorPage />}>
  <MainApp />
</ErrorBoundary>
```

### Question 12: How do I coordinate multiple concurrent HTTP requests?
**Answer:** Use `Promise.all` inside `useEffect` and track loading/state updates carefully to avoid updating unmounted components.

**Explanation:** Parallel requests reduce latency, but you must guard against stale states by checking mounted flags or cancelling requests.

**Example:** 
```
useEffect(() => {
  let cancelled = false;
  Promise.all([fetchA(), fetchB()]).then(([a,b]) => {
    if (!cancelled) setData({a,b});
  });
  return () => { cancelled = true; };
}, []);
```

### Question 13: When should I use Suspense for data fetching?
**Answer:** Use Suspense when paired with a data fetching library that exposes `read()`/`cache`, letting React suspend rendering until data resolves.

**Explanation:** Suspense allows declarative waiting states, but requires compatible fetchers (Relay, React Cache, or custom wrappers). Use for large component trees that should wait collectively.

**Example:** Wrap a `UserProfile` with `<Suspense fallback={<Spinner/>}>` and have the component call `userCache.read()`.

### Question 14: How do I share utility hooks across projects?
**Answer:** Extract them into reusable packages or local shared modules and document the required dependencies/states.

**Explanation:** Hooks like `useToggle` or `usePrevious` benefit from isolation. Publish as private npm packages or keep in `hooks/` folder with consistent exports.

**Example:** `export const usePrevious = (value) => { const ref = useRef(); useEffect(() => { ref.current = value; }); return ref.current; };`

### Question 15: How do I keep rendering deterministic during tests?
**Answer:** Avoid randomness and time-based effects inside components; use mocks for timers (`jest.useFakeTimers`) and stable IDs.

**Explanation:** Tests break when components rely on `Date.now()` or random values. Mock them or inject them via props to keep outputs predictable.

**Example:** 
```
jest.useFakeTimers();
expect(screen.getByText('0')).toBeInTheDocument();
```

### Question 16: How do I manage `useEffect` dependency arrays without over-including values?
**Answer:** Include only values used inside the effect; memoize callbacks/objects passed as dependencies or move them outside the hook.

**Explanation:** Passing un-memoized functions causes repeated executions. Use `useCallback` or define helpers inside the effect if they don't need to persist.

**Example:** 
```
useEffect(() => { fetchData(id); }, [id]);
```

### Question 17: How can I measure the rendering cost of React components?
**Answer:** Use React Profiler’s flame graph, especially the “render time” column, to compare component durations.

**Explanation:** Long render times usually indicate heavy computations or large lists; look for “Commit” events that dominate the timeline.

**Example:** Highlight a component, then interact with the app to see how frequently it commits.

### Question 18: When should I split code with `React.lazy` and `Suspense`?
**Answer:** Use lazy loading for large, infrequently used routes or components to shrink initial bundles.

**Explanation:** Wrap lazily loaded components in `<Suspense fallback>`. Ensure surrounding components handle the loading state gracefully.

**Example:** 
```
const Dashboard = lazy(() => import("./Dashboard"));
<Suspense fallback={<Spinner />}><Dashboard /></Suspense>
```

### Question 19: How do I virtualize long lists for better performance?
**Answer:** Use libraries like `react-window` to render only visible rows and avoid DOM bloat.

**Explanation:** Rendering thousands of rows slows React; virtualization keeps DOM small while preserving scroll behavior.

**Example:** 
```
<FixedSizeList height={300} itemSize={35} itemCount={items.length}>{...}</FixedSizeList>
```

### Question 20: How do I debug custom hook behavior?
**Answer:** Extract logic into utilities, use `console.log` with `useDebugValue`, and write hook-specific tests with `renderHook`.

**Explanation:** Hooks can't be called outside components; testing libraries provide helpers to mount them in isolation for assertions.

**Example:** 
```
const { result } = renderHook(() => useCounter());
```

### Question 21: How do I choose between local state and a global store?
**Answer:** Keep state local unless multiple distant parts of the app truly need to share and coordinate it.

**Explanation:** Over-globalizing state increases coupling and re-render risk. Start local, then lift only when the sharing need becomes real.

**Example:** Modal open state usually stays local; authenticated user state is often global.

### Question 22: How do I avoid stale closures in event handlers and effects?
**Answer:** Use functional state updates, correct dependency arrays, or stable event patterns when callbacks depend on changing values.

**Explanation:** Stale closures happen when a callback captures old state and keeps using it later. This is a common source of “why is my state outdated?” bugs.

**Example:** `setCount(c => c + 1)` is safer than `setCount(count + 1)` inside delayed callbacks.

### Question 23: What makes a custom hook worth extracting?
**Answer:** Extract a hook when logic is reused, stateful, and easier to test or read when separated from the component.

**Explanation:** Not every helper needs a hook. Good hooks usually encapsulate stateful side effects or repeated UI behavior patterns.

**Example:** `useDebouncedValue` is a strong hook candidate.

### Question 24: How do I debounce user input without making the UI feel broken?
**Answer:** Keep the input controlled immediately, but debounce only the expensive side effect like filtering or API search.

**Explanation:** Debouncing the input itself makes typing feel laggy. Debouncing the follow-up effect keeps the interface responsive.

**Example:** Update `query` immediately, then debounce the search request.

### Question 25: How do I avoid prop drilling without overusing Context?
**Answer:** Pass props a few levels when simple, and use composition or colocated providers before defaulting to a giant global context.

**Explanation:** Context solves real problems, but overusing it can make dependencies implicit and harder to debug.

**Example:** Pass a render prop or child component rather than putting everything into one app-wide context.

### Question 26: How do I keep list keys stable?
**Answer:** Use durable IDs from data, not array indexes, whenever list order can change.

**Explanation:** Unstable keys cause state loss, incorrect animations, and confusing UI bugs during insertions or reordering.

**Example:** Use `item.id` rather than `index` in sortable lists.

### Question 27: How do I model loading, success, and error states cleanly?
**Answer:** Use one explicit state model or reducer so impossible combinations do not appear.

**Explanation:** Scattered booleans like `isLoading`, `hasError`, and `data` can drift into contradictory states. A state machine mindset helps.

**Example:** Keep one `status` field with values like `idle`, `loading`, `success`, and `error`.

### Question 28: How do I avoid expensive recalculations during typing?
**Answer:** Move heavy work out of render, memoize derived results when needed, and debounce or defer expensive updates.

**Explanation:** Typing performance often suffers because filtering, sorting, or formatting runs on every keystroke.

**Example:** Use a deferred query value before filtering a very large list.

### Question 29: How do I make reusable components flexible without overengineering them?
**Answer:** Start with a narrow API, expose a few extension points, and avoid premature abstraction.

**Explanation:** Components become hard to maintain when they try to solve every future need up front.

**Example:** Offer `children`, `className`, and one or two render props before adding many flags.

### Question 30: How do I reset component state intentionally?
**Answer:** Reset by changing a `key`, dispatching a reducer reset action, or explicitly setting initial state.

**Explanation:** Hidden state resets confuse users. Make reset behavior explicit and predictable in the component API.

**Example:** Change a form component key when switching to a different record.

### Question 31: How do I keep forms responsive with many fields?
**Answer:** Minimize unnecessary parent renders, isolate field components, and validate incrementally instead of on every global change.

**Explanation:** Large forms slow down when each keystroke forces the whole tree to re-render.

**Example:** Split address, contact, and preferences into separate memoized field groups.

### Question 32: How do I make React components easier to test?
**Answer:** Keep side effects thin, push calculations into pure helpers, and favor observable behavior over implementation details.

**Explanation:** Tests should assert what the user sees and does, not internal state variable names.

**Example:** Test that a spinner appears while loading rather than testing a private `loading` variable.

### Question 33: How do I handle optimistic UI updates safely?
**Answer:** Update the UI immediately, keep enough context to roll back, and reconcile with the server response later.

**Explanation:** Optimistic updates improve responsiveness, but they need a rollback path for failed requests.

**Example:** Insert a temporary todo item locally, then remove or replace it after the API response.

### Question 34: How do I prevent effect chains from causing infinite loops?
**Answer:** Avoid setting state inside an effect unless the effect truly depends on external inputs, and keep dependencies honest.

**Explanation:** Infinite loops usually come from effects that update a value they also depend on without any guard.

**Example:** Derive values in render when possible instead of storing them through an effect.

### Question 35: How do I handle accessibility in custom components?
**Answer:** Use semantic HTML first, then add ARIA roles, keyboard support, and visible focus states only where needed.

**Explanation:** Accessibility is easier when you start from native elements instead of rebuilding controls from divs.

**Example:** Use a real `<button>` for clickable actions instead of a styled `<div>`.

### Question 36: When should I split a component into smaller ones?
**Answer:** Split when a component has multiple responsibilities, repeated conditional branches, or unrelated state clusters.

**Explanation:** Smaller components improve readability and isolate render cost, but splitting too early can also add noise.

**Example:** Separate a dashboard page into header, filters, summary cards, and results table components.

### Question 37: How do I handle browser-only APIs in SSR-aware apps?
**Answer:** Guard them inside effects or runtime checks so server rendering does not access `window` or `document`.

**Explanation:** Browser globals do not exist during server render, so direct access causes crashes or hydration mismatches.

**Example:** Check `typeof window !== "undefined"` before reading local storage.

### Question 38: How do I keep component APIs understandable for teammates?
**Answer:** Prefer a few clear props over many boolean flags, and document the expected usage patterns.

**Explanation:** Component APIs become confusing when every edge case becomes a prop. Clear defaults and naming matter more than sheer flexibility.

**Example:** Prefer `variant="compact"` over multiple flags like `small`, `dense`, and `tight`.

### Question 39: How do I handle hydration mismatch issues?
**Answer:** Keep server and client output deterministic and delay browser-specific rendering until after mount.

**Explanation:** Hydration mismatches often come from timestamps, random IDs, or browser-only state rendered too early.

**Example:** Render a placeholder first, then show local-time formatting after mount.

### Question 40: How do I reason about state ownership?
**Answer:** State should live at the lowest level that needs to control it, but no lower.

**Explanation:** Good state ownership reduces prop drilling and avoids making sibling coordination harder than it needs to be.

**Example:** Keep a selected row state in the table parent, not inside each row.

### Question 41: How do I make loading states feel smoother?
**Answer:** Use skeletons, preserve layout space, and avoid flashing spinners for very short operations.

**Explanation:** Smooth loading UX is about visual stability as much as raw speed.

**Example:** Show card skeletons for a dashboard instead of collapsing the whole layout.

### Question 42: How do I keep CSS and component logic from becoming tangled?
**Answer:** Keep styling concerns declarative and avoid condition-heavy class logic spread across many branches.

**Explanation:** When styling logic becomes unreadable, component intent gets buried. Extract style helpers or smaller components when needed.

**Example:** Build a small helper that maps status to class names instead of inline nested ternaries.

### Question 43: How do I decide whether a re-render problem is worth fixing?
**Answer:** Measure first and only optimize when the re-render creates visible lag, wasted work, or unstable behavior.

**Explanation:** Not every re-render is a bug. Optimization without evidence adds complexity and can make code harder to understand.

**Example:** Use the Profiler before adding memoization everywhere.

### Question 44: How do I design component contracts for async data?
**Answer:** Decide whether the component receives ready data, loading state, or a resource abstraction, and keep that contract consistent.

**Explanation:** Components become messy when some callers pass raw data and others expect the component to fetch by itself.

**Example:** A table component should accept `rows`, `loading`, and `error` instead of fetching internally.

### Question 45: What short rule of thumb summarizes good React design?
**Answer:** Keep state close to where it is used, make renders cheap, and make data flow obvious.

**Explanation:** That rule helps teams avoid both premature global state and premature optimization.

**Example:** Local form state, explicit props, and measured performance tuning usually beat clever abstractions.

### React – Phiên bản tiếng Việt
1. **Câu hỏi:** Ngăn re-render thừa?
   - **Trả lời:** Memoize props/hàm, chia component nhỏ và dùng `React.memo`.
2. **Câu hỏi:** Khi nào dùng `useReducer`?
   - **Trả lời:** Khi state phức tạp, nhiều giá trị liên quan và cần centralize logic.
3. **Câu hỏi:** Context gây re-render?
   - **Trả lời:** Tạo context nhỏ, memoize provider value.
4. **Câu hỏi:** Đo performance?
   - **Trả lời:** Dùng DevTools Profiler, kiểm tra “render time”.
5. **Câu hỏi:** Derived state?
   - **Trả lời:** Dùng `useMemo` hay selectors để tính toán từ state/props.
6. **Câu hỏi:** Fetch bất đồng bộ mà không leak?
   - **Trả lời:** Dùng `AbortController` hoặc flag mounted để tránh cập nhật sau unmount.
7. **Câu hỏi:** Lift state hay context?
   - **Trả lời:** Lift lên ancestor gần nhất; dùng context khi cần chia sẻ sâu.
8. **Câu hỏi:** Kết hợp thư viện imperative?
   - **Trả lời:** Dùng `useRef` + `useEffect` để init/destroy.
9. **Câu hỏi:** Form phức tạp?
   - **Trả lời:** Dùng `useReducer` hoặc thư viện (react-hook-form).
10. **Câu hỏi:** Memo selector?
   - **Trả lời:** Dùng `useMemo` hoặc Reselect để giữ referential equality.
11. **Câu hỏi:** Global errors?
   - **Trả lời:** Error Boundary với fallback UI và logging.
12. **Câu hỏi:** Concurrent HTTP?
   - **Trả lời:** `Promise.all` với kiểm tra mounted flag/tránh cập nhật không hợp lệ.
13. **Câu hỏi:** Suspense data fetching?
   - **Trả lời:** Dùng kết hợp hook hỗ trợ như Relay/React Cache, bọc trong `<Suspense>`.
14. **Câu hỏi:** Hook dùng chung?
   - **Trả lời:** Xuất thành module hoặc package, document dependency.
15. **Câu hỏi:** Render deterministic khi test?
   - **Trả lời:** Mock timers, giá trị ngẫu nhiên, dùng IDs cố định.
16. **Câu hỏi:** Quản lý `useEffect`?
   - **Trả lời:** Chỉ đưa vào dependencies giá trị thực sự cần, memoize callback.
17. **Câu hỏi:** Đánh giá chi phí render?
   - **Trả lời:** Dùng Profiler, xem “Commit” tốn thời gian nhất.
18. **Câu hỏi:** Code splitting?
   - **Trả lời:** Dùng `React.lazy` + `Suspense` cho route lớn.
19. **Câu hỏi:** Virtualize list?
   - **Trả lời:** Dùng `react-window` để render chỉ các phần tử hiển thị.
20. **Câu hỏi:** Debug custom hook?
   - **Trả lời:** Dùng `renderHook`, `useDebugValue`, log rõ ràng.
21. **Câu hỏi:** Khi nào dùng state local thay vì global store?
   - **Trả lời:** Giữ state local trừ khi nhiều vùng xa nhau thật sự cần dùng chung.
22. **Câu hỏi:** Tránh stale closure?
   - **Trả lời:** Dùng functional update, dependency đúng, và callback ổn định.
23. **Câu hỏi:** Khi nào nên tách custom hook?
   - **Trả lời:** Khi logic được tái dùng, có state/effect, và đọc dễ hơn khi tách riêng.
24. **Câu hỏi:** Debounce input đúng cách?
   - **Trả lời:** Cập nhật input ngay, chỉ debounce tác vụ nặng như search hoặc filter.
25. **Câu hỏi:** Tránh prop drilling mà không lạm dụng Context?
   - **Trả lời:** Ưu tiên props vài tầng, composition, rồi mới dùng context.
26. **Câu hỏi:** Giữ list key ổn định?
   - **Trả lời:** Dùng ID bền vững từ dữ liệu, tránh dùng index nếu thứ tự thay đổi.
27. **Câu hỏi:** Mô hình loading/success/error sạch?
   - **Trả lời:** Dùng một state model rõ ràng hoặc reducer để tránh trạng thái mâu thuẫn.
28. **Câu hỏi:** Tránh tính toán nặng khi gõ?
   - **Trả lời:** Đưa việc nặng ra khỏi render, memoize hoặc defer/debounce update.
29. **Câu hỏi:** Component tái sử dụng nhưng không overengineer?
   - **Trả lời:** Bắt đầu API hẹp, mở rộng vừa đủ, tránh trừu tượng quá sớm.
30. **Câu hỏi:** Reset state có chủ đích?
   - **Trả lời:** Dùng `key`, action reset của reducer, hoặc set lại initial state rõ ràng.
31. **Câu hỏi:** Form nhiều field mà vẫn mượt?
   - **Trả lời:** Tách field group, giảm parent rerender, validate tăng dần.
32. **Câu hỏi:** Component dễ test hơn?
   - **Trả lời:** Giữ effect mỏng, tách pure helper, test hành vi quan sát được.
33. **Câu hỏi:** Optimistic UI an toàn?
   - **Trả lời:** Update UI ngay nhưng luôn có dữ liệu để rollback nếu request fail.
34. **Câu hỏi:** Tránh effect chain vô hạn?
   - **Trả lời:** Không set state trong effect trừ khi thật sự cần và dependency phải trung thực.
35. **Câu hỏi:** Accessibility cho component custom?
   - **Trả lời:** Ưu tiên semantic HTML, rồi bổ sung ARIA, keyboard, focus state.
36. **Câu hỏi:** Khi nào nên tách component nhỏ hơn?
   - **Trả lời:** Khi component có nhiều trách nhiệm hoặc nhiều cụm state không liên quan.
37. **Câu hỏi:** Dùng browser API trong app có SSR?
   - **Trả lời:** Chỉ truy cập trong effect hoặc kiểm tra `typeof window`.
38. **Câu hỏi:** Giữ API component dễ hiểu?
   - **Trả lời:** Dùng ít props rõ nghĩa, tránh quá nhiều boolean flag.
39. **Câu hỏi:** Xử lý hydration mismatch?
   - **Trả lời:** Giữ output server/client nhất quán và hoãn phần phụ thuộc browser đến sau mount.
40. **Câu hỏi:** Quyền sở hữu state nên đặt ở đâu?
   - **Trả lời:** Đặt ở mức thấp nhất đủ để điều khiển nhưng không thấp hơn.
41. **Câu hỏi:** Loading state mượt hơn?
   - **Trả lời:** Dùng skeleton, giữ layout ổn định, tránh spinner nhấp nháy.
42. **Câu hỏi:** Tránh CSS và logic bị rối?
   - **Trả lời:** Giữ styling khai báo rõ ràng, tách helper hoặc component nhỏ khi class logic quá nhiều.
43. **Câu hỏi:** Khi nào đáng tối ưu re-render?
   - **Trả lời:** Khi đã đo và thấy lag hoặc có lãng phí rõ ràng, không tối ưu theo cảm tính.
44. **Câu hỏi:** Thiết kế contract cho async data?
   - **Trả lời:** Quy định rõ component nhận `data/loading/error` hay tự fetch, đừng trộn lẫn.
45. **Câu hỏi:** Quy tắc nhớ nhanh cho React?
   - **Trả lời:** Đặt state gần nơi dùng, render rẻ, data flow rõ ràng.

## 4. SQL / Tối ưu
- **Đọc thêm:** _Use The Index, Luke_, _SQL Performance Explained_.  
- **Thực hành:** viết truy vấn phức tạp (CTE, window functions) rồi chạy `EXPLAIN ANALYZE` để xem kế hoạch thực thi; thử tối ưu bằng index, rewrite, limit.  
- **Kết hợp:** lưu lại các pattern query và kế hoạch tối ưu của riêng mình để review trước phỏng vấn.

## SQL / Tối ưu – Top Questions
### Question 1: How do I read an `EXPLAIN ANALYZE` plan to find the bottleneck?
**Answer:** Start at the top node, look for the highest `Actual Time` and rows, and spot sequential scans or nested loops dragging performance.

**Explanation:** `EXPLAIN ANALYZE` shows actual execution data; focus on expensive nodes, check if they use indexes, and note repeated loops.

**Example:** A nested loop over 1000 rows indicates missing join condition or index; consider rewriting join order or adding an index.

### Question 2: When should I add indexes versus rewriting the query?
**Answer:** Add indexes when filters/join keys are stable and selective; rewrite queries when the execution order or filters prevent index use.

**Explanation:** Indexes help where equality/lookups happen frequently. If a query references functions or calculations, rewrite it to use indexed columns or create expression indexes.

**Example:** Instead of `WHERE LOWER(name) = 'x'`, store names normalized and query the indexed column.

### Question 3: How do window functions affect query performance?
**Answer:** Window functions like `ROW_NUMBER` may require sorting; ensure you limit rows before applying them or use indexes on partition/order columns.

**Explanation:** Sorting large datasets is expensive. Use filters or subqueries to narrow the input or pre-aggregate before the window operation.

**Example:** Use `ROW_NUMBER() OVER (PARTITION BY user_id ORDER BY created_at DESC)` inside a CTE that already filters `WHERE status='active'`.

### Question 4: What’s the trade-off between `JOIN` and `IN`?
**Answer:** Joins usually scale better because database engines can optimize execution, whereas `IN (subquery)` may re-run for each row unless correlated properly.

**Explanation:** Joins allow the optimizer to pick the best plan and can benefit from indexes. Use `IN` for small static lists, but prefer `EXISTS` or explicit joins otherwise.

**Example:** Replace `WHERE user_id IN (SELECT user_id FROM active_users)` with a join to avoid repeated subquery execution.

### Question 5: How do I approach query optimization iteratively?
**Answer:** Measure current performance, identify hotspots via `EXPLAIN ANALYZE`, then apply one change at a time (index, rewrite, limit) and re-measure.

**Explanation:** Avoid blind optimization; use actual execution stats, try targeted changes, and verify their impact before moving on.

**Example:** After adding an index, rerun `EXPLAIN ANALYZE` and compare `actual time` to ensure the improvement is real.

### Question 6: How do I spot missing indexes that trigger sequential scans?
**Answer:** Look for `Seq Scan` nodes in `EXPLAIN ANALYZE` on large tables, then index columns used in `WHERE` or join conditions.

**Explanation:** Sequential scans over millions of rows indicate the planner has no index to use; adding a covering index drastically reduces row reads.

**Example:** For `WHERE created_at >= ...`, add `CREATE INDEX ON jobs (created_at)`.

### Question 7: When should I denormalize tables for performance?
**Answer:** Denormalize when joins become too expensive for analytical/reporting queries and duplication cost is acceptable.

**Explanation:** Denormalization trades storage for faster reads. Use it where write frequency is low and read latency matters most, or create materialized views refreshed on a schedule.

**Example:** Store user info with each log entry instead of joining users for each report.

### Question 8: How do I keep pagination fast on large tables?
**Answer:** Use cursor pagination (`WHERE id > :last_seen`) with indexed columns instead of `OFFSET` to avoid scanning skipped rows.

**Explanation:** `OFFSET` still reads skipped rows; cursor pagination only touches rows after the last seen ID, leveraging indexes.

**Example:** 
```
SELECT * FROM jobs WHERE id > :cursor ORDER BY id LIMIT 20;
```

### Question 9: How should I influence join ordering?
**Answer:** Let the optimizer decide, but push selective filters earlier via subqueries or CTEs if necessary to reduce row counts before joins.

**Explanation:** Applying `WHERE` clauses before joins or using `JOIN` hints (sparingly) helps the optimizer see smaller datasets, improving performance.

**Example:** Filter the smaller table in a CTE before joining to a larger dimension table.

### Question 10: What does `loops` mean in EXPLAIN output?
**Answer:** `loops` shows how many times the node executed; multiply by `rows` to understand total processed rows and spot underestimated costs.

**Explanation:** High loops indicate repeated execution (e.g., nested loops). Compare estimates with actuals to determine if statistics are stale.

**Example:** If a node loops 100 times with 100 rows each (10,000 total), ensure indexes/statistics support that pattern.

### Question 11: How do I use covering indexes to avoid lookups?
**Answer:** Include all queried columns in the index so the planner can satisfy the query entirely from the index without touching the table.

**Explanation:** Covering indexes (multi-column indexes matching filters and selects) reduce I/O by avoiding heap access. Order columns by filter/join priority.

**Example:** Querying `SELECT id, status FROM jobs WHERE status = 'open'` benefits from an index on `(status, id)`.

### Question 12: When should I use materialized views?
**Answer:** Use them for expensive aggregations that don’t require real-time freshness, refreshing periodically or on-demand.

**Explanation:** Materialized views store precomputed results, speeding repeated queries but needing refresh logic to stay current.

**Example:** `REFRESH MATERIALIZED VIEW weekly_summary;` scheduled nightly for stable reports.

### Question 13: How do I avoid index bloat?
**Answer:** Drop unused indexes, limit index length, and avoid duplicate indexes covering the same columns in different orders.

**Explanation:** Each index consumes space and slows writes. Analyze `pg_stat_user_indexes` (Postgres) to find rarely scanned indexes.

**Example:** Replace separate indexes on `(a,b)` and `(b,a)` with a single one if only `(a,b)` is used.

### Question 14: How do I profile disk I/O impact on queries?
**Answer:** Monitor `EXPLAIN ANALYZE`’s `I/O` counters (if available) or inspect `pg_stat_statements` together with system tools (`iostat`) to see read/write pressure.

**Explanation:** Queries that hit disk frequently are slow; detect them by looking at `read`/`write` waits and by checking buffer/cache usage.

**Example:** A query showing high `buffers` read suggests missing indexes or large table scans.

### Question 15: How can I use CTEs without hurting performance?
**Answer:** Use inline CTEs (supported by Postgres 12+ with `MATERIALIZED`/`NOT MATERIALIZED` hints) and avoid unnecessary materialization.

**Explanation:** CTEs used as optimization fences can force materialization (Postgres <12). Prefer subqueries or `NOT MATERIALIZED` when you expect the optimizer to inline.

**Example:** `WITH data AS (SELECT ... ) NOT MATERIALIZED SELECT ...` ensures the CTE is inlined where possible.

### Question 16: How do I keep planner statistics accurate?
**Answer:** Run `ANALYZE` on tables after significant data changes or rely on autovacuum/autoanalyze tuned thresholds.

**Explanation:** Stale stats mislead the optimizer, causing bad plans. Call `ANALYZE table` or configure `autovacuum_analyze_threshold` to keep estimates fresh.

**Example:** `ANALYZE jobs;`

### Question 17: How do I avoid parameter sniffing issues?
**Answer:** Use `EXECUTE` with literals (in Postgres) or add plan guides, and consider using prepared statements that recompile per varying parameters.

**Explanation:** Parameter whispers can cause suboptimal plans because the optimizer caches one plan that suits only certain parameter values. Rewriting queries to include `CASE` or using `PL/pgSQL` functions per scenario helps.

**Example:** 
```
EXECUTE format('SELECT ... WHERE id = %s', quote_literal(id));
```

### Question 18: When should I use temporary tables?
**Answer:** Use them for complex transformations that require multiple passes or for storing intermediate results reused in the same session.

**Explanation:** Temp tables reduce repeated computation in big ETL tasks or report queries and are automatically dropped at session end.

**Example:** 
```
CREATE TEMP TABLE tmp AS SELECT ...;
SELECT ... FROM tmp JOIN ...;
```

### Question 19: How do I capture slow queries for analysis?
**Answer:** Enable `log_min_duration_statement` (Postgres) or trace in MySQL, then inspect logs for queries exceeding thresholds.

**Explanation:** Logging slow statements lets you examine actual SQL and plan to optimize without manually sampling.

**Example:** `ALTER SYSTEM SET log_min_duration_statement = 200;`

### Question 20: How do I reduce lock contention during batch updates?
**Answer:** Batch updates in small transactions, use `SELECT FOR UPDATE SKIP LOCKED`, or apply optimistic locking mechanisms.

**Explanation:** Large transactions hold locks long; breaking them reduces waiting time. `SKIP LOCKED` lets multiple workers process without stepping on each other.

**Example:** 
```
UPDATE jobs SET status='done' WHERE id IN (
  SELECT id FROM jobs WHERE status='pending' FOR UPDATE SKIP LOCKED LIMIT 100
);
```

### Question 21: How do I choose column order in a composite index?
**Answer:** Put the most selective and commonly filtered columns first, then columns used for sorting or covering.

**Explanation:** Composite indexes work best when their leftmost columns match real query patterns. Wrong order often makes an index far less useful.

**Example:** For `WHERE status = ? AND created_at > ? ORDER BY created_at`, an index on `(status, created_at)` is often stronger than `(created_at, status)`.

### Question 22: When should I use `EXISTS` instead of `IN`?
**Answer:** Prefer `EXISTS` when checking whether related rows exist, especially for large subqueries.

**Explanation:** `EXISTS` can short-circuit earlier and often expresses intent more clearly for relational existence checks.

**Example:** Use `WHERE EXISTS (SELECT 1 FROM orders o WHERE o.user_id = u.id)` for existence filtering.

### Question 23: How do I optimize `ORDER BY ... LIMIT` queries?
**Answer:** Add indexes that support both the filter and the sort so the engine can avoid sorting large result sets.

**Explanation:** Sorting is expensive when the database must read many rows first. Matching indexes can turn that into an index walk instead.

**Example:** A feed query often benefits from `(user_id, created_at DESC)`.

### Question 24: How do I know an index is hurting write performance?
**Answer:** Look for slow inserts/updates on heavily indexed tables and audit whether each index is actually used.

**Explanation:** Every extra index adds maintenance work on writes. Read-heavy gains must justify that write cost.

**Example:** A table with many rarely used indexes may become much slower under batch inserts.

### Question 25: When should I partition a table?
**Answer:** Partition when tables are very large and queries naturally filter by a partition key like date or tenant.

**Explanation:** Partitioning can reduce scan volume and maintenance cost, but it also adds operational complexity and is not a default win.

**Example:** Event logs partitioned by month are easier to archive and query by time window.

### Question 26: How do I optimize case-insensitive search?
**Answer:** Normalize data, use expression indexes, or use database-native text search features instead of full table scans.

**Explanation:** Functions like `LOWER(column)` can block normal index use unless you support them explicitly with the right index strategy.

**Example:** Create an index on `LOWER(email)` if that lookup is common.

### Question 27: How do I reduce expensive count queries?
**Answer:** Avoid exact counts when not needed, use filtered counters, cached totals, or approximate metadata for large tables.

**Explanation:** `COUNT(*)` over huge datasets can be expensive, especially with extra joins or filters.

**Example:** Show “1000+ results” instead of exact totals on deep search pages.

### Question 28: How do I compare two query plans usefully?
**Answer:** Compare actual timing, row counts, join strategy, and whether sorts/scans disappeared after the change.

**Explanation:** A lower estimated cost is not enough. You want actual runtime improvements and fewer wasteful operations.

**Example:** Check whether a seq scan became an index scan after adding an index.

### Question 29: How do I avoid sorting huge intermediate result sets?
**Answer:** Filter earlier, pre-aggregate sooner, and add indexes that support the required order.

**Explanation:** Large sorts usually indicate the query is doing too much work before narrowing the data.

**Example:** Move restrictive `WHERE` clauses into a subquery before a window function.

### Question 30: How do I decide if a query should be rewritten as multiple steps?
**Answer:** Split it when one giant query becomes unreadable, spills too much memory, or repeats expensive work.

**Explanation:** Sometimes two or three simpler queries with temp tables or staged processing are easier to tune than one monster query.

**Example:** Materialize a filtered subset first, then join it to reporting tables.

### Question 31: How do I optimize joins on nullable columns?
**Answer:** Be explicit about null handling and avoid assumptions that indexes will behave the same as on non-nullable keys.

**Explanation:** Null semantics can change join results and planner choices. Data cleanup or schema adjustments may be better than query tricks.

**Example:** Filter out null join keys early when they are not meaningful for the query.

### Question 32: What is a good process for tuning a slow report query?
**Answer:** Start from the business need, inspect plan hotspots, trim unused fields, pre-aggregate where possible, and remeasure after each change.

**Explanation:** Reports often accumulate accidental complexity over time. Tuning is easier when you reduce scope before optimizing the remaining work.

**Example:** Remove columns nobody reads before investing in complex indexing.

### Question 33: How do I spot cardinality-estimation problems?
**Answer:** Compare estimated rows versus actual rows in `EXPLAIN ANALYZE` and investigate big mismatches.

**Explanation:** Large estimate errors often point to stale statistics, skewed data, or predicates the planner does not understand well.

**Example:** If the planner expects 10 rows and gets 100,000, join choice may be badly wrong.

### Question 34: How do I use partial indexes effectively?
**Answer:** Create them for frequent queries that filter a small, stable subset of the table.

**Explanation:** Partial indexes stay smaller and faster when most rows are irrelevant to the common query pattern.

**Example:** Index only active records with `WHERE deleted_at IS NULL`.

### Question 35: How do I decide between OLTP-style queries and reporting-style queries?
**Answer:** Keep transaction queries narrow and fast, and offload broad analytics to separate reporting paths when possible.

**Explanation:** Mixing operational and analytical workloads on the same patterns often leads to painful compromises.

**Example:** Use summary tables or warehouse exports for dashboard analytics.

### Question 36: How do I optimize updates that touch many rows?
**Answer:** Batch them, index the filter columns, and avoid rewriting unchanged values.

**Explanation:** Large updates can cause locks, bloat, and long transaction times. Smaller chunks are easier on the system.

**Example:** Update 5,000 rows at a time instead of 500,000 in one transaction.

### Question 37: How do I know if a CTE should become a materialized view?
**Answer:** Promote it when the same expensive logic is reused often and real-time freshness is not required.

**Explanation:** Repeatedly paying the same heavy query cost is a sign the result may deserve persistence.

**Example:** A daily revenue rollup reused by many dashboards can move into a materialized view.

### Question 38: How do I optimize text search beyond `LIKE '%term%'`?
**Answer:** Use full-text search, trigram indexes, or dedicated search systems when substring matching becomes too slow.

**Explanation:** Leading-wildcard `LIKE` queries usually bypass normal indexes and degrade quickly as tables grow.

**Example:** Postgres `GIN` indexes with trigram support help fuzzy text search a lot.

### Question 39: How do I decide if query caching is worth it?
**Answer:** Cache when the query is expensive, repeated, and the staleness tradeoff is acceptable.

**Explanation:** Caching can hide database cost, but invalidation and freshness rules must be clear or the cache becomes a source of bugs.

**Example:** Cache top dashboard metrics for 30 seconds if exact real-time values are not required.

### Question 40: How do I tune queries with heavy aggregation?
**Answer:** Pre-filter input rows, aggregate in fewer passes, and use summary tables when the same aggregation repeats frequently.

**Explanation:** Aggregations become expensive mainly when they process too much raw data too often.

**Example:** Aggregate active users per day from a filtered subset rather than the full events table.

### Question 41: How do I balance readability and performance in SQL?
**Answer:** Prefer readable queries first, then optimize the specific hotspots revealed by measurement.

**Explanation:** Over-optimized unreadable SQL is hard to maintain and often unnecessary outside a few critical paths.

**Example:** Keep a clear CTE version unless profiling proves it is the bottleneck.

### Question 42: How do I optimize deletes on large tables?
**Answer:** Delete in batches, filter through indexed columns, and plan for vacuum/cleanup afterward.

**Explanation:** Massive deletes create bloat and lock pressure. Smaller chunks are easier to recover from and monitor.

**Example:** Delete old logs in date ranges of 10,000 rows per run.

### Question 43: How do I know whether a query should move to a data warehouse?
**Answer:** Move it when it is analytically heavy, scans huge historical data, and competes with transactional workloads.

**Explanation:** Some queries do not belong on the primary operational database, especially dashboards with wide scans and many joins.

**Example:** Multi-year trend analysis often belongs in a warehouse or reporting replica.

### Question 44: How do I optimize for multi-tenant databases?
**Answer:** Include tenant filters in indexes, avoid cross-tenant scans, and design queries so tenant boundaries stay explicit.

**Explanation:** Tenant-aware indexing prevents one tenant’s workload from scanning everyone else’s data.

**Example:** Index `(tenant_id, created_at)` for tenant-scoped feeds.

### Question 45: What short rule of thumb summarizes practical SQL optimization?
**Answer:** Measure first, reduce scanned rows early, support the final access pattern with the right indexes, and verify with `EXPLAIN ANALYZE`.

**Explanation:** Most useful SQL tuning comes down to doing less work and proving the database is actually doing less work afterward.

**Example:** Filter earlier, sort less, and confirm the plan improved instead of guessing.

### SQL / Tối ưu – Phiên bản tiếng Việt
1. **Câu hỏi:** Đọc EXPLAIN để tìm điểm nghẽn?
   - **Trả lời:** Bắt đầu từ node trên cùng, xem `Actual Time` lớn nhất và các seq/nested scan.
2. **Câu hỏi:** Khi nào thêm index hay rewrite query?
   - **Trả lời:** Thêm index nếu filter/join ổn định; rewrite nếu planner không dùng index.
3. **Câu hỏi:** Window function ảnh hưởng gì?
   - **Trả lời:** Gây sort; lọc trước khi áp dụng hoặc thêm index cho partition/order.
4. **Câu hỏi:** JOIN vs IN?
   - **Trả lời:** JOIN tối ưu hơn cho dữ liệu lớn; IN dùng cho danh sách nhỏ.
5. **Câu hỏi:** Tối ưu lặp lại?
   - **Trả lời:** Đo, chỉnh index/rewrite/limit từng bước và chạy lại EXPLAIN.
6. **Câu hỏi:** Nhận diện thiếu index?
   - **Trả lời:** Xem `Seq Scan` trên bảng lớn và index cột filter/join đó.
7. **Câu hỏi:** Denormalize khi nào?
   - **Trả lời:** Khi joins quá chậm cho report và có thể chấp nhận trùng dữ liệu.
8. **Câu hỏi:** Pagination nhanh?
   - **Trả lời:** Dùng cursor (`WHERE id > last_seen`) thay vì OFFSET.
9. **Câu hỏi:** Ảnh hưởng của order join?
   - **Trả lời:** Để optimizer quyết định, dùng filter trước khi join nếu cần.
10. **Câu hỏi:** `loops` nghĩa là gì?
   - **Trả lời:** Số lần node chạy; multiply với rows để ra tổng dòng xử lý.
11. **Câu hỏi:** Covering index?
   - **Trả lời:** Index bao gồm tất cả cột cần select tránh truy cập bảng.
12. **Câu hỏi:** Materialized view?
   - **Trả lời:** Dùng cho aggregate nặng, refresh định kỳ.
13. **Câu hỏi:** Tránh index bloat?
   - **Trả lời:** Xoá index không dùng, gom các index tương đồng.
14. **Câu hỏi:** Profil IO?
   - **Trả lời:** Dùng `pg_stat_statements`/`iostat`, xem `buffers`.
15. **Câu hỏi:** CTE không làm chậm?
   - **Trả lời:** Dùng `NOT MATERIALIZED`/inline nếu không muốn materialize.
16. **Câu hỏi:** Giữ stats chính xác?
   - **Trả lời:** Chạy `ANALYZE` sau khi dữ liệu thay đổi lớn.
17. **Câu hỏi:** Tránh parameter sniffing?
   - **Trả lời:** Dùng `EXECUTE format()` hoặc plan riêng cho tham số khác nhau.
18. **Câu hỏi:** Khi dùng temp table?
   - **Trả lời:** Khi cần lưu kết quả trung gian cho ETL hoặc báo cáo phức tạp.
19. **Câu hỏi:** Bắt slow query?
   - **Trả lời:** Bật `log_min_duration_statement` và kiểm tra log.
20. **Câu hỏi:** Giảm lock contention?
   - **Trả lời:** Chia batch nhỏ, `FOR UPDATE SKIP LOCKED`.
21. **Câu hỏi:** Thứ tự cột trong composite index?
   - **Trả lời:** Đặt cột lọc phổ biến và chọn lọc cao ở trước, rồi đến cột sort/cover.
22. **Câu hỏi:** Khi nào dùng `EXISTS` thay vì `IN`?
   - **Trả lời:** Khi chỉ cần kiểm tra sự tồn tại, nhất là với subquery lớn.
23. **Câu hỏi:** Tối ưu `ORDER BY ... LIMIT`?
   - **Trả lời:** Tạo index hỗ trợ cả filter lẫn sort để tránh sort lớn.
24. **Câu hỏi:** Nhận biết index làm chậm write?
   - **Trả lời:** Theo dõi insert/update chậm trên bảng có quá nhiều index và audit mức độ dùng thực tế.
25. **Câu hỏi:** Khi nào partition table?
   - **Trả lời:** Khi bảng rất lớn và truy vấn tự nhiên bám theo khóa như thời gian hoặc tenant.
26. **Câu hỏi:** Tối ưu tìm kiếm không phân biệt hoa thường?
   - **Trả lời:** Normalize dữ liệu, dùng expression index hoặc full-text/trigram.
27. **Câu hỏi:** Giảm chi phí query đếm?
   - **Trả lời:** Tránh exact count khi không cần, dùng cache/approximate/counter riêng.
28. **Câu hỏi:** So sánh hai query plan như thế nào?
   - **Trả lời:** So actual time, actual rows, join strategy, sort/scan có giảm hay không.
29. **Câu hỏi:** Tránh sort trên tập trung gian quá lớn?
   - **Trả lời:** Filter sớm, pre-aggregate, và dùng index hỗ trợ thứ tự.
30. **Câu hỏi:** Khi nào nên tách query thành nhiều bước?
   - **Trả lời:** Khi query quá khó đọc, tốn memory, hoặc lặp lại phần việc nặng.
31. **Câu hỏi:** Join trên cột nullable?
   - **Trả lời:** Xử lý null rõ ràng và đừng giả định planner sẽ tối ưu như khóa không null.
32. **Câu hỏi:** Quy trình tune query báo cáo chậm?
   - **Trả lời:** Bắt đầu từ nhu cầu nghiệp vụ, xem điểm nghẽn, cắt bớt field thừa, rồi đo lại.
33. **Câu hỏi:** Nhận diện cardinality-estimation sai?
   - **Trả lời:** So sánh estimated rows và actual rows trong EXPLAIN ANALYZE.
34. **Câu hỏi:** Partial index dùng khi nào?
   - **Trả lời:** Khi truy vấn thường xuyên chỉ đụng một tập con nhỏ và ổn định của bảng.
35. **Câu hỏi:** Phân biệt query OLTP và reporting?
   - **Trả lời:** Query giao dịch nên hẹp và nhanh; analytics rộng nên đi lối riêng.
36. **Câu hỏi:** Tối ưu update nhiều dòng?
   - **Trả lời:** Batch nhỏ, index cột filter, tránh rewrite giá trị không đổi.
37. **Câu hỏi:** Khi nào CTE nên thành materialized view?
   - **Trả lời:** Khi logic nặng được dùng đi dùng lại và không cần thời gian thực.
38. **Câu hỏi:** Tìm kiếm text tốt hơn `LIKE '%term%'`?
   - **Trả lời:** Dùng full-text search, trigram index, hoặc hệ search chuyên dụng.
39. **Câu hỏi:** Khi nào nên cache query?
   - **Trả lời:** Khi query đắt, lặp lại nhiều, và chấp nhận được độ trễ dữ liệu.
40. **Câu hỏi:** Tối ưu aggregation nặng?
   - **Trả lời:** Lọc sớm, giảm số lượt aggregate, và dùng bảng tổng hợp nếu lặp lại.
41. **Câu hỏi:** Cân bằng readability và performance?
   - **Trả lời:** Viết dễ đọc trước, chỉ tối ưu chỗ thật sự nóng sau khi đo.
42. **Câu hỏi:** Tối ưu delete trên bảng lớn?
   - **Trả lời:** Xoá theo batch, lọc bằng cột có index, và tính tới vacuum/cleanup.
43. **Câu hỏi:** Khi nào nên đưa query sang warehouse?
   - **Trả lời:** Khi query phân tích quá nặng và cạnh tranh tài nguyên với workload giao dịch.
44. **Câu hỏi:** Tối ưu DB đa tenant?
   - **Trả lời:** Đưa `tenant_id` vào index và tránh scan chéo tenant.
45. **Câu hỏi:** Quy tắc nhớ nhanh cho tối ưu SQL?
   - **Trả lời:** Đo trước, giảm số dòng scan sớm, tạo đúng index, rồi kiểm tra lại bằng EXPLAIN ANALYZE.

## Kỹ thuật ôn luyện
- Tách thời gian mỗi ngày cho 1 chủ đề, gồm: 30 phút lý thuyết, 30 phút code bài tập, 15 phút tái nhìn lại lỗi.  
- Ghi chú bằng markdown, highlight các khái niệm chưa hiểu rồi revisit 1 lần/tuần.  
- Sau mỗi tuần, thử giải bài phỏng vấn liên quan (LeetCode FastAPI/React/SQL) và ghi lại cách giải trong file này (có thể thêm phụ lục mới).

## Các câu hỏi và câu trả lời ưu tiên nhất
- **Q:** Khi nào nên chọn async (asyncio) thay vì multithreading cho phần xử lý I/O, và cách so sánh thực tế?
  - **A:** Chọn asyncio khi mã chủ yếu chờ I/O (HTTP, DB, file) vì event loop tận dụng được thread đơn, giảm overhead đồng bộ. So sánh bằng cách chạy một tập benchmark nhỏ (đếm thời gian xử lý đồng thời trong sync vs async, ghi `time.perf_counter()` hoặc `asyncio.get_running_loop().time()`), đồng thời quan sát CPU/độ trễ để xác định điểm bão hòa thread pool.
- **Q:** Làm sao bảo đảm dependency injection trong FastAPI mà vẫn kiểm soát được background task và token bảo mật?
  - **A:** Dùng `Depends` với `yield` để mở/đóng session/connection, kết hợp scope `request` để đảm bảo context sạch. Khởi tạo `OAuth2PasswordBearer` hoặc `HTTPBearer` trong dependency bảo mật, kiểm tra token và `raise HTTPException` nếu lỗi. Background task chạy qua `BackgroundTasks` để tách khỏi response chính và luôn log lỗi.
- **Q:** Phân tích re-render trong React và tối ưu bằng hooks?
  - **A:** Dùng DevTools Profile để thấy thành phần re-render nhiều, kiểm tra props/hook dependency thay đổi. Dùng `React.memo`, `useMemo`, `useCallback` để giữ referential equality; tách component lớn thành nhỏ hơn để giảm khu vực render. Đảm bảo không tạo hàm/đối tượng mới trong render đối với props/dep quan trọng.
- **Q:** Cách đọc `EXPLAIN ANALYZE` và định hướng tối ưu SQL để thuyết phục người phỏng vấn?
  - **A:** Đọc plan từ trên xuống dưới: tìm node có chi phí lớn nhất và thời gian thực tế cao; chú ý seq scan, nested loop, hash join. Sau đó điều chỉnh bằng index (multi-column, biểu thức), rewrite câu truy vấn (CTE, LIMIT, filter sớm) và chạy lại `EXPLAIN ANALYZE` để xác nhận giảm thời gian và số rows. Ghi lại trước/sau và các chỉ số chính (actual time, rows, loops) để thuyết phục người phỏng vấn.

## High-Frequency Questions
### Question: How can I detect when blocking code is starving my asyncio workflow?
**Answer:** Watch for synchronous I/O or CPU-heavy work inside coroutines and move it outside the event loop using `asyncio.to_thread`/`run_in_executor` or native async equivalents.

**Explanation:** If an `async` function awaits and then spends several milliseconds in blocking disk, network, or CPU work, it prevents the loop from processing other tasks. Logging `asyncio.get_running_loop().time()` before and after suspicious sections or using `asyncio.Task.get_stack()` during profiling highlights the culprit. Replace the blocking call with a library that provides async primitives or offload the work to a thread/process pool explicitly so the event loop can stay responsive.

**Example:** Instead of calling `requests.get(...)` inside an async endpoint, wrap it with `await asyncio.to_thread(requests.get, ...)` or swap to `httpx.AsyncClient.get` to keep the coroutine non-blocking.

### Question: What is the simplest way to reuse a FastAPI dependency between a request handler and a background task?
**Answer:** Define the shared resource (e.g., DB session, HTTP client) as a dependency function that yields the resource, use it in the endpoint, and pass it explicitly to the `BackgroundTasks` callback so it reuses the same logic.

**Explanation:** Dependencies that use `yield` are ideal for setup/teardown. Within your endpoint, declare the dependency and start the background task, passing the resource returned by the dependency to the task’s call. This keeps lifecycle management centralized while allowing the task to reuse the same client/session without instantiating new ones accidentally.

**Example:**
```
async def get_db():
    async with async_session() as session:
        yield session

@app.post("/process")
async def process_item(background_tasks: BackgroundTasks, db=Depends(get_db)):
    background_tasks.add_task(run_async_job, db)
    return {"status": "queued"}
```
## Bản tiếng Việt
- Tài liệu này tập trung vào 4 chủ đề chính: Python/Concurrency, FastAPI, React và SQL/Tối ưu.
- Mỗi phần hiện có 45 câu hỏi trọng yếu bằng tiếng Anh kèm bản tóm tắt tiếng Việt để ôn nhanh theo từng chủ đề.
- Phần Python nhấn mạnh async vs threading, GIL, event loop, retry, worker pool, idempotency và vận hành dịch vụ concurrent.
- Phần FastAPI tập trung vào dependency injection, async DB, auth, lifecycle, background jobs, docs, testing và thiết kế API ổn định.
- Phần React bao phủ hooks, state ownership, rendering, data flow, form handling, accessibility, performance và async UI.
- Phần SQL đi từ EXPLAIN ANALYZE, index, joins, pagination, aggregation đến partitioning, caching và tối ưu workload đa tenant.
- Phần kỹ thuật ôn luyện và các câu hỏi ưu tiên vẫn giữ vai trò ôn nhanh các khái niệm nền tảng trước khi đi sâu vào từng nhóm 45 câu hỏi.
