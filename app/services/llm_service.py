import json
import re
import requests
from typing import Any, Dict, Optional

from app.utils.config import settings
from app.utils.logger import logger


# ----------------------------------------------------------------------
# Strict JSON schemas (Groq "structured outputs").
# Strict mode needs every property listed in "required" and
# additionalProperties false. Only basic keywords are used, because counts
# and ranges (e.g. exactly 4 options) are checked locally afterwards.
# ----------------------------------------------------------------------
def _obj(**props):
    return {"type": "object", "properties": props, "required": list(props), "additionalProperties": False}


_STR = {"type": "string"}
_RESOURCE = _obj(title=_STR, url=_STR, type=_STR)
_PROJECT = _obj(title=_STR, description=_STR)

SKILLS_SCHEMA = _obj(extracted_skills={"type": "array", "items": _obj(skill_name=_STR, confidence={"type": "number"})})
PLAN_ELABORATION_SCHEMA = _obj(phases={"type": "array", "items": _obj(
    index={"type": "integer"}, title=_STR, duration=_STR,
    skills={"type": "array", "items": _obj(id=_STR, name=_STR, action=_STR)},
    resources={"type": "array", "items": _RESOURCE},
    projects={"type": "array", "items": _PROJECT},
)})
ROADMAP_PROPOSAL_SCHEMA = _obj(phases={"type": "array", "items": _obj(
    index={"type": "integer"}, title=_STR, duration=_STR,
    skills={"type": "array", "items": _obj(id=_STR, name=_STR, action=_STR)},
    projects={"type": "array", "items": _PROJECT},
)})
REMEDIAL_SCHEMA = _obj(
    title=_STR, duration=_STR, skills={"type": "array", "items": _STR},
    resources={"type": "array", "items": _RESOURCE}, projects={"type": "array", "items": _PROJECT},
)
STUDY_NOTES_SCHEMA = _obj(
    title=_STR, overview=_STR,
    learning_objectives={"type": "array", "items": _STR},
    key_concepts={"type": "array", "items": _obj(term=_STR, explanation=_STR)},
    study_plan={"type": "array", "items": _obj(step=_STR, action=_STR)},
    practice_prompts={"type": "array", "items": _STR},
    quick_recap={"type": "array", "items": _STR},
)
SUMMARY_SCHEMA = _obj(summary=_STR)
QUIZ_SCHEMA = _obj(questions={"type": "array", "items": _obj(
    question=_STR, options={"type": "array", "items": _STR},
    correct_index={"type": "integer"}, explanation=_STR, skill=_STR,
)})


class LLMError(Exception):
    """A Groq failure the user can act on. ``str(exc)`` is safe to show.

    kind: not_configured | auth | rate_limit | timeout | connection |
          upstream | bad_request | bad_response
    status_code is the HTTP status this should become. Never 401, because the
    frontend logs the user out on 401.
    """

    _MESSAGES = {
        "not_configured": ("The AI service is not configured on the server (missing GROQ_API_KEY).", 503),
        "auth": ("The AI service rejected the server's API key. Please contact the administrator.", 503),
        "rate_limit": ("The AI service is rate-limited right now. Please wait a minute and try again.", 429),
        "timeout": ("The AI service took too long to respond. Please try again.", 504),
        "connection": ("Could not reach the AI service. Please try again shortly.", 503),
        "upstream": ("The AI service had an internal error. Please try again shortly.", 502),
        "bad_request": ("The AI service rejected the request. Please try again.", 502),
        "bad_response": ("The AI service returned an unusable response. Please try again.", 502),
    }

    def __init__(self, kind: str):
        message, status = self._MESSAGES.get(kind, self._MESSAGES["upstream"])
        super().__init__(message)
        self.kind = kind
        self.status_code = status

    @staticmethod
    def from_status(status: int) -> "LLMError":
        if status in (401, 403):
            return LLMError("auth")
        if status == 429:
            return LLMError("rate_limit")
        if status in (408, 504):
            return LLMError("timeout")
        if status >= 500:
            return LLMError("upstream")
        return LLMError("bad_request")


