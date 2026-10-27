import json
import subprocess
import unittest
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path

from thejokebot.commands import dashboard_metrics, dashboard_workflows


REPO_ROOT = Path(__file__).resolve().parents[1]
DASHBOARD_HTML = REPO_ROOT / "dashboard" / "index.html"
DASHBOARD_JS = REPO_ROOT / "dashboard" / "app.js"
DASHBOARD_CSS = REPO_ROOT / "dashboard" / "styles.css"


class _Node:
    def __init__(self, tag, attributes, parent=None):
        self.tag = tag
        self.attributes = dict(attributes)
        self.parent = parent
        self.children = []
        self.text = ""

    def descendants(self):
        for child in self.children:
            yield child
            yield from child.descendants()


class _DocumentParser(HTMLParser):
    VOID_ELEMENTS = {
        "area",
        "base",
        "br",
        "col",
        "embed",
        "hr",
        "img",
        "input",
        "link",
        "meta",
        "source",
        "track",
        "wbr",
    }

    def __init__(self):
        super().__init__()
        self.root = _Node("document", [])
        self.stack = [self.root]

    def handle_starttag(self, tag, attrs):
        node = _Node(tag, attrs, self.stack[-1])
        self.stack[-1].children.append(node)
        if tag not in self.VOID_ELEMENTS:
            self.stack.append(node)

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag not in self.VOID_ELEMENTS:
            self.stack.pop()

    def handle_endtag(self, tag):
        if len(self.stack) > 1 and self.stack[-1].tag == tag:
            self.stack.pop()

    def handle_data(self, data):
        self.stack[-1].text += data


class DashboardUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        parser = _DocumentParser()
        parser.feed(DASHBOARD_HTML.read_text())
        parser.close()
        cls.nodes = list(parser.root.descendants())
        cls.by_id = {
            node.attributes["id"]: node for node in cls.nodes if "id" in node.attributes
        }

    def test_dashboard_tabs_have_reciprocal_accessible_relationships(self):
        tabs = [node for node in self.nodes if node.attributes.get("role") == "tab"]
        panels = [
            node for node in self.nodes if node.attributes.get("role") == "tabpanel"
        ]

        self.assertEqual(len(tabs), 2)
        self.assertEqual(len(panels), 2)
        self.assertEqual(
            sum(tab.attributes.get("aria-selected") == "true" for tab in tabs), 1
        )
        for tab in tabs:
            panel = self.by_id[tab.attributes["aria-controls"]]
            self.assertEqual(panel.attributes["aria-labelledby"], tab.attributes["id"])

    def test_range_controls_have_one_pressed_button_each(self):
        for attribute, count in (
            ("data-range", 6),
            ("data-operations-range", 6),
            ("data-top-range", 3),
            ("data-performance-age", 2),
        ):
            buttons = [node for node in self.nodes if attribute in node.attributes]
            self.assertEqual(len(buttons), count)
            self.assertEqual(
                sum(
                    button.attributes.get("aria-pressed") == "true"
                    for button in buttons
                ),
                1,
            )

    def test_operational_overview_and_tables_are_fully_visible(self):
        operations_panel = self.by_id["operations-panel"]
        details = [
            node for node in operations_panel.descendants() if node.tag == "details"
        ]

        self.assertEqual(details, [])
        for element_id in (
            "operational-pulse",
            "automation-rate",
            "posting-delivery-rate",
            "provider-table",
            "workflow-table",
        ):
            self.assertTrue(
                self._has_ancestor(self.by_id[element_id], operations_panel)
            )
        self.assertEqual(
            self.by_id["provider-table"].parent.parent.attributes["aria-labelledby"],
            "providers-heading",
        )
        self.assertEqual(
            self.by_id["workflow-table"].parent.parent.attributes["aria-labelledby"],
            "workflows-heading",
        )

    def test_collected_operational_alerts_have_specific_dashboard_messages(self):
        now = datetime(2026, 10, 27, 12, tzinfo=timezone.utc)
        alerts = dashboard_workflows._operational_alerts(
            {
                "workflows": [
                    {
                        "name": "python_tests",
                        "consecutive_failures": 6,
                    },
                    {
                        "name": "bluesky_follows_and_likes",
                        "last_run_at": "2026-10-27T07:00:00Z",
                        "last_conclusion": "failure",
                        "expected_interval_hours": 2,
                    },
                ]
            },
            {"providers": [{"configured": True, "healthy": False}]},
            {"windows": {"7": {"missed": 2}}},
            now,
            state={"joke_requests": {}},
            workflow_runs=[
                {
                    "id": 42,
                    "name": "bluesky_follows_and_likes",
                    "conclusion": "failure",
                    "created_at": "2026-10-27T07:00:00Z",
                }
            ],
            workflow_activity={"runs": [{"id": 42, "follows": 1}]},
        )
        alerts.extend(
            [
                {"kind": "stale_dashboard"},
                {"kind": "provider_health", "count": 2},
                {"kind": "posting_delivery", "count": 1},
                {"kind": "future_alert"},
            ]
        )
        javascript = DASHBOARD_JS.read_text()
        names = javascript[
            javascript.index("function displayName(") : javascript.index(
                "function appendCell("
            )
        ]
        formatter = javascript[
            javascript.index("function operationalAlertText(") : javascript.index(
                "function renderOperationalPulse("
            )
        ]
        result = subprocess.run(
            [
                "node",
                "-e",
                'const fs = require("node:fs");'
                'const numberFormat = new Intl.NumberFormat("en-GB");'
                + names
                + formatter
                + "console.log(JSON.stringify("
                'JSON.parse(fs.readFileSync(0, "utf8")).map(operationalAlertText)));',
            ],
            input=json.dumps(alerts),
            check=True,
            capture_output=True,
            text=True,
        )
        self.assertEqual(
            json.loads(result.stdout),
            [
                "Python tests failed 6 consecutive completed runs; check the workflow logs",
                "Follows and likes is overdue",
                "Follows and likes failed most recently",
                "Follows and likes run 42 failed after making changes; verify saved state against completed actions before retrying",
                "Joke-request checking is overdue; check the Follows and likes workflow",
                "1 configured provider needs attention",
                "2 posting slots missed in 7 complete days",
                "Dashboard collection is overdue",
                "2 configured providers need attention",
                "1 posting slot missed in 7 complete days",
                "Unrecognised operational alert: future_alert; check the dashboard collector",
            ],
        )

    def test_audience_growth_unifies_sources_and_removes_generic_privacy_copy(self):
        text = " ".join(node.text.strip() for node in self.nodes if node.text.strip())

        self.assertIn("Audience growth", text)
        self.assertNotIn("Discovery activity", text)
        self.assertNotIn("Account and targeting details are not retained", text)
        for source_id in ("followback", "interaction", "discovery"):
            self.assertIn(f"growth-{source_id}-success", self.by_id)
            self.assertIn(f"growth-{source_id}-30", self.by_id)
            self.assertIn(f"growth-{source_id}-90", self.by_id)
        self.assertEqual(self.by_id["growth-cohort-table"].tag, "table")

    def test_growth_labels_separate_follow_completion_from_relationship_outcomes(self):
        source = self.by_id["growth-followback-success"].parent
        self.assertIn(
            "Follow completion", " ".join(node.text for node in source.children)
        )
        self.assertIn("response-window-duration", self.by_id)
        self.assertNotIn("30-day protection", DASHBOARD_HTML.read_text())
        self.assertIn("Existing followers", DASHBOARD_HTML.read_text())

    def test_collected_growth_shows_follow_counts_and_observed_cohort_samples(self):
        now = datetime(2026, 10, 27, 12, tzinfo=timezone.utc)
        social = {
            "completed_runs": 1,
            "follow_back_candidates": 8,
            "follow_back_added": 6,
            "interaction_candidates": 12,
            "interaction_eligible": 5,
            "interaction_added": 3,
            "runs": [{"created_at": now.isoformat()}],
        }
        growth = dashboard_metrics._audience_growth_metrics(
            {},
            [],
            {"selected": 20, "followed": 10},
            social,
            now,
        )
        growth["cohorts"]["periods"] = [
            {
                "month": "2026-09",
                "source": "discovery",
                "acquired": 20,
                "checkpoints": {
                    "30": {
                        "observed": 10,
                        "still_following": 4,
                        "rate": 40,
                        "pending_due": 2,
                    },
                    "90": {
                        "observed": 0,
                        "still_following": 0,
                        "rate": None,
                        "pending_due": 1,
                    },
                },
            }
        ]
        rendered = self._render_growth(growth, social=social, days=90)

        self.assertEqual(rendered["growth-followback-success"], "6/8 (75%)")
        self.assertEqual(
            rendered["growth-interaction-context"],
            "12 candidates; 5 eligible accounts",
        )
        self.assertEqual(
            rendered["growth-discovery-30"],
            "4/10 observed (40%) · 2 due",
        )
        self.assertEqual(rendered["growth-discovery-90"], "Not yet observed · 1 due")
        self.assertEqual(
            rendered["growth-reciprocity-note"], "4/10 observed accounts following us"
        )
        self.assertEqual(rendered["response-window-duration"], "90-day protection")

    def test_growth_unavailable_and_zero_denominators_are_not_success(self):
        growth = dashboard_metrics._audience_growth_metrics(
            {}, [], {}, {}, datetime(2026, 10, 27, tzinfo=timezone.utc)
        )
        for days in (None, 30):
            with self.subTest(days=days):
                rendered = self._render_growth(growth, days=days)
                self.assertEqual(rendered["growth-followback-success"], "--")
                self.assertEqual(rendered["growth-discovery-30"], "Not yet observed")
                self.assertEqual(
                    rendered["response-window-duration"],
                    "Duration unavailable" if days is None else "30-day protection",
                )

    def test_growth_keeps_legacy_telemetry_and_zero_cohort_outcomes_readable(self):
        growth = dashboard_metrics._audience_growth_metrics(
            {},
            [],
            {},
            {"interaction_eligible": 3, "interaction_added": 0},
            datetime(2026, 10, 27, tzinfo=timezone.utc),
        )
        growth["cohorts"]["periods"] = [
            {
                "month": "2026-09",
                "source": "interaction",
                "acquired": 3,
                "checkpoints": {
                    "30": {"observed": 3, "still_following": 0, "rate": 0},
                },
            }
        ]
        rendered = self._render_growth(growth, social={"completed_runs": 1})
        self.assertEqual(rendered["growth-interaction-context"], "3 eligible accounts")
        self.assertEqual(rendered["growth-interaction-success"], "0/3 (0%)")
        self.assertEqual(rendered["growth-interaction-30"], "0/3 observed (0%)")
        self.assertEqual(rendered["growth-interaction-90"], "Not yet observed")
        self.assertNotIn("NaN", json.dumps(rendered))

    @staticmethod
    def _render_growth(growth, *, social=None, days=None):
        javascript = DASHBOARD_JS.read_text()
        growth_functions = javascript[
            javascript.index("function checkpointSummary(") : javascript.index(
                "function renderStarterPackAttribution("
            )
        ]
        maintenance = javascript[
            javascript.index("function renderNetworkMaintenance(") : javascript.index(
                "function renderSocialActivity("
            )
        ]
        result = subprocess.run(
            [
                "node",
                "-e",
                'const fs = require("node:fs");'
                'const metrics = JSON.parse(fs.readFileSync(0, "utf8"));'
                'const numberFormat = new Intl.NumberFormat("en-GB");'
                'const percentageFormat = new Intl.NumberFormat("en-GB", {maximumFractionDigits:1});'
                'const dateFormat = new Intl.DateTimeFormat("en-GB");'
                "const values = {};"
                "const setText = (id, value) => { values[id] = value; };"
                "const metricText = value => value == null ? '--' : numberFormat.format(value);"
                "const signedNumber = value => String(value);"
                "const renderTable = () => {};"
                "const document = {getElementById: () => ({})};"
                + growth_functions
                + maintenance
                + "renderAudienceGrowth();renderNetworkMaintenance(metrics.network_maintenance);"
                + "console.log(JSON.stringify(values));",
            ],
            input=json.dumps(
                {
                    "audience_growth": growth,
                    "social_activity": social or {},
                    "network_maintenance": {"response_window": {"days": days}},
                }
            ),
            check=True,
            capture_output=True,
            text=True,
        )
        return json.loads(result.stdout)

    def test_starter_pack_introductions_show_separate_windows(self):
        self.assertIn("starter-pack-total-7", self.by_id)
        self.assertIn("starter-pack-total-30", self.by_id)
        self.assertEqual(
            self.by_id["starter-pack-total-7"].parent.attributes,
            {},
        )

    def test_audience_growth_has_responsive_source_layout(self):
        stylesheet = DASHBOARD_CSS.read_text()

        self.assertIn(
            ".growth-source-grid {\n  display: grid;\n  grid-template-columns: repeat(3, minmax(0, 1fr));",
            stylesheet,
        )
        self.assertIn(
            ".growth-source-grid {\n    grid-template-columns: 1fr;\n  }",
            stylesheet,
        )

    def test_latest_and_top_jokes_share_the_bluesky_embed_renderer(self):
        javascript = DASHBOARD_JS.read_text()

        self.assertIn("function createPostEmbed(post)", javascript)
        self.assertIn("stage.replaceChildren(createPostEmbed(latest))", javascript)
        self.assertIn("article.append(createPostEmbed(post))", javascript)
        self.assertIn("window.bluesky.scan(container)", javascript)
        self.assertEqual(self.by_id["top-posts"].attributes["aria-live"], "polite")

    def test_top_jokes_use_responsive_columns(self):
        stylesheet = DASHBOARD_CSS.read_text()

        self.assertIn(
            ".post-grid {\n  display: grid;\n  grid-template-columns: repeat(2, minmax(0, 1fr));",
            stylesheet,
        )
        self.assertIn(
            "@media (max-width: 900px)",
            stylesheet,
        )
        self.assertIn(
            ".post-grid {\n    grid-template-columns: 1fr;\n  }",
            stylesheet,
        )

    def test_no_script_fallback_exposes_both_dashboard_views(self):
        no_script_styles = [
            node
            for node in self.nodes
            if node.tag == "style"
            and any(parent.tag == "noscript" for parent in self._ancestors(node))
        ]

        self.assertEqual(len(no_script_styles), 1)
        self.assertIn('[role="tabpanel"][hidden]', no_script_styles[0].text)
        self.assertIn("display: block", no_script_styles[0].text)

    def test_pages_staging_contains_deployed_dashboard_assets(self):
        subprocess.run(
            [str(REPO_ROOT / "scripts" / "prepare-dashboard-pages.sh")],
            cwd=REPO_ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
        staging = REPO_ROOT / ".agent-tmp" / "pages"
        for relative_path in (
            ".nojekyll",
            "index.html",
            "app.js",
            "history.js",
            "styles.css",
            "data/metrics.json",
            "data/history/daily.json",
            "images/jokebot_cover.png",
            "images/jokebot_logo.webp",
        ):
            self.assertTrue((staging / relative_path).exists(), relative_path)

    @staticmethod
    def _ancestors(node):
        current = node.parent
        while current is not None:
            yield current
            current = current.parent

    @classmethod
    def _has_ancestor(cls, node, ancestor):
        return ancestor in cls._ancestors(node)


if __name__ == "__main__":
    unittest.main()
