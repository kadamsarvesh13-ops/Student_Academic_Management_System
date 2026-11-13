# Agile Project Documentation - SRAMS

## Product vision
To develop an intelligent, secure and user-friendly Student Record and Academic Management
System that simplifies institutional administration by providing centralised student
information, automated attendance management, academic performance tracking and
comprehensive reporting.

## Scrum roles (edit names for your team)
| Role | Responsibility |
|---|---|
| Product Owner | Defines features and priorities |
| Scrum Master | Runs the Agile workflow and removes blockers |
| Developer 1 | Frontend and dashboard |
| Developer 2 | Database and backend |
| Developer 3 | Attendance and marks |
| Developer 4 | AI, testing and reports |

## Epics
1. Authentication  2. Student Management  3. Course Management  4. Attendance
5. Marks and Performance  6. Notifications  7. Reporting

## Product backlog (priority, story points)
| # | Epic | User story | Priority | Points |
|---|---|---|---|---|
| 1 | Authentication | As a user I want to log in securely so that only I can access my data | High | 3 |
| 2 | Student Mgmt | As an admin I want to add a student so that records are centralised | High | 3 |
| 3 | Student Mgmt | As an admin I want to search students by name or ID so that I find records quickly | High | 2 |
| 4 | Attendance | As faculty I want to record attendance so that it is accurate and digital | High | 5 |
| 5 | Marks | As faculty I want to enter marks so that results are calculated | High | 5 |
| 6 | Course Mgmt | As an admin I want to manage courses and assign faculty | Medium | 3 |
| 7 | Attendance | As faculty/student I want attendance reports | Medium | 5 |
| 8 | Marks | As a student I want grades calculated automatically | Medium | 3 |
| 9 | Notifications | As a student I want low-attendance and result alerts | Medium | 5 |
| 10 | Reporting | As an admin I want PDF/Excel/CSV reports | Medium | 5 |
| 11 | Marks | As faculty I want to see students at academic risk (AI prediction) | Low | 8 |
| 12 | Marks | As a student I want an assistant to answer questions on my records | Low | 8 |

## Acceptance criteria
| Story | Acceptance criteria | Where it is tested |
|---|---|---|
| Login | Registered users can log in; wrong password is rejected; 5 failures lock the account; passwords are hashed | `tests/test_auth.py` |
| Add student | Admin can save a student with a unique ID; invalid email/mobile/semester are rejected; duplicate email rejected | `tests/test_students.py` |
| Search student | Students are found by name or ID and filtered by department/semester/division | `tests/test_students.py` |
| Attendance | Faculty can save attendance; no duplicate record per student, course and date; future dates rejected; % = present/total x 100 | `tests/test_attendance.py` |
| Marks | Marks above the configured maximum are rejected; marks can be updated | `tests/test_marks.py` |
| Grade calculation | Total, %, grade and SGPA are correct at every grade boundary | `tests/test_marks.py` |
| Course management | Admin can create/update courses, assign faculty, enrol students | `tests/conftest.py` (fixtures) |
| Reports | PDF, Excel and CSV files are generated and open | `tests/test_ai_and_reports.py` |
| Role management | Users can only open pages for their role; students only see their own records | `tests/test_auth.py`, `tests/test_ai_and_reports.py` |
| AI prediction | Model trains from history, reports held-out accuracy, refuses to guess without data | `tests/test_ai_and_reports.py` |

## Sprint plan
| Sprint | Goal | Items | Deliverable |
|---|---|---|---|
| 1 | Authentication and project setup | Project skeleton, database, login, roles, basic dashboard | Working authentication |
| 2 | Student and course management | Student CRUD, search, courses, enrolment | Student and course modules |
| 3 | Attendance and marks | Attendance, percentage, marks, grades | Academic management modules |
| 4 | Analytics and reporting | Dashboard, PDF/Excel reports, notifications | Reporting system |
| 5 | AI and deployment | Prediction model, chatbot, testing, deployment | Complete prototype |

## Scrum board (template - update as your team works)
| Backlog | To do | In progress | Done |
|---|---|---|---|
| | | | |

The code in this repository implements all items above; your team should move cards on the board
as you review and demonstrate each one.

## Scrum ceremonies
* **Sprint planning** - pick stories for the sprint from the backlog and estimate points.
* **Daily stand-up** (15 min) - what I did, what I will do, blockers.
* **Sprint review** - demo the increment to the Product Owner.
* **Sprint retrospective** - what went well, what to improve.
* **Backlog refinement** - re-prioritise and re-estimate stories.