class LLMService:
    """LLM-backed content generation using Groq as the primary provider."""

    def __init__(self):
        self.groq_url = "https://api.groq.com/openai/v1/chat/completions"
        self.groq_api_key = getattr(settings, "GROQ_API_KEY", "")
        self.model = getattr(settings, "GROQ_MODEL", "openai/gpt-oss-120b")

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
    # Streaming chat (AI tutor)
    # ------------------------------------------------------------------

    def _stream_groq_chat(self, system_prompt: str, history: list, user_message: str):
        """Yield content deltas from Groq's OpenAI-compatible SSE stream."""
        if not self.groq_api_key:
            raise LLMError("not_configured")
        payload = {
            "model": self.model,
            "messages": ([{"role": "system", "content": system_prompt}]
                         + (history or []) + [{"role": "user", "content": user_message}]),
            "temperature": 0.2,
            "max_completion_tokens": settings.GROQ_CHAT_MAX_COMPLETION_TOKENS,
            "reasoning_effort": settings.GROQ_REASONING_EFFORT,
            "stream": True,
        }
        try:
            response = requests.post(
                self.groq_url,
                headers={"Authorization": f"Bearer {self.groq_api_key}", "Content-Type": "application/json"},
                json=payload,
                timeout=settings.GROQ_TIMEOUT_SECONDS,
                stream=True,
            )
        except requests.exceptions.Timeout:
            raise LLMError("timeout") from None
        except requests.exceptions.RequestException:
            raise LLMError("connection") from None
        response.encoding = "utf-8"
        try:
            if not response.ok:
                logger.error("Groq stream error: %s - %s", response.status_code, response.text[:500])
                raise LLMError.from_status(response.status_code)
            for raw_line in response.iter_lines(decode_unicode=True):
                if not raw_line:
                    continue
                line = raw_line.strip()
                if line.startswith("data:"):
                    line = line[5:].strip()
                if line == "[DONE]":
                    break
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    continue
                choices = record.get("choices") or []
                delta = (choices[0].get("delta") or {}).get("content") if choices else None
                if delta:
                    yield delta
        finally:
            response.close()

    def chat_stream(self, system_prompt: str, history: list, user_message: str):
        """Stream the tutor's answer from Groq."""
        emitted = False
        try:
            for chunk in self._stream_groq_chat(system_prompt, history, user_message):
                emitted = True
                yield chunk
        except LLMError:
            if emitted:
                raise RuntimeError("Tutor stream interrupted after partial output") from None
            raise
        except Exception as exc:
            logger.warning("Groq tutor stream failed: %s", exc)
            if emitted:
                raise RuntimeError("Tutor stream interrupted after partial output") from exc
            raise LLMError("connection") from None

        if not emitted:
            raise LLMError("bad_response")

    # ------------------------------------------------------------------
    # Chat (AI tutor)
    # ------------------------------------------------------------------

    def chat(
        self,
        system_prompt: str,
        history: list,
        user_message: str,
    ) -> str:
        """Generate a conversational tutor response using the configured Groq model."""

        reply = self._call_groq(
            user_message,
            json_mode=False,
            system_prompt=system_prompt,
            history=history,
            model=self.model,
            max_tokens=settings.GROQ_CHAT_MAX_COMPLETION_TOKENS,
        )
        return reply

    # ------------------------------------------------------------------
    # Groq primary provider
    # ------------------------------------------------------------------

    def _call_groq(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        history: Optional[list] = None,
        model: Optional[str] = None,
        temperature: Optional[float] = None,
        seed: Optional[int] = None,
        json_mode: bool = False,
        timeout_seconds: Optional[int] = None,
        schema: Optional[dict] = None,
        schema_name: str = "response",
        max_tokens: Optional[int] = None,
        reasoning_effort: Optional[str] = None,
        reasoning_format: Optional[str] = None,
    ) -> Optional[str]:
        """Call Groq's OpenAI-compatible chat-completions API.

        With ``json_mode`` and a ``schema``, Groq's strict structured outputs
        constrain the reply to that schema. Without a schema, the reply is
        free text that ``_generate_json`` validates and repairs locally.

        `json_mode=True` requests a valid JSON object from Groq, preserving the
        structured-output contract expected by roadmap, skill, and quiz code.
        The API key is read from environment-backed settings and is never logged.
        """
        if not self.groq_api_key:
            logger.error("GROQ_API_KEY is not configured; cannot call the LLM provider.")
            raise LLMError("not_configured")

        requested_model = model or self.model
        is_gpt_oss = requested_model.startswith("openai/gpt-oss")

        effective_system_prompt = system_prompt or (
            "You are an expert learning-path architect. "
            "Produce accurate, practical and structured learning plans. "
            "Follow the requested output format exactly."
        )
        if json_mode:
            # Keep the JSON-only contract explicit in the prompt. GPT-OSS can
            # occasionally trigger Groq's server-side JSON-object validator
            # with an empty failed_generation. For GPT-OSS, request normal text
            # and validate/repair JSON locally in _generate_json instead.
            effective_system_prompt += (
                "\n\nFor this request, return exactly one syntactically valid JSON object. "
                "Do not include Markdown fences, comments, or prose before or after the JSON."
            )

        payload = {
            "model": requested_model,
            "messages": (
                [{"role": "system", "content": effective_system_prompt}]
                + (history or [])
                + [{"role": "user", "content": prompt}]
            ),
            "temperature": 0.1 if temperature is None else temperature,
            "max_completion_tokens": max_tokens or settings.GROQ_MAX_COMPLETION_TOKENS,
        }
        if is_gpt_oss:
            # Only reasoning models accept this parameter; Groq rejects it (HTTP 400)
            # for non-reasoning models such as Llama.
            payload["reasoning_effort"] = reasoning_effort or settings.GROQ_REASONING_EFFORT
        elif requested_model.startswith("qwen/"):
            # Qwen3 on Groq: reasoning_effort is 'none' (non-thinking) or 'default'/levels; with JSON mode the
            # reasoning format must be 'hidden' or 'parsed' (the 'raw' default is rejected).
            payload["reasoning_effort"] = reasoning_effort or "none"
            payload["reasoning_format"] = reasoning_format or "hidden"
        if seed is not None:
            payload["seed"] = int(seed)
        if json_mode and schema:
            payload["response_format"] = {
                "type": "json_schema",
                "json_schema": {"name": schema_name, "strict": True, "schema": schema},
            }
            if is_gpt_oss:
                payload["include_reasoning"] = False
        elif json_mode:
            if is_gpt_oss:
                # GPT-OSS uses a separate reasoning field. Excluding it keeps
                # the completion content focused on the JSON expected by the
                # application's existing parser. This avoids a Groq-side
                # json_validate_failed response before local repair can run.
                payload["include_reasoning"] = False
            else:
                payload["response_format"] = {"type": "json_object"}

        try:
            logger.info("Calling Groq model %s (json_mode=%s)", payload["model"], json_mode)
            response = requests.post(
                self.groq_url,
                headers={
                    "Authorization": f"Bearer {self.groq_api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
                timeout=timeout_seconds or settings.GROQ_TIMEOUT_SECONDS,
            )
        except requests.exceptions.Timeout as exc:
            logger.error("Groq request timed out: %s", exc)
            raise LLMError("timeout") from None
        except requests.exceptions.RequestException as exc:
            logger.error("Groq connection error: %s", exc)
            raise LLMError("connection") from None

        if not response.ok:
            # The body is logged for the operator; it is never shown to the user.
            logger.error("Groq API error: %s - %s", response.status_code, response.text[:500])
            raise LLMError.from_status(response.status_code)

        try:
            choices = response.json().get("choices", [])
            content = choices[0].get("message", {}).get("content") if choices else None
            finish_reason = choices[0].get("finish_reason") if choices else None
        except (ValueError, TypeError, KeyError, IndexError, AttributeError) as exc:
            logger.error("Unexpected Groq response format: %s", exc)
            raise LLMError("bad_response") from None
        if json_mode and finish_reason == "length":
            logger.error("Groq output was cut off at the token limit; raise GROQ_MAX_COMPLETION_TOKENS.")
            raise LLMError("bad_response")
        if not isinstance(content, str) or not content.strip():
            logger.error("Groq returned an empty completion (finish_reason=%s).", finish_reason)
            raise LLMError("bad_response")
        return content

    # ------------------------------------------------------------------
    # Generic JSON generation
    # ------------------------------------------------------------------

    def _generate_json(
        self,
        prompt: str,
        retries: int = 1,
        model: Optional[str] = None,
        timeout_seconds: Optional[int] = None,
        schema: Optional[dict] = None,
        schema_name: str = "response",
        max_tokens: Optional[int] = None,
        reasoning_effort: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Generate a JSON object.

        With ``schema`` the reply is constrained by Groq's strict structured
        outputs. If Groq rejects the schema (HTTP 400) the call is repeated
        once as plain JSON text, so a schema problem can never take a feature
        down. An unparseable reply gets ``retries`` repair attempts, then
        ``{}`` is returned (callers decide how to degrade). LLMError for
        key/quota/timeout problems propagates.
        """
        use_schema = schema

        def call(text: str) -> Optional[str]:
            nonlocal use_schema
            try:
                return self._call_groq(
                    text, json_mode=True, model=model, timeout_seconds=timeout_seconds,
                    schema=use_schema, schema_name=schema_name,
                    max_tokens=max_tokens, reasoning_effort=reasoning_effort,
                )
            except LLMError as exc:
                if use_schema is not None and exc.kind == "bad_request":
                    logger.warning("Groq rejected the JSON schema '%s'; retrying as plain JSON.", schema_name)
                    use_schema = None
                    return self._call_groq(
                        text, json_mode=True, model=model, timeout_seconds=timeout_seconds,
                        max_tokens=max_tokens, reasoning_effort=reasoning_effort,
                    )
                if exc.kind == "bad_response" and retries > 0:
                    return None  # empty/truncated: fall through to the repair attempt
                raise

        parsed = self._extract_json(call(prompt) or "")
        if parsed is not None:
            return parsed

        if retries > 0:
            logger.warning("Groq returned unusable JSON. Attempting one repair generation.")
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
            parsed = self._extract_json(call(repair_prompt) or "")
            if parsed is not None:
                return parsed

        return {}

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
            schema=SKILLS_SCHEMA,
            schema_name="extracted_skills",
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
        # The search service already ranks resources, so the LLM does not
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

1. The REQUIRED SKILL LIST below is authoritative. Use only those exact
   skill names in every phase's "skills" array. Do not invent, rename,
   generalize, substitute, or add technologies/topics.

2. Cover all required skills exactly once, in the order supplied. Group
   adjacent related skills into phases of 1-4 skills. Do not enforce a
   minimum number of phases; the number of phases must fit the skill list.

REQUIRED SKILL LIST (authoritative and ordered):
{json.dumps(missing_skills, ensure_ascii=False)}

3. Progress from foundational concepts to advanced concepts and projects,
   while preserving the supplied required-skill order.

4. Learner's already-known skills are context only; do not add them back:
{json.dumps(possessed_skills, ensure_ascii=False)}

5. Each phase should contain a focused title, realistic duration, relevant
   verified resources when available, and one small practical project.

6. Project requirements must use only technologies from that phase's skills
   or prerequisite skills already listed earlier in the roadmap. Do not add
   unrelated frameworks, languages, databases, or tools.

7. If there are too few required skills for five phases, return fewer phases.
   Never invent a skill to satisfy a phase-count target.

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

- only exact skill names from the REQUIRED SKILL LIST appear in "skills";
- all required skills appear once and in the supplied order;
- the number of phases matches the amount of material, not an arbitrary minimum;
- every phase has a duration;
- resources match their phase and use URLs only from the verified list;
- no discussion/forum resource is used;
- projects progressively increase in difficulty without introducing unrelated technologies.

Return ONLY JSON.
"""

        result = self._generate_json(
            prompt,
            retries=1,
            reasoning_effort=settings.GROQ_ROADMAP_REASONING_EFFORT,
        )

        phases = result.get("phases", [])
        if not isinstance(phases, list):
            phases = []

        # Defense in depth for any caller that still uses the generic method:
        # only skills from the authorized list survive, and the final skills
        # are reconstructed in the supplied order. Unknown LLM-invented skills
        # can never leak into the saved roadmap's skills array.
        return {"phases": self._enforce_generated_skill_scope(phases, missing_skills)}

    @staticmethod
    def _normalize_skill_label(value: Any) -> str:
        return re.sub(r"[^a-z0-9]+", "", str(value or "").casefold())

    @classmethod
    def _enforce_generated_skill_scope(cls, phases: list, allowed_skills: list) -> list:
        """Guarantee complete, ordered coverage from the allowed skill list.

        A fully compliant model response keeps its authored phase metadata.
        If the model invents, omits, duplicates, or reorders skills, discard its
        grouping and metadata and reconstruct safe, ordered skill-only phases.
        """
        allowed = []
        seen_allowed = set()
        for skill in allowed_skills or []:
            name = str(skill).strip()
            key = cls._normalize_skill_label(name)
            if name and key and key not in seen_allowed:
                allowed.append(name)
                seen_allowed.add(key)
        if not allowed:
            return []

        canonical_by_key = {cls._normalize_skill_label(name): name for name in allowed}
        common_aliases = {
            "react": "React.js",
            "nodejs": "Node.js & Express",
            "expressjs": "Node.js & Express",
            "javascript": "JavaScript Fundamentals",
            "js": "JavaScript Fundamentals",
            "ts": "TypeScript",
            "tailwind": "CSS Frameworks (Tailwind)",
            "tailwindcss": "CSS Frameworks (Tailwind)",
            "git": "Version Control (Git)",
        }
        for alias, canonical_name in common_aliases.items():
            canonical_key = cls._normalize_skill_label(canonical_name)
            if canonical_key in canonical_by_key:
                canonical_by_key[alias] = canonical_by_key[canonical_key]

        def canonicalize(raw_skill):
            if isinstance(raw_skill, dict):
                raw_skill = raw_skill.get("name") or raw_skill.get("id") or ""
            return canonical_by_key.get(cls._normalize_skill_label(raw_skill))

        safe_phases = [phase for phase in phases if isinstance(phase, dict)]
        cleaned_by_phase = []
        observed = []
        has_unknown = False
        for phase in safe_phases:
            raw_skills = phase.get("skills", [])
            if not isinstance(raw_skills, list):
                has_unknown = True
                raw_skills = []
            cleaned = []
            for raw in raw_skills:
                name = canonicalize(raw)
                if name is None:
                    has_unknown = True
                    continue
                cleaned.append(name)
                observed.append(name)
            cleaned_by_phase.append((phase, cleaned))

        compliant = (
            not has_unknown
            and [cls._normalize_skill_label(name) for name in observed]
            == [cls._normalize_skill_label(name) for name in allowed]
        )
        if compliant:
            output = []
            for phase, names in cleaned_by_phase:
                if not names:
                    continue
                normalized = dict(phase)
                normalized["skills"] = names
                output.append(normalized)
            return output

        logger.warning(
            "Generic roadmap response violated the required-skill allow-list/order; "
            "rebuilding phases deterministically."
        )
        chunks = [allowed[i:i + 3] for i in range(0, len(allowed), 3)]
        return [
            {
                "title": f"Phase {index + 1}: {', '.join(chunk[:2])}",
                "duration": "Flexible",
                "skills": chunk,
            }
            for index, chunk in enumerate(chunks)
        ]

    # ------------------------------------------------------------------
    # Plan-then-elaborate generation (prerequisite-aware planner)
    # ------------------------------------------------------------------

    @staticmethod
    def build_plan_elaboration_prompt(
        plan_phases: list,
        goal_name: str = "",
        learner: Optional[dict] = None,
        resources: Optional[list] = None,
        include_extras: bool = True,
    ) -> str:
        """Prompt that asks the LLM to ELABORATE a fixed plan, not to re-plan it.

        ``plan_phases`` is a list of ``{"index": int, "skills": [{"id", "name",
        "action"}]}`` dicts produced from ``path_planner.Plan``. With
        ``include_extras=False`` only titles/durations are requested (used by
        the research experiments, which disable resource discovery).
        """
        learner = learner or {}
        compact_plan = json.dumps(plan_phases, ensure_ascii=False)
        extras_schema = (
            ',\n      "resources": [{"title": "...", "url": "https://...", "type": "documentation"}],'
            '\n      "projects": [{"title": "...", "description": "..."}]'
        ) if include_extras else ""
        resource_rules = ""
        if include_extras:
            if isinstance(resources, dict):
                resource_rules = (
                    "\nRESOURCE RULES:\n"
                    "- Resource candidates are grouped by the exact plan phase index.\n"
                    "- For phase index N, use URLs only from key N in the resource map; never borrow a URL from another phase.\n"
                    "- Use the supplied title and URL exactly; do not invent or modify either.\n"
                    "- If a phase's candidate list is empty, return an empty resources array for that phase.\n"
                    "- Never use forums, discussion threads, social-media posts or search pages.\n\n"
                    f"VERIFIED RESOURCES BY PHASE INDEX:\n{json.dumps(resources, ensure_ascii=False)}\n"
                )
            else:
                resource_rules = (
                    "\nRESOURCE RULES:\n"
                    "- Only use URLs from the VERIFIED RESOURCE LIST below; never invent or modify a URL.\n"
                    "- A resource must actually teach a skill in that phase; leave resources empty if none fits.\n"
                    "- Never use forums, discussion threads, social-media posts or search pages.\n\n"
                    f"VERIFIED RESOURCE LIST:\n{json.dumps(resources or [], ensure_ascii=False)}\n"
                )
        return f"""
You are given a FIXED, pre-computed learning plan. Your job is only to elaborate it.

HARD RULES:
- Do NOT add, remove, rename or reorder skills.
- Do NOT move a skill into a different phase.
- Return exactly {len(plan_phases)} phases, with the same "index" values.
- Copy each skill's "id" and "name" exactly as given.
- If a phase in FIXED PLAN has a "title", copy that title exactly.
- Resources and projects must teach or apply ONLY that phase's listed skills
  plus prerequisites in earlier phases. Do not introduce unrelated technology.
- A project must be a realistic small exercise for the listed skills, not a
  generic project pasted into every phase.
- Do not add skills into project descriptions merely to make the project sound advanced.
- Action meaning: "learn" = full instruction; "review" = short refresher.

Return ONLY valid JSON of this form:

{{
  "phases": [
    {{
      "index": 0,
      "title": "Phase title",
      "duration": "2 weeks",
      "skills": [{{"id": "...", "name": "...", "action": "learn"}}]{extras_schema}
    }}
  ]
}}
{resource_rules}
LEARNER:
Goal: {goal_name or "Unknown"}
Experience: {learner.get("experience_level", "beginner")}
Hours per week: {learner.get("available_hours_per_week", 10)}
Learning style: {learner.get("learning_style", "visual")}

FIXED PLAN:
{compact_plan}

Return ONLY JSON.
"""

    @staticmethod
    def _skill_key(entry: Any) -> str:
        if isinstance(entry, dict):
            entry = entry.get("id") or entry.get("name") or ""
        return str(entry).strip().casefold()

    @classmethod
    def merge_elaboration_with_plan(cls, plan_phases: list, llm_result: Optional[dict]) -> Dict[str, Any]:
        """Enforce the plan: skills and their order always come from the plan.

        The LLM contributes only title/duration (and resources/projects when
        present). Returns ``{"phases": [...], "adherence": float}`` where
        adherence is the fraction of phases whose LLM-listed skills matched the
        planned skills in the same order (a diagnostic, not a gate).
        """
        raw_phases = (llm_result or {}).get("phases", []) if isinstance(llm_result, dict) else []
        if not isinstance(raw_phases, list):
            raw_phases = []
        by_index = {}
        for pos, ph in enumerate(raw_phases):
            if isinstance(ph, dict):
                idx = ph.get("index", pos)
                if isinstance(idx, int) and idx not in by_index:
                    by_index[idx] = ph

        merged, matches = [], 0
        for planned in plan_phases:
            idx = planned["index"]
            ph = by_index.get(idx, {})
            planned_keys = [cls._skill_key(sk) for sk in planned["skills"]]
            listed = ph.get("skills", []) if isinstance(ph.get("skills", []), list) else []
            listed_keys = [cls._skill_key(sk) for sk in listed]
            # accept either ids or names as the copied form
            planned_names = [str(sk.get("name", "")).strip().casefold() for sk in planned["skills"]]
            if listed_keys == planned_keys or listed_keys == planned_names:
                matches += 1
            # Curated curricula provide an authoritative phase title. For
            # planner/experiment inputs without one, preserve the LLM title.
            phase_title = planned.get("title") or ph.get("title") or f"Phase {idx + 1}"
            phase = {
                "title": str(phase_title).strip() or f"Phase {idx + 1}",
                "duration": str(ph.get("duration") or "").strip() or "Flexible",
                "skills": [sk.get("name") or sk.get("id") for sk in planned["skills"]],
                "skill_ids": [sk.get("id") for sk in planned["skills"]],
                "actions": [sk.get("action") for sk in planned["skills"]],
            }
            if isinstance(ph.get("resources"), list):
                phase["resources"] = ph["resources"]
            if isinstance(ph.get("projects"), list):
                phase["projects"] = ph["projects"]
            merged.append(phase)
        adherence = (matches / len(plan_phases)) if plan_phases else 1.0
        return {"phases": merged, "adherence": adherence}

    def generate_roadmap_proposal(
        self,
        *,
        goal_name: str,
        learner: dict,
        target_skill_ids: list,
        candidate_skills: list,
        prerequisite_edges: list,
        mastery_by_skill: dict,
        weak_threshold: float = 0.50,
        strong_threshold: float = 0.85,
    ) -> Dict[str, Any]:
        """Ask the LLM to propose an uncurated roadmap before validation.

        The supplied candidate catalogue is limited to the goal's prerequisite
        closure. The LLM proposes phase grouping and an order; a separate
        deterministic validator checks scope, mastery, coverage and dependency
        order before the proposal can be used in production.
        """
        prompt = f"""
You are designing a personalized learning roadmap. PROPOSE the roadmap; do not
assume a precomputed ordering has already been selected. A deterministic
validator will check your proposal after you return it.

GOAL: {goal_name or 'Unknown goal'}
LEARNER CONTEXT:
- Experience: {learner.get('experience_level', 'beginner')}
- Hours per week: {learner.get('available_hours_per_week', 10)}
- Learning style: {learner.get('learning_style', 'visual')}
- Weak mastery threshold: {weak_threshold}
- Mastered threshold: {strong_threshold}

TARGET SKILL IDS (the goal's required outcomes):
{json.dumps(target_skill_ids, ensure_ascii=False)}

ALLOWED SKILL CATALOGUE (use IDs and names exactly):
{json.dumps(candidate_skills, ensure_ascii=False)}

PREREQUISITE EDGES (each pair is [prerequisite_id, dependent_id]):
{json.dumps(prerequisite_edges, ensure_ascii=False)}

MASTERY BY SKILL ID (0 to 1; missing entries mean 0):
{json.dumps(mastery_by_skill, ensure_ascii=False)}

REQUIREMENTS:
1. Use only skills from the allowed catalogue. Never invent, rename or infer a new skill.
2. Include every target skill that is below the mastered threshold. A mastered
   target may be omitted.
3. Include prerequisite skills needed by included targets, unless those skills
   are already mastered. Do not omit an unmastered prerequisite.
4. Place prerequisites before the skills that depend on them, including when
   they are in different phases. The validator will repair errors, but aim to
   return a valid order.
5. Avoid skills whose mastery is at or above the mastered threshold. For each
   remaining skill, use action "learn" below the weak threshold and "review"
   otherwise.
6. Group related skills into sensible phases, normally 1-4 skills per phase.
   Use concise titles and realistic durations based on the learner's weekly hours.
7. Each phase should contain a small, practical project that uses only skills
   included in that phase or prerequisite skills in earlier phases.
8. Do not add resources or URLs. Resources will be retrieved and verified
   separately after the skill sequence is validated.
9. The skill IDs/names are the source of truth; do not put non-skill topics in
   the skills array. Return valid JSON matching the schema exactly.

Return only the JSON object with a "phases" array.
"""
        result = self._generate_json(
            prompt,
            retries=1,
            schema=ROADMAP_PROPOSAL_SCHEMA,
            schema_name="roadmap_proposal",
            reasoning_effort=settings.GROQ_ROADMAP_REASONING_EFFORT,
        )
        phases = result.get("phases", []) if isinstance(result, dict) else []
        return {"phases": phases if isinstance(phases, list) else []}

    @classmethod
    def merge_proposal_with_validated_plan(cls, proposal: dict, plan_phases: list) -> Dict[str, Any]:
        """Keep proposal metadata while taking skills exclusively from validation.

        This is safe only when validation did not need structural repair.
        Resource fields are deliberately omitted because retrieved resources are
        attached by RoadmapService after URL and relevance checks.
        """
        raw_phases = (proposal or {}).get("phases", []) if isinstance(proposal, dict) else []
        by_index = {}
        by_skill_signature = {}

        def skill_signature(skills):
            if not isinstance(skills, list):
                return ()
            return tuple(
                cls._skill_key(skill)
                for skill in skills
                if cls._skill_key(skill)
            )

        for position, phase in enumerate(raw_phases if isinstance(raw_phases, list) else []):
            if isinstance(phase, dict):
                index = phase.get("index", position)
                if isinstance(index, int) and index not in by_index:
                    by_index[index] = phase
                signature = skill_signature(phase.get("skills", []))
                if signature and signature not in by_skill_signature:
                    by_skill_signature[signature] = phase

        merged = []
        for phase in plan_phases:
            index = phase["index"]
            # Validation normalizes phase indices to 0-based sequence. The LLM
            # may have used 1-based indices, so skill identity is the safer way
            # to retain project ideas and durations from the corresponding
            # proposal phase. Use the numeric index only as a fallback.
            signature = skill_signature(phase.get("skills", []))
            raw = by_skill_signature.get(signature) or by_index.get(index, {})
            item = {
                "title": str(phase.get("title") or raw.get("title") or f"Phase {index + 1}").strip(),
                "duration": str(raw.get("duration") or "Flexible").strip(),
                "skills": [skill.get("name") or skill.get("id") for skill in phase.get("skills", [])],
                "skill_ids": [skill.get("id") for skill in phase.get("skills", [])],
                "actions": [skill.get("action") for skill in phase.get("skills", [])],
                "projects": raw.get("projects", []) if isinstance(raw.get("projects"), list) else [],
            }
            merged.append(item)
        return {"phases": merged}

    @staticmethod
    def _valid_project_items(value: Any) -> list[dict]:
        """Keep only project objects the roadmap UI can render safely."""
        if not isinstance(value, list):
            return []
        result = []
        for item in value:
            if not isinstance(item, dict):
                continue
            title = str(item.get("title") or "").strip()
            description = str(item.get("description") or "").strip()
            if title and description:
                result.append({"title": title, "description": description})
        return result

    @staticmethod
    def _project_phase_skill_keys(skills: Any) -> set[str]:
        """Return both IDs and names so phases can be matched after repair."""
        if not isinstance(skills, list):
            return set()
        keys = set()
        for skill in skills:
            if isinstance(skill, dict):
                for field in ("id", "name"):
                    value = str(skill.get(field) or "").strip().casefold()
                    if value:
                        keys.add(value)
            else:
                value = str(skill or "").strip().casefold()
                if value:
                    keys.add(value)
        return keys

    @classmethod
    def preserve_proposal_projects(
        cls, proposal: Optional[dict], plan_phases: list, roadmap: Optional[dict]
    ) -> Optional[dict]:
        """Restore proposal projects if repair/re-elaboration dropped them.

        A repaired plan can add or move skills, so matching solely by numeric
        phase index is unsafe. Match by skill overlap and never overwrite valid
        projects already produced by the corrected-plan elaboration.
        """
        if not isinstance(roadmap, dict):
            return roadmap
        final_phases = roadmap.get("phases")
        raw_phases = proposal.get("phases", []) if isinstance(proposal, dict) else []
        if not isinstance(final_phases, list) or not isinstance(raw_phases, list):
            return roadmap

        sources = []
        for source_index, raw in enumerate(raw_phases):
            if not isinstance(raw, dict):
                continue
            projects = cls._valid_project_items(raw.get("projects"))
            skill_keys = cls._project_phase_skill_keys(raw.get("skills"))
            if projects and skill_keys:
                sources.append({"index": source_index, "projects": projects, "skill_keys": skill_keys})

        used_sources = set()
        restored = 0
        for final_index, phase in enumerate(final_phases):
            if not isinstance(phase, dict) or cls._valid_project_items(phase.get("projects")):
                continue
            planned = plan_phases[final_index] if final_index < len(plan_phases) else {}
            target_keys = cls._project_phase_skill_keys(planned.get("skills", []))
            if not target_keys:
                target_keys = cls._project_phase_skill_keys(phase.get("skills", []))
            candidates = []
            for source in sources:
                if source["index"] in used_sources:
                    continue
                overlap = len(target_keys & source["skill_keys"])
                if overlap:
                    candidates.append((overlap, -abs(final_index - source["index"]), source))
            if not candidates:
                continue
            _, _, best = max(candidates, key=lambda candidate: (candidate[0], candidate[1]))
            phase["projects"] = best["projects"]
            used_sources.add(best["index"])
            restored += len(best["projects"])

        if restored:
            logger.info("Restored %d project idea(s) from the validated LLM proposal after plan repair", restored)
        return roadmap

    @staticmethod
    def _fallback_project_for_phase(title: str, skills: list[str]) -> dict:
        """Create a concrete last-resort project when all LLM paths omit one."""
        text = (title + " " + " ".join(skills)).casefold()
        if any(token in text for token in ("html", "css", "responsive", "web foundation")):
            return {"title": "Responsive Multi-Page Website", "description": "Build a small website with semantic HTML, reusable page sections, navigation, and responsive CSS. Check the layout at mobile and desktop widths and fix the issues you find."}
        if any(token in text for token in ("react", "next.js", "nextjs", "frontend", "front-end")):
            return {"title": "Interactive Component-Based Dashboard", "description": "Build a small dashboard with reusable UI components, page or route navigation, form state, and loading, empty, and error states. Verify the main user flows in the browser."}
        if any(token in text for token in ("javascript", "typescript", "browser")):
            return {"title": "Interactive Task Tracker", "description": "Create a task tracker with add, edit, complete, and delete actions. Validate user input, handle empty states, and test at least three realistic usage cases."}
        if any(token in text for token in ("node.js", "express", "backend", "restful api", "api development", "server-side")):
            return {"title": "RESTful CRUD API", "description": "Implement create, read, update, and delete endpoints for one resource. Validate request bodies, return appropriate HTTP status codes, and test success and failure cases."}
        if any(token in text for token in ("database", "sql", "mongodb", "persistence")):
            return {"title": "Persistent Task Manager", "description": "Connect a small task-management feature to a database. Support creating, listing, updating, and deleting records, and verify that data persists after restarting the application."}
        if any(token in text for token in ("auth", "security", "permission", "jwt")):
            return {"title": "Protected User Workspace", "description": "Add user registration and sign-in to a small application, protect a private route, validate inputs, and test both authorized and unauthorized access."}
        if any(token in text for token in ("deploy", "docker", "ci/cd", "production", "devops")):
            return {"title": "Deployable Application with CI Checks", "description": "Package a small application for deployment, document required configuration, add a health check, and create an automated workflow that runs tests before building or deploying it."}
        if any(token in text for token in ("machine learning", "classification", "regression", "neural network", "model evaluation", "mlops")):
            return {"title": "End-to-End Model Experiment", "description": "Use a suitable dataset to train a baseline model, evaluate it with task-appropriate metrics, inspect representative errors, and document what the results do and do not show."}
        if any(token in text for token in ("data", "pandas", "statistics", "visualization", "analytics")):
            return {"title": "Dataset Exploration Report", "description": "Select a small dataset, clean and summarize it using the phase skills, create two useful visualizations or analyses, and write a short report of findings and limitations."}

        focus = ", ".join(skill for skill in skills[:3] if skill) or title or "the phase skills"
        lead = skills[0] if skills else title or "Skills"
        return {"title": f"{lead} Applied Mini-Project", "description": f"Build a small, working deliverable that demonstrates {focus}. Include one realistic use case, test it with representative inputs, and document the key implementation decisions."}

    @classmethod
    def ensure_project_ideas(cls, roadmap: Optional[dict]) -> Optional[dict]:
        """Guarantee each returned phase has at least one renderable project."""
        if not isinstance(roadmap, dict):
            return roadmap
        phases = roadmap.get("phases")
        if not isinstance(phases, list):
            return roadmap
        for phase in phases:
            if not isinstance(phase, dict):
                continue
            projects = cls._valid_project_items(phase.get("projects"))
            if projects:
                phase["projects"] = projects
                continue
            skills_value = phase.get("skills", [])
            skills = [str(skill).strip() for skill in skills_value if str(skill).strip()] if isinstance(skills_value, list) else []
            phase["projects"] = [cls._fallback_project_for_phase(str(phase.get("title") or ""), skills)]
            logger.warning("No project idea generated for phase '%s'; inserted deterministic fallback", phase.get("title", "Untitled phase"))
        return roadmap

    def generate_roadmap_from_plan(self, context: dict, plan_phases: list) -> Dict[str, Any]:
        """Elaborate a deterministic or curated plan without changing its skills.

        The plan may come from a seeded curriculum, the optional graph planner,
        or prerequisite-first fallback planning for custom goals. The same
        return shape is used for every production roadmap path.
        """
        phase_resource_context = context.get("verified_resources_by_phase")
        if isinstance(phase_resource_context, dict):
            compact_resources = {
                str(index): [
                    {
                        "title": resource.get("title", ""),
                        "url": resource.get("url", ""),
                        "type": resource.get("type", "article"),
                        "matched_skill": resource.get("matched_skill", ""),
                    }
                    for resource in (phase_resources or [])[:6]
                ]
                for index, phase_resources in phase_resource_context.items()
            }
        else:
            compact_resources = [
                {
                    "title": r.get("title", ""), "url": r.get("url", ""), "type": r.get("type", "article"),
                    "skill": r.get("skill", ""), "source": r.get("source", ""),
                }
                for r in (context.get("verified_live_resources") or [])[:20]
            ]
        prompt = self.build_plan_elaboration_prompt(
            plan_phases,
            goal_name=context.get("goal_skill_name", ""),
            learner=context,
            resources=compact_resources,
            include_extras=True,
        )
        try:
            result = self._generate_json(
                prompt,
                retries=1,
                schema=PLAN_ELABORATION_SCHEMA,
                schema_name="plan_elaboration",
                reasoning_effort=settings.GROQ_ROADMAP_REASONING_EFFORT,
            )
        except LLMError as exc:
            if exc.kind != "bad_response":
                raise  # key/quota/timeout problems must reach the user, not be hidden
            logger.warning("Plan elaboration unusable; keeping the bare plan.")
            result = {}
        merged = self.merge_elaboration_with_plan(plan_phases, result)
        logger.info("Planner elaboration adherence: %.2f", merged["adherence"])
        return {"phases": merged["phases"]}

    # ------------------------------------------------------------------
    # Strict, reproducible generation for experiments (no fallbacks)
    # ------------------------------------------------------------------

    def generate_experiment_json(
        self,
        prompt: str,
        provider: str = "groq",
        model: Optional[str] = None,
        temperature: float = 0.1,
        seed: Optional[int] = None,
        timeout_seconds: Optional[int] = None,
        system_prompt: Optional[str] = None,
        max_tokens: Optional[int] = None,
        reasoning_effort: Optional[str] = None,
    ) -> Dict[str, Any]:
        """One strict Groq generation call: no repair retry or HF fallback.

        Returns ``{"parsed", "raw", "provider", "model", "latency_s"}``. The
        ``model`` reported is the one actually requested, so results can never
        be silently mixed across models.
        """
        import time

        started = time.time()
        if provider != "groq":
            raise ValueError(
                f"Unsupported provider: {provider!r}. This project now uses Groq; "
                "use provider='groq' or the experiment harness's mock provider."
            )

        used_model = model or self.model
        try:
            raw = self._call_groq(
                prompt,
                json_mode=True,
                system_prompt=system_prompt,
                model=used_model,
                timeout_seconds=timeout_seconds,
                temperature=temperature,
                seed=seed,
                max_tokens=max_tokens,
                reasoning_effort=reasoning_effort,
            )
        except LLMError as exc:
            logger.error("Experiment call failed: %s", exc.kind)
            raw = None
        parsed = self._extract_json(raw or "") if raw else None
        return {
            "parsed": parsed,
            "raw": raw,
            "provider": provider,
            "model": used_model,
            "latency_s": round(time.time() - started, 3),
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

        try:
            result = self._generate_json(
                prompt, retries=1, schema=REMEDIAL_SCHEMA, schema_name="remedial_phase",
            )
        except LLMError as exc:
            logger.warning("Remedial phase elaboration unavailable (%s); using a plain review phase.", exc.kind)
            result = {}

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
            schema=STUDY_NOTES_SCHEMA,
            schema_name="study_notes",
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
            schema=SUMMARY_SCHEMA,
            schema_name="learner_summary",
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
    "explanation": "...",
    "skill": "one listed skill"
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
- Assign every question to exactly one of the listed skills using the `skill` field.

Phase:
{phase_title}

Skills:
{", ".join(skills) or "General foundations"}
"""

        # LLMError (key, quota, timeout...) propagates so the user is told why.
        result = self._generate_json(
            prompt,
            retries=1,
            model=self.model,
            timeout_seconds=settings.GROQ_QUIZ_TIMEOUT_SECONDS,
            schema=QUIZ_SCHEMA,
            schema_name="quiz",
            max_tokens=settings.GROQ_QUIZ_MAX_COMPLETION_TOKENS,
        )

        questions = result.get(
            "questions",
            [],
        )

        if not isinstance(
            questions,
            list,
        ):
            raise LLMError("bad_response")

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

            question["skill"] = question.get("skill") or (skills[len(valid_questions) % len(skills)] if skills else "General foundations")

            valid_questions.append(
                question
            )

        if not valid_questions:
            # Never substitute canned questions: a quiz that is not about the
            # material would corrupt the learner's mastery estimate.
            logger.warning("No valid AI quiz questions returned.")
            raise LLMError("bad_response")
        return valid_questions


llm_service = LLMService()