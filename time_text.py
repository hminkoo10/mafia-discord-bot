from __future__ import annotations


def duration_text(seconds: int) -> str:
    if seconds % 60 == 0:
        return f"{seconds // 60}분"
    return f"{seconds}초"


def play_duration_text(seconds: int) -> str:
    minutes = seconds // 60
    if minutes <= 0:
        return "1분 미만"
    return f"{minutes}분"
