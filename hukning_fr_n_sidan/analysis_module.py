from __future__ import annotations

import math
import statistics

# ---------------------------------------------------------------------------
# Module-level state for detect_rep
# ---------------------------------------------------------------------------
_phase = "ready"          # "ready" | "moving"
_VIS_THRESHOLD = 0.35

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _best_knee_bend(pose_data: dict) -> float:
    l = pose_data.get("left_knee_bend_2d", 0.0) or 0.0
    r = pose_data.get("right_knee_bend_2d", 0.0) or 0.0
    return max(l, r)


def _depth_frames(frames: list) -> list:
    return [f for f in frames if _best_knee_bend(f) > 20.0]


def _avg_shin_angle(frames: list) -> float:
    vals = [max(f.get("left_shin_angle", 0.0) or 0.0, f.get("right_shin_angle", 0.0) or 0.0)
            for f in frames]
    vals = [v for v in vals if v > 1.0]
    return statistics.mean(vals) if vals else 0.0


def _trunk_lean(pose_data: dict) -> float:
    """Return trunk lean from vertical (0=upright). Uses trunk_lean_2d if available."""
    val = pose_data.get("trunk_lean_2d")
    if val is None:
        val = pose_data.get("trunk_lean_angle", 0.0)
    return val or 0.0


# ---------------------------------------------------------------------------
# Public interface
# ---------------------------------------------------------------------------

def get_instructions() -> list[str]:
    return [
        "Ställ dig med ena sidan mot kameran.",
        "Utför lugna och kontrollerade hukningar ned till minst 90 grader i knäleden."
    ]


def reset_round():
    global _phase
    _phase = "ready"


def detect_rep(pose_data: dict) -> bool:
    global _phase

    # Start threshold: knee barely bent (< 15°) → patient is standing
    # Moving threshold: knee bent beyond 25° → patient has started a squat
    knee_bend = _best_knee_bend(pose_data)

    if _phase == "ready":
        if knee_bend > 25.0:
            _phase = "moving"
            return False

    elif _phase == "moving":
        if knee_bend < 15.0:
            _phase = "ready"
            return True

    return False


def generate_rep_feedback(rep_data: dict) -> list[str]:
    frames = rep_data.get("frames", [])
    rep_number = rep_data.get("rep_number", 1)

    feedback = []
    feedback.append(f"Rep {rep_number} klar.")

    if not frames:
        return feedback

    # --- Depth check (knee bend should reach at least 90°) ---
    knee_bends = [_best_knee_bend(f) for f in frames]
    max_knee_bend = max(knee_bends) if knee_bends else 0.0

    if max_knee_bend < 90.0:
        feedback.append("Försök att böja knäna lite mer – sikta på minst 90 graders böjning i knäleden.")
    else:
        feedback.append("Bra djup på hukningen!")

    # --- Trunk lean check (25–45 degrees from vertical) ---
    bent_frames = _depth_frames(frames)
    if bent_frames:
        trunk_leans = [_trunk_lean(f) for f in bent_frames]
        trunk_leans = [v for v in trunk_leans if v > 0.5]
        if trunk_leans:
            avg_trunk = statistics.mean(trunk_leans)
            if avg_trunk < 25.0:
                feedback.append("Du är lite för upprätt i överkroppen – luta dig något mer framåt när du hukar.")
            elif avg_trunk > 45.0:
                feedback.append("Du lutar överkroppen för mycket framåt – försök hålla ryggen mer upprätt.")

    # --- Knees over toes check (shin angle) ---
    avg_shin = _avg_shin_angle(bent_frames if bent_frames else frames)
    if avg_shin > 30.0:
        feedback.append("Skjut höfterna bakåt – knäna rör sig för långt framför tårna.")

    if len(feedback) == 2 and "Bra djup" in feedback[1]:
        feedback.append("Fortsätt så – håll rörelsen lugn och kontrollerad.")

    return feedback


def get_session_summary(session_data: dict) -> list[str]:
    total_reps = session_data.get("total_reps", 0)
    rounds = session_data.get("rounds", [])
    round_feedback = session_data.get("round_feedback", [])

    lines = []

    if total_reps == 0:
        lines.append("Inga repetitioner registrerades under passet.")
        lines.append("Ställ dig med sidan mot kameran och utför kontrollerade hukningar ned till minst 90 graders knäböjning.")
        lines.append("Se till att hela kroppen syns i bild och att rörelsen är tydlig.")
        return lines

    lines.append(f"Du genomförde totalt {total_reps} repetitioner under passet. Bra jobbat!")

    # --- Per-round depth analysis ---
    round_peaks = []
    for r in rounds:
        vals = [_best_knee_bend(f) for f in r.get("frames", []) if _best_knee_bend(f) > 5.0]
        round_peaks.append(max(vals) if vals else 0.0)

    depth_threshold = 90.0

    if len(round_peaks) >= 2:
        if round_peaks[-1] > round_peaks[0] + 10.0:
            lines.append("Ditt djup förbättrades under passets gång – bra progression!")
        elif round_peaks[0] > round_peaks[-1] + 10.0:
            lines.append(f"Djupet var bättre i de tidiga omgångarna – försök hålla samma nivå även i de senare omgångarna.")
        elif all(p >= depth_threshold for p in round_peaks):
            lines.append("Du höll ett bra djup i samtliga omgångar – knäböjningen nådde 90 grader konsekvent.")
        elif all(p < depth_threshold for p in round_peaks):
            lines.append("Djupet nådde inte riktigt 90 grader i någon omgång – försök sjunka lite lägre nästa gång.")
        else:
            lines.append("Djupet varierade mellan omgångarna – sikta på 90 graders knäböjning i varje rep.")
    elif len(round_peaks) == 1:
        if round_peaks[0] >= depth_threshold:
            lines.append("Du nådde ett bra djup i hukningen.")
        else:
            lines.append("Försök sjunka lite djupare nästa gång – sikta på 90 graders böjning i knäleden.")

    # --- Trunk lean feedback from round feedback ---
    trunk_issues = sum(
        1 for fb_list in round_feedback
        for fb in fb_list
        if "lutar" in fb or "upprätt" in fb
    )
    shin_issues = sum(
        1 for fb_list in round_feedback
        for fb in fb_list
        if "knäna" in fb and "tår" in fb
    )

    if trunk_issues > 0 and trunk_issues == len(round_feedback):
        lines.append("Överkroppens lutning var ett återkommande tema – kom ihåg att hålla lutningen mellan 25 och 45 grader.")
    elif trunk_issues > 0 and round_feedback and trunk_issues < len(round_feedback):
        lines.append("Överkroppslutningen förbättrades under passet – fortsätt med det!")

    if shin_issues > 0 and shin_issues == len(round_feedback):
        lines.append("Knäna rörde sig för långt framför tårna i flera omgångar – tänk på att skjuta höfterna bakåt.")

    # --- Positive close if no major issues ---
    if trunk_issues == 0 and shin_issues == 0:
        lines.append("Din teknik såg bra ut – bra balans och kontroll i rörelsen.")

    lines.append("Bra avslutat pass!")

    return lines


def get_relevant_joints() -> list:
    return [
        ("Knäböjning", "left_knee_bend_2d"),
        ("Bållutning", "trunk_lean_2d"),
    ]