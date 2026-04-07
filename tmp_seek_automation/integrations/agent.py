try:
    from meta_ai_api import MetaAI
except Exception:
    MetaAI = None
try:
    from dotenv import load_dotenv
except Exception:
    def load_dotenv():
        return None
try:
    from openai import OpenAI
except Exception:
    OpenAI = None
import logging
import os
import re
import requests
import json

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
)

class AIAgent:
    def __init__(self, name, model=""):
        if os.getenv("OPENAI_KEY"):
            self.agent = OpenAiAgent(name, model)
            return

        # Prefer local LLM gateway when configured
        if os.getenv("INTERNAL_LLM_SHARED_TOKEN") or os.getenv("LLM_GATEWAY_BASE_URL"):
            self.agent = LocalAgent(name, model)
            return

        self.agent = MetaAI(name)


class LocalAgent:
    def __init__(self, name, model):
        self.name = name
        self.model = model or os.getenv("LLM_UPSTREAM_MODEL", "gpt-4o-mini")
        self.base = (os.getenv("LLM_GATEWAY_BASE_URL") or "http://127.0.0.1:8101/v1").rstrip()
        self.token = os.getenv("INTERNAL_LLM_SHARED_TOKEN")

    def _gateway_url(self):
        base = self.base.rstrip("/")
        if base.endswith("/v1"):
            return f"{base}/chat/completions"
        return f"{base}/v1/chat/completions"

    def _call_gateway(self, system_content: str, user_content: str, temperature: float = 0.2):
        # Test mode: return a canned response to speed local testing without a gateway
        fake = os.getenv("LLM_TEST_FAKE_RESP")
        if fake:
            logging.info("LLM_TEST_FAKE_RESP detected; returning fake response")
            return str(fake)

        url = self._gateway_url()
        payload = {
            "model": self.model,
            "temperature": temperature,
            "messages": [
                {"role": "system", "content": system_content},
                {"role": "user", "content": user_content},
            ],
        }
        headers = {"Content-Type": "application/json"}
        if self.token:
            headers["X-Internal-LLM-Token"] = self.token
            # Some gateways expect an Authorization header as well
            try:
                headers["Authorization"] = f"Bearer {self.token}"
            except Exception:
                pass
        def _post_try(u, h):
            try:
                r = requests.post(u, headers=h, json=payload, timeout=120)
                return r
            except Exception as e:
                logging.debug('POST to %s failed: %s', u, e)
                return None

        resp = _post_try(url, headers)
        # If unauthorized, try sensible fallbacks to help debug local gateway/ollama setups
        if resp is not None and resp.status_code == 401:
            logging.warning('LLM gateway returned 401 for %s; attempting fallbacks', url)
            # 1) try without internal token header (maybe gateway expects Authorization only or none)
            headers_no_token = {k: v for k, v in headers.items() if k not in ('X-Internal-LLM-Token', 'Authorization')}
            resp = _post_try(url, headers_no_token) or resp
            if resp is not None and resp.status_code == 401:
                # 2) try upstream base URL if configured (some setups expose Ollama directly)
                upstream = os.getenv('LLM_UPSTREAM_BASE_URL')
                if upstream:
                    up = upstream.rstrip('/')
                    if up.endswith('/v1'):
                        up_url = f"{up}/chat/completions"
                    else:
                        up_url = f"{up}/v1/chat/completions"
                    logging.info('Attempting upstream fallback to %s', up_url)
                    resp = _post_try(up_url, headers_no_token) or resp

        if resp is None:
            raise RuntimeError('Failed to contact LLM endpoint (no response)')

        if not (200 <= resp.status_code < 300):
            try:
                body = resp.text
            except Exception:
                body = '<no body>'
            logging.error('LLM gateway error status=%s body=%s', resp.status_code, body)
            resp.raise_for_status()
        data = resp.json()
        try:
            content = data.get("choices", [])[0].get("message", {}).get("content", "")
        except Exception:
            content = ""
        return content or ""

    # ---- prompt compression helpers ----
    def _extract_top_keywords(self, text: str, k: int = 12) -> list[str]:
        tokens = re.findall(r"[a-zA-Z][a-zA-Z0-9+#.-]*", str(text or "").lower())
        stop = set(["the","and","for","with","from","that","this","you","your","our","are","have","has","will"])
        counts = {}
        for t in tokens:
            if len(t) < 3 or t in stop:
                continue
            counts[t] = counts.get(t, 0) + 1
        items = sorted(counts.items(), key=lambda x: -x[1])[:k]
        return [w for w, _ in items]

    def _extract_relevant_snippets(self, jd_text: str, resume_text: str, top_k: int = 6, snippet_chars: int = 300) -> str:
        jd_keywords = set(self._extract_top_keywords(jd_text, k=top_k * 2))
        lines = [l.strip() for l in str(resume_text or "").splitlines() if l.strip()]
        scored = []
        for line in lines:
            lw = line.lower()
            score = sum(1 for kw in jd_keywords if kw in lw)
            if score > 0:
                scored.append((score, line))
        scored.sort(key=lambda x: -x[0])
        snippets = []
        for _, line in scored[:top_k]:
            s = line
            if len(s) > snippet_chars:
                s = s[:snippet_chars].rsplit(' ', 1)[0] + '...'
            snippets.append(s)
        return "\n".join(snippets)

    def _compress_context(self, jd_text: str, resume_text: str) -> tuple[str, str]:
        # Returns (short_jd_summary, trimmed_resume_snippets)
        jd_tokens = self._extract_top_keywords(jd_text, k=20)
        jd_summary = "Keywords: " + ", ".join(jd_tokens[:12])
        resume_snips = self._extract_relevant_snippets(jd_text, resume_text, top_k=6, snippet_chars=300)
        return jd_summary, resume_snips

    def prepare_cover_letter(self, job_data, resume, convert_to_australian_language):
        job_content = job_data.get('content', {})
        job_description = job_content.get('sections', '')
        company_profile = job_data.get('companyProfile', {})
        company_name = company_profile.get('name', 'N/A')
        position = job_data.get('title', 'Unknown position')
        if company_name == 'N/A':
            company_name = 'Hiring Manager'

        australian_language = (
            "Adjust spelling to Australian English (e.g., optimise, customise, utilise instead of optimize, customize, utilize)."
            if convert_to_australian_language else ""
        )

        # Decide whether to compress the prompt to reduce token usage and latency
        compress_enabled = os.getenv("LLM_PROMPT_COMPRESSION", "1").lower() not in ("0", "false")
        raw_prompt = None
        if compress_enabled:
            try:
                jd_text = "\n".join(job_description) if isinstance(job_description, list) else str(job_description)
                jd_summary, resume_snips = self._compress_context(jd_text, resume)
                system = (
                    "You are a highly skilled, professional career writer. "
                    "Your task: produce a concise, targeted cover letter starting with a salutation and ending with a closing."
                )
                raw_prompt = (
                    f"Job title: {position}\nCompany: {company_name}\n"
                    f"{jd_summary}\n\nRelevant resume snippets:\n{resume_snips}\n\n"
                    "Write a professional cover letter of max 400 words. Start with a salutation and end with a closing."
                )
            except Exception:
                raw_prompt = None

        if not raw_prompt:
            # fallback to full prompt (less efficient)
            jd_text = "\n".join(job_description) if isinstance(job_description, list) else str(job_description)
            system = (
                "You are a highly skilled, professional career writer. "
                "Your sole task is to generate the complete cover letter text. "
                "Respond only with the final, polished cover letter text."
            )
            raw_prompt = (
                f"## Goal\nGenerate a professional cover letter for {position} at {company_name}.\n\n"
                f"Resume:\n{resume}\n\nJob description:\n{jd_text}\n\n"
                "Constraints: max 400 words, no placeholders, start with salutation, end with closing."
            )

        start_ts = __import__('time').time()
        content = self._call_gateway(system, raw_prompt)
        elapsed = __import__('time').time() - start_ts
        logging.info("prepare_cover_letter | model=%s chars_in=%d time_s=%.2f", self.model, len(raw_prompt or ""), elapsed)
        text = content.strip()
        if text.startswith("{"):
            try:
                obj = json.loads(text)
                if isinstance(obj, dict) and obj.get("cover_letter"):
                    text = str(obj.get("cover_letter"))
            except Exception:
                pass
        return text

    def review_coverletter(self, cover_letter_text, original_resume, original_job_description, adjustment_requests=""):
        prompt = f"""
            Verify and lightly adjust the cover letter text.\n
            [COVER_LETTER_TEXT]\n
            {cover_letter_text}\n
            [ORIGINAL_RESUME_TEXT]\n
            {original_resume}\n
            [ORIGINAL_JOB_DESCRIPTION_TEXT]\n
            {original_job_description}\n
            [ADJUSTMENT_REQUESTS]\n
            {adjustment_requests or 'No specific adjustments provided.'}
        """
        system = (
            "You are a professional editor and compliance specialist. "
            "Verify the cover letter against the resume and job description, then return only the adjusted cover letter text."
        )
        content = self._call_gateway(system, prompt)
        return content.strip()

    def evaluate_fit(self, job_data, resume_text):
        # Ask the LLM to score fit and provide evidence. Expect JSON output.
        job_content = job_data.get('content', {})
        job_description = '\n'.join(job_content.get('sections') or []) if job_content else ''
        position = job_data.get('title', '')
        company = job_data.get('companyProfile', {}).get('name', '')

        system = (
            "You are an expert hiring evaluator. Provide a JSON object with fields:"
            " total_score (0.0-1.0), domain_score (0.0-1.0), tech_score (0.0-1.0), evidence (array of strings), summary (short)."
        )

        user = (
            f"Evaluate how well the following resume matches the job.\nJob title: {position}\nCompany: {company}\n"
            "Job description:\n" + job_description + "\n\nResume:\n" + resume_text +
            "\n\nReturn ONLY a single valid JSON object with the required numeric scores and an array of short evidence statements."
        )

        try:
            content = self._call_gateway(system, user, temperature=0.2)
            text = content.strip()
            # write raw LLM eval to logs for diagnostics
            try:
                logs_dir = os.path.normpath(os.path.join(os.path.dirname(__file__), '..', 'logs'))
                os.makedirs(logs_dir, exist_ok=True)
                fname = os.path.join(logs_dir, f"llm_eval_{int(__import__('time').time())}.json")
                with open(fname, 'w', encoding='utf-8') as fh:
                    fh.write(text)
                logging.info("Wrote LLM eval raw output to %s", fname)
            except Exception:
                logging.debug("Failed to write llm eval log file", exc_info=True)
            if text.startswith('{'):
                obj = json.loads(text)
                # normalize numeric fields
                def _n(v):
                    try:
                        return float(v)
                    except Exception:
                        return 0.0
                return {
                    'total_score': max(0.0, min(1.0, _n(obj.get('total_score', obj.get('score', 0.0))))),
                    'domain_score': max(0.0, min(1.0, _n(obj.get('domain_score', 0.0)))),
                    'tech_score': max(0.0, min(1.0, _n(obj.get('tech_score', 0.0)))),
                    'evidence': obj.get('evidence') if isinstance(obj.get('evidence'), list) else [],
                    'summary': str(obj.get('summary') or '')
                }
        except Exception:
            pass

        # Fallback heuristic: simple token overlap ratio
        try:
            job_words = set(re.findall(r"\w+", job_description.lower()))
            resume_words = set(re.findall(r"\w+", resume_text.lower()))
            if not job_words:
                return {'total_score': 0.0, 'domain_score': 0.0, 'tech_score': 0.0, 'evidence': [], 'summary': 'no job description'}
            overlap = len(job_words & resume_words) / max(1, len(job_words))
            return {'total_score': float(overlap), 'domain_score': float(overlap), 'tech_score': float(overlap), 'evidence': [], 'summary': 'heuristic overlap'}
        except Exception:
            return {'total_score': 0.0, 'domain_score': 0.0, 'tech_score': 0.0, 'evidence': [], 'summary': 'fallback error'}


