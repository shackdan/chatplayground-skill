def is_response_stable(history: list, window: int = 2) -> bool:
    if len(history) < window:
        return False
    recent = history[-window:]
    if any(not text.strip() for text in recent):
        return False
    return len(set(recent)) == 1
