"""fake_moodle 的种子数据：3 门课、若干作业、学院通知、教师信息。时间相对“现在”生成，保证演示时总有近期截止的作业。"""

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
    requirements: str = "在线提交 PDF 文件"
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
    category: str = "教务"
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
        Course(101, "CS3105", "网络编程", "王建国"),
        Course(102, "CS3201", "操作系统", "李敏"),
        Course(103, "MA2004", "概率论与数理统计", "陈思远"),
    ]
    assigns = [
        Assignment(
            1001,
            101,
            "实验一：基于 socket 的 HTTP 服务器",
            "实现一个支持 keep-alive 与 chunked 的 HTTP/1.1 服务器，并用 curl 和浏览器测试。",
            _at(3),
            "提交源代码压缩包与实验报告 PDF",
            [Attachment("实验一指导书.pdf", b"%PDF-1.4 lab1 v1")],
        ),
        Assignment(
            1002,
            101,
            "实验二：WebSocket 聊天室",
            "基于 RFC 6455 实现握手与帧编解码，完成多人聊天室。",
            _at(10),
            "提交 Git 仓库链接",
            [Attachment("实验二指导书.pdf", b"%PDF-1.4 lab2")],
        ),
        Assignment(
            1003,
            101,
            "课程大作业开题报告",
            "每组提交一份 3–5 页开题报告，说明选题、分工与进度计划。",
            _at(6, 12, 0),
            "每组一份 PDF，文件名：组号-开题报告.pdf",
        ),
        Assignment(
            1101,
            102,
            "作业 3：进程调度模拟",
            "用任意语言实现 FCFS、SJF、RR 三种调度算法并比较平均等待时间。",
            _at(4),
            "提交代码与结果截图",
        ),
        Assignment(1102, 102, "期中复习题", "完成第 1–5 章复习题，不计分。", _at(12)),
        Assignment(
            1201,
            103,
            "第 7 周习题",
            "教材习题 4.1–4.12（奇数题）。",
            _at(2, 18, 0),
            "拍照上传，纸质版课上交",
        ),
        Assignment(
            1202, 103, "小测验准备", "下周三课上小测验，范围：随机变量及其分布。", _at(8, 10, 0)
        ),
    ]
    notices = [
        Notice(
            1,
            "关于2026年秋季学期期中考试安排的通知",
            "各位同学：本学期期中考试将于11月9日至11月13日进行，具体考场安排请登录教务系统查询。面向全体本科生。地点：各教学楼。",
            time.time() - 2 * DAY,
            "教务",
        ),
        Notice(
            2,
            "计算机学院2026年“互联网+”创新创业大赛报名通知",
            "面向计算机学院全体本科生，报名截止时间为11月15日23:59，请以团队形式报名。地点：学院楼 305。",
            time.time() - 1 * DAY,
            "竞赛",
        ),
        Notice(
            3,
            "图书馆数据库试用通知",
            "图书馆新增 IEEE Xplore 试用权限，试用期至12月31日。",
            time.time() - 3 * DAY,
            "服务",
        ),
        Notice(
            4,
            "2024级研究生学术讲座：分布式系统中的一致性",
            "本周五下午3点在学术报告厅举行，面向研究生，欢迎感兴趣的本科生参加。",
            time.time() - 0.5 * DAY,
            "讲座",
        ),
    ]
    teachers = [
        Teacher(
            1,
            "王建国",
            "副教授",
            "计算机楼 A512",
            "010-6278-1234",
            "wangjg@school.edu",
            ["网络编程"],
        ),
        Teacher(
            2, "李敏", "教授", "计算机楼 B208", "010-6278-2234", "limin@school.edu", ["操作系统"]
        ),
        Teacher(
            3,
            "陈思远",
            "讲师",
            "理学楼 316",
            "010-6278-3234",
            "chensy@school.edu",
            ["概率论与数理统计"],
        ),
    ]
    return {"courses": courses, "assignments": assigns, "notices": notices, "teachers": teachers}