class OpenAiAgent:
    def __init__(self, name, model):
        self.client = OpenAI(api_key=os.getenv("OPENAI_KEY"))
        self.model = model
        self.name = name
    
    def prepare_cover_letter(self, job_data, resume, convert_to_australian_language):
        job_content = job_data.get('content', {})
        job_description = job_content.get('sections', '')
        
        company_profile = job_data.get('companyProfile', {})
        company_name = company_profile.get('name', 'N/A')
        
        position = job_data.get('title', 'Unknown position')
        if company_name == 'N/A':
            company_name = 'Hiring Manager'

        australian_language = (
            "Adjust spelling to Australian English (e.g., optimise, customise, utilise instead of optimize, customize, utilize)."
            if convert_to_australian_language else ""
        )

        prompt = f"""
            ## Optimized Prompt for Generating a Cover Letter

            ### Goal
            You are an expert career consultant and professional writer. Your task is to generate a 
            **highly targeted, compelling, and professional cover letter** based on the provided 
            **Resume** and **Job Description** below.

            ### Required Inputs (Context)
            1.  **[RESUME_TEXT]:**
                ---
                {resume}
                ---
            2.  **[JOB_DESCRIPTION_TEXT]:**
                ---
                {job_description}
                ---* 
            3. **Company to Address:** {company_name}
            4. **Position Applied For:** {position}
            5.  **Format and Content Constraint (CRITICAL):**
                * Your output **MUST NOT** contain *any* generic placeholders enclosed in square brackets 
                (e.g., `[Company Name]`, `[Position Title]`).
                * **DO NOT** generate any content *before* the salutation or *after* the closing.
    
                * **Specifically, you MUST NOT include:**
                    - The current date
                    - A sender's address, postcode, or contact information (this is on the resume)
                    - A recipient's address or postcode
    
                * The output must start *directly* with the salutation (e.g., "Dear Hiring Manager,").
                * The output must end *directly* with the closing (e.g., "Sincerely,"). **Do not add a name after the closing.**
            ---

            ### Constraints and Negative Prompting

            The generated cover letter **must strictly adhere** to the following rules:

            1.  **Skills Fabrication Constraint (CRITICAL):**
                * **NEVER** invent, fabricate, or include any skill, technology, experience, 
                accomplishment, or responsibility in the cover letter that is **not explicitly 
                mentioned** in the provided **[resume]**.
            2.  **Length and Structure Constraint:** The cover letter must be **no more than 400 words** and must follow a standard professional three-to-five-paragraph business letter format.
            3.  **Tone Constraint:** The tone must be professional, confident, and enthusiastic.
            4.  **Language Constraint:** {australian_language}

            ---

            ### Generation Step

            Follow this **two-step process** for your final output:

            #### **Step 1: Analysis and Skill Mapping (Internal Step)**
            Internally, create a list of 5-7 **key required skills** from the **[JOB_DESCRIPTION_TEXT]**. 
            Then, cross-reference this list with the **[RESUME_TEXT]** to identify 3-5 **matching skills** that can be used as evidence in the letter.

            #### **Step 2: Cover Letter Generation (Primary Output)**
            Generate the complete cover letter using all the context and adhering to all constraints.

            ---

            ### **FINAL RESPONSE FORMAT**

            The final output must strictly follow this structure:

            ```
            [The complete, generated cover letter text, with no extra sections or commentary]
            ```
            """

        response = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are a highly skilled, professional career writer. "
                        "Your sole task is to generate the complete cover letter text. "
                        "Respond *only* with the final, polished cover letter text. "
                        "Do not include any introductory remarks, commentary, explanations, "
                        "or any text other than the cover letter itself. "
                        "Adhere strictly to the requested structure and formatting rules."
                    )
                },
                {"role": "user", "content": prompt}
            ]
        )

        cover_text = response.choices[0].message.content.strip()
        print(cover_text)
        print("-"*50)
        final_coverletter = self.review_coverletter(cover_text, resume, job_description)
        print(final_coverletter)
        print(cover_text == final_coverletter)
        return final_coverletter.strip('```')

    def review_coverletter(self, cover_letter_text, original_resume, original_job_description, adjustment_requests=""):
        prompt = f"""
            ## Optimized Prompt for Cover Letter Verification and Small Adjustments

            ### Goal
            You are an expert editor and compliance officer. Your task is to **verify** the provided cover 
            letter text against the original constraints and then apply any requested **small, stylistic 
            adjustments** without changing the core factual evidence.

            ### Required Inputs (Context)
            1.  **[COVER_LETTER_TEXT]:** (The letter to be edited)
                ---
                {cover_letter_text}
                ---
            2.  **[ORIGINAL_RESUME_TEXT]:** (Used for re-verification)
                ---
                {original_resume}
                ---
            3.  **[ORIGINAL_JOB_DESCRIPTION_TEXT]:** (Used for context)
                ---
                {original_job_description}
                ---
            4.  **[ADJUSTMENT_REQUESTS]:**
                ---
                {adjustment_requests or "No specific adjustments provided. Focus only on verification and minor flow improvements."}
                ---

            ### Verification Constraints (CRITICAL)

            You **MUST** ensure the following rules are still strictly met in the final output:

            1.  **NO SKILLS FABRICATION:** The letter *cannot* contain any skill, experience, or claim that is not factually supported by the **[ORIGINAL_RESUME_TEXT]**.
            2.  **LENGTH/STRUCTURE:** The main cover letter body must remain **under 500 words** and follow a professional business letter structure.
            ---

            ### Adjustment Process
            
            1.  **Verification:** First, internally re-verify the **[COVER_LETTER_TEXT]** against the factual content of the **[ORIGINAL_RESUME_TEXT]**. If a factual error is found (a fabricated skill), **correct the error** by removing the fabricated statement.
            2.  **Refinement:** Apply any changes requested in the **[ADJUSTMENT_REQUESTS]** while respecting all constraints. If no specific requests are made, make only very minor, high-quality, flow-of-text improvements.
            3. **PLACEHOLDER REMOVAL (MANDATORY RULE):**
                - Your final output **MUST NOT** contain any square brackets (`[` or `]`).
                - If you find *any* text enclosed in square brackets (e.g., `[Date]`, `[Your Address]`, `[Company Name]`), 
                  you **must delete the placeholder text AND the brackets entirely.**
                - **Example Transformation:**
                    - ❌ **Input:** `[Date] \n [Your Address] \n [Postcode] \n \n Dear [Hiring Manager], \n I am applying for the role...`
                    - ✅ **Correct Output:** `\n \n Dear , \n I am applying for the role...`
            4.  **Final Output:** Produce the final, polished cover letter text.
            ---

            ### **FINAL RESPONSE FORMAT**

            Your final output must be **ONLY** the completely verified and adjusted cover letter. Do not include any commentary, analysis, or introductory text.

            ```
            [The complete, verified, and adjusted cover letter text]
            ```
            """
        
        response = self.client.chat.completions.create(
        model=self.model,
        messages=[
                {
                    "role": "system",
                    "content": (
                    "You are a professional editor and compliance specialist. "
                        "Your sole task is to verify and adjust the provided cover letter text. "
                        "Your response must ONLY be the final, verified, and adjusted cover letter. "
                        "Strictly adhere to all constraints, especially the 'NO SKILLS FABRICATION' rule."
                    )
                },
                {"role": "user", "content": prompt}
            ]
        )

        final_coverletter = response.choices[0].message.content.strip().replace('-', '')
        return final_coverletter

    def write_email_contents(self):
        email_prompt = f"""
            **Task:** Write a short, polite cold email to a recruiter.
            The email must mention that the resume and cover letter are attached.
            Do not include a subject line.

            **Required Output Format (Strictly follow this):**
            Dear Hiring Manager,
            [contents of email]
            Best Regards
            {self.name}
        """

        response = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are an AI assistant specialized in drafting concise, professional, "
                        "and polite cold emails for recruiters. Your *only* output must be the "
                        "email body text. Do not include a subject line, any introductory or "
                        "concluding commentary, or extra text of any kind. Strict adherence to "
                        "the provided email format is required."
                    )
                },
                {"role": "user", "content": email_prompt}
            ]
        )

        email_text = response.choices[0].message.content.strip()
        return email_text


