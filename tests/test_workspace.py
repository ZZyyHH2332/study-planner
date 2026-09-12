"""Offline workspace regressions. Only isolated temporary databases are used."""

import json
import sys
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "skills" / "study-planner" / "scripts"))
import dashboard
import db_manager
import demo_data


class WorkspaceTests(unittest.TestCase):
    def node(self, identifier, mastery=.1, due=None, kind="concept", **extra):
        return dict(note_id=identifier, title=identifier, mastery=mastery,
                    next_review=due, concept_type=kind, **extra)

    def build(self, nodes, edges=(), reviews=(), **kwargs):
        return dashboard.build_workspace_data(nodes, edges, reviews,
                                              today=date(2026,9,12), **kwargs)

    def test_empty_workspace(self):
        data = self.build([])
        self.assertEqual(data["queue"], [])
        self.assertEqual(data["streak"], 0)
        self.assertEqual(len(data["calendar"]), 84)
        self.assertTrue(all(n == 0 for _, n in data["calendar"]))

    def test_due_priority_and_mastered_due(self):
        nodes = [self.node("new"), self.node("future", due="2026-09-20"),
                 self.node("due", due="2026-09-12"), self.node("old", .9, "2026-09-09"),
                 self.node("moc", kind="moc"), self.node("null", kind=None)]
        data = self.build(nodes)
        self.assertEqual(data["queue"], ["old", "due", "new"])

    def test_transitive_missing_and_cyclic_prerequisites(self):
        nodes = [self.node("a", .2, "2026-09-20"), self.node("b", .9),
                 self.node("c"), self.node("missing"), self.node("x"), self.node("y")]
        edges = [dict(source_id=a,target_id=b,edge_type="prerequisite")
                 for a,b in [("a","b"),("b","c"),("unknown","missing"),("x","y"),("y","x")]]
        data = self.build(nodes, edges)
        self.assertEqual(data["queue"], [])
        self.assertEqual(data["blocked_count"], 5)
        self.assertIn("a", next(n for n in data["nodes"] if n["note_id"] == "c")["blockers"])

    def test_due_reviews_are_not_blocked_by_prerequisites(self):
        data = self.build([self.node("a"),self.node("b",due="2026-09-12")],
                          [dict(source_id="a",target_id="b",edge_type="prerequisite")])
        self.assertEqual(data["queue"], ["b","a"])

    def test_related_edges_do_not_block(self):
        data = self.build([self.node("a"),self.node("b")],
                          [dict(source_id="a",target_id="b",edge_type="related")])
        self.assertEqual(len(data["queue"]), 2)

    def test_bad_dates_and_numbers_are_safe(self):
        data = self.build([self.node("n", float("nan"), "not-a-date", difficulty="oops")])
        self.assertEqual(data["queue"], [])
        self.assertEqual(data["nodes"][0]["mastery"], 0)
        self.assertEqual(data["nodes"][0]["difficulty"], 2)
        dashboard._safe_json(data)

    def test_streak_can_end_yesterday(self):
        reviews = [dict(review_date=d) for d in ["2026-09-11","2026-09-10","2026-09-08","2026-10-01"]]
        data = self.build([], reviews=reviews)
        self.assertEqual(data["streak"], 2)
        self.assertEqual(data["today_reviews"], 0)
        self.assertEqual(sum(count for _,count in data["calendar"]), 3)

    def test_configurable_threshold(self):
        nodes = [self.node("a",.8,"2026-09-20"),self.node("b")]
        edge = [dict(source_id="a",target_id="b",edge_type="prerequisite")]
        self.assertEqual(self.build(nodes,edge,config={"mastery_threshold":.9})["queue"], [])
        self.assertEqual(self.build(nodes,edge,config={"mastery_threshold":.7})["queue"], ["b"])

    def test_html_script_boundary_and_template_tokens(self):
        attack = '</script><img src=x onerror=alert(1)>__SCRIPT__'
        node = self.node("test", title_override=attack)
        node["title"] = attack
        html = dashboard.render_html({},[node],[],[],{},today=date(2026,9,12))
        self.assertNotIn('</script><img', html)
        data_text = html.split('<script type="application/json" id="workspace-data">',1)[1].split('</script>',1)[0]
        self.assertEqual(json.loads(data_text)["nodes"][0]["title"], attack)
        self.assertNotIn('src="https://', html)
        self.assertNotIn('href="https://', html)
        for marker in ["calendar-chart","mastery-chart","rating-chart","distribution-chart","graph-chart","stat-cards"]:
            self.assertIn(marker,html)

    def test_duplicate_titles_are_not_merged(self):
        reviews = [dict(note_id=n,title="same",new_mastery=m,review_date="2026-09-11")
                   for n,m in [("a",.2),("b",.8),("a",.4),("b",.9)]]
        self.assertEqual(len(dashboard.query_mastery_trends(reviews)), 2)
        self.assertEqual(len(dashboard.query_learning_velocity(reviews)), 2)
        self.assertAlmostEqual(dashboard.query_learning_velocity(reviews)[0]["velocity"], .2)

    def test_demo_requires_no_config_or_database(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(db_manager,"load_config",side_effect=AssertionError), patch.object(db_manager,"get_connection",side_effect=AssertionError):
            path = dashboard.generate_demo(Path(folder)/"nested"/"demo.html",False)
            self.assertTrue(Path(path).is_file())
            self.assertIn('"demo":true',Path(path).read_text(encoding="utf-8"))

    def test_render_does_not_read_note_content(self):
        with tempfile.TemporaryDirectory() as folder:
            secret = Path(folder)/"note.md"
            secret.write_text("DO_NOT_EMBED_THIS_NOTE",encoding="utf-8")
            node = self.node("local",file_path=str(secret),excerpt="DO_NOT_EMBED_THIS_NOTE")
            html = dashboard.render_html({},[node],[],[],{})
            self.assertNotIn("DO_NOT_EMBED_THIS_NOTE",html)

    def test_real_database_generation_leaves_rows_unchanged(self):
        with tempfile.TemporaryDirectory() as folder:
            config = {"db_path":str(Path(folder)/"test.db"),"vault_path":folder}
            db_manager.init_database(config)
            db_manager.upsert_node("n",title="真实数据库夹具",concept_type="concept",config=config)
            before = db_manager.get_all_nodes(config)
            dashboard.generate_dashboard(config,Path(folder)/"out"/"dashboard.html",False)
            self.assertEqual(before,db_manager.get_all_nodes(config))

    def test_demo_is_deterministic(self):
        self.assertEqual(demo_data.make_demo_data(date(2026,9,12)),demo_data.make_demo_data(date(2026,9,12)))


if __name__ == "__main__":
    unittest.main()
