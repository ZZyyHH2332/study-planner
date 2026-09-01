#!/usr/bin/env python3
"""Obsidian Vault scanner for Study Planner plugin.

Scans the Vault directory, parses markdown frontmatter, and extracts
knowledge nodes and edges into the SQLite database.

Supports four note types:
  - Fleeting (00_Inbox): not scanned for graph
  - Literature (10_Sources): stored as nodes with type "literature"
  - Permanent (20_Zettelkasten): stored as nodes with learning metadata
  - MOC (30_MOCs): stored as nodes with type "moc"

Link resolution:
  - [[Filename]] links are resolved via filename → note_id mapping
  - Unresolved links create stub nodes marked as "unresolved"
"""

import json
import os
import re
import sys
from pathlib import Path
from datetime import datetime, timezone

# Try to import yaml, fall back to simple parser
try:
    import yaml
    HAS_YAML = True
except ImportError:
    HAS_YAML = False

# Import db_manager from same directory
script_dir = Path(__file__).resolve().parent
sys.path.insert(0, str(script_dir))
import db_manager


LINK_PATTERN = re.compile(r'\[\[([^\]]+)\]\]')

VAULT_FOLDERS = {
    "00_Inbox": "fleeting",
    "10_Sources": "literature",
    "20_Zettelkasten": "permanent",
    "30_MOCs": "moc",
}


def parse_frontmatter(content):
    """Parse YAML frontmatter from markdown content.

    Returns (frontmatter_dict, body) or ({}, content) if no frontmatter.
    """
    if not content.startswith("---"):
        return {}, content

    parts = content.split("---", 2)
    if len(parts) < 3:
        return {}, content

    fm_text = parts[1].strip()
    body = parts[2]

    if HAS_YAML:
        try:
            fm = yaml.safe_load(fm_text)
            if fm is None:
                fm = {}
            return fm, body
        except yaml.YAMLError:
            pass

    return _parse_yaml_simple(fm_text), body


def _parse_yaml_simple(text):
    """Simple YAML parser for frontmatter without PyYAML.

    Handles key: value, lists (- item), and inline lists ([a, b]).
    """
    result = {}
    current_key = None

    for line in text.split("\n"):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue

        if stripped.startswith("- ") and current_key:
            value = stripped[2:].strip()
            if current_key not in result:
                result[current_key] = []
            if isinstance(result[current_key], list):
                result[current_key].append(_parse_value(value))
            continue

        if ":" in stripped:
            key, _, value = stripped.partition(":")
            key = key.strip()
            value = value.strip()

            if value == "":
                current_key = key
                result[key] = []
            else:
                current_key = key
                result[key] = _parse_value(value)

    return result


def _parse_value(value):
    """Parse a YAML value string into appropriate Python type."""
    value = value.strip()

    if value.startswith("[") and value.endswith("]"):
        inner = value[1:-1]
        items = [v.strip().strip("'\"") for v in inner.split(",")]
        return [item for item in items if item]

    if value.startswith('"') and value.endswith('"'):
        return value[1:-1]

    if value.startswith("'") and value.endswith("'"):
        return value[1:-1]

    if value.lower() in ("true", "yes"):
        return True
    if value.lower() in ("false", "no"):
        return False

    try:
        if "." in value:
            return float(value)
        return int(value)
    except ValueError:
        return value


def extract_links(field_value):
    """Extract [[link]] references from a frontmatter field value.

    Handles strings, lists, and mixed formats.
    """
    if not field_value:
        return []

    if isinstance(field_value, list):
        text = " ".join(str(v) for v in field_value)
    else:
        text = str(field_value)

    return LINK_PATTERN.findall(text)


def get_note_type(file_path, vault_path):
    """Determine note type from file location in Vault."""
    rel_path = Path(file_path).relative_to(vault_path)
    parts = rel_path.parts

    if len(parts) > 0:
        folder = parts[0]
        return VAULT_FOLDERS.get(folder)

    return None


