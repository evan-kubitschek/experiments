#!/usr/bin/env python3
"""Export Fathom meeting transcripts to markdown files with YAML frontmatter."""

import argparse
import json
import os
import re
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

import requests

API_BASE = "https://api.fathom.ai/external/v1"
RATE_LIMIT_PER_MIN = 60
PERSONAL_DOMAINS = {"gmail.com", "yahoo.com", "hotmail.com", "outlook.com", "aol.com",
                    "icloud.com", "proton.me", "protonmail.com", "live.com", "me.com"}


def load_client_mapping(path: Path | None) -> dict[str, str]:
    """Load domain->client name mapping from a JSON file."""
    if path and path.exists():
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    # Check for default location next to this script
    default = Path(__file__).parent / "client_domains.json"
    if default.exists():
        with open(default, encoding="utf-8") as f:
            return json.load(f)
    return {}


def identify_clients(meeting: dict, internal_domain: str, client_map: dict[str, str]) -> list[str]:
    """Identify client names from external participant domains."""
    external_domains: dict[str, int] = {}

    invitees = meeting.get("calendar_invitees") or []
    for inv in invitees:
        email = inv.get("email", "")
        if not email or "@" not in email:
            continue
        domain = email.split("@", 1)[1].lower()
        if domain == internal_domain or domain in PERSONAL_DOMAINS:
            continue
        external_domains[domain] = external_domains.get(domain, 0) + 1

    if not external_domains:
        return []

    clients = []
    for domain in sorted(external_domains, key=external_domains.get, reverse=True):
        name = client_map.get(domain, domain)
        if name not in clients:
            clients.append(name)
    return clients


def get_api_key() -> str:
    key = os.environ.get("FATHOM_API_KEY")
    if not key:
        print("Error: FATHOM_API_KEY environment variable is not set.", file=sys.stderr)
        sys.exit(1)
    return key


def sanitize_filename(title: str) -> str:
    """Convert a meeting title to a safe filename component."""
    s = title.lower().strip()
    s = re.sub(r"[^\w\s-]", "", s)
    s = re.sub(r"[\s_]+", "_", s)
    s = re.sub(r"-+", "-", s)
    return s[:100]


def fetch_meetings(
    api_key: str,
    created_after: str | None = None,
    created_before: str | None = None,
) -> list[dict]:
    """Fetch all meetings with transcripts, handling pagination and rate limiting."""
    headers = {"X-Api-Key": api_key}
    params: dict = {"include_transcript": "true"}
    if created_after:
        params["created_after"] = created_after
    if created_before:
        params["created_before"] = created_before

    all_meetings: list[dict] = []
    cursor: str | None = None
    request_times: list[float] = []
    page = 0

    while True:
        if cursor:
            params["cursor"] = cursor

        # Rate limiting: keep a sliding window of request timestamps
        now = time.monotonic()
        request_times = [t for t in request_times if now - t < 60]
        if len(request_times) >= RATE_LIMIT_PER_MIN:
            wait = 60 - (now - request_times[0]) + 0.1
            print(f"  Rate limit approaching, waiting {wait:.1f}s...")
            time.sleep(wait)

        page += 1
        print(f"  Fetching page {page}...", end="", flush=True)

        resp = requests.get(
            f"{API_BASE}/meetings", headers=headers, params=params, timeout=30
        )
        request_times.append(time.monotonic())

        if resp.status_code == 429:
            retry_after = int(resp.headers.get("Retry-After", "10"))
            print(f" rate limited, retrying in {retry_after}s...")
            time.sleep(retry_after)
            continue

        resp.raise_for_status()
        data = resp.json()

        items = data.get("items", [])
        all_meetings.extend(items)
        print(f" got {len(items)} meetings (total: {len(all_meetings)})")

        cursor = data.get("next_cursor")
        if not cursor:
            break

    return all_meetings


def compute_duration(meeting: dict) -> str:
    """Compute a human-readable duration from recording start/end times."""
    start = meeting.get("recording_start_time")
    end = meeting.get("recording_end_time")
    if not start or not end:
        return "unknown"
    try:
        t_start = datetime.fromisoformat(start.replace("Z", "+00:00"))
        t_end = datetime.fromisoformat(end.replace("Z", "+00:00"))
        delta = t_end - t_start
        total_seconds = int(delta.total_seconds())
        hours, remainder = divmod(total_seconds, 3600)
        minutes, seconds = divmod(remainder, 60)
        if hours > 0:
            return f"{hours}h {minutes}m {seconds}s"
        return f"{minutes}m {seconds}s"
    except (ValueError, TypeError):
        return "unknown"


def yaml_escape(value: str) -> str:
    """Escape a string for safe YAML scalar output."""
    if any(c in value for c in ":#{}[]&*?|>!%@`\"'\n"):
        escaped = value.replace("\\", "\\\\").replace('"', '\\"')
        return f'"{escaped}"'
    return value


