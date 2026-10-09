"""
Triage3AM File Handler (v2): High-efficiency streaming file processing,
zero-dependency multipart/form-data parser, dynamic dataset discovery,
safe path resolution, and multi-format incident export.
"""

import os
import io
import re
import gzip
import json
import csv
import zipfile
from pathlib import Path
from typing import Generator, Tuple, Dict, Any, List, Optional, Union

# 100MB default maximum upload size
MAX_UPLOAD_SIZE = 100 * 1024 * 1024


class SafePathManager:
    """Provides path traversal protection and secure file management."""

    @staticmethod
    def resolve_safe_path(base_dir: str, requested_path: str) -> Optional[Path]:
        """Resolves requested_path relative to base_dir, strictly preventing directory traversal."""
        try:
            if not requested_path:
                return None
            clean_name = requested_path.replace('\x00', '').strip()
            # Explicitly reject directory traversal attempts or absolute paths
            if '..' in clean_name or clean_name.startswith('/') or clean_name.startswith('\\'):
                return None
            if os.path.dirname(clean_name):
                return None

            base = Path(base_dir).resolve()
            target = (base / clean_name).resolve()

            # Ensure target is strictly inside base directory
            if base in target.parents or target == base:
                return target
            return None
        except Exception:
            return None

    @staticmethod
    def scan_presets(datasets_dir: str) -> List[Dict[str, Any]]:
        """Dynamically scans dataset directory and generates metadata for all discovered log files."""
        presets = []
        base = Path(datasets_dir)
        if not base.exists() or not base.is_dir():
            return presets

        # Supported log extensions
        valid_extensions = {'.log', '.txt', '.gz', '.json'}
        files = sorted(base.iterdir(), key=lambda p: p.name.lower())

        for file_path in files:
            if file_path.is_file() and any(file_path.name.endswith(ext) for ext in valid_extensions):
                size_bytes = file_path.stat().st_size
                is_gz = file_path.name.endswith('.gz')

                # Sample the file to estimate line count and detect services
                lines_count, services, scenario_type, title, desc = SafePathManager._inspect_log_file(file_path, is_gz)

                presets.append({
                    'id': file_path.name,
                    'title': title,
                    'description': desc,
                    'services': services[:6],
                    'lines': lines_count,
                    'size_bytes': size_bytes,
                    'size_formatted': SafePathManager._format_size(size_bytes),
                    'is_compressed': is_gz,
                    'type': scenario_type
                })

        return presets

    @staticmethod
    def _inspect_log_file(path: Path, is_gz: bool) -> Tuple[int, List[str], str, str, str]:
        """Samples up to 100 lines to infer scenario, services, and line count."""
        lines_sample = []
        total_lines = 0
        services_set = set()

        try:
            opener = gzip.open(path, 'rt', encoding='utf-8', errors='replace') if is_gz else open(path, 'r', encoding='utf-8', errors='replace')
            with opener as f:
                for idx, line in enumerate(f):
                    total_lines += 1
                    if idx < 100:
                        lines_sample.append(line)
                    # Extract service names from brackets e.g. [order-service]
                    svc_match = re.search(r'\[([a-zA-Z0-9_\-]+(?:-service|-api|-worker|-db|-app|-gateway|cluster)?)\]', line)
                    if svc_match:
                        services_set.add(svc_match.group(1).lower())
        except Exception:
            total_lines = total_lines or 1000

        # Title and description inference based on filename or contents
        fname = path.name.lower()
        if 'ecommerce' in fname or 'db' in fname or 'postgres' in fname:
            title = 'Scenario 1: Black Friday Checkout Cascade'
            desc = 'PostgreSQL pool exhaustion cascades into Hikari pool timeout, payment retry storm, and 504 Gateway Timeouts.'
            stype = 'Database Starvation'
        elif 'oom' in fname or 'k8s' in fname or 'crashloop' in fname:
            title = 'Scenario 2: Kubernetes OOMKilled & CrashLoop'
            desc = 'Java Heap OOM kills auth-service pod; kernel oom-killer evicts container, cascading auth failures.'
            stype = 'Memory Exhaustion'
        elif 'redis' in fname or 'cache' in fname or 'stampede' in fname:
            title = 'Scenario 3: Redis Cache Eviction & Stampede'
            desc = 'Redis maxmemory eviction stalls, triggering 450+ concurrent thread stampede on MySQL read-replicas.'
            stype = 'Cache Starvation'
        else:
            clean_name = path.name.replace('.log', '').replace('.gz', '').replace('_', ' ').title()
            title = f"Preset: {clean_name}"
            desc = f"Raw enterprise telemetry dataset with {total_lines:,} lines."
            stype = "System Telemetry"

        return total_lines, sorted(list(services_set)), stype, title, desc

    @staticmethod
    def _format_size(size_bytes: int) -> str:
        for unit in ['B', 'KB', 'MB', 'GB']:
            if size_bytes < 1024.0:
                return f"{size_bytes:.1f} {unit}"
            size_bytes /= 1024.0
        return f"{size_bytes:.1f} TB"


