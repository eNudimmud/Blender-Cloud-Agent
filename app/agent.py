"""Planners return inert scene data. They never execute code or submit jobs."""
import json
import re
import unicodedata
from urllib.parse import urlsplit

import httpx

from app.models import AgentPlan, SceneObject, SceneSpec

COLORS = {
    "rouge": "#e55b59", "red": "#e55b59", "bleu": "#5d9ddd", "blue": "#5d9ddd",
    "vert": "#77caba", "green": "#77caba", "jaune": "#edcd65", "yellow": "#edcd65",
    "orange": "#eb9951", "violet": "#aa85df", "purple": "#aa85df", "blanc": "#eeeeee",
    "white": "#eeeeee", "noir": "#333333", "black": "#333333", "rose": "#e597c6", "pink": "#e597c6",
}
SHAPES = {"cube": "cube", "sphere": "sphere", "boule": "sphere", "cylindre": "cylinder", "cylinder": "cylinder"}
COLOR_ALIASES = {"bleue": "bleu", "verte": "vert", "blanche": "blanc", "noire": "noir"}
CREATE_WORDS = {"ajoute", "ajouter", "cree", "creer", "create", "add"}
EDIT_WORDS = {"rends", "change", "modifie", "recolore", "deplace", "move", "resize", "remove", "supprime", "delete", "make", "set"}
HELP = ("Je peux ajouter un cube, une sphère ou un cylindre, changer sa couleur ou sa taille, "
        "le déplacer (x=2 y=0 z=1) ou le supprimer. Une action par message. "
        "Exemple : « Ajoute un cube rouge de taille 2 ». Aucun rendu avant confirmation.")


def guided_plan(scene: SceneSpec, message: str, object_id=None) -> AgentPlan:
    text = "".join(c for c in unicodedata.normalize("NFD", message.lower()) if unicodedata.category(c) != "Mn")
    words = set(re.findall(r"[a-z]+", text))
    words |= {COLOR_ALIASES.get(word, word) for word in words}
    if (words & {"python", "exec", "execute", "script", "import", "telecharge", "download", "sans", "without", "not", "pas", "aucun", "aucune", "jamais", "never", "non"}
            or re.search(r"\b(?:don['’]t|n['’])", text)
            or "http" in text or "__" in text):
        return AgentPlan(summary=HELP)
    found = [value for word, value in SHAPES.items() if word in words]
    if len(found) > 1 or re.search(r"\b(?:[2-9]|[1-9][0-9]+)\s+(?:cubes|spheres|cylindres|cylinders)\b", text):
        return AgentPlan(summary=HELP)
    colors = {value for word, value in COLORS.items() if word in words}
    hex_color = re.search(r"#[0-9a-f]{6}\b", text)
    if hex_color:
        colors.add(hex_color.group())
    if len(colors) > 1 or (words & CREATE_WORDS and words & EDIT_WORDS):
        return AgentPlan(summary=HELP)
    color = next(iter(colors), None)
    number = r"-?\d+(?:[.,]\d+)?(?:e[+-]?\d+)?"
    size_match = re.search(r"\b(?:taille|size)\s*(?:de|of|a|=|:)?\s*(" + number + r")(?=$|[\s;,])", text)
    if words & {"taille", "size"} and size_match is None:
        return AgentPlan(summary=HELP)
    size = float(size_match[1].replace(",", ".")) if size_match else None
    axis_names = re.findall(r"\b([xyz])\s*=", text)
    axis_values = re.findall(r"\b([xyz])\s*=\s*(" + number + r")(?=$|[\s;,])", text)
    if len(axis_names) != len(axis_values) or len(set(axis_names)) != len(axis_names):
        return AgentPlan(summary=HELP)
    axes = {axis: float(value.replace(",", ".")) for axis, value in axis_values}
    if words & CREATE_WORDS and not found:
        return AgentPlan(summary=HELP)
    edit = words & EDIT_WORDS
    result = scene.model_copy(deep=True)
    if found and not edit:
        obj = SceneObject(shape=found[0], name=found[0].capitalize(), color=color or "#77caba",
                          size=size if size is not None else 2,
                          position=tuple(axes.get(a, 0) for a in "xyz"))
        result.objects.append(obj)
        summary = f"Ajouter {obj.name.lower()}, taille {obj.size:g}, couleur {obj.color}."
    elif result.objects:
        candidates = [obj for obj in result.objects
                      if (not object_id or obj.id == object_id) and (not found or obj.shape == found[0])]
        if not candidates:
            return AgentPlan(summary="Cet objet n’existe pas dans le projet. " + HELP)
        obj = candidates[-1]
        if words & {"remove", "supprime", "delete"}:
            if words & {"tous", "tout", "all"}:
                return AgentPlan(summary=HELP)
            result.objects.remove(obj)
            summary = f"Supprimer {obj.name.lower()} ({obj.id[:6]})."
        elif color or size is not None or axes:
            if color:
                obj.color = color
            if size is not None:
                obj.size = size
            if axes:
                obj.position = tuple(axes.get(a, obj.position[i]) for i, a in enumerate("xyz"))
            summary = f"Modifier {obj.name.lower()} ({obj.id[:6]}) : taille {obj.size:g}, couleur {obj.color}, position {obj.position}."
        else:
            return AgentPlan(summary=HELP)
    else:
        return AgentPlan(summary=HELP)
    return AgentPlan(summary=summary, scene=SceneSpec.model_validate(result.model_dump()))


