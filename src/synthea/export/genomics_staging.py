"""Synthetic pathological TNM (8th edition) assignment for the genomics pack.

The platform records staging as asserted and never derives it (D6); this module
belongs to the *generator*. Stock Synthea modules state a stage numeral and
sometimes T/N/M categories that do not agree with each other (for example cT1 cN1
"stage IA"), which would put contradictions into the Spanish reports, so the pack
assigns a coherent, hand-checked combination per site instead. The module's stage
numeral (I-IV) is only used to choose among the combinations.

Sources: AJCC Cancer Staging Manual, 8th edition, anatomic stage groups for breast,
non-small cell lung and colon cancer, and the pathological prognostic grouping for
prostate (T, N, M, PSA and Grade Group). Only combinations that are valid in the 8th
edition are listed; size limits follow the T definitions of that edition.
SYNTHETIC; pending pathologist review of the tables (spec section 6).
"""
import random
import re
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

EDITION = "8"

# T/N/M here are pathological categories without prefix. size is the greatest
# dimension of the invasive tumour in mm where T is size-defined (breast, lung);
# None means the site's T is not size-defined and any plausible size may be drawn.
# nodes is the range of positive regional nodes allowed by the N category.
# (numeral, group, t, n, m, size range, positive node range, psa range, gleason)
_Row = Tuple[str, str, str, str, str, Optional[Tuple[int, int]], Tuple[int, int], Optional[Tuple[float, float]], Optional[str]]

TABLES: Dict[str, List[_Row]] = {
    "breast": [
        ("I", "IA", "T1c", "N0", "M0", (11, 20), (0, 0), None, None),
        ("II", "IIA", "T2", "N0", "M0", (21, 50), (0, 0), None, None),
        ("II", "IIB", "T2", "N1a", "M0", (21, 50), (1, 3), None, None),
        ("III", "IIIA", "T3", "N1a", "M0", (51, 80), (1, 3), None, None),
        ("IV", "IV", "T2", "N1a", "M1", (21, 50), (1, 3), None, None),
    ],
    "lung": [
        ("I", "IA", "T1b", "N0", "M0", (11, 20), (0, 0), None, None),
        ("I", "IA", "T1c", "N0", "M0", (21, 30), (0, 0), None, None),
        ("I", "IB", "T2a", "N0", "M0", (31, 40), (0, 0), None, None),
        ("II", "IIA", "T2b", "N0", "M0", (41, 50), (0, 0), None, None),
        ("II", "IIB", "T3", "N0", "M0", (51, 70), (0, 0), None, None),
        ("III", "IIIA", "T2a", "N2", "M0", (31, 40), (1, 4), None, None),
        ("IV", "IVB", "T2a", "N1", "M1c", (31, 40), (1, 3), None, None),
    ],
    "colorectal": [
        ("I", "I", "T2", "N0", "M0", None, (0, 0), None, None),
        ("II", "IIA", "T3", "N0", "M0", None, (0, 0), None, None),
        ("II", "IIB", "T4a", "N0", "M0", None, (0, 0), None, None),
        ("III", "IIIA", "T2", "N1a", "M0", None, (1, 1), None, None),
        ("III", "IIIB", "T3", "N1b", "M0", None, (2, 3), None, None),
        ("IV", "IVA", "T3", "N1b", "M1a", None, (2, 3), None, None),
    ],
    # prostate pathological prognostic groups: (T, N, M, PSA, Grade Group); Gleason strings per Grade Group
    "prostate": [
        ("I", "I", "T2", "N0", "M0", None, (0, 0), (4.0, 9.9), "3+3=6"),
        ("II", "IIA", "T2", "N0", "M0", None, (0, 0), (10.0, 19.9), "3+3=6"),
        ("II", "IIB", "T2", "N0", "M0", None, (0, 0), (4.0, 19.9), "3+4=7"),
        ("II", "IIC", "T2", "N0", "M0", None, (0, 0), (4.0, 19.9), "4+3=7"),
        ("III", "IIIA", "T2", "N0", "M0", None, (0, 0), (20.0, 60.0), "3+4=7"),
        ("III", "IIIB", "T3a", "N0", "M0", None, (0, 0), (4.0, 19.9), "3+4=7"),
    ],
}

GRADE_GROUP = {"3+3=6": 1, "3+4=7": 2, "4+3=7": 3, "4+4=8": 4, "4+5=9": 5, "5+5=10": 5}
# colorectal pT is not size-defined; draw within this plausible range
_FREE_SIZE = (15, 55)


@dataclass(frozen=True)
class Staging:
    family: str
    group: str
    t: str
    n: str
    m: str
    size_mm: int
    nodes_positive: int
    nodes_examined: int
    psa: Optional[float] = None
    gleason: Optional[str] = None

    @property
    def grade_group(self) -> Optional[int]:
        return GRADE_GROUP.get(self.gleason) if self.gleason else None

    def clinical(self) -> Dict[str, str]:
        return {"t": "c" + self.t, "n": "c" + self.n, "m": "c" + self.m, "stage": self.group}

    def pathological(self) -> Dict[str, str]:
        return {"t": "p" + self.t, "n": "p" + self.n, "m": "c" + self.m, "stage": self.group}


_NUMERAL = re.compile(r"\b(IV|III|II|I|0)\b")


def numeral_of(text: Optional[str]) -> Optional[str]:
    if not text:
        return None
    m = _NUMERAL.search(text.upper())
    return m.group(1) if m else None


def choose_staging(family: str, seed: str, numeral_hint: Optional[str]) -> Staging:
    rng = random.Random(f"{seed}:staging")
    rows = TABLES[family]
    pool = [r for r in rows if r[0] == numeral_hint] or rows
    numeral, group, t, n, m, size, pos, psa, gleason = rng.choice(pool)
    sz = rng.randint(*(size or _FREE_SIZE)) if family != "prostate" else rng.randint(10, 35)
    npos = rng.randint(*pos)
    if family == "colorectal":
        examined = rng.randint(max(12, npos + 1), 24)
    elif family == "prostate":
        examined = rng.randint(8, 16)
    else:
        examined = rng.randint(max(8, npos + 1), 18)
    return Staging(family, group, t, n, m, sz, npos, examined,
                   round(rng.uniform(*psa), 1) if psa else None, gleason)