class StreamingLogReader:
    """Streams log lines efficiently without loading entire files into memory."""

    @staticmethod
    def stream_lines(
        source: Union[str, bytes, io.IOBase, Path],
        max_lines: Optional[int] = None,
        offset: int = 0
    ) -> Generator[Tuple[int, str], None, None]:
        """
        Yields (line_no, line_string) tuples from strings, files, or streams.
        Supports automatic gzip decompression when magic bytes or .gz extension detected.
        """
        line_count = 0
        yielded_count = 0

        # Case 1: String input
        if isinstance(source, str):
            # If it's a file path that exists on disk
            if os.path.exists(source) and os.path.isfile(source):
                source = Path(source)
            else:
                # In-memory string
                for line in source.splitlines():
                    line_count += 1
                    if line_count <= offset:
                        continue
                    if max_lines is not None and yielded_count >= max_lines:
                        break
                    yielded_count += 1
                    yield (line_count, line.rstrip('\r\n'))
                return

        # Case 2: Path or File Path string
        if isinstance(source, Path):
            is_gz = source.name.endswith('.gz') or StreamingLogReader.is_gzip_file(str(source))
            opener = gzip.open(source, 'rt', encoding='utf-8', errors='replace') if is_gz else open(source, 'r', encoding='utf-8', errors='replace')
            with opener as f:
                for line in f:
                    line_count += 1
                    if line_count <= offset:
                        continue
                    if max_lines is not None and yielded_count >= max_lines:
                        break
                    yielded_count += 1
                    yield (line_count, line.rstrip('\r\n'))
            return

        # Case 3: Raw bytes
        if isinstance(source, bytes):
            is_gz = len(source) >= 2 and source[:2] == b'\x1f\x8b'
            if is_gz:
                stream = gzip.GzipFile(fileobj=io.BytesIO(source))
                text_stream = io.TextIOWrapper(stream, encoding='utf-8', errors='replace')
                for line in text_stream:
                    line_count += 1
                    if line_count <= offset:
                        continue
                    if max_lines is not None and yielded_count >= max_lines:
                        break
                    yielded_count += 1
                    yield (line_count, line.rstrip('\r\n'))
                return
            else:
                text_stream = io.StringIO(source.decode('utf-8', errors='replace'))
                for line in text_stream:
                    line_count += 1
                    if line_count <= offset:
                        continue
                    if max_lines is not None and yielded_count >= max_lines:
                        break
                    yielded_count += 1
                    yield (line_count, line.rstrip('\r\n'))
                return

        # Case 4: File-like object (io.IOBase)
        if hasattr(source, 'read'):
            # Check if binary or text
            first_bytes = source.read(2)
            is_gz = (first_bytes == b'\x1f\x8b')
            # Rewind if possible
            if hasattr(source, 'seek'):
                source.seek(0)

            if is_gz:
                stream = gzip.GzipFile(fileobj=source)
                text_stream = io.TextIOWrapper(stream, encoding='utf-8', errors='replace')
                for line in text_stream:
                    line_count += 1
                    if line_count <= offset:
                        continue
                    if max_lines is not None and yielded_count >= max_lines:
                        break
                    yielded_count += 1
                    yield (line_count, line.rstrip('\r\n'))
            else:
                # If binary stream, wrap in TextIOWrapper
                if isinstance(first_bytes, bytes):
                    text_stream = io.TextIOWrapper(source, encoding='utf-8', errors='replace')
                else:
                    text_stream = source
                for line in text_stream:
                    line_count += 1
                    if line_count <= offset:
                        continue
                    if max_lines is not None and yielded_count >= max_lines:
                        break
                    yielded_count += 1
                    yield (line_count, line.rstrip('\r\n'))

    @staticmethod
    def is_gzip_file(filepath: str) -> bool:
        """Checks for gzip magic number (0x1f, 0x8b)."""
        try:
            with open(filepath, 'rb') as f:
                header = f.read(2)
                return header == b'\x1f\x8b'
        except Exception:
            return False


