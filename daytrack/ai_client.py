"""
AI Client Module
================
Groq AI client for natural language parsing, task matching,
and weekly summary generation.
"""

import json
import logging
from typing import Dict, List, Optional

from groq import Groq

logger = logging.getLogger(__name__)

VALID_CATEGORIES = {"work", "health", "personal", "learning", "other"}
VALID_STATUSES = {"done", "partial", "skipped"}


class ContentSafetyError(Exception):
    """Raised when AI detects inappropriate or irrelevant content."""
    pass


class GroqAIClient:
    """Handles all Groq API interactions with structured prompts."""

    def __init__(self, api_key: str, model: str = "llama-3.1-70b-versatile",
                 max_tokens: int = 1024, temperature: float = 0.7):
        self.client = Groq(api_key=api_key)
        self.model = model
        self.max_tokens = max_tokens
        self.temperature = temperature

    def _call_groq(self, system_prompt: str, user_prompt: str) -> str:
        """Call Groq API with retry on failure."""
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                max_tokens=self.max_tokens,
                temperature=self.temperature,
            )
            return response.choices[0].message.content.strip()
        except Exception as e:
            logger.error(f"Groq API call failed: {e}")
            raise

    def _parse_json_response(self, response: str):
        """Parse JSON from AI response, stripping markdown fences if present."""
        text = response.strip()
        if text.startswith("```"):
            lines = text.split("\n")
            lines = lines[1:]  # remove opening fence
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            text = "\n".join(lines)
        return json.loads(text)

    def parse_morning_plan(self, plan_text: str) -> List[dict]:
        """Parse natural language plan into structured tasks."""
        system = (
            "You are a task extraction assistant for a daily planning bot.\n"
            "Your ONLY job is to extract actionable daily tasks from the user's plan.\n\n"
            "SAFETY RULES (strictly enforce):\n"
            "- If the input contains profanity, slurs, hate speech, or inappropriate language, "
            "return: {\"error\": \"inappropriate\"}\n"
            "- If the input is completely unrelated to daily tasks/plans (e.g., random questions, "
            "jokes, gibberish, political opinions, personal attacks), "
            "return: {\"error\": \"irrelevant\"}\n"
            "- If the input is a greeting or small talk with no tasks, "
            "return: {\"error\": \"no_tasks\"}\n\n"
            "If the input IS a valid daily plan:\n"
            "Return a JSON array of objects with \"title\" (string) and "
            "\"category\" (one of: work, health, personal, learning, other).\n"
            "Only return valid JSON, no other text."
        )
        for attempt in range(2):
            try:
                raw = self._call_groq(system, plan_text)
                parsed = self._parse_json_response(raw)
                # Check for safety rejection
                if isinstance(parsed, dict) and "error" in parsed:
                    error_type = parsed["error"]
                    if error_type == "inappropriate":
                        raise ContentSafetyError("Please keep it clean and friendly. No bad language here! 🙏")
                    elif error_type == "irrelevant":
                        raise ContentSafetyError("That doesn't look like a daily plan. Tell me about your tasks for today! 📝")
                    elif error_type == "no_tasks":
                        raise ContentSafetyError("I didn't find any tasks in that. What are you planning to do today? 😊")
                if not isinstance(parsed, list):
                    raise ValueError("Expected a JSON array")
                for t in parsed:
                    if t.get("category") not in VALID_CATEGORIES:
                        t["category"] = "other"
                return parsed
            except (json.JSONDecodeError, ValueError) as e:
                if attempt == 0:
                    logger.warning(f"Retrying morning parse due to: {e}")
                    continue
                raise
        return []

    def match_evening_update(self, tasks: List[dict], update_text: str) -> List[dict]:
        """Match evening update against morning tasks."""
        system = (
            "You are a task status matcher for a daily planning bot.\n"
            "Given a list of morning tasks and an evening update, determine the status of each task.\n\n"
            "SAFETY RULES (strictly enforce):\n"
            "- If the evening update contains profanity, slurs, hate speech, or inappropriate language, "
            "return: {\"error\": \"inappropriate\"}\n"
            "- If the evening update is completely unrelated to the tasks or daily activities, "
            "return: {\"error\": \"irrelevant\"}\n\n"
            "If the input IS a valid evening update:\n"
            "Return a JSON array with \"title\", \"category\", and "
            "\"status\" (one of: done, partial, skipped) for each task.\n"
            "Only return valid JSON, no other text."
        )
        user_prompt = f"Morning tasks: {json.dumps(tasks)}\nEvening update: {update_text}"
        for attempt in range(2):
            try:
                raw = self._call_groq(system, user_prompt)
                parsed = self._parse_json_response(raw)
                if isinstance(parsed, dict) and "error" in parsed:
                    error_type = parsed["error"]
                    if error_type == "inappropriate":
                        raise ContentSafetyError("Please keep it clean and friendly. No bad language here! 🙏")
                    elif error_type == "irrelevant":
                        raise ContentSafetyError("That doesn't seem related to your tasks. How did your planned tasks go? 💬")
                if not isinstance(parsed, list):
                    raise ValueError("Expected a JSON array")
                for t in parsed:
                    if t.get("status") not in VALID_STATUSES:
                        t["status"] = "skipped"
                return parsed
            except (json.JSONDecodeError, ValueError) as e:
                if attempt == 0:
                    logger.warning(f"Retrying evening match due to: {e}")
                    continue
                raise
        return []

    def generate_weekly_insight(self, week_data: dict) -> dict:
        """Generate weekly reflection and suggestions."""
        system = (
            "You are a reflective weekly coach. Given a user's week data, provide a warm, "
            "encouraging summary and actionable suggestions.\n"
            "Return JSON with \"summary\" (string) and \"suggestions\" (string).\n"
            "Only return valid JSON, no other text."
        )
        for attempt in range(2):
            try:
                raw = self._call_groq(system, json.dumps(week_data))
                result = self._parse_json_response(raw)
                if not isinstance(result, dict):
                    raise ValueError("Expected a JSON object")
                return {
                    "summary": result.get("summary", ""),
                    "suggestions": result.get("suggestions", ""),
                }
            except (json.JSONDecodeError, ValueError) as e:
                if attempt == 0:
                    logger.warning(f"Retrying weekly insight due to: {e}")
                    continue
                raise
        return {"summary": "", "suggestions": ""}
