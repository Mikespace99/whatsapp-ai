"""
Utility for filtering available time slots by the user's expressed
time-of-day preference (morning / afternoon / evening).
"""

# Time-of-day bands: (start_hour_inclusive, end_hour_exclusive)
_BANDS: dict[str, tuple[int, int]] = {
    "morning":   (6,  12),
    "afternoon": (12, 18),
    "evening":   (18, 24),
}


def filter_slots_by_preference(
    slots: list[str],
    preference: str | None,
    n: int = 3,
) -> list[str]:
    """
    Return up to *n* slots that match the user's time-of-day preference.

    Args:
        slots:      List of available slot strings in "HH:MM" format,
                    already sorted chronologically by get_available_slots().
        preference: One of "morning", "afternoon", "evening", or None.
                    When None (no preference expressed), returns the first *n*
                    slots unchanged — preserving previous behaviour.
        n:          Maximum number of slots to return (default 3).

    Returns:
        A list of at most *n* slot strings.
        If a preference is given but no slot falls within that band, falls back
        to the first *n* slots so the user is never shown an empty list.
    """
    if preference and preference in _BANDS:
        start_h, end_h = _BANDS[preference]
        filtered = [
            s for s in slots
            if start_h <= int(s.split(":")[0]) < end_h
        ]
        if filtered:
            return filtered[:n]
        # Preference expressed but no matching slots — fall through to default
        # so the caller can communicate "no afternoon slots" explicitly if needed.
        # Returning [] lets the handler distinguish "no slots at all" from
        # "no slots in preferred band".
        return []

    # No preference → original behaviour
    return slots[:n]
