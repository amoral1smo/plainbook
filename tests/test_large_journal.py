#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""A journal of some years: the front page draws its newest weeks and offers
the rest, and a read after a save parses only the file that changed."""
import importlib
import os
import re
import sys
import tempfile
import threading
import unittest
import urllib.request
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from plainbook import store
from plainbook.model import Account, Trade

ROW = re.compile(r'<tr><td class="cell"><a href="/trade/([^"?]+)')


def trade(root, day, pair="EURUSD", pnl=100.0):
    return Trade(id=store.new_id(root, day, pair), account="broker",
                 pair=pair, direction="long", style="swing", entry_tf="H4",
                 risk=1.0, opened=day, result="Win" if pnl > 0 else "Lose",
                 pnl=pnl, closed=day + timedelta(hours=5))


class ParsedCacheCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = self.tmp.name
        store.save_account(self.root, Account(id="broker", name="Broker",
                                              start_balance=10000))
        self.t = store.save_trade(self.root, trade(self.root, datetime(2025, 3, 3, 10)))

    def tearDown(self):
        self.tmp.cleanup()

    def test_a_record_changed_in_memory_does_not_reach_the_next_read(self):
        first = store.all_trades(self.root)[0]
        first.pair = "GBPUSD"
        first.execution.append("IDM")
        again = store.all_trades(self.root)[0]
        self.assertEqual((again.pair, again.execution), ("EURUSD", []))

    def test_a_save_is_read_back(self):
        store.all_trades(self.root)
        t = store.all_trades(self.root)[0]
        t.pnl = 250.0
        store.save_trade(self.root, t)
        self.assertEqual(store.all_trades(self.root)[0].pnl, 250.0)

    def test_a_file_edited_by_hand_in_place_is_read_back(self):
        store.all_trades(self.root)
        path = os.path.join(store.trade_dir(self.root, self.t.id), store.TRADE_FILE)
        with open(path, encoding="utf-8") as f:
            text = f.read()
        with open(path, "w", encoding="utf-8") as f:
            f.write(text.replace("EURUSD", "AUDNZD"))
        os.utime(path, ns=(os.stat(path).st_atime_ns, os.stat(path).st_mtime_ns + 10**9))
        self.assertEqual(store.all_trades(self.root)[0].pair, "AUDNZD")

    def test_a_trade_moved_to_the_trash_is_gone_and_forgotten(self):
        store.all_trades(self.root)
        store.delete_trade(self.root, self.t.id)
        self.assertEqual(store.all_trades(self.root), [])
        inside = os.path.join(self.root, store.JOURNAL, store.TRADES, "")
        self.assertFalse([p for p in store._parsed if p.startswith(inside)])

    def test_a_file_that_does_not_read_is_named_every_time(self):
        path = os.path.join(store.trade_dir(self.root, self.t.id), store.TRADE_FILE)
        with open(path, encoding="utf-8") as f:
            text = f.read()
        with open(path, "w", encoding="utf-8") as f:
            f.write(text.replace("entry: 2025-03-03", "entry: 2025-13-03"))
        for _ in range(2):
            problems = []
            self.assertEqual(store.all_trades(self.root, problems), [])
            self.assertEqual(len(problems), 1)


class FrontRowsCase(unittest.TestCase):
    """Fourteen weeks of three trades, drawn with room for ten rows."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.root = cls.tmp.name
        store.save_account(cls.root, Account(id="broker", name="Broker",
                                             start_balance=10000))
        monday = datetime(2025, 1, 6, 9)
        cls.ids = []
        for week in range(14):
            for day in range(3):
                t = store.save_trade(cls.root, trade(
                    cls.root, monday + timedelta(weeks=week, days=day),
                    pnl=100.0 if day else -50.0))
                cls.ids.append(t.id)
        os.environ["PLAINBOOK_ROOT"] = cls.root
        import plainbook.server
        cls.S = importlib.reload(plainbook.server)
        cls.rows = cls.S.FRONT_ROWS
        cls.S.FRONT_ROWS = 10
        cls.server = cls.S.Server(("127.0.0.1", 0), cls.S.Handler)
        cls.port = cls.server.server_address[1]
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.S.FRONT_ROWS = cls.rows
        cls.tmp.cleanup()
        os.environ.pop("PLAINBOOK_ROOT", None)

    def get(self, path):
        with urllib.request.urlopen(f"http://127.0.0.1:{self.port}{path}") as r:
            return r.read().decode("utf-8")

    def test_the_front_page_draws_whole_newest_weeks_and_offers_the_rest(self):
        html = self.get("/")
        rows = ROW.findall(html)
        # three weeks of three fit in ten rows, a fourth would not
        self.assertEqual(sorted(rows), sorted(self.ids[-9:]))
        self.assertEqual(html.count('<tr class="group">'), 3)
        self.assertIn("The newest 9 of 42 trades.", html)
        self.assertIn('href="/?all=1"', html)

    def test_every_drawn_week_carries_its_whole_total(self):
        html = self.get("/")
        self.assertEqual(html.count('<span class="dates">3 trades</span>'), 3)
        self.assertEqual(html.count('>+150<'), 3)

    def test_all_draws_every_trade_and_keeps_it_on_the_trades(self):
        html = self.get("/?all=1")
        self.assertEqual(len(ROW.findall(html)), 42)
        self.assertNotIn("The newest", html)
        self.assertIn(f'href="/trade/{self.ids[0]}?via=journal&all=1"', html)

    def test_a_filter_and_the_grouping_go_along_to_the_rest(self):
        html = self.get("/?group=month&account=broker")
        self.assertIn('href="/?group=month&amp;account=broker&amp;all=1"', html)

    def test_the_tiles_still_count_the_whole_selection(self):
        html = self.get("/")
        self.assertRegex(html, r'<div class="value">42</div><div class="sub">trades</div>')

    def test_a_journal_that_fits_is_drawn_as_it_was(self):
        self.S.FRONT_ROWS = 500
        try:
            html = self.get("/")
        finally:
            self.S.FRONT_ROWS = 10
        self.assertEqual(len(ROW.findall(html)), 42)
        self.assertNotIn("The newest", html)


if __name__ == "__main__":
    unittest.main()
