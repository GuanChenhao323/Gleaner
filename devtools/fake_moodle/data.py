"""fake_moodle seed data: 3 courses, assignments, college notices, teachers. Times are relative to now so demos always have near-term deadlines."""

from __future__ import annotations

import time
from dataclasses import dataclass, field


@dataclass
class Attachment:
    name: str
    content: bytes

    @property
    def size(self) -> int:
        return len(self.content)


@dataclass
class Assignment:
    id: int
    course_id: int
    name: str
    intro: str
    due: float
    requirements: str = "Submit a PDF online"
    attachments: list[Attachment] = field(default_factory=list)
    modified: float = field(default_factory=time.time)
    visible: bool = True


@dataclass
class Course:
    id: int
    shortname: str
    fullname: str
    teacher: str


@dataclass
class Notice:
    id: int
    title: str
    body: str
    published: float
    category: str = "Academic"
    attachments: list[Attachment] = field(default_factory=list)


@dataclass
class Teacher:
    id: int
    name: str
    title: str
    office: str
    phone: str
    email: str
    courses: list[str]


DAY = 86400


def _at(days: float, hour: int = 23, minute: int = 59) -> float:
    lt = time.localtime(time.time() + days * DAY)
    return time.mktime((lt.tm_year, lt.tm_mon, lt.tm_mday, hour, minute, 0, 0, 0, -1))


def seed() -> dict[str, object]:
    courses = [
        Course(101, "CS3105", "Network Programming", "Jianguo Wang"),
        Course(102, "CS3201", "Operating Systems", "Min Li"),
        Course(103, "MA2004", "Probability and Statistics", "Siyuan Chen"),
    ]
    assigns = [
        Assignment(
            1001,
            101,
            "Lab 1: Socket HTTP server",
            "Build an HTTP/1.1 server with keep-alive and chunked transfer; test with curl and a browser.",
            _at(3),
            "Submit source archive and lab report PDF",
            [Attachment("lab1-guide.pdf", b"%PDF-1.4 lab1 v1")],
        ),
        Assignment(
            1002,
            101,
            "Lab 2: WebSocket chat room",
            "Implement RFC 6455 handshake and frames; finish a multi-user chat room.",
            _at(10),
            "Submit Git repository URL",
            [Attachment("lab2-guide.pdf", b"%PDF-1.4 lab2")],
        ),
        Assignment(
            1003,
            101,
            "Course project proposal",
            "Each team submits a 3–5 page proposal covering topic, roles, and schedule.",
            _at(6, 12, 0),
            "One PDF per team; filename: team-id-proposal.pdf",
        ),
        Assignment(
            1101,
            102,
            "Assignment 3: Process scheduling simulation",
            "Implement FCFS, SJF, and RR in any language and compare average waiting time.",
            _at(4),
            "Submit code and result screenshots",
        ),
        Assignment(1102, 102, "Midterm review problems", "Complete review problems for chapters 1–5 (ungraded).", _at(12)),
        Assignment(
            1201,
            103,
            "Week 7 exercises",
            "Textbook exercises 4.1–4.12 (odd numbers).",
            _at(2, 18, 0),
            "Upload photos; hand in paper copy in class",
        ),
        Assignment(
            1202,
            103,
            "Quiz prep",
            "In-class quiz next Wednesday; scope: random variables and their distributions.",
            _at(8, 10, 0),
        ),
    ]
    notices = [
        Notice(
            1,
            "Fall 2026 midterm exam schedule",
            "Midterms run Nov 9–13. Check the academic system for rooms. For all undergraduates.",
            time.time() - 2 * DAY,
            "Academic",
        ),
        Notice(
            2,
            "CS College 2026 Internet+ Innovation Competition signup",
            "Open to all CS undergraduates. Deadline Nov 15 23:59. Register as a team. Room 305, College building.",
            time.time() - 1 * DAY,
            "Contest",
        ),
        Notice(
            3,
            "Library database trial notice",
            "IEEE Xplore trial access is available through Dec 31.",
            time.time() - 3 * DAY,
            "Service",
        ),
        Notice(
            4,
            "Graduate lecture: Consistency in distributed systems",
            "Friday 3pm in the lecture hall. For graduate students; undergrads welcome.",
            time.time() - 0.5 * DAY,
            "Lecture",
        ),
    ]
    teachers = [
        Teacher(
            1,
            "Jianguo Wang",
            "Associate Professor",
            "CS Building A512",
            "010-6278-1234",
            "wangjg@school.edu",
            ["Network Programming"],
        ),
        Teacher(
            2,
            "Min Li",
            "Professor",
            "CS Building B208",
            "010-6278-2234",
            "limin@school.edu",
            ["Operating Systems"],
        ),
        Teacher(
            3,
            "Siyuan Chen",
            "Lecturer",
            "Science Building 316",
            "010-6278-3234",
            "chensy@school.edu",
            ["Probability and Statistics"],
        ),
    ]
    return {"courses": courses, "assignments": assigns, "notices": notices, "teachers": teachers}
