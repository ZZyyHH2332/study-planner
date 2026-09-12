"""Configuration and scheduling regressions without a personal vault."""
import json
import sys
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "skills" / "study-planner" / "scripts"))
import db_manager
import fsrs_engine
import profile_manager


class ConfigTests(unittest.TestCase):
    def test_default_path_is_project_root(self):
        with patch.object(Path,"is_file",return_value=False):
            with self.assertRaises(FileNotFoundError) as error:
                db_manager.load_config()
        self.assertIn(str(ROOT/"config.json"),str(error.exception))

    def test_relative_paths_resolve_against_config(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/"config.json"
            path.write_text(json.dumps({"db_path":"data/a.db","vault_path":"notes"}),encoding="utf-8-sig")
            config = db_manager.load_config(path)
            self.assertEqual(config["db_path"],str(Path(folder)/"data"/"a.db"))
            self.assertEqual(config["vault_path"],str(Path(folder)/"notes"))
            self.assertFalse((Path(folder)/"data").exists())

    def test_bad_configuration_reports_error(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/"config.json"
            for value in [[],{}, {"db_path":42,"vault_path":"notes"}]:
                path.write_text(json.dumps(value),encoding="utf-8")
                with self.assertRaises(ValueError):
                    db_manager.load_config(path)


class SchedulerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.config = {"db_path":str(Path(self.temp.name)/"test.db"),"vault_path":self.temp.name}
        db_manager.init_database(self.config)
        profile_manager.init_profile(self.config)

    def tearDown(self):
        self.temp.cleanup()

    def add(self,note_id,due=None,mastery=.1,kind="concept",state="pending",difficulty=2):
        db_manager.upsert_node(note_id,title=note_id,next_review=due,mastery=mastery,
                               concept_type=kind,learning_state=state,difficulty=difficulty,config=self.config)

    def test_due_order_includes_mastered_and_excludes_nonlearning(self):
        today = datetime.now().date()
        self.add("new")
        self.add("today",today.isoformat())
        self.add("old",(today-timedelta(days=4)).isoformat(),.95,state="mastered")
        self.add("yesterday",(today-timedelta(days=1)).isoformat())
        self.add("future",(today+timedelta(days=1)).isoformat())
        for i,kind in enumerate(["moc","literature","stub",None,""]):
            self.add("skip"+str(i),kind=kind)
        expected = ["old","yesterday","today","new"]
        self.assertEqual([n["note_id"] for n in fsrs_engine.get_due_reviews(self.config)],expected)
        self.assertEqual([n["note_id"] for n in fsrs_engine.get_review_queue(2,self.config)],expected[:2])
        self.assertEqual(fsrs_engine.get_review_queue(0,self.config),[])

    def test_queue_ties_are_deterministic(self):
        for key in ["c","a","b"]:
            self.add(key)
        self.assertEqual([n["note_id"] for n in fsrs_engine.get_due_reviews(self.config)],["a","b","c"])

    def test_bad_limits_fail(self):
        for limit in [-1,True,1.2,"4"]:
            with self.assertRaises(ValueError):
                fsrs_engine.get_review_queue(limit,self.config)

    def test_hard_never_longer_than_good(self):
        for repetition in range(6):
            for ease in [1.3,2.5,3.0]:
                hard = fsrs_engine.calculate_interval(repetition,ease,2,10)[0]
                good = fsrs_engine.calculate_interval(repetition,ease,3,10)[0]
                easy = fsrs_engine.calculate_interval(repetition,ease,4,10)[0]
                self.assertLessEqual(hard,good)
                self.assertLessEqual(good,easy)

    def test_invalid_rating_never_writes(self):
        self.add("n")
        before = db_manager.get_node("n",self.config)
        for rating in [0,5,True,3.0,"3",None]:
            with self.assertRaises(ValueError):
                fsrs_engine.schedule_review("n",rating,self.config)
            with self.assertRaises(ValueError):
                fsrs_engine.calculate_interval(1,2.5,rating)
        self.assertEqual(before,db_manager.get_node("n",self.config))

    def test_latest_log_uses_id_when_timestamp_ties(self):
        self.add("n")
        db_manager.upsert_node("n",review_count=3,config=self.config)
        conn = db_manager.get_connection(self.config)
        for interval in [3,10]:
            conn.execute("INSERT INTO review_log(note_id,review_date,rating,new_interval,created_at) VALUES(?,?,?,?,?)",("n","2026-09-10",3,interval,"2026-09-10 10:00:00"))
        conn.commit()
        conn.close()
        result = fsrs_engine.schedule_review("n",3,self.config)
        self.assertEqual(result["prev_interval"],10)
        self.assertEqual(result["new_interval"],25)

    def test_session_preserves_intervals_after_bkt_creates_pending_log(self):
        from session_sync import StudySession
        self.add("n")
        session = StudySession(self.config)
        intervals = [session.review("n",3,True)["new_interval"] for _ in range(4)]
        self.assertEqual(intervals,[2,4,10,25])
        conn = db_manager.get_connection(self.config)
        recorded = [r[0] for r in conn.execute("SELECT new_interval FROM review_log ORDER BY id")]
        conn.close()
        self.assertEqual(recorded,intervals)
        summary = session.end()
        self.assertEqual(summary["reviews_count"],4)
        self.assertEqual(summary["frontmatter_synced"]["skipped"],1)

    def test_session_invalid_input_does_not_create_session_or_change_mastery(self):
        from session_sync import StudySession
        self.add("n")
        before = db_manager.get_node("n",self.config)
        session = StudySession(self.config)
        with self.assertRaises(ValueError):
            session.review("n",5,True)
        with self.assertRaises(ValueError):
            session.review("missing",3,True)
        self.assertEqual(before,db_manager.get_node("n",self.config))
        self.assertEqual(db_manager.get_stats(self.config)["total_sessions"],0)

    def test_lapse_resets_next_successful_interval(self):
        from session_sync import StudySession
        self.add("n")
        session = StudySession(self.config)
        for _ in range(3):
            session.review("n",3,True)
        self.assertEqual(session.review("n",1,False)["new_interval"],0)
        self.assertEqual(session.review("n",3,True)["new_interval"],2)
        session.end()

    def test_stats_respect_custom_threshold(self):
        self.add("n",mastery=.8)
        self.assertEqual(db_manager.get_stats(dict(self.config,mastery_threshold=.9))["mastered_nodes"],0)
        self.assertEqual(db_manager.get_stats(self.config)["mastered_nodes"],1)


if __name__ == "__main__":
    unittest.main()
