"""Mission planner module.

Orchestrator logic that decomposes a goal into milestones, features,
and a validation contract using Shrewd for LLM calls.
"""

import json
import logging
import os
from typing import Any, Optional

from hub.mission.repo_intelligence import RepoInfo, analyze_repository

logger = logging.getLogger(__name__)


PLANNING_SYSTEM_PROMPT = """You are a mission planner for an autonomous software engineering system.
Your job is to decompose a development goal into clear, executable milestones.

Each milestone contains features (units of work) and success criteria.
After all milestones, a validation contract defines how to verify the work.

Rules:
- Create 2-5 milestones depending on complexity
- Each milestone has 1-5 features
- Features should be independent where possible for parallel execution
- Include a validator feature in the last milestone
- Success criteria must be testable
- The validation contract should include test commands and check paths

Output JSON only, no markdown fences."""


PLANNING_USER_PROMPT = """## Goal
{description}

## Target Repository
{repo_path}

## Repository Context
{repo_context}

## Model Preferences
- Orchestrator: {orchestrator_model}
- Worker: {worker_model}
- Validator: {validator_model}

Produce a plan with milestones, features, and a validation contract."""


def plan_mission(
    description: str,
    repo_path: str,
    orchestrator_model: Optional[str] = None,
    worker_model: Optional[str] = None,
    validator_model: Optional[str] = None,
) -> dict[str, Any]:
    """Create a mission plan by analyzing the repo and calling the LLM.

    Returns a dict with:
    - milestones: list of milestone dicts
    - validation_contract: dict
    """
    # Analyze repository
    repo_info = analyze_repository(repo_path) if repo_path else None

    # Build repo context
    repo_context = _build_repo_context(repo_info)

    # Build prompt
    user_prompt = PLANNING_USER_PROMPT.format(
        description=description,
        repo_path=repo_path or "unknown",
        repo_context=repo_context,
        orchestrator_model=orchestrator_model or "default",
        worker_model=worker_model or "default",
        validator_model=validator_model or "default",
    )

    # Call LLM via Shrewd
    plan_text = _call_llm(PLANNING_SYSTEM_PROMPT, user_prompt, orchestrator_model)

    # Parse plan
    plan = _parse_plan(plan_text)
    plan["repo_info"] = repo_info.to_dict() if repo_info else None
    return plan


def _build_repo_context(repo_info: Optional[RepoInfo]) -> str:
    """Build a text context from repository analysis."""
    if not repo_info:
        return "No repository context available."

    parts = []
    if repo_info.frameworks:
        parts.append(f"Frameworks: {', '.join(repo_info.frameworks)}")
    if repo_info.test_commands:
        parts.append(f"Test commands: {', '.join(repo_info.test_commands)}")
    if repo_info.build_commands:
        parts.append(f"Build commands: {', '.join(repo_info.build_commands)}")
    if repo_info.entry_points:
        parts.append(f"Entry points: {', '.join(repo_info.entry_points)}")
    if repo_info.directories:
        parts.append(f"Top-level dirs: {', '.join(repo_info.directories[:20])}")
    if repo_info.conventions:
        parts.append("Conventions:")
        for conv in repo_info.conventions[:3]:
            parts.append(f"  {conv[:500]}")

    return "\n".join(parts) if parts else "Minimal repository context."


def _call_llm(system_prompt: str, user_prompt: str, model_override: Optional[str] = None) -> str:
    """Call the LLM via Shrewd for planning.

    Falls back to a simple heuristic plan if Shrewd is unavailable.
    """
    shrewd_url = os.environ.get("SHREWD_URL", "http://shrewd:8089").rstrip("/")
    shrewd_key = os.environ.get("SHREWD_API_KEY", "")

    try:
        import httpx

        headers = {"Content-Type": "application/json"}
        if shrewd_key:
            headers["Authorization"] = f"Bearer {shrewd_key}"

        payload = {
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "response_format": {"type": "json_object"},
        }
        if model_override:
            payload["model"] = model_override

        with httpx.Client(timeout=120.0) as client:
            resp = client.post(f"{shrewd_url}/api/chat", json=payload, headers=headers)
            if resp.status_code == 200:
                data = resp.json()
                choices = data.get("choices", [])
                if choices:
                    return choices[0].get("message", {}).get("content", "")

        logger.warning("Shrewd returned unexpected response: %s", resp.text[:200])
    except Exception as e:
        logger.warning("Shrewd unavailable, using heuristic plan: %s", e)

    # Fallback: heuristic plan
    return _heuristic_plan(user_prompt)


def _heuristic_plan(user_prompt: str) -> str:
    """Generate a simple heuristic plan when LLM is unavailable."""
    # Extract description from prompt
    desc = "Implement the requested feature"
    for line in user_prompt.splitlines():
        if "Goal" in line:
            continue
        if line.strip() and not line.startswith("#") and not line.startswith("-"):
            desc = line.strip()
            break

    plan = {
        "milestones": [
            {
                "name": "Planning",
                "description": "Analyze requirements and design",
                "success_criteria": ["Requirements documented", "Design decisions recorded"],
                "features": [
                    {
                        "name": "Analyze requirements",
                        "description": desc,
                        "role": "worker",
                    }
                ],
            },
            {
                "name": "Implementation",
                "description": "Implement the feature",
                "success_criteria": ["Code written", "Tests pass"],
                "features": [
                    {"name": "Write implementation", "description": desc, "role": "worker"},
                    {"name": "Write tests", "description": "Add tests for the feature", "role": "worker"},
                ],
            },
            {
                "name": "Validation",
                "description": "Verify the implementation",
                "success_criteria": ["All checks pass"],
                "features": [
                    {"name": "Run validation", "description": "Run tests and checks", "role": "validator"},
                ],
            },
        ],
        "validation_contract": {
            "description": "Feature works correctly",
            "test_commands": ["pytest"],
            "check_paths": [],
            "max_severity": "major",
        },
    }
    return json.dumps(plan)


def _parse_plan(text: str) -> dict[str, Any]:
    """Parse LLM output into structured plan."""
    # Strip markdown fences if present
    text = text.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        lines = lines[1:]  # Remove opening fence
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]  # Remove closing fence
        text = "\n".join(lines)

    try:
        plan = json.loads(text)
    except json.JSONDecodeError:
        logger.warning("Failed to parse LLM plan as JSON, using heuristic")
        return json.loads(_heuristic_plan(""))

    # Validate structure
    if "milestones" not in plan:
        plan["milestones"] = []
    if not isinstance(plan["milestones"], list):
        plan["milestones"] = []

    # Ensure each milestone has required fields
    for i, ms in enumerate(plan["milestones"]):
        ms.setdefault("name", f"milestone-{i}")
        ms.setdefault("description", "")
        ms.setdefault("success_criteria", [])
        ms.setdefault("features", [])
        for j, f in enumerate(ms["features"]):
            f.setdefault("name", f"feature-{j}")
            f.setdefault("description", "")
            f.setdefault("role", "worker")

    vc = plan.get("validation_contract")
    if not vc:
        plan["validation_contract"] = {
            "description": "Default validation",
            "test_commands": [],
            "check_paths": [],
            "max_severity": "major",
        }

    return plan
