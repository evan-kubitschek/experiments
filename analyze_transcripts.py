#!/usr/bin/env python3
"""Analyze exported Fathom transcripts: tag clients, summarize by client, extract key info.

Reads existing markdown transcripts, identifies clients from participant emails,
and produces a per-client analysis report. Can also retroactively add client tags
to existing files.
"""

import json
import re
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

PERSONAL_DOMAINS = {"gmail.com", "yahoo.com", "hotmail.com", "outlook.com", "aol.com",
                    "icloud.com", "proton.me", "protonmail.com", "live.com", "me.com"}


def load_client_mapping(script_dir: Path) -> dict[str, str]:
    path = script_dir / "client_domains.json"
    if path.exists():
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    return {}


def parse_frontmatter(text: str) -> dict[str, any]:
    """Parse YAML frontmatter from markdown text (simple parser, no pyyaml needed)."""
    match = re.match(r"^---\n(.*?)\n---", text, re.DOTALL)
    if not match:
        return {}
    fm = {}
    current_key = None
    current_list = None
    for line in match.group(1).splitlines():
        # List item
        list_match = re.match(r"^  - (.+)$", line)
        if list_match and current_key:
            val = list_match.group(1).strip().strip('"').strip("'")
            if current_list is None:
                current_list = []
            current_list.append(val)
            fm[current_key] = current_list
            continue

        # Key: value
        kv = re.match(r"^(\w[\w_]*)\s*:\s*(.*)$", line)
        if kv:
            current_key = kv.group(1)
            val = kv.group(2).strip().strip('"').strip("'")
            current_list = None
            if val:
                fm[current_key] = val
            # else value might be a list on next lines
            continue

    return fm


def extract_emails_from_participants(participants: list[str]) -> list[str]:
    """Pull email addresses out of participant strings like 'Name <email>'."""
    emails = []
    for p in participants:
        m = re.search(r"<([^>]+@[^>]+)>", p)
        if m:
            emails.append(m.group(1).lower())
        elif "@" in p:
            emails.append(p.strip().lower())
    return emails


def identify_clients_from_emails(emails: list[str], internal_domain: str,
                                  client_map: dict[str, str]) -> list[str]:
    domain_counts: dict[str, int] = {}
    for email in emails:
        domain = email.split("@", 1)[1]
        if domain == internal_domain or domain in PERSONAL_DOMAINS:
            continue
        domain_counts[domain] = domain_counts.get(domain, 0) + 1

    clients = []
    for domain in sorted(domain_counts, key=domain_counts.get, reverse=True):
        name = client_map.get(domain, domain)
        if name not in clients:
            clients.append(name)
    return clients


def get_external_participants(participants: list[str], internal_domain: str) -> list[str]:
    """Return participant display strings that are external."""
    external = []
    for p in participants:
        m = re.search(r"<([^>]+@[^>]+)>", p)
        if m:
            domain = m.group(1).split("@", 1)[1].lower()
            if domain != internal_domain:
                external.append(p)
        elif "@" in p:
            domain = p.strip().split("@", 1)[1].lower()
            if domain != internal_domain:
                external.append(p)
    return external


def parse_duration_to_minutes(duration_str: str) -> float:
    """Convert '1h 23m 45s' or '23m 45s' to total minutes."""
    if not duration_str or duration_str == "unknown":
        return 0
    hours = re.search(r"(\d+)h", duration_str)
    minutes = re.search(r"(\d+)m", duration_str)
    seconds = re.search(r"(\d+)s", duration_str)
    total = 0.0
    if hours:
        total += int(hours.group(1)) * 60
    if minutes:
        total += int(minutes.group(1))
    if seconds:
        total += int(seconds.group(1)) / 60
    return total


