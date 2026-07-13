"""
Conformance Report (G4)

Generates machine-readable and human-readable conformance reports.
"""

import json
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from envelope.verification.conformance import ConformanceRunResult, TestResult
from envelope.verification.golden_set import GoldenSetResult


@dataclass
class ConformanceReport:
    """
    Complete conformance report.

    Combines conformance test results, golden set results,
    and system status into a comprehensive report.
    """
    report_id: UUID
    generated_at: datetime
    manifest_name: str
    manifest_version: str
    conformance_results: ConformanceRunResult | None = None
    golden_set_results: list[GoldenSetResult] = field(default_factory=list)
    system_status: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def overall_pass(self) -> bool:
        """Check if all tests passed."""
        if self.conformance_results and not self.conformance_results.success:
            return False

        for gs_result in self.golden_set_results:
            if not gs_result.success:
                return False

        return True

    @property
    def summary(self) -> dict[str, Any]:
        """Get summary of results."""
        conformance_passed = 0
        conformance_failed = 0
        conformance_total = 0

        if self.conformance_results:
            conformance_passed = self.conformance_results.passed
            conformance_failed = self.conformance_results.failed
            conformance_total = self.conformance_results.total

        golden_passed = sum(r.passed for r in self.golden_set_results)
        golden_failed = sum(r.failed for r in self.golden_set_results)
        golden_total = sum(r.total for r in self.golden_set_results)

        return {
            "overall_pass": self.overall_pass,
            "conformance": {
                "passed": conformance_passed,
                "failed": conformance_failed,
                "total": conformance_total,
            },
            "golden_sets": {
                "passed": golden_passed,
                "failed": golden_failed,
                "total": golden_total,
                "sets_count": len(self.golden_set_results),
            },
        }

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "report_id": str(self.report_id),
            "generated_at": self.generated_at.isoformat(),
            "manifest": {
                "name": self.manifest_name,
                "version": self.manifest_version,
            },
            "overall_pass": self.overall_pass,
            "summary": self.summary,
            "conformance_results": (
                {
                    "run_id": str(self.conformance_results.run_id),
                    "passed": self.conformance_results.passed,
                    "failed": self.conformance_results.failed,
                    "skipped": self.conformance_results.skipped,
                    "errors": self.conformance_results.errors,
                    "duration_ms": self.conformance_results.duration_ms,
                    "executions": [
                        {
                            "test_id": e.test_id,
                            "result": e.result.value,
                            "message": e.message,
                            "duration_ms": e.duration_ms,
                        }
                        for e in self.conformance_results.executions
                    ],
                }
                if self.conformance_results
                else None
            ),
            "golden_set_results": [
                {
                    "run_id": str(r.run_id),
                    "set_name": r.set_name,
                    "passed": r.passed,
                    "failed": r.failed,
                    "duration_ms": r.duration_ms,
                    "executions": [
                        {
                            "test_id": e.test_id,
                            "passed": e.passed,
                            "message": e.message,
                            "duration_ms": e.duration_ms,
                        }
                        for e in r.executions
                    ],
                }
                for r in self.golden_set_results
            ],
            "system_status": self.system_status,
            "metadata": self.metadata,
        }

    def to_json(self, indent: int = 2) -> str:
        """Convert to JSON string."""
        return json.dumps(self.to_dict(), indent=indent)


