import math
import statistics

# ---------------------------------------------------------------------------
# Module-level state for detect_rep
# ---------------------------------------------------------------------------
_phase = "ready"          # "ready" | "moving"
_rep_count = 0

# Visibility threshold for standard landmarks
_VIS_THRESHOLD = 0.35

# ---------------------------------------------------------------------------
# Thresholds derived from reference video + boundary values
#   knee_bend range: 3–110°  →  30% = ~35°, 60% = ~69°
#   We use loose anatomical thresholds for detect_rep (any recognizable attempt)
#   and boundary values only inside feedback functions.
# ---------------------------------------------------------------------------
_REP_START_BEND   = 20.0   # knee starts to flex (moving phase begins)
_REP_RETURN_BEND  = 15.0   # knee nearly straight again (rep completed)


# ---------------------------------------------------------------------------
# Helpers (verbatim from spec)
# ---------------------------------------------------------------------------

def _best_knee_bend(pose_data: dict) -> float:
    l = pose_data.get("left_knee_bend_2d", 0.0) or 0.0
    r = pose_data.get("right_knee_bend_2d", 0.0) or 0.0
    return max(l, r)


def _depth_frames(frames: list) -> list:
    return [f for f in frames if _best_knee_bend(f) > 20.0]


def _avg_shin_angle(frames: list) -> float:
    vals = [max(f.get("left_shin_angle", 0.0) or 0.0,
                f.get("right_shin_angle", 0.0) or 0.0)
            for f in frames]
    vals = [v for v in vals if v > 1.0]
    return statistics.mean(vals) if vals else 0.0


def _heel_rise(pose_data: dict, side: str = "auto") -> float:
    kpts = pose_data.get("keypoints", {})
    if side == "auto":
        lh = kpts.get("left_heel")
        rh = kpts.get("right_heel")
        lf = kpts.get("left_foot_index")
        rf = kpts.get("right_foot_index")
        l_vis = min(lh[3] if lh else 0, lf[3] if lf else 0)
        r_vis = min(rh[3] if rh else 0, rf[3] if rf else 0)
        side = "left" if l_vis >= r_vis else "right"
    heel = kpts.get(f"{side}_heel")
    foot_index = kpts.get(f"{side}_foot_index")
    if not heel or not foot_index:
        return 0.0
    if min(heel[3], foot_index[3]) < 0.20:
        return 0.0
    return foot_index[1] - heel[1]


def _angle_2d(ax, ay, bx, by, cx, cy) -> float:
    vax, vay = ax - bx, ay - by
    vcx, vcy = cx - bx, cy - by
    mag = math.hypot(vax, vay) * math.hypot(vcx, vcy)
    if mag < 1e-10:
        return 180.0
    return math.degrees(math.acos(max(-1.0, min(1.0, (vax * vcx + vay * vcy) / mag))))


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def get_instructions() -> list:
    return [
        "Stand sideways to the camera with your feet shoulder-width apart.",
        "Perform slow, controlled squats aiming for a 90-degree knee bend, keeping your heels flat and your chest up."
    ]


def detect_rep(pose_data: dict) -> bool:
    """Two-phase state machine: ready → moving → ready."""
    global _phase, _rep_count

    bend = _best_knee_bend(pose_data)

    if _phase == "ready":
        if bend > _REP_START_BEND:
            _phase = "moving"
    elif _phase == "moving":
        if bend < _REP_RETURN_BEND:
            _phase = "ready"
            _rep_count += 1
            return True

    return False


def reset_round():
    global _phase, _rep_count
    _phase = "ready"
    _rep_count = 0


