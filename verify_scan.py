#!/usr/bin/env python3
"""Verify the knowledge graph data in SQLite after vault scan."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent / "skills" / "study-planner" / "scripts"))
import db_manager

config = db_manager.load_config()

print("=== Knowledge Nodes ===")
nodes = db_manager.get_all_nodes(config)
for node in nodes:
    print(f"  [{node['note_id']}] {node['title']}")
    print(f"    type: {node.get('concept_type', 'N/A')}")
    print(f"    difficulty: {node.get('difficulty', 'N/A')}")
    print(f"    mastery: {node.get('mastery', 'N/A')}")
    print(f"    state: {node.get('learning_state', 'N/A')}")
    print(f"    file: {node.get('file_path', 'N/A')}")
    print()

print("\n=== Knowledge Edges ===")
edges = db_manager.get_edges(config=config)
for edge in edges:
    src = db_manager.get_node(edge["source_id"], config=config)
    tgt = db_manager.get_node(edge["target_id"], config=config)
    src_title = src["title"] if src else edge["source_id"]
    tgt_title = tgt["title"] if tgt else edge["target_id"]
    print(f"  {src_title} --[{edge['edge_type']}]--> {tgt_title}")

print(f"\n=== Stats ===")
stats = db_manager.get_stats(config)
for key, val in stats.items():
    print(f"  {key}: {val}")