def scan_vault(config=None):
    """Scan the entire Vault and update the database.

    Returns a summary dict with scan statistics.
    """
    if config is None:
        config = db_manager.load_config()

    vault_path = Path(config["vault_path"])
    if not vault_path.exists():
        return {"error": f"Vault not found: {vault_path}"}

    db_manager.init_database(config)

    notes = []
    filename_to_id = {}

    # Pass 1: Collect all notes and build filename → id mapping
    for md_file in vault_path.rglob("*.md"):
        if md_file.parent.name == ".obsidian":
            continue
        if "99_System" in md_file.parts:
            continue
        if md_file.name.startswith("template") or md_file.parent.name == "Templates":
            continue

        note_type = get_note_type(md_file, vault_path)
        if note_type is None or note_type == "fleeting":
            continue

        content = md_file.read_text(encoding="utf-8")
        fm, body = parse_frontmatter(content)

        filename = md_file.stem
        note_id = str(fm.get("id", filename))

        filename_to_id[filename] = note_id

        notes.append({
            "file_path": str(md_file),
            "filename": filename,
            "note_id": note_id,
            "note_type": note_type,
            "frontmatter": fm,
            "body": body,
        })

    # Pass 2: Process notes and write to database
    nodes_created = 0
    nodes_updated = 0
    edges_created = 0
    stub_nodes = 0
    unresolved_links = []

    for note in notes:
        fm = note["frontmatter"]
        note_id = note["note_id"]
        note_type = note["note_type"]

        existing = db_manager.get_node(note_id, config)

        if note_type == "permanent":
            difficulty = fm.get("difficulty")
            if difficulty is not None:
                try:
                    difficulty = int(difficulty)
                except (ValueError, TypeError):
                    difficulty = None

            mastery = fm.get("mastery")
            if mastery is not None:
                try:
                    mastery = float(mastery)
                except (ValueError, TypeError):
                    mastery = None

            db_manager.upsert_node(
                note_id=note_id,
                title=fm.get("title", note["filename"]),
                difficulty=difficulty,
                concept_type=fm.get("concept_type"),
                mastery=mastery,
                learning_state=fm.get("learning_state"),
                file_path=note["file_path"],
                ease_factor=fm.get("ease_factor"),
                review_count=fm.get("review_count"),
                last_reviewed=fm.get("last_reviewed"),
                next_review=fm.get("next_review"),
                config=config,
            )
        elif note_type == "moc":
            db_manager.upsert_node(
                note_id=note_id,
                title=fm.get("title", note["filename"]),
                concept_type="moc",
                file_path=note["file_path"],
                config=config,
            )
        elif note_type == "literature":
            db_manager.upsert_node(
                note_id=note_id,
                title=note["filename"],
                concept_type="literature",
                file_path=note["file_path"],
                config=config,
            )

        if existing:
            nodes_updated += 1
        else:
            nodes_created += 1

        # Clear old edges for this node (target side) before re-adding
        db_manager.clear_edges(note_id, config)

        # Process prerequisite edges
        if note_type == "permanent":
            prereq_links = extract_links(fm.get("prerequisites"))
            for link in prereq_links:
                link_filename = link.split("|")[0].split("#")[0].strip()
                source_id = filename_to_id.get(link_filename, link_filename)

                if link_filename not in filename_to_id:
                    # Create stub node for unresolved link
                    stub = db_manager.get_node(source_id, config)
                    if not stub:
                        db_manager.upsert_node(
                            note_id=source_id,
                            title=link_filename,
                            concept_type="stub",
                            file_path=None,
                            config=config,
                        )
                        stub_nodes += 1
                    unresolved_links.append({
                        "source": link_filename,
                        "target": note_id,
                        "resolved": False,
                    })

                db_manager.upsert_edge(
                    source_id=source_id,
                    target_id=note_id,
                    edge_type="prerequisite",
                    config=config,
                )
                edges_created += 1

            # Process related edges (bidirectional, type "related")
            related_links = extract_links(fm.get("related"))
            for link in related_links:
                link_filename = link.split("|")[0].split("#")[0].strip()
                related_id = filename_to_id.get(link_filename, link_filename)

                if link_filename not in filename_to_id:
                    stub = db_manager.get_node(related_id, config)
                    if not stub:
                        db_manager.upsert_node(
                            note_id=related_id,
                            title=link_filename,
                            concept_type="stub",
                            file_path=None,
                            config=config,
                        )
                        stub_nodes += 1
                    unresolved_links.append({
                        "source": link_filename,
                        "target": note_id,
                        "resolved": False,
                    })

                db_manager.upsert_edge(
                    source_id=note_id,
                    target_id=related_id,
                    edge_type="related",
                    config=config,
                )
                edges_created += 1

        # Process MOC membership (up links)
        if note_type in ("permanent", "moc"):
            up_links = extract_links(fm.get("up"))
            for link in up_links:
                link_filename = link.split("|")[0].split("#")[0].strip()
                moc_id = filename_to_id.get(link_filename, link_filename)

                db_manager.upsert_edge(
                    source_id=note_id,
                    target_id=moc_id,
                    edge_type="belongs_to",
                    config=config,
                )
                edges_created += 1

        # Process Literature "inspired" links
        if note_type == "literature":
            inspired_links = extract_links(fm.get("inspired"))
            for link in inspired_links:
                link_filename = link.split("|")[0].split("#")[0].strip()
                target_id = filename_to_id.get(link_filename, link_filename)

                db_manager.upsert_edge(
                    source_id=note_id,
                    target_id=target_id,
                    edge_type="inspired",
                    config=config,
                )
                edges_created += 1

    # Detect cycles in prerequisite graph
    cycles = detect_cycles(config)

    summary = {
        "vault_path": str(vault_path),
        "total_notes_scanned": len(notes),
        "nodes_created": nodes_created,
        "nodes_updated": nodes_updated,
        "edges_created": edges_created,
        "stub_nodes": stub_nodes,
        "unresolved_links": len(unresolved_links),
        "cycles_detected": len(cycles),
        "scan_time": datetime.now(timezone.utc).isoformat(),
    }

    if unresolved_links:
        summary["unresolved_details"] = unresolved_links[:10]

    if cycles:
        summary["cycle_details"] = cycles[:5]

    return summary


