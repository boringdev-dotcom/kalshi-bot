"""Matching ESPN's team names to Kalshi's.

The two rarely agree ('Rayo Vallecano' / 'Vallecano', 'Borussia Mönchengladbach' /
'M´gladbach', 'Athletic Club' / 'Bilbao'), and their team codes differ too (Man City is
MNC on ESPN, MCI on Kalshi). A match is found by date and both names together, which
is far more forgiving than matching one name at a time.
"""

from __future__ import annotations

import re
import unicodedata
from difflib import SequenceMatcher

# Words that say nothing about which club it is.
NOISE = {
    "fc", "afc", "cf", "ac", "as", "sc", "ssc", "sv", "us", "rc", "cd", "ud", "sd", "ca", "calcio", "club",
    "de", "la", "le", "the", "and", "hotspur", "albion", "hove", "1", "04", "05", "07", "29", "1899", "1846",
    "vfl", "vfb", "tsg", "fsv", "ogc", "aj", "rcd", "real", "city", "united", "town", "alsace", "stade",
}
# Names one side uses that share nothing with the other's.
ALIASES = {
    "psg": "paris saint germain",
    "inter": "internazionale",
    "bilbao": "athletic",
    "athletic club": "athletic",
    "koln": "cologne",
    "fc koln": "cologne",
    "mgladbach": "monchengladbach",
    "m gladbach": "monchengladbach",
    "man city": "manchester city",
    "man utd": "manchester united",
    "man united": "manchester united",
    "spurs": "tottenham",
    "wolves": "wolverhampton",
    "atletico": "atletico madrid",
    "deportivo de la coruna": "deportivo",
    "hamburg": "hamburg",
    "hamburger": "hamburg",
}


def normalize(name: str) -> str:
    text = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    text = re.sub(r"[^a-z0-9 ]+", " ", text.lower().replace("&", " and "))
    text = re.sub(r"\s+", " ", text).strip()
    return ALIASES.get(text, text)


def _tokens(name: str) -> set[str]:
    return {t for t in normalize(name).split() if t not in NOISE} or set(normalize(name).split())


def similarity(a: str, b: str) -> float:
    """0..1: how surely two names are the same club."""
    na, nb = normalize(a), normalize(b)
    if na == nb:
        return 1.0
    ta, tb = _tokens(a), _tokens(b)
    if ta and tb and (ta <= tb or tb <= ta):
        return 0.9
    jac = len(ta & tb) / len(ta | tb) if ta and tb else 0.0
    return max(jac, 0.8 * SequenceMatcher(None, na, nb).ratio())


def split_title(title: str) -> tuple[str, str]:
    """'Manchester City vs Fulham: Total Goals' -> ('Manchester City', 'Fulham')."""
    head = title.split(":")[0]
    parts = re.split(r"\s+vs\.?\s+", head, maxsplit=1)
    return (parts[0].strip(), parts[1].strip()) if len(parts) == 2 else (head.strip(), "")


def pair_score(home: str, away: str, k_home: str, k_away: str) -> float:
    """How well an ESPN home/away pair matches a Kalshi pair; both must clear a floor."""
    sh, sa = similarity(home, k_home), similarity(away, k_away)
    return 0.0 if min(sh, sa) < 0.45 else sh + sa