class MetaAgent:
    def __init__(self, name):
        self.client = MetaAI()
        self.name = name
    
    def prepare_cover_letter(self, job_data, resume, convert_to_australian_language):
        job_description = job_data.get('content', '').get('sections', '')
        position = job_data.get('title', 'Unknown position')
        company_name = job_data.get('companyProfile', {}).get('name', 'Unknown company')

        australian_language = "be sure the adjust the output of this cover letter to austrlian type language for example convert 'ize' type words such as optimize, customize, utilize, etc to optimise, customise, utilise, etc"


        prompt = f"""
            Create a cover letter for the {position} position at {company_name}.
            Job description: {job_description}
            Based on my resume: {resume}
            {australian_language if convert_to_australian_language else ""}
            be sure to format this cover letter with dot points & line breaks to clearly outline sections/items as this text will be converted to a pdf file
            structure the cover letter as follows:
            Dear {company_name}
            contents of the email
            Best Regards
            {self.name}
            treat this as a final copy & only return the contents of the email
            """
        
        initial_cover = self.client.prompt(message=prompt, new_conversation=True)

        cleaned_letter = re.sub(rf".*?(Dear .*?Best Regards\n{self.name}\n).*", r"\1", initial_cover['message'], flags=re.DOTALL)
        return cleaned_letter

    def write_email_contents(self):
        email_content = self.client.prompt(message=f"""
            Now write the contents of the email, I have scraped these email of these recruiters so keep the cold email brief and to the point, I will also be attaching my resume and cover letter
            format the email in as follows & exclude a subject:
            Dear first name
            contents of email
            Best Regards
            {self.name}
        """)

        cleaned_email_content = re.sub(rf".*?(Dear .*?Best Regards\n{self.name}\n).*", r"\1", email_content['message'], flags=re.DOTALL)
        return cleaned_email_content
