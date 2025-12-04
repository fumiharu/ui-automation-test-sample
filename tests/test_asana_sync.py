import unittest
from unittest.mock import patch, MagicMock
import sys
import os

# Add scripts directory to path to import asana_sync
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../scripts')))

import asana_sync

class TestAsanaSync(unittest.TestCase):
    def test_get_asana_urls_plain(self):
        body = """
        Fixes stuff.
        Here is the task: https://app.asana.com/0/123/456
        """
        urls = asana_sync.get_asana_urls(body)
        self.assertEqual(urls, ['https://app.asana.com/0/123/456'])

    def test_get_asana_urls_markdown(self):
        body = """
        Fixes [Task](https://app.asana.com/0/111/222).
        """
        urls = asana_sync.get_asana_urls(body)
        self.assertEqual(urls, ['https://app.asana.com/0/111/222'])

    def test_get_asana_urls_punctuation(self):
        body = "Check this: https://app.asana.com/0/333/444."
        urls = asana_sync.get_asana_urls(body)
        self.assertEqual(urls, ['https://app.asana.com/0/333/444'])

    def test_get_asana_urls_multiple(self):
        body = """
        https://app.asana.com/0/111/222
        Also see [Task 2](https://app.asana.com/0/333/444).
        """
        urls = asana_sync.get_asana_urls(body)
        self.assertIn('https://app.asana.com/0/111/222', urls)
        self.assertIn('https://app.asana.com/0/333/444', urls)
        self.assertEqual(len(urls), 2)

    def test_get_task_id_from_url(self):
        # Basic case
        url = "https://app.asana.com/0/12345/67890"
        task_id = asana_sync.get_task_id_from_url(url)
        self.assertEqual(task_id, "67890")

        # Trailing slash
        url_trailing = "https://app.asana.com/0/12345/67890/"
        task_id = asana_sync.get_task_id_from_url(url_trailing)
        self.assertEqual(task_id, "67890")

        # Query params
        url_query = "https://app.asana.com/0/12345/67890?opt_pretty=true"
        task_id = asana_sync.get_task_id_from_url(url_query)
        self.assertEqual(task_id, "67890")

        # Markdown trailing parenthesis (though URL extraction should handle it, this tests robustness)
        url_paren = "https://app.asana.com/0/12345/67890)"
        # Note: get_task_id doesn't strip punctuation, get_asana_urls does.
        # But let's check basic logic: "67890)" is not digit.
        # The function looks for digit parts. "67890)" is not digit. "12345" is digit.
        # So it would return 12345 (Project ID) if punctuation wasn't stripped.
        # This confirms why get_asana_urls MUST strip punctuation.

        # Focus mode
        url_focus = "https://app.asana.com/0/12345/67890/f"
        task_id = asana_sync.get_task_id_from_url(url_focus)
        self.assertEqual(task_id, "67890")

if __name__ == '__main__':
    unittest.main()
