import os
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


class MigrationTest(unittest.TestCase):
    def test_upgrade_creates_ai_writing_tables(self):
        project_root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as directory:
            database_path = Path(directory) / 'blog.db'
            env = os.environ.copy()
            env['DATABASE_URL'] = f'sqlite:///{database_path}'
            result = subprocess.run(
                [sys.executable, '-m', 'alembic', 'upgrade', 'head'],
                cwd=project_root,
                env=env,
                capture_output=True,
                text=True,
                timeout=30,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            with sqlite3.connect(database_path) as connection:
                tables = {
                    row[0]
                    for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")
                }
            self.assertTrue({
                'ai_writing_session', 'ai_writing_message', 'ai_writing_image',
                'ai_research_source', 'ai_writing_job'
            }.issubset(tables))
            with sqlite3.connect(database_path) as connection:
                columns = {
                    row[1]
                    for row in connection.execute("PRAGMA table_info('ai_writing_session')")
                }
            self.assertTrue({'research_queries', 'citation_warnings'}.issubset(columns))
            self.assertTrue({
                'writing_mode', 'style_notes', 'pre_humanized_title',
                'pre_humanized_content', 'humanize_summary'
            }.issubset(columns))


if __name__ == '__main__':
    unittest.main()