def generate_rep_feedback(rep_data: dict) -> list:
    rep_number = rep_data.get("rep_number", 1)
    frames = rep_data.get("frames", [])

    lines = []

    # --- Opening acknowledgment ---
    lines.append(f"Rep {rep_number} done.")

    if not frames:
        lines.append("Keep going — focus on depth and an upright torso.")
        return lines

    # ------------------------------------------------------------------ #
    # Compute per-rep metrics                                              #
    # ------------------------------------------------------------------ #

    # Maximum knee bend reached this rep
    max_bend = max((_best_knee_bend(f) for f in frames), default=0.0)

    # Torso lean — average across frames where some squat depth is present
    bent_frames = _depth_frames(frames)

    torso_vals = [f.get("trunk_lean_2d", 0.0) or 0.0 for f in (bent_frames if bent_frames else frames)]
    torso_vals = [v for v in torso_vals if v > 1.0]
    avg_torso = statistics.mean(torso_vals) if torso_vals else 0.0

    # Heel rise — only during bent phase
    heel_rise_max = 0.0
    if bent_frames:
        rises = [_heel_rise(f) for f in bent_frames]
        heel_rise_max = max(rises) if rises else 0.0

    # Shin / knees-over-toes
    avg_shin = _avg_shin_angle(bent_frames if bent_frames else frames)

    # Shoulder horizontal drift (side view: x coordinate)
    kpts_list = [f.get("keypoints", {}) for f in frames]
    shoulder_xs = []
    for kpts in kpts_list:
        ls = kpts.get("left_shoulder")
        rs = kpts.get("right_shoulder")
        for s in [ls, rs]:
            if s and s[3] >= _VIS_THRESHOLD:
                shoulder_xs.append(s[0])
    shoulder_drift = (max(shoulder_xs) - min(shoulder_xs)) if len(shoulder_xs) >= 2 else 0.0

    # ------------------------------------------------------------------ #
    # Priority 1 — Heel rise (injury risk)                               #
    # ------------------------------------------------------------------ #
    if heel_rise_max > 0.02:
        lines.append("Your heels lifted off the ground — try to keep them flat throughout the squat.")

    # ------------------------------------------------------------------ #
    # Priority 2 — Knee depth (boundary: bend > 90°)                    #
    # ------------------------------------------------------------------ #
    if max_bend < 90:
        lines.append("Try to squat a little deeper — aim for a 90-degree bend in your knees.")
    else:
        lines.append("Good depth on that rep — you reached the target knee bend.")

    # ------------------------------------------------------------------ #
    # Priority 3 — Knees over toes                                       #
    # ------------------------------------------------------------------ #
    if avg_shin > 30:
        lines.append("Push your hips back a little more — your knees are travelling too far forward over your toes.")

    # ------------------------------------------------------------------ #
    # Priority 4 — Torso lean (boundary: 20–45°)                        #
    # ------------------------------------------------------------------ #
    if avg_torso > 45:
        lines.append("Try to keep your chest more upright — you're leaning forward too much through the squat.")
    elif avg_torso < 20 and max_bend >= 40:
        lines.append("A slight forward lean is perfectly fine — you're staying very upright, which is great.")

    # ------------------------------------------------------------------ #
    # Priority 5 — Shoulder drift (forward/backward sway)               #
    # ------------------------------------------------------------------ #
    if shoulder_drift > 0.12:
        lines.append("Try to keep your shoulders tracking straight up and down without drifting forward or back.")

    # ------------------------------------------------------------------ #
    # Encouragement if no issues found                                   #
    # ------------------------------------------------------------------ #
    if len(lines) == 2:
        # Only opening + depth line so far → no problems detected
        lines.append("Great form — keep your heels down and chest up as you go.")

    return lines


