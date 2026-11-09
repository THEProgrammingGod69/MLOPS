"""What each of the model's 21 inputs is called in the wild.

For every model feature this lists the column names other institutions use. ``direct``
names measure the same thing in the same kind of unit. ``proxy`` names measure a related
behaviour on a different scale, so they go through percentile transport (see
``transforms.py``) and count for less in the Institution Fit Score.
"""
from typing import Dict, List

TARGETS: Dict[str, dict] = {
    "highest_education": {"kind": "education", "direct": [
        "highest education", "education", "education level", "qualification", "highest qualification",
        "prior qualification", "entry qualification", "previous education", "highest degree", "prior degree",
        "admission level", "previous qualification", "academic background", "12th board", "10th board", "school board", "board", "previous school"], "proxy": []},
    "num_of_prev_attempts": {"kind": "count", "direct": [
        "num of prev attempts", "previous attempts", "prev attempts", "attempts", "retakes", "repeats",
        "times repeated", "repeat count", "repeated"], "proxy": [
        "backlogs", "history of backlogs", "arrears", "kt", "reappear", "re appear", "supplementary"]},
    "studied_credits": {"kind": "count", "direct": [
        "studied credits", "credits", "credit load", "enrolled credits", "credit hours", "units", "total credits",
        "credits registered", "semester credits", "cu"], "proxy": ["course load", "subjects enrolled", "subjects", "number of courses"]},
    "registration_day": {"kind": "day_offset", "direct": [
        "registration day", "date registration", "days before start", "registration offset", "enrolment offset"],
        "proxy": [], "date": ["registration date", "enrollment date", "enrolment date", "admission date", "date of admission", "joining date", "date registered"]},
    "code_module": {"kind": "module", "direct": ["code module", "module", "module code"], "proxy": [
        "course", "course code", "course id", "subject", "subject code", "department", "program", "programme", "branch", "stream", "major", "class"]},
    "code_presentation": {"kind": "presentation", "direct": ["code presentation", "presentation"], "proxy": [
        "term", "semester", "session", "intake", "batch", "academic year", "cohort"]},
    "module_presentation_length": {"kind": "duration_days", "direct": [
        "module presentation length", "presentation length", "course length", "course length days", "term length", "semester days", "duration days", "module length"],
        "proxy": ["duration weeks", "course weeks", "term weeks", "semester weeks", "duration months"]},
    "asm_submission_count": {"kind": "count", "direct": [
        "asm submission count", "assessments submitted", "assignments submitted", "submissions", "submission count",
        "assignments completed", "assessments completed", "homework submitted", "tests taken", "coursework submitted", "num assignments"], "proxy": []},
    "asm_mean_score": {"kind": "score", "direct": [
        "asm mean score", "mean score", "average score", "avg score", "assessment score", "average marks", "avg marks",
        "marks", "percentage", "internal marks", "internals", "ia marks", "cia", "midterm", "midterm score", "mid sem", "test score",
        "coursework score", "score", "grade percentage", "final percentage", "first period grade", "g1"],
        "proxy": ["gpa", "cgpa", "sgpa", "grade", "letter grade", "grade point", "grades"]},
    "asm_score_std": {"kind": "spread", "direct": ["asm score std", "score std", "score sd", "marks std", "marks sd", "score deviation", "score variance"], "proxy": []},
    "asm_failed_count": {"kind": "count", "direct": [
        "asm failed count", "failed assessments", "failed assignments", "failures", "fails", "failed count", "subjects failed", "courses failed", "failed subjects", "current backlogs"], "proxy": []},
    "asm_average_delay": {"kind": "delay", "direct": [
        "asm average delay", "average delay", "avg delay", "submission delay", "avg days late", "days late", "average days late", "lateness"],
        "proxy": ["late submissions", "late assignments", "late count"]},
    "vle_total_clicks": {"kind": "activity", "direct": [
        "vle total clicks", "total clicks", "clicks", "lms clicks", "vle clicks", "page views", "pageviews", "canvas views", "moodle hits", "lms hits", "portal hits", "total views"],
        "proxy": ["logins", "login count", "total logins", "portal logins", "lms logins", "lms activity", "online activity", "hours online", "lms hours", "time on platform", "study hours", "study time", "studytime"]},
    "vle_active_days": {"kind": "days_0_28", "direct": [
        "vle active days", "active days", "days active", "login days", "days logged in", "days present", "attendance days", "classes attended"],
        "proxy": ["attendance", "attendance percentage", "attendance pct", "attendance rate", "attendance percent", "attendance %", "percent attendance", "presence"]},
    "vle_days_since_last_activity": {"kind": "days_since", "direct": [
        "vle days since last activity", "days since last activity", "days since login", "days since last login", "days inactive", "inactivity days", "last activity days"],
        "proxy": ["days absent", "absences", "absent days", "days absent recently"], "date": ["last login", "last login date", "last activity", "last activity date", "last seen", "last access", "last accessed"]},
    "vle_clicks_last_7_days": {"kind": "activity", "direct": [
        "vle clicks last 7 days", "clicks last 7 days", "clicks 7d", "last 7 days clicks", "weekly clicks", "last week clicks"],
        "proxy": ["logins last week", "weekly logins", "last week activity", "recent activity", "activity last week"]},
    "vle_clicks_last_14_days": {"kind": "activity", "direct": [
        "vle clicks last 14 days", "clicks last 14 days", "clicks 14d", "last 14 days clicks", "two week clicks", "fortnight clicks"],
        "proxy": ["logins last 14 days", "logins last two weeks", "activity last 2 weeks", "biweekly activity"]},
    "vle_forum_clicks": {"kind": "activity", "direct": ["vle forum clicks", "forum clicks", "forum views", "discussion views", "discussion clicks"],
        "proxy": ["forum posts", "discussion posts", "posts", "raisedhands", "raised hands", "participation", "class participation", "discussion", "discussions"]},
    "vle_resource_clicks": {"kind": "activity", "direct": ["vle resource clicks", "resource clicks", "resource views", "resources viewed", "materials viewed", "file views"],
        "proxy": ["visitedresources", "visited resources", "downloads", "file downloads", "materials accessed", "lecture views", "video views", "videos watched", "library visits", "viewannouncements"]},
    "vle_quiz_clicks": {"kind": "activity", "direct": ["vle quiz clicks", "quiz clicks", "quiz views", "quiz attempts", "quizzes attempted", "quizzes taken"],
        "proxy": ["practice tests", "mock tests", "self assessments", "quizzes"]},
    "vle_activity_type_diversity": {"kind": "diversity", "direct": ["vle activity type diversity", "activity type diversity", "activity types", "tools used", "features used", "distinct activities"], "proxy": []},
}

