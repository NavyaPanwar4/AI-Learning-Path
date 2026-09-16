import json
import re
import requests
from typing import Any, Dict, Optional

from app.utils.config import settings
from app.utils.logger import logger


class LLMService:
    """Groq-backed content generation with an opt-in local fallback."""

    def __init__(self):
        self.groq_url = "https://api.groq.com/openai/v1/chat/completions"
        self.groq_api_key = settings.GROQ_API_KEY
        self.model = settings.GROQ_MODEL
        self.hf_model = settings.HF_FALLBACK_MODEL

    @staticmethod
    def _extract_json(response_text: str) -> Optional[Dict[str, Any]]:
        """Recover a JSON object even if a model wraps it in a Markdown fence."""
        if not response_text:
            return None
        cleaned = response_text.strip()
        fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", cleaned, re.DOTALL)
        candidate = fenced.group(1) if fenced else cleaned
        try:
            parsed = json.loads(candidate)
            return parsed if isinstance(parsed, dict) else None
        except json.JSONDecodeError:
            start, end = candidate.find("{"), candidate.rfind("}")
            if start == -1 or end == -1 or end <= start:
                return None
            try:
                parsed = json.loads(candidate[start : end + 1])
                return parsed if isinstance(parsed, dict) else None
            except json.JSONDecodeError:
                return None

    def _call_groq(self, prompt: str) -> Optional[str]:
        if not self.groq_api_key:
            logger.error("GROQ_API_KEY is not configured.")
            return None

        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": "You produce accurate learning content. Follow the requested output format exactly."},
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.2,
            "max_completion_tokens": 4096,
            # GPT-OSS can spend the whole completion budget on hidden reasoning.
            # Low effort keeps structured learning responses fast and leaves room for content.
            "reasoning_effort": "medium",
        }
        try:
            logger.info("Calling Groq model %s", self.model)
            response = requests.post(
                self.groq_url,
                headers={"Authorization": f"Bearer {self.groq_api_key}", "Content-Type": "application/json"},
                json=payload,
                timeout=settings.GROQ_TIMEOUT_SECONDS,
            )
            if response.ok:
                return response.json().get("choices", [{}])[0].get("message", {}).get("content", "")
            logger.error("Groq API error: %s - %s", response.status_code, response.text)
        except requests.exceptions.RequestException as exc:
            logger.error("Groq connection error: %s", exc)
        return None

    def _call_huggingface(self, prompt: str) -> Optional[str]:
        """Never download a local model unless explicitly enabled in the environment."""
        if not settings.ENABLE_HF_FALLBACK:
            return None
        logger.warning("Using explicitly enabled Hugging Face fallback: %s", self.hf_model)
        try:
            from transformers import pipeline
            generator = pipeline("text-generation", model=self.hf_model, device_map="auto")
            result = generator(prompt, max_new_tokens=512, num_return_sequences=1)
            return result[0]["generated_text"][len(prompt) :]
        except Exception as exc:
            logger.error("Hugging Face fallback failed: %s", exc)
            return None

    def _generate_json(self, prompt: str, retries: int = 2) -> Dict[str, Any]:
        for attempt in range(retries):
            response_text = self._call_groq(prompt) or self._call_huggingface(prompt)
            parsed = self._extract_json(response_text or "")
            if parsed is not None:
                return parsed
            logger.warning("LLM did not return usable JSON (attempt %s/%s).", attempt + 1, retries)
        return {}

    def extract_skills(self, text: str) -> Dict[str, Any]:
        prompt = f'''Read the text and extract only skills the learner currently knows.
Return only one valid JSON object with exactly this shape:
{{"extracted_skills":[{{"skill_name":"Python","confidence":0.95}}]}}
Text: {text}'''
        result = self._generate_json(prompt)
        return {"extracted_skills": result.get("extracted_skills", [])}

    def generate_roadmap(self, context: dict) -> Dict[str, Any]:
        prompt = f'''Create a personalized learning roadmap. Return only one valid JSON object, with no Markdown or commentary, matching this shape:
{{"phases":[{{"title":"Phase name","duration":"2 weeks","skills":["skill"],"resources":[{{"title":"Resource title","url":"https://example.com","type":"article"}}],"projects":[{{"title":"Project name","description":"Project details"}}]}}]}}

Requirements:
- Create 3 to 6 progressive phases, each named for what it actually covers (not "Phase 1", "Phase 2").
- Every phase must tie directly to specific items in "Needs to learn" below — do not include generic filler phases (e.g. a vague "Fundamentals" phase) that don't map to a listed skill.
- Include 2 to 4 useful resources per phase, prioritising reputable official documentation, respected educational publishers, or well-known learning platforms.
- The "Verified live resources" list below were fetched via live web search moments ago and confirmed reachable — each one is tagged with the specific skill it was searched for ("skill" field). Only place a resource in a phase that actually covers that tagged skill; never copy the same resource, or the same set of resources, into more than one phase unless those phases genuinely share that exact skill. "Reachable" is also not the same as "good": skip any tagged resource that looks like a forum thread, social media post, opinion piece, or off-topic result, even though it's in the list.
- When you use a resource from that list, output only "title", "url", and "type" for it — drop the "skill" and "content" fields, they're for your reference only.
- If you need a resource beyond that list, only include a URL you are highly confident is real and currently live (a well-known top-level page, e.g. an official docs homepage, not a specific article or blog post you're guessing exists); every resource is checked for reachability afterward and dropped if it's dead, so it is always safer to omit a resource than invent a link.
- Every phase's resources array should be distinct from every other phase's — do not repeat the same title/url pair (or the same whole set) across multiple phases, whether it came from the verified list or your own knowledge.
- Use resource type "article", "documentation", "course", or "video".
- Design 1-2 original, practical projects per phase yourself, specific enough that a learner could start building immediately — sized to the phase's skills and the learner's experience level, never just a skill name restated as a project.
- Do not generate study notes yet.

Learner context:
- Experience level: {context.get("experience_level")}
- Hours per week: {context.get("available_hours_per_week")}
- Learning style: {context.get("learning_style")}
- Goal: {context.get("goal_skill_name", "Unknown")}
- Already knows: {", ".join(context.get("possessed_skills", [])) or "None"}
- Needs to learn: {", ".join(context.get("missing_skills", [])) or "Not specified"}
- Verified live resources (fetched just now, confirmed reachable): {json.dumps(context.get("verified_live_resources", []))}'''
        result = self._generate_json(prompt)
        return result if isinstance(result.get("phases"), list) else {"phases": []}

    def generate_study_notes(self, *, phase_title: str, skills: list[str], duration: str, experience_level: str) -> Dict[str, Any]:
        prompt = f'''Create clear, original study notes for one learning-path phase. Return only one valid JSON object, with no Markdown fences, matching this exact shape:
{{"title":"Study notes: phase title","overview":"2-3 sentence overview","learning_objectives":["objective"],"key_concepts":[{{"term":"term","explanation":"plain-language explanation"}}],"study_plan":[{{"step":"Day or step label","action":"specific action"}}],"practice_prompts":["question or exercise"],"quick_recap":["short takeaway"]}}

Requirements:
- Write for a {experience_level} learner.
- Make explanations practical and concise.
- Include 3-5 objectives, 4-7 key concepts, a 4-6 step study plan, 3 practice prompts, and 3-5 recap points.
- Do not claim facts that require a current web search and do not use citations.

Phase: {phase_title}
Suggested duration: {duration}
Skills: {", ".join(skills) or "General foundations"}'''
        return self._generate_json(prompt)

    def generate_learner_summary(self, context: dict) -> str:
        """Short 2-3 sentence characterization of the learner for their
        profile dashboard, grounded only in their real data — no invented
        specifics."""
        prompt = f'''Write a short, encouraging 2-3 sentence summary characterizing this learner for their profile dashboard. Return only one valid JSON object, no Markdown, matching this shape:
{{"summary":"2-3 sentence summary"}}

Requirements:
- Second person ("You are...", "You prefer...").
- Base it only on the data given below — never invent specific facts, numbers, or skills not listed.
- Mention their experience level, learning style, and at most one strong skill and one improvement area if present.
- Keep it warm and motivating, not generic corporate-speak.

Learner data:
- Experience level: {context.get("experience_level", "beginner")}
- Learning style: {context.get("learning_style", "visual")}
- Current goal: {context.get("goal_name", "Not set")}
- Strong skills: {", ".join(context.get("strong_skills", [])) or "None yet"}
- Needs improvement: {", ".join(context.get("needs_improvement", [])) or "None flagged"}'''
        result = self._generate_json(prompt)
        return result.get("summary", "") or ""

    def generate_quiz(self, phase_title: str, skills: list, difficulty: str = "beginner") -> list:
        prompt = f'''Create a 4-question multiple choice quiz testing understanding of this learning phase. Return only one valid JSON object, no Markdown, matching this shape:
{{"questions":[{{"question":"...","options":["A","B","C","D"],"correct_index":0,"explanation":"..."}}]}}

Requirements:
- Exactly 4 questions, each with exactly 4 options.
- Test conceptual understanding relevant to the listed skills, not trivia — appropriate for a {difficulty} learner.
- correct_index is 0-based, pointing to the correct entry in "options".
- explanation is one short sentence on why that answer is correct.

Phase: {phase_title}
Skills covered: {", ".join(skills) or "General foundations"}'''
        result = self._generate_json(prompt)
        questions = result.get("questions", [])
        valid = [
            q for q in questions
            if isinstance(q, dict)
            and q.get("question")
            and isinstance(q.get("options"), list) and len(q["options"]) == 4
            and isinstance(q.get("correct_index"), int) and 0 <= q["correct_index"] < 4
        ]
        return valid

llm_service = LLMService()