def get_session_summary(session_data: dict) -> list:
    total_reps = session_data.get("total_reps", 0)
    rounds = session_data.get("rounds", [])
    round_feedback = session_data.get("round_feedback", [])

    lines = []

    # ------------------------------------------------------------------ #
    # Zero-rep guard                                                      #
    # ------------------------------------------------------------------ #
    if total_reps == 0:
        lines.append("No reps were completed this session.")
        lines.append("Stand sideways to the camera, bend your knees to a 90-degree squat, and return to standing to register each rep.")
        lines.append("Focus on keeping your heels flat and squatting with control.")
        return lines

    lines.append(f"You completed {total_reps} squat{'s' if total_reps != 1 else ''} this session — well done.")

    # ------------------------------------------------------------------ #
    # Per-round depth progression                                         #
    # ------------------------------------------------------------------ #
    round_peaks = []
    for r in rounds:
        vals = [_best_knee_bend(f) for f in r.get("frames", []) if _best_knee_bend(f) > 5]
        round_peaks.append(max(vals) if vals else 0.0)

    depth_threshold = 90.0

    if len(round_peaks) >= 2:
        first = round_peaks[0]
        last = round_peaks[-1]
        if last > first + 10:
            lines.append("Your squat depth improved as the session went on — great progression.")
        elif first > last + 10:
            lines.append("Your depth was better in the early rounds; fatigue may have crept in toward the end.")
        elif all(p >= depth_threshold for p in round_peaks):
            lines.append("You maintained good squat depth in every round.")
        elif all(p < depth_threshold for p in round_peaks):
            lines.append("Try to squat a little deeper in future sessions — aim for a 90-degree knee bend at the bottom.")
    elif len(round_peaks) == 1:
        if round_peaks[0] >= depth_threshold:
            lines.append("You reached a good squat depth.")
        else:
            lines.append("Next time, focus on squatting a little deeper — aim for a 90-degree knee bend.")

    # ------------------------------------------------------------------ #
    # Persistent issues from round_feedback                              #
    # ------------------------------------------------------------------ #
    heel_issue_rounds = 0
    shin_issue_rounds = 0
    torso_issue_rounds = 0

    for rf in round_feedback:
        rf_text = " ".join(rf).lower() if rf else ""
        if "heel" in rf_text:
            heel_issue_rounds += 1
        if "toes" in rf_text or "shin" in rf_text or "forward" in rf_text:
            shin_issue_rounds += 1
        if "lean" in rf_text or "chest" in rf_text:
            torso_issue_rounds += 1

    num_rounds = max(len(round_feedback), 1)

    if heel_issue_rounds == num_rounds and num_rounds >= 1:
        lines.append("Your heels were lifting throughout the session — working on ankle mobility will help you keep them flat.")
    elif heel_issue_rounds > 0:
        lines.append("There were a few reps where your heels came up — keep focusing on ankle flexibility.")

    if shin_issue_rounds == num_rounds and num_rounds >= 1:
        lines.append("Your knees were consistently travelling too far forward — practise sitting your hips back as you squat.")
    elif shin_issue_rounds > 0:
        lines.append("On some reps your knees moved too far over your toes — try shifting your weight back through your heels.")

    if torso_issue_rounds == num_rounds and num_rounds >= 1:
        lines.append("Keeping your chest more upright will be a key focus for your next session.")
    elif torso_issue_rounds > 0:
        lines.append("There were moments of excessive forward lean — practise bracing your core and keeping your chest up.")

    # ------------------------------------------------------------------ #
    # Check for improvement across rounds on specific issues             #
    # ------------------------------------------------------------------ #
    if (len(round_feedback) >= 2 and
            "heel" in " ".join(round_feedback[0]).lower() and
            "heel" not in " ".join(round_feedback[-1]).lower()):
        lines.append("Your heel control improved during the session — great adjustment.")

    # ------------------------------------------------------------------ #
    # Closing positive observation                                        #
    # ------------------------------------------------------------------ #
    if total_reps >= 5:
        lines.append("You put in a solid effort today — keep building on this in your next session.")
    else:
        lines.append("Keep practising controlled squats to build strength and confidence in the movement.")

    return lines


def get_relevant_joints() -> list:
    return [
        ("Left Knee", "left_knee_bend_2d"),
        ("Right Knee", "right_knee_bend_2d"),
        ("Torso Lean", "trunk_lean_2d"),
    ]