import subprocess
import unittest
from html.parser import HTMLParser
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
DASHBOARD_HTML = REPO_ROOT / "dashboard" / "index.html"


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

    def handle_starttag(self, tag, attributes):
        node = _Node(tag, attributes, self.stack[-1])
        self.stack[-1].children.append(node)
        if tag not in self.VOID_ELEMENTS:
            self.stack.append(node)

    def handle_startendtag(self, tag, attributes):
        self.handle_starttag(tag, attributes)
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
        for attribute in ("data-range", "data-top-range"):
            buttons = [node for node in self.nodes if attribute in node.attributes]
            self.assertEqual(len(buttons), 3)
            self.assertEqual(
                sum(
                    button.attributes.get("aria-pressed") == "true"
                    for button in buttons
                ),
                1,
            )

    def test_operational_overview_precedes_collapsed_tables(self):
        operations_panel = self.by_id["operations-panel"]
        details = [
            node for node in operations_panel.descendants() if node.tag == "details"
        ]

        self.assertEqual(len(details), 2)
        for element_id in (
            "operational-pulse",
            "automation-rate",
            "posting-delivery-rate",
        ):
            self.assertNotIn(self.by_id[element_id].parent, details)
            self.assertFalse(
                any(
                    ancestor is not None and ancestor in details
                    for ancestor in self._ancestors(self.by_id[element_id])
                )
            )
        self.assertTrue(self._has_ancestor(self.by_id["provider-table"], details[0]))
        self.assertTrue(self._has_ancestor(self.by_id["workflow-table"], details[1]))
        self.assertEqual(
            self.by_id["provider-table"].parent.parent.attributes["aria-labelledby"],
            "providers-heading",
        )
        self.assertEqual(
            self.by_id["workflow-table"].parent.parent.attributes["aria-labelledby"],
            "workflows-heading",
        )

    def test_discovery_uses_clear_success_rate_wording(self):
        text = " ".join(node.text.strip() for node in self.nodes if node.text.strip())
        self.assertIn("Follow success rate", text)

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
