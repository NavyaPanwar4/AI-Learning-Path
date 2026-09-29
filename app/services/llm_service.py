import json
import re
import requests
from typing import Any, Dict, Optional

from app.utils.config import settings
from app.utils.logger import logger


class LLMService:
    """LLM-backed content generation with local Ollama support."""

    def __init__(self):
        self.groq_url = "https://api.groq.com/openai/v1/chat/completions"
        self.groq_api_key = getattr(settings, "GROQ_API_KEY", "")
        self.model = getattr(settings, "GROQ_MODEL", "")
        self.hf_model = getattr(settings, "HF_FALLBACK_MODEL", "")

        self.ollama_url = getattr(
            settings,
            "OLLAMA_URL",
            "http://localhost:11434/api/chat",
        )
        self.ollama_model = getattr(
            settings,
            "OLLAMA_MODEL",
            "qwen3:8b",
        )
        self.ollama_chat_model = getattr(
            settings,
            "OLLAMA_CHAT_MODEL",
            "qwen3:1.7b",
        )

    # ------------------------------------------------------------------
    # JSON utilities
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_json(response_text: str) -> Optional[Dict[str, Any]]:
        """Extract a JSON object from an LLM response."""

        if not response_text:
            return None

        cleaned = response_text.strip()

        # Remove markdown code fences if the model still returns them.
        fenced = re.search(
            r"```(?:json)?\s*(\{.*?\})\s*```",
            cleaned,
            re.DOTALL,
        )

        candidate = (
            fenced.group(1)
            if fenced
            else cleaned
        )

        try:
            parsed = json.loads(candidate)

            if isinstance(parsed, dict):
                return parsed

        except json.JSONDecodeError:
            pass

        # Try finding the outermost JSON object.
        start = candidate.find("{")
        end = candidate.rfind("}")

        if start == -1 or end == -1 or end <= start:
            return None

        try:
            parsed = json.loads(
                candidate[start:end + 1]
            )

            if isinstance(parsed, dict):
                return parsed

        except json.JSONDecodeError:
            pass

        return None

    # ------------------------------------------------------------------
    # Ollama
    # ------------------------------------------------------------------

    def _call_ollama(
        self,
        prompt: str,
        json_mode: bool = False,
        system_prompt: Optional[str] = None,
        history: Optional[list] = None,
        model: Optional[str] = None,
    ) -> Optional[str]:
        """Call the local Ollama model. Pass `model` to override the default
        (e.g. a smaller/faster model for chat vs. structured generation)."""

        messages = [
            {
                "role": "system",
                "content": system_prompt or (
                    "You are an expert learning-path architect. "
                    "Produce accurate, practical and structured "
                    "learning plans. Follow the requested output "
                    "format exactly."
                ),
            },
        ]

        if history:
            messages.extend(history)

        messages.append({
            "role": "user",
            "content": prompt,
        })

        payload = {
            "model": model or self.ollama_model,
            "messages": messages,
            "stream": False,
            "options": {
                "temperature": 0.1,
            },
        }

        # Ollama supports structured JSON output through this field.
        if json_mode:
            payload["format"] = "json"

        try:
            logger.info(
                "Calling local Ollama model %s",
                model or self.ollama_model,
            )

            response = requests.post(
                self.ollama_url,
                json=payload,
                timeout=300,
            )

            if response.ok:
                data = response.json()

                return (
                    data.get("message", {})
                    .get("content", "")
                )

            logger.error(
                "Ollama API error: %s - %s",
                response.status_code,
                response.text,
            )

        except requests.exceptions.RequestException as exc:
            logger.error(
                "Ollama connection error: %s",
                exc,
            )

        return None

    # ------------------------------------------------------------------
    # Chat (AI tutor)
    # ------------------------------------------------------------------

    def chat(
        self,
        system_prompt: str,
        history: list,
        user_message: str,
    ) -> str:
        """Free-text chat turn through the local Qwen3/Ollama model, given a
        system prompt built from the learner's live context and their recent
        message history. Not JSON mode — this is conversational text."""

        reply = self._call_ollama(
            user_message,
            json_mode=False,
            system_prompt=system_prompt,
            history=history,
            model=self.ollama_chat_model,
        )

        return reply or (
            "Sorry, I'm having trouble reaching the tutor model right now. "
            "Please try again in a moment."
        )

    # ------------------------------------------------------------------
    # Groq fallback
    # ------------------------------------------------------------------

    def _call_groq(
        self,
        prompt: str,
    ) -> Optional[str]:

        if not self.groq_api_key:
            return None

        payload = {
            "model": self.model,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "You produce accurate learning content. "
                        "Follow the requested output format exactly."
                    ),
                },
                {
                    "role": "user",
                    "content": prompt,
                },
            ],
            "temperature": 0.2,
            "max_completion_tokens": 4096,
            "reasoning_effort": "medium",
        }

        try:
            logger.info(
                "Calling Groq model %s",
                self.model,
            )

            response = requests.post(
                self.groq_url,
                headers={
                    "Authorization": (
                        f"Bearer {self.groq_api_key}"
                    ),
                    "Content-Type": "application/json",
                },
                json=payload,
                timeout=settings.GROQ_TIMEOUT_SECONDS,
            )

            if response.ok:
                return (
                    response.json()
                    .get("choices", [{}])[0]
                    .get("message", {})
                    .get("content", "")
                )

            logger.error(
                "Groq API error: %s - %s",
                response.status_code,
                response.text,
            )

        except requests.exceptions.RequestException as exc:
            logger.error(
                "Groq connection error: %s",
                exc,
            )

        return None

    # ------------------------------------------------------------------
    # Hugging Face fallback
    # ------------------------------------------------------------------

    def _call_huggingface(
        self,
        prompt: str,
    ) -> Optional[str]:
        """Use Hugging Face only when explicitly enabled."""

        if not getattr(
            settings,
            "ENABLE_HF_FALLBACK",
            False,
        ):
            return None

        logger.warning(
            "Using explicitly enabled Hugging Face fallback: %s",
            self.hf_model,
        )

        try:
            from transformers import pipeline

            generator = pipeline(
                "text-generation",
                model=self.hf_model,
                device_map="auto",
            )

            result = generator(
                prompt,
                max_new_tokens=512,
                num_return_sequences=1,
            )

            return result[0]["generated_text"][
                len(prompt):
            ]

        except Exception as exc:
            logger.error(
                "Hugging Face fallback failed: %s",
                exc,
            )

        return None

    # ------------------------------------------------------------------
    # Generic JSON generation
    # ------------------------------------------------------------------

    def _generate_json(
        self,
        prompt: str,
        retries: int = 1,
    ) -> Dict[str, Any]:
        """
        Generate JSON using Ollama's native JSON mode.

        The previous implementation regenerated the entire large
        response up to three times. That was extremely expensive
        locally. We now use JSON mode and only retry once if necessary.
        """

        response_text = self._call_ollama(
            prompt,
            json_mode=True,
        )

        parsed = self._extract_json(
            response_text or ""
        )

        if parsed is not None:
            return parsed

        logger.warning(
            "Ollama returned unusable JSON. "
            "Attempting one repair generation."
        )

        if retries > 0:
            repair_prompt = f"""
Return ONLY valid JSON.

The previous response was invalid or could not be parsed.

Re-create the requested output while following the JSON structure
exactly.

Do not use Markdown.
Do not include explanations outside JSON.

Original task:

{prompt}
"""

            response_text = self._call_ollama(
                repair_prompt,
                json_mode=True,
            )

            parsed = self._extract_json(
                response_text or ""
            )

            if parsed is not None:
                return parsed

        # Only use cloud fallbacks if they are configured.
        response_text = self._call_groq(prompt)

        parsed = self._extract_json(
            response_text or ""
        )

        if parsed is not None:
            return parsed

        response_text = self._call_huggingface(
            prompt
        )

        parsed = self._extract_json(
            response_text or ""
        )

        return parsed or {}

    # ------------------------------------------------------------------
    # Skill extraction
    # ------------------------------------------------------------------

    def extract_skills(
        self,
        text: str,
    ) -> Dict[str, Any]:

        prompt = f"""
Extract only the technical skills the learner currently knows.

Do not extract:
- goals
- desired skills
- job titles
- vague interests
- technologies merely mentioned as examples

Return:

{{
  "extracted_skills": [
    {{
      "skill_name": "Python",
      "confidence": 0.95
    }}
  ]
}}

Learner text:

{text}
"""

        result = self._generate_json(
            prompt,
            retries=1,
        )

        return {
            "extracted_skills": result.get(
                "extracted_skills",
                [],
            )
        }

    # ------------------------------------------------------------------
    # Roadmap generation
    # ------------------------------------------------------------------

    def generate_roadmap(
        self,
        context: dict,
    ) -> Dict[str, Any]:

        missing_skills = context.get(
            "missing_skills",
            [],
        )

        possessed_skills = context.get(
            "possessed_skills",
            [],
        )

        verified_resources = context.get(
            "verified_live_resources",
            [],
        )

        # Keep the resource context compact.
        #
        # The search service already ranks resources, so Qwen3 does not
        # need to process a huge number of candidates.
        compact_resources = []

        for resource in verified_resources[:20]:
            compact_resources.append(
                {
                    "title": resource.get(
                        "title",
                        "",
                    ),
                    "url": resource.get(
                        "url",
                        "",
                    ),
                    "type": resource.get(
                        "type",
                        "article",
                    ),
                    "skill": resource.get(
                        "skill",
                        "",
                    ),
                    "source": resource.get(
                        "source",
                        "",
                    ),
                    "quality_score": resource.get(
                        "quality_score",
                        0,
                    ),
                }
            )

        prompt = f"""
Create a complete learning roadmap.

Return ONLY valid JSON using this structure:

{{
  "phases": [
    {{
      "title": "Phase title",
      "duration": "2 weeks",
      "skills": ["topic 1", "topic 2"],
      "resources": [
        {{
          "title": "Resource title",
          "url": "https://...",
          "type": "documentation"
        }}
      ],
      "projects": [
        {{
          "title": "Project title",
          "description": "What the learner builds"
        }}
      ]
    }}
  ]
}}

ROADMAP REQUIREMENTS:

1. Create AT LEAST 5 meaningful phases.

2. Cover ALL required skills:
{json.dumps(missing_skills, ensure_ascii=False)}

3. Progress from foundational concepts to advanced concepts
   and practical projects.

4. Do not spend an entire phase teaching skills the learner
   already knows:
{json.dumps(possessed_skills, ensure_ascii=False)}

5. Each phase should contain:
   - a focused title
   - realistic duration
   - 2-6 related skills/topics
   - relevant resources when available
   - a practical project

6. Projects must become progressively more difficult.

7. Do not add unrelated technologies merely to increase
   the number of phases.

8. For a broad goal, use 5-7 phases when appropriate.
   If more phases are genuinely necessary for complete
   coverage, use more than 7.

RESOURCE RULES:

Only use URLs from the VERIFIED RESOURCE LIST below.

Never invent a URL.

Never modify a supplied URL.

Never use:
- Reddit
- Stack Overflow questions
- Quora
- forums
- discussion threads
- social-media posts
- generic search pages
- unrelated blogs
- opinion/discussion pages

Prefer:
- official documentation
- structured courses
- authoritative tutorials
- established educational platforms
- verified instructional videos

Do not repeat the same resource unnecessarily.

A resource must actually teach the topic in that phase.

VERIFIED RESOURCE LIST:

{json.dumps(compact_resources, ensure_ascii=False)}

LEARNER:

Goal:
{context.get("goal_skill_name", "Unknown")}

Experience:
{context.get("experience_level", "beginner")}

Hours per week:
{context.get("available_hours_per_week", 10)}

Learning style:
{context.get("learning_style", "visual")}

Already knows:
{json.dumps(possessed_skills, ensure_ascii=False)}

Needs to learn:
{json.dumps(missing_skills, ensure_ascii=False)}

Before returning the JSON, verify:

- at least 5 phases exist;
- every required skill is covered;
- phases progress logically;
- each phase has duration;
- resources match their phase;
- resources come only from the verified list;
- no discussion/forum resource is used;
- projects progressively increase in difficulty.

Return ONLY JSON.
"""

        result = self._generate_json(
            prompt,
            retries=1,
        )

        phases = result.get(
            "phases",
            [],
        )

        if not isinstance(
            phases,
            list,
        ):
            phases = []

        return {
            "phases": phases
        }

    # ------------------------------------------------------------------
    # Remedial phase generation (adaptive loop)
    # ------------------------------------------------------------------

    def generate_remedial_phase(self, context: dict) -> Dict[str, Any]:
        """Generate ONE focused review phase targeting specific weak skills,
        to be inserted into an existing roadmap when quiz performance shows
        the learner is struggling. Same JSON shape as a normal roadmap
        phase, so it can be dropped straight into the phases list."""

        weak_skills = context.get("weak_skills", [])
        compact_resources = []
        for resource in context.get("verified_live_resources", [])[:12]:
            compact_resources.append({
                "title": resource.get("title", ""),
                "url": resource.get("url", ""),
                "type": resource.get("type", "article"),
            })

        prompt = f"""
The learner is struggling with specific skills inside an existing learning
roadmap. Create ONE short, focused review phase to help them before they
continue.

Return ONLY valid JSON using this structure:

{{
  "title": "Phase title",
  "duration": "3-5 days",
  "skills": {json.dumps(weak_skills, ensure_ascii=False)},
  "resources": [
    {{ "title": "Resource title", "url": "https://...", "type": "documentation" }}
  ],
  "projects": [
    {{ "title": "Project title", "description": "A small, targeted exercise" }}
  ]
}}

CONTEXT:

The learner scored {context.get("score_pct", "a low score")}% on a quiz
covering: {json.dumps(context.get("phase_skills", weak_skills), ensure_ascii=False)}

The specific skills they are weak in are:
{json.dumps(weak_skills, ensure_ascii=False)}

Learner experience level: {context.get("experience_level", "beginner")}
Learning style: {context.get("learning_style", "visual")}

REQUIREMENTS:

1. Title should clearly signal this is a quick review/reinforcement phase
   (e.g. "Review: X" or "Strengthening Y"), not a brand-new topic.
2. Keep it short — this bridges a gap, it is not a full phase.
3. Cover ONLY the weak skills listed above, nothing else.
4. Only use URLs from this verified resource list — never invent one:
{json.dumps(compact_resources, ensure_ascii=False)}
5. Include exactly one small, targeted practice project.

Return ONLY JSON.
"""

        result = self._generate_json(prompt, retries=1)

        return {
            "title": result.get("title") or f"Review: {', '.join(weak_skills[:2]) or 'Weak Areas'}",
            "duration": result.get("duration") or "3-5 days",
            "skills": weak_skills,
            "resources": result.get("resources") if isinstance(result.get("resources"), list) else [],
            "projects": result.get("projects") if isinstance(result.get("projects"), list) else [],
        }

    # ------------------------------------------------------------------
    # Study notes
    # ------------------------------------------------------------------

    def generate_study_notes(
        self,
        *,
        phase_title: str,
        skills: list[str],
        duration: str,
        experience_level: str,
    ) -> Dict[str, Any]:

        prompt = f"""
Create clear study notes for this learning phase.

Return ONLY valid JSON:

{{
  "title": "Study notes",
  "overview": "Short overview",
  "learning_objectives": [],
  "key_concepts": [
    {{
      "term": "term",
      "explanation": "explanation"
    }}
  ],
  "study_plan": [
    {{
      "step": "Step 1",
      "action": "Specific action"
    }}
  ],
  "practice_prompts": [],
  "quick_recap": []
}}

Requirements:

- 3-5 learning objectives.
- 4-7 key concepts.
- 4-6 study steps.
- 3 practice prompts.
- 3-5 recap points.
- Appropriate for a {experience_level} learner.
- Practical and concise.
- No external URLs.
- No Markdown.

Phase:
{phase_title}

Duration:
{duration}

Skills:
{", ".join(skills) or "General foundations"}
"""

        return self._generate_json(
            prompt,
            retries=1,
        )

    # ------------------------------------------------------------------
    # Learner summary
    # ------------------------------------------------------------------

    def generate_learner_summary(
        self,
        context: dict,
    ) -> str:

        prompt = f"""
Write a short learner profile summary.

Return ONLY:

{{
  "summary": "2-3 sentence summary"
}}

Use only the supplied information.

Experience:
{context.get("experience_level", "beginner")}

Learning style:
{context.get("learning_style", "visual")}

Goal:
{context.get("goal_name", "Not set")}

Strong skills:
{", ".join(context.get("strong_skills", [])) or "None yet"}

Needs improvement:
{", ".join(context.get("needs_improvement", [])) or "None flagged"}
"""

        result = self._generate_json(
            prompt,
            retries=1,
        )

        return result.get(
            "summary",
            "",
        ) or ""

    # ------------------------------------------------------------------
    # Quiz generation
    # ------------------------------------------------------------------

    def generate_quiz(
        self,
        phase_title: str,
        skills: list,
        difficulty: str = "beginner",
    ) -> list:

        prompt = f"""
Create exactly 4 multiple-choice questions.

Return ONLY:

{{
  "questions": [
    {{
      "question": "...",
      "options": ["A", "B", "C", "D"],
      "correct_index": 0,
      "explanation": "..."
    }}
  ]
}}

Requirements:

- Exactly 4 questions.
- Exactly 4 options each.
- correct_index is 0-3.
- Test understanding rather than trivia.
- Questions must relate to the listed skills.
- Appropriate for {difficulty}.
- Keep explanations short.

Phase:
{phase_title}

Skills:
{", ".join(skills) or "General foundations"}
"""

        result = self._generate_json(
            prompt,
            retries=1,
        )

        questions = result.get(
            "questions",
            [],
        )

        if not isinstance(
            questions,
            list,
        ):
            return []

        valid_questions = []

        for question in questions:

            if not isinstance(
                question,
                dict,
            ):
                continue

            options = question.get(
                "options"
            )

            correct_index = question.get(
                "correct_index"
            )

            if not question.get(
                "question"
            ):
                continue

            if not isinstance(
                options,
                list,
            ) or len(options) != 4:
                continue

            if not isinstance(
                correct_index,
                int,
            ):
                continue

            if not 0 <= correct_index < 4:
                continue

            valid_questions.append(
                question
            )

        return valid_questions


llm_service = LLMService()