class MultipartFormDataParser:
    """
    Pure Python zero-dependency streaming multipart/form-data parser.
    Safely extracts uploaded files and text fields without external dependencies.
    """

    @staticmethod
    def parse(
        body_stream: io.BufferedIOBase,
        content_type_header: str,
        content_length: int,
        max_size: int = MAX_UPLOAD_SIZE
    ) -> Dict[str, Any]:
        """
        Parses multipart/form-data.
        Returns a dictionary with 'fields': {name: str} and 'files': {name: {'filename', 'content', 'size', 'type'}}.
        """
        result = {'fields': {}, 'files': {}}
        if not content_type_header or 'multipart/form-data' not in content_type_header:
            return result

        if content_length > max_size:
            raise ValueError(f"Payload size ({content_length} bytes) exceeds limit of {max_size} bytes")

        # Extract boundary parameter
        boundary_match = re.search(r'boundary=([^;]+)', content_type_header)
        if not boundary_match:
            raise ValueError("Missing multipart boundary in Content-Type header")

        boundary_str = boundary_match.group(1).strip('"\'')
        boundary_bytes = boundary_str.encode('utf-8')
        delimiter = b'--' + boundary_bytes
        end_delimiter = delimiter + b'--'

        raw_data = body_stream.read(content_length)
        if len(raw_data) > max_size:
            raise ValueError(f"Uploaded data exceeded {max_size} bytes limit")

        parts = raw_data.split(delimiter)
        for part in parts:
            if not part or part == b'--\r\n' or part == b'--':
                continue

            # Strip leading \r\n
            if part.startswith(b'\r\n'):
                part = part[2:]
            # Strip trailing \r\n
            if part.endswith(b'\r\n'):
                part = part[:-2]

            # Split header and body by double CRLF
            header_end = part.find(b'\r\n\r\n')
            if header_end == -1:
                continue

            raw_headers = part[:header_end].decode('utf-8', errors='replace')
            body_content = part[header_end + 4:]

            # Parse headers in part
            field_name = None
            filename = None
            part_content_type = 'text/plain'

            for hline in raw_headers.split('\r\n'):
                if hline.lower().startswith('content-disposition:'):
                    name_m = re.search(r'name="([^"]+)"', hline)
                    if name_m:
                        field_name = name_m.group(1)
                    file_m = re.search(r'filename="([^"]+)"', hline)
                    if file_m:
                        filename = os.path.basename(file_m.group(1))
                elif hline.lower().startswith('content-type:'):
                    part_content_type = hline.split(':', 1)[1].strip()

            if not field_name:
                continue

            if filename is not None:
                # It's an uploaded file
                # Check if it's gzip compressed
                is_gz = filename.endswith('.gz') or (len(body_content) >= 2 and body_content[:2] == b'\x1f\x8b')
                if is_gz:
                    try:
                        decompressed = gzip.decompress(body_content)
                        text_content = decompressed.decode('utf-8', errors='replace')
                    except Exception:
                        text_content = body_content.decode('utf-8', errors='replace')
                else:
                    text_content = body_content.decode('utf-8', errors='replace')

                result['files'][field_name] = {
                    'filename': filename,
                    'size': len(body_content),
                    'content_type': part_content_type,
                    'content': text_content,
                    'is_compressed': is_gz
                }
            else:
                # Text form field
                result['fields'][field_name] = body_content.decode('utf-8', errors='replace')

        return result


