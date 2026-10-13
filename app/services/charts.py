"""Plotly figures for the dashboard."""
import plotly.graph_objects as go


def subject_marks_chart(summary: list) -> go.Figure:
    """summary comes from marks_analysis.subject_summary."""
    fig = go.Figure(go.Bar(
        x=[s["subject_code"] for s in summary],
        y=[round(s["average"], 1) for s in summary],
        customdata=[[s["subject_name"], round(s["highest"], 1), round(s["lowest"], 1), s["students"]] for s in summary],
        hovertemplate="%{customdata[0]}<br>Average: %{y}%<br>Highest: %{customdata[1]}%"
                      "<br>Lowest: %{customdata[2]}%<br>Students: %{customdata[3]}<extra></extra>",
    ))
    fig.update_layout(title="Average marks by subject", xaxis_title="Subject",
                      yaxis_title="Average marks (%)", yaxis_range=[0, 100])
    return fig


def attendance_distribution_chart(distribution: list) -> go.Figure:
    fig = go.Figure(go.Bar(
        x=[d["range"] for d in distribution],
        y=[d["students"] for d in distribution],
    ))
    fig.update_layout(title="Attendance distribution", xaxis_title="Attendance range",
                      yaxis_title="Number of students")
    return fig


def semester_trend_chart(trends: list) -> go.Figure:
    labels = [f"Sem {t['semester']}" for t in trends]
    fig = go.Figure()
    fig.add_bar(name="Average attendance (%)", x=labels, y=[t["average_attendance"] for t in trends])
    fig.add_bar(name="Average marks (%)", x=labels, y=[t["average_marks"] for t in trends])
    fig.update_layout(title="Semester-wise performance", xaxis_title="Semester",
                      yaxis_title="Percent", yaxis_range=[0, 100], barmode="group")
    return fig


def student_attendance_chart(report: list, threshold: float) -> go.Figure:
    """report: rows with subject_code, percentage (from student_dashboard.attendance_for_student)."""
    rows = [r for r in report if r["percentage"] is not None]
    fig = go.Figure(go.Bar(
        x=[r["subject_code"] for r in rows],
        y=[round(r["percentage"], 1) for r in rows],
    ))
    fig.add_hline(y=threshold, line_dash="dash", annotation_text=f"Warning level {threshold:g}%")
    fig.update_layout(title="My attendance by subject", xaxis_title="Subject",
                      yaxis_title="Attendance (%)", yaxis_range=[0, 100])
    return fig


def marks_trend_chart(points: list) -> go.Figure:
    """points from student_dashboard.trend_points: one line per subject."""
    fig = go.Figure()
    for subject in sorted({p["subject_code"] for p in points}):
        subject_points = [p for p in points if p["subject_code"] == subject]
        fig.add_scatter(
            name=subject, mode="lines+markers",
            x=[p["step"] for p in subject_points],
            y=[round(p["percentage"], 1) for p in subject_points],
            text=[p["assessment_name"] for p in subject_points],
            hovertemplate="%{text}<br>%{y}%<extra>" + subject + "</extra>",
        )
    fig.update_layout(title="My marks over time", xaxis_title="Assessment number",
                      yaxis_title="Marks (%)", yaxis_range=[0, 100], xaxis=dict(dtick=1))
    return fig
