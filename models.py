#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Maestro - pydantic veri modelleri (Faz 3a).

Durum (state) JSON'u icin elle yazilmis dict kontrolleri yerine pydantic ile
otomatik tip dogrulama ve temizleme. Bozuk/beklenmedik veri gelirse model
guvenli varsayilanlara duser; uygulama kirilmaz.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator


class OrkestraState(BaseModel):
    """Akisin ilerleme durumu (.orkestra_state.json icerigi)."""

    model_config = ConfigDict(extra="ignore")  # bilinmeyen alanlari yok say

    completed: list[int] = Field(default_factory=list)
    last_run: str | None = None
    workflow_hash: str | None = None

    @field_validator("completed", mode="before")
    @classmethod
    def _coerce_completed(cls, value: Any) -> list[int]:
        # int'e cevrilebilen, pozitif ve benzersiz adim indekslerini koru.
        result: list[int] = []
        if isinstance(value, (list, tuple)):
            for item in value:
                try:
                    idx = int(item)
                except (TypeError, ValueError):
                    continue
                if idx > 0 and idx not in result:
                    result.append(idx)
        return result

    @field_validator("last_run", "workflow_hash", mode="before")
    @classmethod
    def _str_or_none(cls, value: Any) -> str | None:
        # Metin olmayan degerleri (sayi, None, vs.) None'a indir.
        return value if isinstance(value, str) else None

    @classmethod
    def from_raw(cls, raw: Any) -> "OrkestraState":
        """Herhangi bir veriden guvenle model uretir; uygunsuzsa varsayilana duser."""
        if not isinstance(raw, dict):
            return cls()
        try:
            return cls.model_validate(raw)
        except ValidationError:
            return cls()

    def to_dict(self) -> dict[str, Any]:
        """Kodun geri kalani state'i dict olarak kullandigi icin sozluge cevirir."""
        return self.model_dump()