def meeting_to_markdown(meeting: dict, internal_domain: str = "",
                        client_map: dict[str, str] | None = None) -> str:
    """Convert a meeting dict to a markdown string with YAML frontmatter."""
    title = meeting.get("title") or meeting.get("meeting_title") or "Untitled Meeting"
    created_at = meeting.get("created_at", "")
    duration = compute_duration(meeting)
    meeting_type = meeting.get("calendar_invitees_domains_type", "unknown")

    invitees = meeting.get("calendar_invitees") or []
    participants = []
    for inv in invitees:
        name = inv.get("name", "")
        email = inv.get("email", "")
        if name and email:
            participants.append(f"{name} <{email}>")
        elif name:
            participants.append(name)
        elif email:
            participants.append(email)

    recorded_by = meeting.get("recorded_by") or {}
    if recorded_by:
        rb_name = recorded_by.get("name", "")
        rb_email = recorded_by.get("email", "")
        rb_str = f"{rb_name} <{rb_email}>" if rb_name and rb_email else rb_name or rb_email
        if rb_str and rb_str not in participants:
            participants.append(rb_str)

    # Identify clients
    clients = identify_clients(meeting, internal_domain, client_map or {}) if internal_domain else []

    # Build YAML frontmatter
    lines = ["---"]
    lines.append(f"title: {yaml_escape(title)}")
    lines.append(f"date: {created_at}")
    lines.append(f"duration: {yaml_escape(duration)}")
    lines.append(f"meeting_type: {yaml_escape(meeting_type)}")
    if clients:
        if len(clients) == 1:
            lines.append(f"client: {yaml_escape(clients[0])}")
        else:
            lines.append("clients:")
            for c in clients:
                lines.append(f"  - {yaml_escape(c)}")
    if participants:
        lines.append("participants:")
        for p in participants:
            lines.append(f"  - {yaml_escape(p)}")
    else:
        lines.append("participants: []")
    if meeting.get("url"):
        lines.append(f"fathom_url: {meeting['url']}")
    if meeting.get("share_url"):
        lines.append(f"share_url: {meeting['share_url']}")
    if meeting.get("recording_id"):
        lines.append(f"recording_id: {meeting['recording_id']}")
    lines.append("---")
    lines.append("")

    # Title
    lines.append(f"# {title}")
    lines.append("")

    # Transcript
    transcript = meeting.get("transcript")
    if transcript:
        lines.append("## Transcript")
        lines.append("")
        for entry in transcript:
            speaker_info = entry.get("speaker", {})
            speaker = speaker_info.get("display_name", "Unknown Speaker")
            timestamp = entry.get("timestamp", "")
            text = entry.get("text", "")
            lines.append(f"**[{timestamp}] {speaker}:** {text}")
            lines.append("")
    else:
        lines.append("*No transcript available for this meeting.*")
        lines.append("")

    return "\n".join(lines)


def save_meeting(meeting: dict, output_dir: Path, internal_domain: str = "",
                 client_map: dict[str, str] | None = None) -> Path:
    """Save a meeting as a markdown file, returning the file path."""
    title = meeting.get("title") or meeting.get("meeting_title") or "Untitled Meeting"
    created_at = meeting.get("created_at", "")

    # Extract date for filename
    try:
        dt = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
        date_str = dt.strftime("%Y-%m-%d")
    except (ValueError, TypeError):
        date_str = "unknown-date"

    safe_title = sanitize_filename(title)
    filename = f"{date_str}_{safe_title}.md"
    filepath = output_dir / filename

    # Handle duplicate filenames
    counter = 1
    while filepath.exists():
        counter += 1
        filepath = output_dir / f"{date_str}_{safe_title}_{counter}.md"

    content = meeting_to_markdown(meeting, internal_domain, client_map)
    filepath.write_text(content, encoding="utf-8")
    return filepath


def parse_date_arg(value: str) -> str:
    """Parse a date string and return an ISO 8601 timestamp."""
    for fmt in ("%Y-%m-%d", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M:%SZ"):
        try:
            dt = datetime.strptime(value, fmt)
            return dt.strftime("%Y-%m-%dT%H:%M:%SZ")
        except ValueError:
            continue
    # Try as-is (already ISO format with timezone)
    try:
        datetime.fromisoformat(value.replace("Z", "+00:00"))
        return value
    except ValueError:
        print(f"Error: Could not parse date '{value}'. Use YYYY-MM-DD or ISO 8601 format.", file=sys.stderr)
        sys.exit(1)


def main():
    parser = argparse.ArgumentParser(
        description="Export Fathom meeting transcripts to markdown files."
    )
    parser.add_argument(
        "--created-after",
        help="Only include meetings created after this date (YYYY-MM-DD or ISO 8601)",
    )
    parser.add_argument(
        "--created-before",
        help="Only include meetings created before this date (YYYY-MM-DD or ISO 8601)",
    )
    parser.add_argument(
        "--output-dir",
        default="./transcripts",
        help="Output directory (default: ./transcripts)",
    )
    parser.add_argument(
        "--internal-domain",
        default="revenueronin.com",
        help="Your company's email domain, used to identify external clients (default: revenueronin.com)",
    )
    parser.add_argument(
        "--client-map",
        help="Path to client_domains.json mapping file (default: auto-detect next to script)",
    )
    args = parser.parse_args()

    api_key = get_api_key()
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    client_map_path = Path(args.client_map) if args.client_map else None
    client_map = load_client_mapping(client_map_path)
    if client_map:
        print(f"Loaded {len(client_map)} client domain mappings.")

    created_after = parse_date_arg(args.created_after) if args.created_after else None
    created_before = parse_date_arg(args.created_before) if args.created_before else None

    print("Fetching meetings from Fathom API...")
    if created_after:
        print(f"  Filter: created after {created_after}")
    if created_before:
        print(f"  Filter: created before {created_before}")

    meetings = fetch_meetings(api_key, created_after, created_before)

    if not meetings:
        print("No meetings found.")
        return

    print(f"\nSaving {len(meetings)} meetings to {output_dir}/")
    for meeting in meetings:
        filepath = save_meeting(meeting, output_dir, args.internal_domain, client_map)
        print(f"  {filepath.name}")

    print(f"\nDone! Exported {len(meetings)} meetings to {output_dir}/")


if __name__ == "__main__":
    main()
