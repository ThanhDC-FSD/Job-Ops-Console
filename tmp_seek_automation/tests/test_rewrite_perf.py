from integrations.agent import LocalAgent
import os
import time

# Use fake response mode so tests run without a real gateway
os.environ['LLM_TEST_FAKE_RESP'] = 'Dear Hiring Manager,\n\nI am excited to apply...\n\nSincerely,'
os.environ['LLM_PROMPT_COMPRESSION'] = '1'

agent = LocalAgent('TestUser', model='test-model')

# Minimal sample inputs
job = {
    'title': 'Software Engineer',
    'companyProfile': {'name': 'Acme Co'},
    'content': {'sections': ['Build APIs with Python and FastAPI', 'Work on cloud integrations and deployments.']}
}
with open(os.path.join(os.path.dirname(__file__), '..', 'input', 'full_doc_stlye.txt'), 'r', encoding='utf-8', errors='ignore') as f:
    resume_text = f.read() if os.path.exists(f.name) else 'Experienced backend engineer with Python and cloud experience.'

start = time.time()
cover = agent.prepare_cover_letter(job, resume_text, convert_to_australian_language=True)
end = time.time()
print('Elapsed:', round(end - start, 3), 's')
print('Cover (truncated):', cover[:300])