class IncidentReportExporter:
    """Formats triage incident analysis into various enterprise report formats."""

    @staticmethod
    def to_slack_markdown(report: Dict[str, Any]) -> str:
        s = report.get('summary', {})
        incidents = report.get('incidents', [])
        p0 = incidents[0] if incidents else {}
        diag = p0.get('diagnosis', {})

        md = f"""🚨 *[INCIDENT ALERT: SEV-{p0.get('priority', 'P0')}] - {s.get('root_cause_summary', 'Service Outage')}*
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
• *Trigger Detected:* `{s.get('outage_started_at', '03:00 UTC')}`
• *Noise Reduction:* `{s.get('total_lines_ingested', 0):,} lines` ➔ `{s.get('actionable_incidents', 0)} incidents` ({s.get('noise_reduction_percentage', 99.9)}% noise filtered in {s.get('time_to_triage_seconds', 0.2)}s)
• *Blast Radius:* {s.get('total_services_impacted', len(s.get('services_impacted', [])))} services affected: `{', '.join(s.get('services_impacted', [])[:5])}`

*Root Cause Hypothesis:*
> {diag.get('trigger', 'Underlying dependency failure')}

*Patient Zero (Earliest Anomaly):*
```{p0.get('patient_zero', {}).get('raw', 'N/A')[:220]}```

*Recommended Immediate Action:*
```{diag.get('command', 'kubectl get pods -A')}```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
_Generated automatically by Triage3AM v2.0 in {s.get('time_to_triage_seconds', 0.2)}s_"""
        return md

    @staticmethod
    def to_incident_postmortem_markdown(report: Dict[str, Any]) -> str:
        s = report.get('summary', {})
        incidents = report.get('incidents', [])
        p0 = incidents[0] if incidents else {}
        cascade = report.get('cascade_chain', [])

        lines = [
            f"# Incident Post-Mortem: {s.get('root_cause_summary', 'Outage Incident')}",
            "",
            f"**Generated:** {s.get('outage_started_at', 'N/A')} | **Severity:** SEV-{p0.get('priority', 'P0')} | **Engine:** Triage3AM v2.0",
            "",
            "## 1. Executive Summary",
            f"- **Outage Root Cause:** {s.get('root_cause_summary', 'Service Failure')}",
            f"- **Telemetry Processed:** {s.get('total_lines_ingested', 0):,} log lines in {s.get('time_to_triage_seconds', 0.1)} seconds",
            f"- **Noise Reduction:** {s.get('noise_reduction_percentage', 0)}% ({s.get('actionable_incidents', 0)} clustered incidents from {s.get('total_error_lines', 0):,} raw errors)",
            f"- **Blast Radius:** {s.get('total_services_impacted', 0)} microservices impacted ({', '.join(s.get('services_impacted', []))})",
            "",
            "## 2. Patient Zero Anomaly",
            f"```text",
            f"Line: {p0.get('patient_zero', {}).get('line_no', 'N/A')} | Service: {p0.get('patient_zero', {}).get('service', 'N/A')} | Time: {p0.get('patient_zero', {}).get('timestamp', 'N/A')}",
            f"{p0.get('patient_zero', {}).get('raw', 'No patient zero captured')}",
            f"```",
            "",
            "## 3. Recommended Remediation & Runbook",
            f"```bash",
            f"{p0.get('diagnosis', {}).get('command', '# No command specified')}",
            f"```",
            "",
            f"{p0.get('diagnosis', {}).get('recommended_fix', 'Inspect system logs.')}",
            "",
            "## 4. Cascading Failure Chain",
            "| Time | Service | Severity | Root Cause Event | Impact |",
            "| :--- | :--- | :--- | :--- | :--- |"
        ]

        for step in cascade:
            trigger_mark = " 🎯 [TRIGGER]" if step.get('is_trigger') else ""
            lines.append(f"| `{step.get('time')}` | **{step.get('service')}**{trigger_mark} | `{step.get('severity')}` | {step.get('event')} | {step.get('impact')} |")

        lines.extend([
            "",
            "## 5. Incident Clusters Breakdown",
            "| Rank | Priority | Service | Cluster Template | Errors | % Total |",
            "| :--- | :--- | :--- | :--- | :--- | :--- |"
        ])

        for inc in incidents:
            tmpl_clean = inc.get('template', '')[:60] + "..." if len(inc.get('template', '')) > 60 else inc.get('template', '')
            lines.append(f"| #{inc.get('rank')} | `{inc.get('priority')}` | `{inc.get('primary_service')}` | `{tmpl_clean}` | {inc.get('line_count'):,} | {inc.get('percentage_of_total')}% |")

        lines.extend([
            "",
            "---",
            "_Automated triage analysis performed by Triage3AM v2.0_"
        ])

        return "\n".join(lines)

    @staticmethod
    def to_csv_summary(report: Dict[str, Any]) -> str:
        incidents = report.get('incidents', [])
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(['Rank', 'ID', 'Priority', 'Service', 'Error_Count', 'Percentage', 'First_Seen', 'Last_Seen', 'Root_Cause', 'Remediation_Command'])

        for inc in incidents:
            writer.writerow([
                inc.get('rank'),
                inc.get('id'),
                inc.get('priority'),
                inc.get('primary_service'),
                inc.get('line_count'),
                inc.get('percentage_of_total'),
                inc.get('first_seen'),
                inc.get('last_seen'),
                inc.get('diagnosis', {}).get('root_cause', ''),
                inc.get('diagnosis', {}).get('command', '')
            ])

        return output.getvalue()


