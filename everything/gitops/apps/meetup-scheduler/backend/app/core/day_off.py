"""Single source of truth for day-off detection.

Rule: a schedule block represents BUSY time. Off-days are simply absence of a block.
Therefore titles that mean "day off" must never be stored as blocks. Use this
helper to validate inputs at every entry point (manual create/update, pattern unit,
AI-generated actions).
"""

DAY_OFF_KEYWORDS = {"휴무", "비번", "off", "오프"}


def is_day_off_title(title: str | None) -> bool:
    """Return True iff the title (after trimming, case-insensitive) is exactly a
    day-off keyword. Substring matches like '근무 / 휴무' are NOT day-offs — those
    are real working blocks that happen to mention the word.
    """
    if not title:
        return False
    return title.strip().lower() in DAY_OFF_KEYWORDS