class ReportGenerator:
    """
    Generator for conformance reports.

    Creates reports from test results with multiple output formats.
    """

    def __init__(
        self,
        manifest_name: str = "",
        manifest_version: str = "",
    ):
        self._manifest_name = manifest_name
        self._manifest_version = manifest_version

    def generate(
        self,
        conformance_results: ConformanceRunResult | None = None,
        golden_set_results: list[GoldenSetResult] | None = None,
        system_status: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> ConformanceReport:
        """Generate a conformance report."""
        return ConformanceReport(
            report_id=uuid4(),
            generated_at=datetime.utcnow(),
            manifest_name=self._manifest_name,
            manifest_version=self._manifest_version,
            conformance_results=conformance_results,
            golden_set_results=golden_set_results or [],
            system_status=system_status or {},
            metadata=metadata or {},
        )

    def render_html(self, report: ConformanceReport) -> str:
        """Render report as HTML."""
        status_class = "pass" if report.overall_pass else "fail"
        status_text = "PASSED" if report.overall_pass else "FAILED"

        conformance_rows = ""
        if report.conformance_results:
            for e in report.conformance_results.executions:
                row_class = "pass" if e.result == TestResult.PASSED else "fail"
                conformance_rows += f"""
                <tr class="{row_class}">
                    <td>{e.test_id}</td>
                    <td>{e.result.value}</td>
                    <td>{e.message}</td>
                    <td>{e.duration_ms:.1f}ms</td>
                </tr>
                """

        golden_sections = ""
        for gs_result in report.golden_set_results:
            gs_rows = ""
            for e in gs_result.executions:
                row_class = "pass" if e.passed else "fail"
                gs_rows += f"""
                <tr class="{row_class}">
                    <td>{e.test_id}</td>
                    <td>{"PASSED" if e.passed else "FAILED"}</td>
                    <td>{e.message}</td>
                    <td>{e.duration_ms:.1f}ms</td>
                </tr>
                """

            golden_sections += f"""
            <h3>Golden Set: {gs_result.set_name}</h3>
            <p>Passed: {gs_result.passed}/{gs_result.total}</p>
            <table>
                <tr>
                    <th>Test ID</th>
                    <th>Result</th>
                    <th>Message</th>
                    <th>Duration</th>
                </tr>
                {gs_rows}
            </table>
            """

        summary = report.summary

        html = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <title>Conformance Report - {report.manifest_name}</title>
            <style>
                body {{
                    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
                    margin: 20px;
                    max-width: 1200px;
                }}
                .header {{
                    border-bottom: 2px solid #333;
                    padding-bottom: 10px;
                    margin-bottom: 20px;
                }}
                .status {{ font-size: 24px; font-weight: bold; }}
                .status.pass {{ color: #28a745; }}
                .status.fail {{ color: #dc3545; }}
                table {{
                    border-collapse: collapse;
                    width: 100%;
                    margin: 15px 0;
                }}
                th, td {{
                    border: 1px solid #ddd;
                    padding: 10px;
                    text-align: left;
                }}
                th {{ background-color: #f5f5f5; }}
                .pass {{ background-color: #d4edda; }}
                .fail {{ background-color: #f8d7da; }}
                .summary {{
                    display: flex;
                    gap: 20px;
                    margin: 20px 0;
                }}
                .summary-card {{
                    padding: 15px;
                    border-radius: 5px;
                    background: #f8f9fa;
                    min-width: 150px;
                }}
                .summary-card h4 {{ margin: 0 0 10px 0; }}
                .meta {{
                    color: #666;
                    font-size: 14px;
                }}
            </style>
        </head>
        <body>
            <div class="header">
                <h1>Conformance Report</h1>
                <p class="meta">
                    Manifest: {report.manifest_name} v{report.manifest_version}<br>
                    Generated: {report.generated_at.strftime('%Y-%m-%d %H:%M:%S UTC')}<br>
                    Report ID: {report.report_id}
                </p>
            </div>

            <div class="status {status_class}">
                Overall Status: {status_text}
            </div>

            <div class="summary">
                <div class="summary-card">
                    <h4>Conformance Tests</h4>
                    <p>Passed: {summary['conformance']['passed']}</p>
                    <p>Failed: {summary['conformance']['failed']}</p>
                </div>
                <div class="summary-card">
                    <h4>Golden Sets</h4>
                    <p>Passed: {summary['golden_sets']['passed']}</p>
                    <p>Failed: {summary['golden_sets']['failed']}</p>
                </div>
            </div>

            <h2>Conformance Test Results</h2>
            {'<p>No conformance tests run.</p>' if not conformance_rows else f'''
            <table>
                <tr>
                    <th>Test ID</th>
                    <th>Result</th>
                    <th>Message</th>
                    <th>Duration</th>
                </tr>
                {conformance_rows}
            </table>
            '''}

            <h2>Golden Set Results</h2>
            {'<p>No golden set tests run.</p>' if not golden_sections else golden_sections}

            <h2>System Status</h2>
            <pre>{json.dumps(report.system_status, indent=2)}</pre>
        </body>
        </html>
        """
        return html

    def render_markdown(self, report: ConformanceReport) -> str:
        """Render report as Markdown."""
        status = "✅ PASSED" if report.overall_pass else "❌ FAILED"
        summary = report.summary

        md = f"""# Conformance Report

**Manifest:** {report.manifest_name} v{report.manifest_version}
**Generated:** {report.generated_at.strftime('%Y-%m-%d %H:%M:%S UTC')}
**Report ID:** {report.report_id}

## Overall Status: {status}

## Summary

| Category | Passed | Failed | Total |
|----------|--------|--------|-------|
| Conformance | {summary['conformance']['passed']} | {summary['conformance']['failed']} | {summary['conformance']['total']} |
| Golden Sets | {summary['golden_sets']['passed']} | {summary['golden_sets']['failed']} | {summary['golden_sets']['total']} |

## Conformance Test Results

"""

        if report.conformance_results:
            md += "| Test ID | Result | Message | Duration |\n"
            md += "|---------|--------|---------|----------|\n"
            for e in report.conformance_results.executions:
                md += f"| {e.test_id} | {e.result.value} | {e.message} | {e.duration_ms:.1f}ms |\n"
        else:
            md += "*No conformance tests run.*\n"

        md += "\n## Golden Set Results\n\n"

        if report.golden_set_results:
            for gs_result in report.golden_set_results:
                md += f"### {gs_result.set_name}\n\n"
                md += f"Passed: {gs_result.passed}/{gs_result.total}\n\n"
                md += "| Test ID | Result | Message |\n"
                md += "|---------|--------|----------|\n"
                for e in gs_result.executions:
                    result = "✅" if e.passed else "❌"
                    md += f"| {e.test_id} | {result} | {e.message} |\n"
                md += "\n"
        else:
            md += "*No golden set tests run.*\n"

        return md
