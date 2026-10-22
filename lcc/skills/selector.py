"""Vorauswahl der Skills je Auftrag: Trigger (Score 1.0) und Embedding-Ähnlichkeit.

Gesamt-Score = max(Trigger, Embedding); sortiert, höchstens skills.max_listed.
Embeddings der Beschreibungen werden in der RAG-DB (skill_embeddings) gecacht;
der Schlüssel enthält Modell + Beschreibung, ein Modellwechsel invalidiert also automatisch.
"""

from __future__ import annotations

import dataclasses
import hashlib
import re
from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np

from lcc import texts
from lcc.config import Config
from lcc.ollama_client import OllamaClient, OllamaError
from lcc.rag.store import Matrix, Store
from lcc.skills.loader import Skill


@dataclass(frozen=True)
class SkillMatch:
    skill: Skill
    score: float
    reason: str
    auto_load: bool = False
    by_trigger: bool = False
    similarity: float | None = None


def matching_trigger(task: str, skill: Skill) -> str | None:
    """Erster Trigger, der im Auftrag vorkommt (Wortgrenzen, Groß/Klein egal)."""
    for trigger in skill.triggers:
        pattern = rf"(?<!\w){re.escape(trigger)}(?!\w)"
        if re.search(pattern, task, flags=re.IGNORECASE):
            return trigger
    return None


def _normalize(vector: Sequence[float]) -> Matrix:
    array = np.asarray(vector, dtype=np.float32).reshape(1, -1)
    norm = float(np.linalg.norm(array)) or 1.0
    return array / norm


class SkillSelector:
    def __init__(
        self,
        config: Config,
        skills: Sequence[Skill],
        client: OllamaClient | None = None,
        store: Store | None = None,
        task_vector: Matrix | None = None,
    ) -> None:
        self.config = config
        self.skills = sorted(skills, key=lambda s: s.name)
        self.client = client
        self.store = store
        # Bereits berechnetes Auftrags-Embedding (z. B. aus der RAG-Suche) – spart eine Anfrage
        self.task_vector = task_vector
        self.warnings: list[str] = []

    @property
    def use_embeddings(self) -> bool:
        return (
            self.config.skills.preselect == "triggers+embed"
            and bool(self.config.models.embed)
            and self.client is not None
        )

    def _cache_key(self, skill: Skill) -> str:
        raw = f"{self.config.models.embed}\n{skill.description}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def embedding_scores(self, task: str) -> dict[str, float]:
        """Kosinus Auftrag ↔ Beschreibung. Auftrag + fehlende Beschreibungen in EINER Anfrage."""
        if not self.use_embeddings or not self.skills or self.client is None:
            return {}
        vectors: dict[str, Matrix] = {}
        missing: list[Skill] = []
        for skill in self.skills:
            cached = (
                self.store.get_skill_embedding(skill.name, self._cache_key(skill))
                if (self.store is not None)
                else None
            )
            if cached is None:
                missing.append(skill)
            else:
                vectors[skill.name] = cached
        inputs = [skill.description for skill in missing]
        if self.task_vector is None:
            inputs.insert(0, task)
        raw: list[list[float]] = []
        if inputs:
            try:
                raw = self.client.embed(self.config.models.embed, inputs)
            except OllamaError as exc:
                self.warnings.append(texts.SKILL_EMBED_FAILED.format(error=exc))
                return {}
        if self.task_vector is None:
            task_vector = _normalize(raw.pop(0))
        else:
            task_vector = _normalize(self.task_vector.ravel().tolist())
        for skill, vector in zip(missing, raw, strict=True):
            normalized = _normalize(vector)
            vectors[skill.name] = normalized
            if self.store is not None:
                self.store.set_skill_embedding(skill.name, self._cache_key(skill), normalized)
        return {
            name: float((vector @ task_vector.T).item())
            for name, vector in vectors.items()
            if vector.shape == task_vector.shape
        }

    def rank(self, task: str) -> list[SkillMatch]:
        """Alle Skills mit Score und Grund, sortiert (beste zuerst, dann alphabetisch)."""
        mode = self.config.skills.preselect
        if mode == "off":
            return [SkillMatch(skill, 0.0, texts.SKILL_REASON_OFF) for skill in self.skills]
        embed_scores = self.embedding_scores(task)
        matches: list[SkillMatch] = []
        for skill in self.skills:
            trigger = matching_trigger(task, skill)
            embed_score = embed_scores.get(skill.name)
            if trigger is not None:
                reason = texts.SKILL_REASON_TRIGGER.format(trigger=trigger)
                matches.append(
                    SkillMatch(skill, 1.0, reason, by_trigger=True, similarity=embed_score)
                )
            elif embed_score is not None:
                reason = texts.SKILL_REASON_EMBED.format(score=embed_score)
                matches.append(SkillMatch(skill, embed_score, reason, similarity=embed_score))
            else:
                matches.append(SkillMatch(skill, 0.0, texts.SKILL_REASON_NONE))
        # Bei Gleichstand gewinnt ein Trigger-Treffer vor reiner Ähnlichkeit; haben mehrere
        # Skills einen Trigger-Treffer, entscheidet die Ähnlichkeit, erst dann das Alphabet.
        matches.sort(
            key=lambda m: (-m.score, not m.by_trigger, -(m.similarity or 0.0), m.skill.name)
        )
        return self._mark_auto_load(matches)

    def _mark_auto_load(self, matches: list[SkillMatch]) -> list[SkillMatch]:
        cfg = self.config.skills
        result: list[SkillMatch] = []
        auto = 0
        for match in matches:
            load = match.score >= cfg.auto_load_min_score and auto < cfg.max_auto_load
            auto += int(load)
            result.append(dataclasses.replace(match, auto_load=load))
        return result

    def select(self, task: str) -> list[SkillMatch]:
        """Vorausgewählte Skills für den Systemprompt (höchstens max_listed)."""
        return self.rank(task)[: self.config.skills.max_listed]