def retag_file(filepath: Path, clients: list[str]) -> bool:
    """Add or update client/clients field in a file's frontmatter. Returns True if modified."""
    text = filepath.read_text(encoding="utf-8")
    match = re.match(r"^(---\n)(.*?)(\n---)", text, re.DOTALL)
    if not match:
        return False

    fm_text = match.group(2)

    # Remove existing client/clients lines
    fm_lines = fm_text.splitlines()
    new_lines = []
    skip_list = False
    for line in fm_lines:
        if re.match(r"^clients?:", line):
            skip_list = True
            continue
        if skip_list and re.match(r"^  - ", line):
            continue
        skip_list = False
        new_lines.append(line)

    # Insert client tag after meeting_type line
    insert_idx = None
    for i, line in enumerate(new_lines):
        if line.startswith("meeting_type:"):
            insert_idx = i + 1
            break

    if insert_idx is None:
        insert_idx = len(new_lines)

    if clients:
        if len(clients) == 1:
            client_escaped = clients[0]
            if any(c in client_escaped for c in ":#{}[]&*?|>!%@`\"'\n"):
                client_escaped = f'"{client_escaped}"'
            new_lines.insert(insert_idx, f"client: {client_escaped}")
        else:
            lines_to_insert = ["clients:"]
            for c in clients:
                escaped = c
                if any(ch in escaped for ch in ":#{}[]&*?|>!%@`\"'\n"):
                    escaped = f'"{escaped}"'
                lines_to_insert.append(f"  - {escaped}")
            for j, l in enumerate(lines_to_insert):
                new_lines.insert(insert_idx + j, l)

    new_fm = "\n".join(new_lines)
    new_text = f"---\n{new_fm}\n---{text[match.end():]}"

    if new_text != text:
        filepath.write_text(new_text, encoding="utf-8")
        return True
    return False


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Analyze and tag Fathom meeting transcripts.")
    parser.add_argument("--transcripts-dir", default="./transcripts",
                        help="Directory containing transcript markdown files (default: ./transcripts)")
    parser.add_argument("--internal-domain", default="revenueronin.com",
                        help="Your company email domain (default: revenueronin.com)")
    parser.add_argument("--retag", action="store_true",
                        help="Retroactively add client tags to existing transcript files")
    parser.add_argument("--output", default="./client_analysis.md",
                        help="Output path for the analysis report (default: ./client_analysis.md)")
    args = parser.parse_args()

    transcripts_dir = Path(args.transcripts_dir)
    if not transcripts_dir.exists():
        print(f"Error: {transcripts_dir} does not exist.", file=sys.stderr)
        sys.exit(1)

    client_map = load_client_mapping(Path(__file__).parent)
    files = sorted(transcripts_dir.glob("*.md"))
    print(f"Found {len(files)} transcript files in {transcripts_dir}/")

    # ── Parse all meetings ──
    meetings = []
    for f in files:
        text = f.read_text(encoding="utf-8")
        fm = parse_frontmatter(text)
        if not fm:
            continue

        participants_raw = fm.get("participants", [])
        if isinstance(participants_raw, str):
            participants_raw = [participants_raw]

        emails = extract_emails_from_participants(participants_raw)
        clients = identify_clients_from_emails(emails, args.internal_domain, client_map)

        meetings.append({
            "file": f,
            "title": fm.get("title", f.stem),
            "date": fm.get("date", ""),
            "duration": fm.get("duration", "unknown"),
            "meeting_type": fm.get("meeting_type", "unknown"),
            "participants": participants_raw,
            "clients": clients,
            "emails": emails,
            "fathom_url": fm.get("fathom_url", ""),
        })

    # ── Retag existing files ──
    if args.retag:
        print("\nRetagging files with client information...")
        tagged = 0
        for m in meetings:
            if retag_file(m["file"], m["clients"]):
                tagged += 1
                client_str = ", ".join(m["clients"]) if m["clients"] else "(internal/personal)"
                print(f"  Tagged: {m['file'].name} -> {client_str}")
        print(f"Updated {tagged} files.")

    # ── Build per-client analysis ──
    client_meetings: dict[str, list] = defaultdict(list)
    for m in meetings:
        if m["clients"]:
            for c in m["clients"]:
                client_meetings[c].append(m)
        else:
            client_meetings["(Internal / Personal)"].append(m)

    # Sort clients by meeting count descending
    sorted_clients = sorted(client_meetings.items(), key=lambda x: len(x[1]), reverse=True)

    # ── Generate report ──
    report = []
    report.append("# Client Meeting Analysis")
    report.append("")
    report.append(f"*Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}*")
    report.append(f"*Total meetings analyzed: {len(meetings)}*")
    report.append(f"*Unique clients/orgs: {len(sorted_clients)}*")
    report.append("")

    # Summary table
    report.append("## Summary")
    report.append("")
    report.append("| Client | Meetings | Total Time | Contacts | Date Range |")
    report.append("|--------|----------|------------|----------|------------|")

    for client_name, c_meetings in sorted_clients:
        count = len(c_meetings)
        total_mins = sum(parse_duration_to_minutes(m["duration"]) for m in c_meetings)
        if total_mins >= 60:
            time_str = f"{int(total_mins // 60)}h {int(total_mins % 60)}m"
        else:
            time_str = f"{int(total_mins)}m"

        all_external = set()
        for m in c_meetings:
            for p in get_external_participants(m["participants"], args.internal_domain):
                name = re.sub(r"\s*<[^>]+>", "", p).strip()
                if name:
                    all_external.add(name)

        dates = []
        for m in c_meetings:
            if m["date"]:
                try:
                    dt = datetime.fromisoformat(m["date"].replace("Z", "+00:00"))
                    dates.append(dt)
                except ValueError:
                    pass

        if dates:
            date_range = f"{min(dates).strftime('%Y-%m-%d')} to {max(dates).strftime('%Y-%m-%d')}"
        else:
            date_range = "—"

        contacts_str = str(len(all_external))
        report.append(f"| {client_name} | {count} | {time_str} | {contacts_str} | {date_range} |")

    report.append("")

    # Detailed per-client sections
    report.append("---")
    report.append("")

    for client_name, c_meetings in sorted_clients:
        if client_name == "(Internal / Personal)":
            continue

        report.append(f"## {client_name}")
        report.append("")

        # Contacts
        all_contacts: dict[str, str] = {}
        for m in c_meetings:
            for p in get_external_participants(m["participants"], args.internal_domain):
                email_match = re.search(r"<([^>]+)>", p)
                name = re.sub(r"\s*<[^>]+>", "", p).strip()
                email = email_match.group(1) if email_match else ""
                if name and name not in all_contacts:
                    all_contacts[name] = email

        if all_contacts:
            report.append("**Contacts:**")
            for name, email in sorted(all_contacts.items()):
                if email:
                    report.append(f"- {name} ({email})")
                else:
                    report.append(f"- {name}")
            report.append("")

        # Total time
        total_mins = sum(parse_duration_to_minutes(m["duration"]) for m in c_meetings)
        if total_mins >= 60:
            time_str = f"{int(total_mins // 60)}h {int(total_mins % 60)}m"
        else:
            time_str = f"{int(total_mins)}m"
        report.append(f"**Total meeting time:** {time_str} across {len(c_meetings)} meetings")
        report.append("")

        # Meeting list (chronological)
        report.append("**Meeting history:**")
        report.append("")
        sorted_meetings = sorted(c_meetings, key=lambda m: m["date"] or "")
        for m in sorted_meetings:
            date_str = ""
            if m["date"]:
                try:
                    dt = datetime.fromisoformat(m["date"].replace("Z", "+00:00"))
                    date_str = dt.strftime("%Y-%m-%d")
                except ValueError:
                    date_str = m["date"][:10]

            link = f"[{m['title']}]({m['file'].name})" if m["title"] else m["file"].name
            dur = m["duration"] if m["duration"] != "unknown" else ""
            report.append(f"- {date_str} — {link} ({dur})")

        report.append("")
        report.append("---")
        report.append("")

    output_path = Path(args.output)
    output_path.write_text("\n".join(report), encoding="utf-8")
    print(f"\nAnalysis report written to {output_path}")

    # Print top-level stats to terminal
    print(f"\n{'='*60}")
    print(f" CLIENT ANALYSIS SUMMARY")
    print(f"{'='*60}")
    print(f" Total meetings:  {len(meetings)}")
    print(f" Unique clients:  {len([c for c, _ in sorted_clients if c != '(Internal / Personal)'])}")
    print(f"{'='*60}")
    print(f" {'Client':<30} {'Meetings':>8}  {'Time':>8}")
    print(f" {'-'*30} {'-'*8}  {'-'*8}")
    for client_name, c_meetings in sorted_clients[:20]:
        total_mins = sum(parse_duration_to_minutes(m["duration"]) for m in c_meetings)
        if total_mins >= 60:
            time_str = f"{int(total_mins // 60)}h {int(total_mins % 60)}m"
        else:
            time_str = f"{int(total_mins)}m"
        display_name = client_name[:30]
        print(f" {display_name:<30} {len(c_meetings):>8}  {time_str:>8}")
    if len(sorted_clients) > 20:
        print(f" ... and {len(sorted_clients) - 20} more")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