def protect_selection(scene, plan, object_id):
    if object_id and plan.scene is not None:
        result = {obj.id: obj for obj in plan.scene.objects}
        for obj in scene.objects:
            if obj.id != object_id and result.get(obj.id) != obj:
                raise ValueError("La proposition modifie un objet hors de la sélection.")
    return plan


def llm_plan(settings, scene, message, history, client=None, object_id=None):
    if not settings.allow_paid_ai:
        raise ValueError("L’IA externe est désactivée : aucune autorisation de dépenses.")
    url = urlsplit(settings.llm_url)
    if (url.scheme != "https" or not url.hostname or url.username or url.password
            or not url.path.endswith("/chat/completions") or not settings.llm_model or not settings.llm_api_key):
        raise ValueError("Configuration du fournisseur IA incomplète.")
    system = (
        "You plan edits for a Blender scene. Return ONLY a JSON object matching this schema: "
        + json.dumps(AgentPlan.model_json_schema())
        + ". Keep existing object IDs. Use only the 3 allowed primitives. Summarize in French. "
        "For unsupported requests set scene=null. Never return code, URLs, tools, file paths or paid actions. "
        "The user will review and explicitly confirm every edit. Scene units are meters, Z is up."
        " If selected_object_id is present, only that existing object may be edited or removed;"
        " leave every other existing object unchanged. New objects may be added."
    )
    payload = {"model": settings.llm_model, "temperature": 0, "max_tokens": 1800,
               "response_format": {"type": "json_object"}, "messages": [
                   {"role": "system", "content": system},
                   {"role": "user", "content": json.dumps({"scene": scene.model_dump(), "history": history[-6:],
                                                        "selected_object_id": object_id, "request": message})},
               ]}
    owned = client is None
    client = client or httpx.Client(timeout=25, follow_redirects=False, trust_env=False)
    try:
        with client.stream("POST", settings.llm_url,
                           headers={"Authorization": f"Bearer {settings.llm_api_key}"}, json=payload) as response:
            response.raise_for_status()
            body = bytearray()
            for chunk in response.iter_bytes(chunk_size=8192):
                body.extend(chunk)
                if len(body) > 65536:
                    raise ValueError("Réponse IA trop volumineuse.")
        content = json.loads(body)["choices"][0]["message"]["content"]
        return protect_selection(scene, AgentPlan.model_validate_json(content), object_id)
    finally:
        if owned:
            client.close()
