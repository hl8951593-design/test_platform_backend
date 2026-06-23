from app.ai_skills.base import AISkill

_SKILLS: dict[str, AISkill] = {}


def register_ai_skill(skill: AISkill) -> AISkill:
    _SKILLS[skill.skill_id] = skill
    return skill


def get_ai_skill(skill_id: str) -> AISkill:
    try:
        return _SKILLS[skill_id]
    except KeyError as exc:
        raise KeyError(f"AI skill not registered: {skill_id}") from exc


def list_ai_skills() -> list[AISkill]:
    return [skill for _, skill in sorted(_SKILLS.items())]
