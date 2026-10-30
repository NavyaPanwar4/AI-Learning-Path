import html
import json
from collections import defaultdict
from datetime import date, datetime
from io import BytesIO

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.platypus import (
    HRFlowable,
    KeepTogether,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from app.db.database import SessionLocal
from app.db.models import ActivityLog, QuizAttempt, QuizQuestionHistory, Roadmap
from app.services.auth_service import auth_service
from app.services.dashboard_service import dashboard_service


INK = colors.HexColor("#25282d")
MUTED = colors.HexColor("#686b65")
BORDER = colors.HexColor("#deddd6")
PALE = colors.HexColor("#f5f4ef")
ACCENT = colors.HexColor("#b8644c")
GREEN = colors.HexColor("#4e795f")
WHITE = colors.white


def _text(value, fallback="—"):
    if value is None or str(value).strip() == "":
        return fallback
    return str(value)


def _p(value, style):
    """Escape saved roadmap/user content before inserting it into a PDF paragraph."""
    return Paragraph(html.escape(_text(value)), style)


def _normalize(value):
    return " ".join(str(value or "").casefold().split())


def _format_date(value, include_time=False):
    if not value:
        return "Not set"
    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, date):
        return value.strftime("%d %b %Y")
    else:
        raw = str(value)
        try:
            dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError:
            try:
                return date.fromisoformat(raw[:10]).strftime("%d %b %Y")
            except ValueError:
                return raw
    return dt.strftime("%d %b %Y, %H:%M") if include_time else dt.strftime("%d %b %Y")


