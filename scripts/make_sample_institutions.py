"""Generate the sample institution exports offered in the Import screen.

All three are synthetic and deliberately awkward: different column names, grading
scales, date formats and separators, so the adapter has real work to do. A shared
latent "engagement" value drives the signals and the recorded outcome.

    python scripts/make_sample_institutions.py
"""
import os
import random
from datetime import date, timedelta

import numpy as np
import pandas as pd

OUT = os.path.join("frontend", "public", "samples")
AS_OF = date(2026, 9, 28)
N = 240


def _dropout(rng, engagement):
    return rng.random(len(engagement)) < 1 / (1 + np.exp(2.4 * engagement + 1.1))


def engineering_college(rng):
    e = rng.normal(0, 1, N)
    last = [AS_OF - timedelta(days=int(max(0, d))) for d in rng.exponential(np.clip(5 - 3.5 * e, 0.5, 25))]
    frame = pd.DataFrame({
        "Roll No": [f"21CS{1000 + i}" for i in range(N)],
        "Gender": rng.choice(["Male", "Female"], N, p=[0.62, 0.38]),
        "Branch": rng.choice(["Computer Engg", "Mechanical", "E&TC", "Civil"], N),
        "Semester": rng.choice(["Sem 3", "Sem 5"], N),
        "12th Board": rng.choice(["HSC", "CBSE", "Diploma", "ISC"], N, p=[0.5, 0.3, 0.15, 0.05]),
        "CGPA": np.clip(np.round(7.1 + 1.1 * e + rng.normal(0, 0.5, N), 2), 3.2, 10),
        "Attendance %": [f"{int(v)}%" for v in np.clip(74 + 13 * e + rng.normal(0, 6, N), 20, 100)],
        "Backlogs": np.clip(np.round(0.7 - 0.7 * e + rng.normal(0, 0.5, N)), 0, 7).astype(int),
        "Assignments Submitted": np.clip(np.round(3 + e + rng.normal(0, 0.6, N)), 0, 6).astype(int),
        "Moodle Logins": np.clip(np.round(32 * np.exp(0.55 * e + rng.normal(0, 0.3, N))), 0, None).astype(int),
        "Last Login": [d.strftime("%d-%m-%Y") for d in last],
        "Dropped Out": ["Yes" if x else "No" for x in _dropout(rng, e)],
    })
    frame.to_csv(os.path.join(OUT, "sample-engineering-college.csv"), index=False)


def community_college(rng):
    e = rng.normal(0, 1, N)
    start = date(2026, 8, 24)
    frame = pd.DataFrame({
        "StudentID": [f"C{50000 + i}" for i in range(N)],
        "Sex": rng.choice(["F", "M"], N, p=[0.56, 0.44]),
        "EducationLevel": rng.choice(["High School", "GED", "Associate Degree", "Bachelor's"], N, p=[0.6, 0.2, 0.15, 0.05]),
        "CreditHours": rng.choice([6, 9, 12, 15], N),
        "GPA": np.clip(np.round(2.8 + 0.6 * e + rng.normal(0, 0.3, N), 2), 0, 4),
        "CanvasPageViews": np.clip(np.round(190 * np.exp(0.7 * e + rng.normal(0, 0.3, N))), 0, None).astype(int),
        "DaysActive": np.clip(np.round(13 + 5 * e + rng.normal(0, 2, N)), 0, 28).astype(int),
        "DiscussionPosts": np.clip(np.round(4 + 2.5 * e + rng.normal(0, 1, N)), 0, None).astype(int),
        "QuizAttempts": np.clip(np.round(5 + 2 * e + rng.normal(0, 1, N)), 0, None).astype(int),
        "LateSubmissions": np.clip(np.round(1.4 - 1.2 * e + rng.normal(0, 0.6, N)), 0, None).astype(int),
        "EnrollmentDate": [(start - timedelta(days=int(d))).isoformat() for d in np.clip(rng.gamma(2, 22, N), 0, 200)],
        "TermStart": start.isoformat(),
        "FinalStatus": ["Withdrawn" if x else "Enrolled" for x in _dropout(rng, e)],
    })
    frame.to_csv(os.path.join(OUT, "sample-community-college.csv"), index=False)


def secondary_school(rng):
    e = rng.normal(0, 1, N)
    letters = np.array(["F", "D", "C", "C+", "B", "B+", "A-", "A"])
    idx = np.clip(np.round(4.2 + 1.6 * e + rng.normal(0, 0.7, N)), 0, 7).astype(int)
    frame = pd.DataFrame({
        "Admission No": [f"ADM/{2600 + i}" for i in range(N)],
        "Sex": rng.choice(["Boy", "Girl"], N),
        "Class": rng.choice(["XI-A", "XI-B", "XI-C"], N),
        "Term Grade": letters[idx],
        "Absences": np.clip(np.round(6 - 4 * e + rng.normal(0, 2, N)), 0, None).astype(int),
        "Study Hours": np.clip(np.round(5 + 2 * e + rng.normal(0, 1, N), 1), 0, None),
        "Homework Submitted": [f"{int(v)}/10" for v in np.clip(np.round(6.5 + 2 * e + rng.normal(0, 1, N)), 0, 10)],
        "Failed Subjects": np.clip(np.round(0.6 - 0.8 * e + rng.normal(0, 0.5, N)), 0, 6).astype(int),
    })
    frame.to_csv(os.path.join(OUT, "sample-secondary-school.csv"), index=False, sep=";")


def main():
    os.makedirs(OUT, exist_ok=True)
    engineering_college(np.random.default_rng(11))
    community_college(np.random.default_rng(22))
    secondary_school(np.random.default_rng(33))
    random.seed(0)
    print("Wrote samples to", OUT)


if __name__ == "__main__":
    main()
