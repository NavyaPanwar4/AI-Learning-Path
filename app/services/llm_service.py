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
            "reasoning_effort": "low",
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
- Create 3 to 6 progressive phases.
- Include 2 to 4 useful resources per phase, prioritising reputable official documentation, respected educational publishers, or well-known learning platforms.
- Use resource type "article", "documentation", "course", or "video".
- Only include URLs you are confident are real; omit a resource rather than inventing a link.
- Do not generate study notes yet.

Learner context:
- Experience level: {context.get("experience_level")}
- Hours per week: {context.get("available_hours_per_week")}
- Learning style: {context.get("learning_style")}
- Goal: {context.get("goal_skill_name", "Unknown")}
- Already knows: {", ".join(context.get("possessed_skills", [])) or "None"}
- Needs to learn: {", ".join(context.get("missing_skills", [])) or "Not specified"}
- Available research resources: {json.dumps(context.get("resources", []))}
- Suggested projects: {json.dumps(context.get("projects", []))}'''
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


llm_service = LLMService()
