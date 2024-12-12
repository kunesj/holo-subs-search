from __future__ import annotations

import typing

from .audio_item import AudioItem
from .base_item import BaseItem
from .diarization_item import DiarizationItem
from .subtitle_item import SubtitleItem, MULTI_LANG

ContentItemType = AudioItem | BaseItem | DiarizationItem | SubtitleItem
CONTENT_ITEM_TYPES = typing.get_args(ContentItemType)
