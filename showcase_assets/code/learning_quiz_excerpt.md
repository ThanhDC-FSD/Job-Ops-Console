# Learning Quiz And Knowledge Workflow Excerpt

This excerpt highlights the **learning subsystem** added to the same operator console: topic seeding, deterministic quiz generation, bilingual knowledge review, and persisted quiz history.

## API Surface

The learning router exposes a compact set of endpoints that support topics, quiz generation, submission, history, and knowledge review.

```python
def build_learning_router(learning: LearningService) -> APIRouter:
    router = APIRouter(prefix="/api", tags=["learning"])

    @router.get("/learning/topics")
    def learning_topics() -> dict:
        learning.ensure_seed_if_empty()
        return {"items": learning.list_topics()}

    @router.get("/learning/quiz")
    def learning_quiz(topic_key: str = Query(...), limit: int = Query(5, ge=1, le=20), lang: str = Query("en")) -> dict:
        return learning.get_quiz(topic_key=topic_key, limit=limit, lang=lang)

    @router.post("/learning/quiz/submit")
    def learning_quiz_submit(payload: LearningQuizSubmitPayload) -> dict:
        return learning.submit_quiz(
            topic_key=payload.topic_key,
            lang=payload.lang,
            items=[item.model_dump() for item in payload.items],
        )

    @router.get("/learning/knowledge")
    def learning_knowledge(topic_key: str = Query(...), limit: int = Query(20, ge=1, le=200), lang: str = Query("en")) -> dict:
        return learning.get_topic_knowledge(topic_key=topic_key, limit=limit, lang=lang)
```

Why this matters:

- the learning module is fully reachable from the same backend used by jobs and automation
- topics seed themselves when the database is empty
- quiz and knowledge endpoints stay separate so the frontend can keep review and testing modes distinct

## Service Logic

The service uses deterministic seeding for stable quiz selection and adds fallback explanations when published content is incomplete.

```python
def get_quiz(self, *, topic_key: str, limit: int = 5, lang: str = "en") -> dict[str, Any]:
    topic = self.repo.get_topic_by_key(topic_key)
    questions = self.repo.list_questions_by_topic(int(topic["id"]))
    seed = int(self._stable_hash(topic_key, str(limit))[:8], 16)
    rng = random.Random(seed)
    picked = list(questions)
    rng.shuffle(picked)
    picked = picked[: max(1, min(limit, len(picked)))]
    ...

def get_topic_knowledge(self, *, topic_key: str, limit: int = 20, lang: str = "en") -> dict[str, Any]:
    ...
    if not final_explanation_en and not final_explanation_vi:
        fallback_en, fallback_vi = fallback_service.build_domain_fallback(
            topic_key=topic.get("topic_key"),
            question_style=str(question.get("difficulty") or "general"),
        )
        ...
        explanation_source = "fallback"
```

Why this matters:

- quiz picks are reproducible instead of feeling random on every refresh
- the knowledge screen still stays useful even when author-provided explanations are incomplete
- local fallback behavior keeps the feature practical on weak, local-only setups

## Frontend Learning Tab

The frontend keeps quiz mode and knowledge mode in the same workspace while preserving topic and language selections.

```jsx
function LearningQuizTab({ t, lang }) {
  const [topicKey, setTopicKey] = useState('')
  const [quizLang, setQuizLang] = useState(lang || 'en')
  const [subTab, setSubTab] = useState('quiz')
  const [quiz, setQuiz] = useState([])
  const [history, setHistory] = useState([])
  const [knowledge, setKnowledge] = useState([])

  async function startQuiz() {
    setSubTab('quiz')
    if (!topicKey) return
    const res = await api.learningQuiz({ topic_key: topicKey, limit: 5, lang: quizLang })
    setQuiz(res.items || [])
    setAnswers({})
    setCurrentIdx(0)
  }

  async function loadKnowledge(force = false) {
    if (!topicKey) return
    const res = await api.learningKnowledge({ topic_key: topicKey, limit: 50, lang: quizLang })
    setKnowledge(res.items || [])
    setKnowledgeMeta({ topicKey, lang: quizLang })
  }
}
```

Why this matters:

- learning stays embedded in the operator console instead of becoming a disconnected tool
- bilingual topic review is handled by the same screen model
- the UI supports both immediate quiz flow and slower knowledge reference flow

## Submission And Results

Quiz submission persists history and returns detailed explanations for feedback.

```jsx
async function submitQuiz() {
  if (!topicKey || quiz.length === 0) return
  const payload = {
    topic_key: topicKey,
    lang: quizLang,
    items: quiz.map((item) => ({
      question_id: item.question_id,
      selected_answer_id: answers[item.question_id] || null,
    })),
  }
  const res = await api.submitLearningQuiz(payload)
  setResult(res)
  await reloadLearningData()
}
```

Why this matters:

- quiz history becomes part of the same measurable workflow as jobs and automation
- explanation-rich results make the feature valuable for review, not just scoring
- the console can support ongoing self-training without introducing extra infrastructure

Design patterns showcased:

- seeded content generation
- fallback enrichment
- bilingual content presentation
- feature integration inside a single local-first console