ROLE_COLUMNS: Dict[str, List[str]] = {
    "student_id": ["student id", "id student", "studentid", "student number", "student no", "roll no", "roll number", "rollno",
                   "enrollment no", "enrolment no", "enrollment number", "registration no", "registration number", "reg no", "regno",
                   "usn", "prn", "uid", "admission no", "admission number", "matric", "matric no", "id", "student"],
    "gender": ["gender", "sex", "m f", "male female"],
    "outcome": ["dropout", "dropped out", "dropped", "withdrawn", "withdrew", "is withdrawn", "final result", "final status", "outcome",
                "status", "student status", "target", "attrition", "left", "retained", "graduated", "class label"],
    "as_of": ["as of", "snapshot date", "report date", "extract date", "data date"],
    "course_start": ["course start", "course start date", "term start", "term start date", "semester start", "start date", "class start", "module start"],
}

EDUCATION_RULES = [
    ("Post Graduate Qualification", ["phd", "ph d", "doctor", "master", "m tech", "mtech", "m sc", "msc", "mba", "post grad", "postgrad", "pg", "mca", "m com", "m a"]),
    ("HE Qualification", ["bachelor", "b tech", "btech", "b e", "be", "b sc", "bsc", "b com", "bcom", "b a", "ba", "bca", "degree", "graduate", "undergrad", "ug", "he qualification", "associate", "university", "college", "tertiary", "higher education"]),
    ("A Level or Equivalent", ["a level", "alevel", "12th", "12", "xii", "hsc", "intermediate", "pre university", "pu", "puc", "cbse", "isc", "high school", "secondary school diploma", "ged", "diploma", "polytechnic", "abitur", "baccalaureate", "senior secondary", "plus two", "grade 12"]),
    ("Lower Than A Level", ["lower than", "10th", "10", "x", "ssc", "sslc", "matric", "gcse", "o level", "middle school", "primary school", "secondary", "some high school", "grade 10", "junior"]),
    ("No Formal quals", ["no formal", "none", "no qualification", "uneducated", "illiterate"]),
]

GENDER_VALUES = {"m": "M", "male": "M", "man": "M", "boy": "M", "1": "M", "f": "F", "female": "F", "woman": "F", "girl": "F", "0": "F"}
POSITIVE_OUTCOMES = {"1", "true", "yes", "y", "dropout", "dropped", "dropped out", "withdrawn", "withdrew", "left", "discontinued", "attrited", "inactive", "fail out", "failed out", "attrition"}
NEGATIVE_OUTCOMES = {"0", "false", "no", "n", "enrolled", "active", "graduate", "graduated", "retained", "pass", "passed", "completed", "distinction", "fail", "continuing", "current", "stayed"}
RETAINED_COLUMNS = {"retained", "graduated"}
LETTER_GRADES = {"A+": 97, "A": 93, "A-": 90, "B+": 87, "B": 83, "B-": 80, "C+": 77, "C": 73, "C-": 70, "D+": 67, "D": 63, "D-": 60,
                 "E": 50, "F": 35, "O": 95, "S": 95, "P": 55, "AB": 0, "I": 45, "W": 30}
