# So sánh RAG workflow: Current vs Target

Tài liệu này so sánh trực tiếp `docs/04_rag_workflow_current.mmd` (current/as‑built) và `docs/04_rag_workflow.mmd` (target). Mục tiêu là chỉ ra khoảng cách, đề xuất cải thiện, và đánh giá tác động hiệu suất nếu nâng lên theo target.

---

**1. Tóm tắt khác biệt nhanh**

| Khu vực | Current (as‑built) | Target (mong muốn) | Khoảng cách chính |
| --- | --- | --- | --- |
| Crawl | LinkedIn qua `linkedin_jobs_jd.py` | LinkedIn + Seek + Apify + `scraper.py` | Thiếu multi‑source và parser hợp nhất |
| Embedding | `job_text_embeddings` | Thêm `vector_index` hợp nhất | Chưa có index chung |
| RAG Query | Chưa có endpoint | Query processor, intent, routing, top‑k | Chưa có pipeline RAG |
| Feedback | Không có feedback loop | Validator + feedback + human review | Thiếu vòng lặp feedback |
| Rewrite | Heuristic context + local LLM | Gate Valid/Partial/Invalid + rerank | Thiếu gate nâng cao + rerank |
| Observability | Log cơ bản | Benchmark + tuning + alerts | Thiếu benchmark và tuning |

---

**2. So sánh chi tiết theo luồng**

**2.1 Crawl + ETL**
1. Current chỉ có luồng LinkedIn, không có Seek/Apify.
2. Target yêu cầu parser hợp nhất và nhiều nguồn dữ liệu.
3. Target có bước “borderline rerank” để xử lý case khó, current chưa có.

**2.2 Retrieval + RAG**
1. Current chỉ lưu embeddings trong `job_text_embeddings` và `learning_question_chunks`.
2. Target dùng `vector_index` hợp nhất để làm retrieval cho nhiều luồng.
3. Target có query processor, intent classifier, routing decision, và RAG answer generator, current chưa có.
4. Target có validator và feedback loop để cập nhật index, current chưa có.

**2.3 CV Rewrite**
1. Current dùng `_select_relevant_jd_context` và `_select_relevant_cv_context`, sau đó gọi local LLM gateway.
2. Target mô tả gate rõ ràng theo Valid/Partial/Invalid và cơ chế rerank.
3. Target gắn output với loop fit evaluation và feedback, current chủ yếu là log và lưu artifacts.

**2.4 Observability**
1. Current chủ yếu là log backend và log enrichment.
2. Target có benchmark runner, tuning thresholds, và alerts.

---

**3. Nếu nâng theo target thì hiệu suất có tăng không?**

**Kết luận ngắn**
1. Hiệu suất về chất lượng câu trả lời và độ ổn định có thể tăng.
2. Hiệu suất về tốc độ tổng thể có thể giảm nếu không có caching và giới hạn tải.
3. Tác động thực tế phụ thuộc vào tài nguyên máy và tần suất chạy.

**Tác động tích cực dự kiến**
1. `vector_index` hợp nhất giúp retrieval nhất quán hơn và giảm trùng lặp embeddings giữa các luồng.
2. Routing decision cho phép tránh gọi LLM khi retrieval đủ tốt, giảm chi phí và độ trễ.
3. Feedback loop giúp cải thiện dần chất lượng, giảm lỗi lặp lại theo thời gian.
4. Gate Valid/Partial/Invalid giúp giảm output “rác”, tăng tính ổn định.

**Chi phí và rủi ro hiệu suất**
1. Top‑k retrieval và scoring tạo thêm latency cho mỗi query.
2. Xây dựng và đồng bộ `vector_index` tăng IO và chi phí lưu trữ.
3. Rerank và validator tăng số lần gọi LLM, làm chậm nếu model local yếu.
4. Human review queue cần quy trình vận hành, nếu thiếu có thể gây “tắc”.

**Tóm lại**
1. Nếu mục tiêu là chất lượng và khả năng mở rộng, target tốt hơn.
2. Nếu mục tiêu là tốc độ và đơn giản, current phù hợp hơn.
3. Phải có caching, giới hạn tần suất, và batch schedule để tránh quá tải.

---

**4. Việc cần cải thiện để tiến gần target**

**Ưu tiên cao (tăng chất lượng nhưng chi phí thấp)**
1. Tạo `vector_index` hợp nhất dạng bảng hoặc view, đồng bộ từ `job_text_embeddings` và `learning_question_chunks`.
2. Thêm endpoint retrieval đơn giản “top‑k search” để kiểm thử RAG mà không thay đổi toàn bộ pipeline.
3. Gắn cờ “planned/not implemented” trong sơ đồ target để tránh hiểu nhầm.

**Ưu tiên trung bình (có thêm chi phí)**
1. Thêm routing decision tối thiểu dựa vào similarity threshold.
2. Thêm validator cho output RAG và lưu feedback cơ bản.
3. Thêm caching cho embedding và retrieval.

**Ưu tiên thấp (phức tạp, cần nguồn lực)**
1. Human review queue với UI duyệt và audit trail.
2. Benchmark runner và tuning dashboard.
3. Multi‑source crawl (Seek, Apify) với parser hợp nhất.

---

**5. Gợi ý cách đọc so sánh**
1. Đọc `docs/04_rag_workflow_current.mmd` để hiểu “cái đang chạy”.
2. Đọc `docs/04_rag_workflow.mmd` để hiểu “đích muốn tới”.
3. Đọc tài liệu này để quyết định ưu tiên cải thiện theo hiệu suất và nguồn lực.