def detect_cycles(config=None):
    """Detect cycles in the prerequisite graph using DFS.

    Returns a list of cycles, each represented as a list of node IDs.
    """
    conn = db_manager.get_connection(config)
    edges = conn.execute(
        "SELECT source_id, target_id FROM knowledge_edges WHERE edge_type = 'prerequisite'"
    ).fetchall()
    conn.close()

    graph = {}
    for edge in edges:
        source = edge["source_id"]
        target = edge["target_id"]
        if source not in graph:
            graph[source] = []
        graph[source].append(target)

    cycles = []
    visited = set()
    rec_stack = set()
    path = []

    def dfs(node):
        if node in rec_stack:
            cycle_start = path.index(node) if node in path else 0
            cycles.append(path[cycle_start:] + [node])
            return
        if node in visited:
            return

        visited.add(node)
        rec_stack.add(node)
        path.append(node)

        for neighbor in graph.get(node, []):
            dfs(neighbor)

        path.pop()
        rec_stack.discard(node)

    for node in graph:
        if node not in visited:
            dfs(node)

    return cycles


def print_summary(summary):
    """Print a human-readable scan summary."""
    print("\n" + "=" * 50)
    print("  Vault Scan Summary")
    print("=" * 50)
    print(f"  Vault: {summary.get('vault_path', 'N/A')}")
    print(f"  Scan time: {summary.get('scan_time', 'N/A')}")
    print(f"  Notes scanned: {summary.get('total_notes_scanned', 0)}")
    print(f"  Nodes created: {summary.get('nodes_created', 0)}")
    print(f"  Nodes updated: {summary.get('nodes_updated', 0)}")
    print(f"  Edges created: {summary.get('edges_created', 0)}")
    print(f"  Stub nodes (unresolved): {summary.get('stub_nodes', 0)}")
    print(f"  Unresolved links: {summary.get('unresolved_links', 0)}")
    print(f"  Cycles detected: {summary.get('cycles_detected', 0)}")

    if summary.get("unresolved_details"):
        print("\n  Unresolved links (first 10):")
        for link in summary["unresolved_details"]:
            print(f"    {link['source']} → {link['target']}")

    if summary.get("cycle_details"):
        print("\n  Cycles detected (first 5):")
        for cycle in summary["cycle_details"]:
            print(f"    {' → '.join(cycle)}")

    print("=" * 50 + "\n")


if __name__ == "__main__":
    summary = scan_vault()
    print_summary(summary)

    if summary.get("error"):
        sys.exit(1)
