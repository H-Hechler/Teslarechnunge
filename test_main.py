import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import main


class FakeTesla:
    def __init__(self, pages, pdf=b'%PDF-1.7 test'):
        self.pages = pages
        self.pdf = pdf
        self.downloads = []

    def get(self, path, **params):
        if path.endswith('/history'):
            return json.dumps({'response': {'data': self.pages[params['pageNo'] - 1]}}).encode()
        self.downloads.append(path)
        return self.pdf


class DownloaderTests(unittest.TestCase):
    def test_all_pages_and_all_invoices_and_skip_existing(self):
        pages = [[{'invoices': [{'contentId': 'a'}, {'contentId': '../b'}]}],
                 [{'invoices': [{'contentId': 'c'}]}], []]
        with tempfile.TemporaryDirectory() as directory:
            api = FakeTesla(pages)
            main.sync(api, Path(directory))
            self.assertEqual(3, len(list(Path(directory).glob('*.pdf'))))
            main.sync(api, Path(directory))
            self.assertEqual(3, len(api.downloads))

    def test_non_pdf_is_not_saved(self):
        with tempfile.TemporaryDirectory() as directory:
            api = FakeTesla([[{'invoices': [{'contentId': 'a'}]}], []], b'<html>error</html>')
            with self.assertRaises(main.AppError):
                main.sync(api, Path(directory))
            self.assertEqual([], list(Path(directory).iterdir()))

    def test_repeated_page_stops(self):
        row = [{'invoices': []}]
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(main.AppError):
                main.sync(FakeTesla([row, row]), Path(directory))

    def test_unknown_history_is_error(self):
        with self.assertRaises(main.AppError):
            main.records_from({'response': {'unexpected': []}})

    def test_refresh_token_is_saved(self):
        api = main.Tesla.__new__(main.Tesla)
        api.client = 'test'
        api.credentials = {'refresh_token': 'old', 'client_secret': 'secret'}
        from unittest.mock import Mock
        api.vault = Mock()
        with patch.object(main, 'token_request', return_value={
                'access_token': 'new-access', 'refresh_token': 'rotated', 'expires_in': 3600}):
            self.assertEqual('new-access', api.token())
        self.assertEqual('rotated', api.vault.write.call_args.args[0]['refresh_token'])


if __name__ == '__main__':
    unittest.main()