class ReportService:
    def _styles(self):
        base = getSampleStyleSheet()
        return {
            "title": ParagraphStyle(
                "ReportTitle", parent=base["Title"], fontName="Helvetica-Bold",
                fontSize=23, leading=27, textColor=INK, alignment=TA_LEFT,
                spaceAfter=5,
            ),
            "subtitle": ParagraphStyle(
                "ReportSubtitle", parent=base["Normal"], fontName="Helvetica",
                fontSize=11, leading=15, textColor=MUTED, spaceAfter=4,
            ),
            "section": ParagraphStyle(
                "ReportSection", parent=base["Heading1"], fontName="Helvetica-Bold",
                fontSize=15, leading=19, textColor=INK, spaceBefore=7, spaceAfter=10,
                keepWithNext=True,
            ),
            "subsection": ParagraphStyle(
                "ReportSubsection", parent=base["Heading2"], fontName="Helvetica-Bold",
                fontSize=10.5, leading=14, textColor=INK, spaceBefore=9, spaceAfter=4,
                keepWithNext=True,
            ),
            "body": ParagraphStyle(
                "ReportBody", parent=base["BodyText"], fontName="Helvetica",
                fontSize=8.5, leading=12, textColor=INK, spaceAfter=4,
            ),
            "small": ParagraphStyle(
                "ReportSmall", parent=base["BodyText"], fontName="Helvetica",
                fontSize=7.5, leading=10, textColor=MUTED, spaceAfter=2,
            ),
            "table": ParagraphStyle(
                "ReportTable", parent=base["BodyText"], fontName="Helvetica",
                fontSize=7.5, leading=9.5, textColor=INK,
            ),
            "table_header": ParagraphStyle(
                "ReportTableHeader", parent=base["BodyText"], fontName="Helvetica-Bold",
                fontSize=7.3, leading=9, textColor=WHITE,
            ),
            "metric_label": ParagraphStyle(
                "MetricLabel", parent=base["Normal"], fontName="Helvetica",
                fontSize=7.4, leading=9, textColor=MUTED, alignment=TA_CENTER,
            ),
            "metric_value": ParagraphStyle(
                "MetricValue", parent=base["Normal"], fontName="Helvetica-Bold",
                fontSize=15, leading=18, textColor=INK, alignment=TA_CENTER,
            ),
            "phase_title": ParagraphStyle(
                "PhaseTitle", parent=base["Heading2"], fontName="Helvetica-Bold",
                fontSize=11, leading=14, textColor=INK, spaceBefore=10, spaceAfter=3,
                keepWithNext=True,
            ),
        }

    def _table_style(self, header=True):
        commands = [
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING", (0, 0), (-1, -1), 6),
            ("RIGHTPADDING", (0, 0), (-1, -1), 6),
            ("TOPPADDING", (0, 0), (-1, -1), 5),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ("GRID", (0, 0), (-1, -1), 0.35, BORDER),
            ("ROWBACKGROUNDS", (0, 1 if header else 0), (-1, -1), [WHITE, PALE]),
        ]
        if header:
            commands.extend([
                ("BACKGROUND", (0, 0), (-1, 0), INK),
                ("TEXTCOLOR", (0, 0), (-1, 0), WHITE),
            ])
        return TableStyle(commands)

    def _page_footer(self, canvas, doc):
        canvas.saveState()
        page_width, _ = letter
        canvas.setStrokeColor(BORDER)
        canvas.setLineWidth(0.5)
        canvas.line(doc.leftMargin, 34, page_width - doc.rightMargin, 34)
        canvas.setFillColor(MUTED)
        canvas.setFont("Helvetica", 7.5)
        canvas.drawString(doc.leftMargin, 21, "Learning Path | Learning Progress Report")
        canvas.drawRightString(page_width - doc.rightMargin, 21, f"Page {doc.page}")
        canvas.restoreState()

    def generate_learning_report(self, user_id: str, goal_id: str) -> bytes:
        db = SessionLocal()
        try:
            roadmap_row = (
                db.query(Roadmap)
                .filter(Roadmap.user_id == str(user_id), Roadmap.goal_id == str(goal_id))
                .first()
            )
            if not roadmap_row:
                raise ValueError("Roadmap not found")
            try:
                roadmap = json.loads(roadmap_row.data)
            except (ValueError, TypeError) as exc:
                raise ValueError("Saved roadmap data is invalid. Please regenerate the roadmap.") from exc

            attempts = (
                db.query(QuizAttempt)
                .filter(QuizAttempt.user_id == str(user_id), QuizAttempt.goal_id == str(goal_id))
                .order_by(QuizAttempt.created_at.desc())
                .all()
            )
            attempt_ids = [row.id for row in attempts]
            question_history = (
                db.query(QuizQuestionHistory)
                .filter(QuizQuestionHistory.attempt_id.in_(attempt_ids))
                .order_by(QuizQuestionHistory.created_at.asc())
                .all()
                if attempt_ids else []
            )
            study_minutes = (
                db.query(ActivityLog)
                .filter(ActivityLog.user_id == str(user_id), ActivityLog.activity_type == "session")
                .with_entities(ActivityLog.duration_minutes)
                .all()
            )
        finally:
            db.close()

        profile = auth_service.get_user_by_id(user_id) or {}
        all_mastery = dashboard_service._skills_mastery(user_id) or []
        mastery_by_name = {_normalize(item.get("skill_name")): item for item in all_mastery}
        phases = roadmap.get("phases") if isinstance(roadmap.get("phases"), list) else []
        attempts_by_id = {attempt.id: attempt for attempt in attempts}

        skill_names = []
        for phase in phases:
            for name in phase.get("skills", []) or []:
                clean_name = str(name).strip()
                if clean_name and _normalize(clean_name) not in {_normalize(value) for value in skill_names}:
                    skill_names.append(clean_name)

        completed_phases = sum(1 for phase in phases if phase.get("completed"))
        total_phase_skills = sum(len(set(phase.get("skills", []) or [])) for phase in phases)
        completed_phase_skills = sum(
            len(set(phase.get("skills", []) or [])) for phase in phases if phase.get("completed")
        )
        skill_coverage = round(completed_phase_skills * 100 / total_phase_skills) if total_phase_skills else 0
        phase_progress = round(completed_phases * 100 / len(phases)) if phases else 0
        total_questions = sum(int(attempt.total_questions or 0) for attempt in attempts)
        total_correct = sum(int(attempt.correct_answers or 0) for attempt in attempts)
        average_score = round(sum(attempt.score_pct for attempt in attempts) / len(attempts)) if attempts else None
        best_score = max((attempt.score_pct for attempt in attempts), default=None)
        latest_score = attempts[0].score_pct if attempts else None
        recorded_question_total = len(question_history)
        recorded_question_correct = sum(1 for row in question_history if row.is_correct)
        recorded_accuracy = round(recorded_question_correct * 100 / recorded_question_total) if recorded_question_total else None
        total_study_minutes = round(sum(float(row[0] or 0) for row in study_minutes))
        roadmap_complete = bool(roadmap.get("is_complete") or roadmap_row.is_complete)

        questions_by_skill = defaultdict(lambda: {"total": 0, "correct": 0})
        questions_by_phase = defaultdict(lambda: {"total": 0, "correct": 0})
        for entry in question_history:
            label = str(entry.skill_name or "Unassigned skill").strip()
            questions_by_skill[label]["total"] += 1
            questions_by_skill[label]["correct"] += int(bool(entry.is_correct))
            attempt = attempts_by_id.get(entry.attempt_id)
            if attempt:
                questions_by_phase[attempt.phase_index]["total"] += 1
                questions_by_phase[attempt.phase_index]["correct"] += int(bool(entry.is_correct))

        attempts_by_phase = defaultdict(list)
        for attempt in attempts:
            attempts_by_phase[attempt.phase_index].append(attempt)

        output = BytesIO()
        styles = self._styles()
        page_width, _ = letter
        usable_width = page_width - 92
        doc = SimpleDocTemplate(
            output,
            pagesize=letter,
            rightMargin=46,
            leftMargin=46,
            topMargin=44,
            bottomMargin=46,
            title="Learning Progress Report",
            author="Learning Path",
        )
        story = []
        learner_name = profile.get("username") or "Learner"
        goal_name = roadmap_row.goal_name or roadmap.get("goal_name") or "Personalized learning path"

        story.append(Paragraph("Learning Progress Report", styles["title"]))
        story.append(Paragraph(html.escape(str(goal_name)), styles["subtitle"]))
        story.append(Paragraph(
            f"Learner: {html.escape(str(learner_name))} &nbsp;&nbsp; | &nbsp;&nbsp; "
            f"Generated: {datetime.now().strftime('%d %b %Y, %H:%M')}",
            styles["small"],
        ))
        story.append(HRFlowable(width="100%", thickness=1, color=BORDER, spaceBefore=8, spaceAfter=12))

        story.append(Paragraph("Learning snapshot", styles["section"]))
        details = [
            ["Roadmap status", "Target completion date", "Created", "Last updated"],
            ["Completed" if roadmap_complete else "In progress", _format_date(roadmap.get("deadline")), _format_date(roadmap_row.created_at), _format_date(roadmap_row.updated_at)],
        ]
        details_table = Table(
            [[_p(cell, styles["table_header"] if ri == 0 else styles["table"]) for cell in row] for ri, row in enumerate(details)],
            colWidths=[usable_width * 0.25] * 4,
            repeatRows=1,
        )
        details_table.setStyle(self._table_style(header=True))
        story.extend([details_table, Spacer(1, 12)])

        metrics = [
            ("Phase progress", f"{completed_phases}/{len(phases)}", f"{phase_progress}% complete"),
            ("Skill coverage", f"{completed_phase_skills}/{total_phase_skills}", f"{skill_coverage}% covered by completed phases"),
            ("Quiz attempts", str(len(attempts)), "Recorded for this roadmap"),
            ("Average quiz score", f"{average_score}%" if average_score is not None else "N/A", "Across all recorded attempts"),
            ("Best / latest score", f"{best_score if best_score is not None else 'N/A'}% / {latest_score if latest_score is not None else 'N/A'}%", "Best and most recent attempt"),
            ("Answers correct", f"{total_correct}/{total_questions}" if total_questions else "N/A", f"Question-log accuracy: {recorded_accuracy}%" if recorded_accuracy is not None else "No question-level log yet"),
        ]
        metric_cells = []
        for label, value, desc in metrics:
            metric_cells.append([
                Paragraph(html.escape(label), styles["metric_label"]),
                Paragraph(html.escape(value), styles["metric_value"]),
                Paragraph(html.escape(desc), styles["small"]),
            ])
        metric_cards = [
            Table([[paragraph] for paragraph in card], colWidths=[usable_width / 3 - 14])
            for card in metric_cells
        ]
        metric_rows = [[metric_cards[0], metric_cards[1], metric_cards[2]], [metric_cards[3], metric_cards[4], metric_cards[5]]]
        metric_table = Table(metric_rows, colWidths=[usable_width / 3] * 3)
        metric_table.setStyle(TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("BACKGROUND", (0, 0), (-1, -1), PALE),
            ("BOX", (0, 0), (-1, -1), 0.5, BORDER),
            ("INNERGRID", (0, 0), (-1, -1), 0.4, BORDER),
            ("LEFTPADDING", (0, 0), (-1, -1), 7),
            ("RIGHTPADDING", (0, 0), (-1, -1), 7),
            ("TOPPADDING", (0, 0), (-1, -1), 8),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
        ]))
        story.extend([metric_table, Spacer(1, 12)])

        story.append(Paragraph("Phase overview", styles["section"]))
        phase_header = ["#", "Phase", "Status", "Duration", "Skills", "Resources", "Projects"]
        phase_rows = [[_p(value, styles["table_header"]) for value in phase_header]]
        for index, phase in enumerate(phases):
            phase_rows.append([
                _p(str(index + 1), styles["table"]),
                _p(phase.get("title", "Untitled phase"), styles["table"]),
                _p("Completed" if phase.get("completed") else "In progress", styles["table"]),
                _p(phase.get("duration", "—"), styles["table"]),
                _p(str(len(set(phase.get("skills", []) or []))), styles["table"]),
                _p(str(len(phase.get("resources", []) or [])), styles["table"]),
                _p(str(len(phase.get("projects", []) or [])), styles["table"]),
            ])
        if len(phase_rows) == 1:
            phase_rows.append([_p("No phases saved", styles["table"])] + [""] * 6)
        phase_table = Table(
            phase_rows,
            colWidths=[22, 166, 67, 62, 55, 62, 54],
            repeatRows=1,
            hAlign="LEFT",
        )
        phase_table.setStyle(self._table_style(header=True))
        story.append(phase_table)

        # A detailed skill page avoids truncating the learner's roadmap to the top 8 skills.
        story.append(PageBreak())
        story.append(Paragraph("Skill mastery and quiz performance", styles["section"]))
        story.append(Paragraph(
            "Mastery is based on the learner profile's recorded skill estimates. A skill without a recorded estimate is shown as Not assessed rather than assigned a guessed score.",
            styles["body"],
        ))
        mastery_rows = [[_p(value, styles["table_header"]) for value in ["Roadmap skill", "Mastery", "Question accuracy", "Questions", "Status"]]]
        if not skill_names:
            mastery_rows.append([_p("No roadmap skills were found", styles["table"]), "", "", "", ""])
        for skill_name in skill_names:
            mastery = mastery_by_name.get(_normalize(skill_name))
            mastery_pct = mastery.get("mastery_pct") if mastery else None
            q = questions_by_skill.get(skill_name, {"total": 0, "correct": 0})
            # Match history case-insensitively if stored labels differ in capitalization.
            if not q["total"]:
                for logged_name, logged_values in questions_by_skill.items():
                    if _normalize(logged_name) == _normalize(skill_name):
                        q = logged_values
                        break
            accuracy = round(q["correct"] * 100 / q["total"]) if q["total"] else None
            mastery_rows.append([
                _p(skill_name, styles["table"]),
                _p(f"{mastery_pct}%" if mastery_pct is not None else "Not assessed", styles["table"]),
                _p(f"{accuracy}%" if accuracy is not None else "No quiz data", styles["table"]),
                _p(str(q["total"]), styles["table"]),
                _p("Mastered" if mastery_pct is not None and mastery_pct >= 80 else "Developing" if mastery_pct is not None and mastery_pct >= 50 else "Needs practice" if mastery_pct is not None else "Not assessed", styles["table"]),
            ])
        mastery_table = Table(mastery_rows, colWidths=[190, 66, 100, 58, 74], repeatRows=1)
        mastery_table.setStyle(self._table_style(header=True))
        story.append(mastery_table)
        story.append(Spacer(1, 12))

        story.append(Paragraph("Quiz results by phase", styles["section"]))
        phase_score_rows = [[_p(value, styles["table_header"]) for value in ["Phase", "Attempts", "Average", "Best", "Question accuracy"]]]
        for index, phase in enumerate(phases):
            phase_attempts = attempts_by_phase.get(index, [])
            scores = [item.score_pct for item in phase_attempts]
            qstats = questions_by_phase.get(index, {"total": 0, "correct": 0})
            qacc = round(qstats["correct"] * 100 / qstats["total"]) if qstats["total"] else None
            phase_score_rows.append([
                _p(phase.get("title", f"Phase {index + 1}"), styles["table"]),
                _p(str(len(phase_attempts)), styles["table"]),
                _p(f"{round(sum(scores) / len(scores))}%" if scores else "N/A", styles["table"]),
                _p(f"{max(scores)}%" if scores else "N/A", styles["table"]),
                _p(f"{qacc}% ({qstats['correct']}/{qstats['total']})" if qacc is not None else "No question log", styles["table"]),
            ])
        if len(phase_score_rows) == 1:
            phase_score_rows.append([_p("No phases saved", styles["table"]), "", "", "", ""])
        phase_score_table = Table(phase_score_rows, colWidths=[202, 58, 66, 58, 104], repeatRows=1)
        phase_score_table.setStyle(self._table_style(header=True))
        story.append(phase_score_table)
        story.append(Spacer(1, 12))

        if questions_by_skill:
            story.append(Paragraph("Question-level results by skill", styles["section"]))
            history_rows = [[_p(value, styles["table_header"]) for value in ["Skill", "Correct", "Attempted", "Accuracy"]]]
            for skill_name, stats in sorted(questions_by_skill.items(), key=lambda item: (item[1]["correct"] / item[1]["total"] if item[1]["total"] else -1, item[0].casefold())):
                accuracy = round(stats["correct"] * 100 / stats["total"]) if stats["total"] else 0
                history_rows.append([
                    _p(skill_name, styles["table"]),
                    _p(str(stats["correct"]), styles["table"]),
                    _p(str(stats["total"]), styles["table"]),
                    _p(f"{accuracy}%", styles["table"]),
                ])
            history_table = Table(history_rows, colWidths=[250, 80, 80, 78], repeatRows=1)
            history_table.setStyle(self._table_style(header=True))
            story.append(history_table)
        else:
            story.append(Paragraph("No question-by-question history is recorded yet. Future submitted quizzes will appear here when the application stores per-question results.", styles["small"]))

        # Include detailed phase contents, not only phase names and completion state.
        story.append(PageBreak())
        story.append(Paragraph("Detailed roadmap plan", styles["section"]))
        for index, phase in enumerate(phases):
            phase_title = _text(phase.get("title"), f"Phase {index + 1}")
            phase_bits = [
                Paragraph(f"Phase {index + 1}: {html.escape(phase_title)}", styles["phase_title"]),
                Paragraph(
                    f"Status: <b>{'Completed' if phase.get('completed') else 'In progress'}</b>"
                    f" &nbsp; | &nbsp; Duration: <b>{html.escape(_text(phase.get('duration'), 'Not specified'))}</b>"
                    f" &nbsp; | &nbsp; Remedial phase: <b>{'Yes' if phase.get('is_remedial') else 'No'}</b>",
                    styles["body"],
                ),
            ]
            skills = [str(value) for value in (phase.get("skills", []) or []) if str(value).strip()]
            phase_bits.append(Paragraph(f"<b>Skills:</b> {html.escape(', '.join(skills) if skills else 'No skills listed')}", styles["body"]))
            story.append(KeepTogether(phase_bits))

            resources = phase.get("resources", []) or []
            story.append(Paragraph(f"Learning resources ({len(resources)})", styles["subsection"]))
            if resources:
                for resource in resources:
                    if isinstance(resource, dict):
                        title = _text(resource.get("title"), "Untitled resource")
                        rtype = _text(resource.get("type"), "Resource")
                        url = str(resource.get("url") or "").strip()
                        line = f"<b>{html.escape(title)}</b> ({html.escape(rtype)})"
                        if url:
                            line += f"<br/><font color='#686b65' size='7'>{html.escape(url)}</font>"
                        story.append(Paragraph(line, styles["body"]))
                    else:
                        story.append(_p(resource, styles["body"]))
            else:
                story.append(Paragraph("No resources listed for this phase.", styles["small"]))

            projects = phase.get("projects", []) or []
            story.append(Paragraph(f"Projects and practice ({len(projects)})", styles["subsection"]))
            if projects:
                for project in projects:
                    if isinstance(project, dict):
                        title = _text(project.get("title"), "Untitled project")
                        story.append(Paragraph(f"<b>{html.escape(title)}</b>", styles["body"]))
                        if project.get("description"):
                            story.append(_p(project.get("description"), styles["body"]))
                    else:
                        story.append(_p(project, styles["body"]))
            else:
                story.append(Paragraph("No project or practice task listed for this phase.", styles["small"]))
            story.append(Spacer(1, 6))

        story.append(PageBreak())
        story.append(Paragraph("Quiz attempt history", styles["section"]))
        if attempts:
            attempt_rows = [[_p(value, styles["table_header"]) for value in ["Date", "Phase", "Score", "Correct answers"]]]
            for attempt in attempts:
                phase_by_id = {phase.get("phase_id"): phase for phase in phases if phase.get("phase_id")}
                matched_phase = phase_by_id.get(getattr(attempt, "phase_id", None))
                if matched_phase is not None:
                    phase_title = matched_phase.get("title", "Archived phase")
                elif getattr(attempt, "phase_id", None):
                    phase_title = "Archived phase"
                elif 0 <= attempt.phase_index < len(phases):
                    phase_title = phases[attempt.phase_index].get("title", f"Phase {attempt.phase_index + 1}")
                else:
                    phase_title = f"Archived phase {attempt.phase_index + 1}"
                attempt_rows.append([
                    _p(_format_date(attempt.created_at, include_time=True), styles["table"]),
                    _p(phase_title, styles["table"]),
                    _p(f"{attempt.score_pct}%", styles["table"]),
                    _p(f"{attempt.correct_answers}/{attempt.total_questions}", styles["table"]),
                ])
            attempt_table = Table(attempt_rows, colWidths=[122, 220, 70, 90], repeatRows=1)
            attempt_table.setStyle(self._table_style(header=True))
            story.append(attempt_table)
        else:
            story.append(Paragraph("No quiz attempts have been recorded for this roadmap yet.", styles["body"]))
        story.append(Spacer(1, 12))
        story.append(Paragraph("Report notes", styles["section"]))
        story.append(Paragraph(
            f"Recorded study-session time across the account: {total_study_minutes} minutes. "
            "This time is account-wide because the current activity records do not associate each session with a specific roadmap. "
            "Mastery values are profile estimates and may differ from quiz question accuracy. Quiz/question metrics include only recorded submissions for this roadmap.",
            styles["small"],
        ))

        doc.build(story, onFirstPage=self._page_footer, onLaterPages=self._page_footer)
        return output.getvalue()


report_service = ReportService()