def get_mime_type(filename: str) -> str:
    """Returns the appropriate MIME type for downloadable files."""
    lower = filename.lower()
    if lower.endswith('.log') or lower.endswith('.txt'):
        return 'text/plain; charset=utf-8'
    elif lower.endswith('.gz'):
        return 'application/gzip'
    elif lower.endswith('.json'):
        return 'application/json; charset=utf-8'
    elif lower.endswith('.csv'):
        return 'text/csv; charset=utf-8'
    elif lower.endswith('.md'):
        return 'text/markdown; charset=utf-8'
    elif lower.endswith('.zip'):
        return 'application/zip'
    return 'application/octet-stream'


class ArchiveManager:
    """Creates compressed zip bundles of files and telemetry datasets."""

    @staticmethod
    def create_zip_bundle(directory_path: str, destination_stream: io.BytesIO) -> int:
        """Packs files from directory_path into a zip stream without temporary files."""
        base = Path(directory_path)
        count = 0
        with zipfile.ZipFile(destination_stream, 'w', compression=zipfile.ZIP_DEFLATED) as zf:
            for file_path in sorted(base.rglob('*')):
                if file_path.is_file() and not file_path.name.startswith('.'):
                    arcname = file_path.relative_to(base)
                    zf.write(file_path, arcname=str(arcname))
                    count += 1
        destination_stream.seek(0)
        return count

