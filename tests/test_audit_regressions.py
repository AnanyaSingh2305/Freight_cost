import contextlib
import importlib.util
import io
import json
import math
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch
from datetime import date, timedelta

from freight_assistant.__main__ import main
from freight_assistant.dashboard_state import analysis_revision, load_saved
from freight_assistant.detection import Config, is_candidate, load_config
from freight_assistant.download_model import MODEL_REVISION, ensure_model
from freight_assistant.evidence import load_annotations
from freight_assistant.metrics import percent_change, weekly_metrics
from freight_assistant.pipeline import ROOT, analyze, save_analysis
from freight_assistant.retrieval import load_cached_vectors
from freight_assistant.validation import load_notes, Shipment


class InputFailureTests(unittest.TestCase):
    def test_unknown_configuration_field_is_an_actionable_cli_error(self):
        with tempfile.TemporaryDirectory() as temporary:
            config = Path(temporary) / 'config.json'
            config.write_text('{"anomaly_theshold_pct": 15}')
            error = io.StringIO()
            with patch.object(sys, 'argv', ['freight_assistant', '--config', str(config)]), contextlib.redirect_stderr(error):
                self.assertEqual(main(), 1)
            self.assertIn('Unknown configuration fields: anomaly_theshold_pct', error.getvalue())
            self.assertNotIn('Traceback', error.getvalue())

    def test_configuration_requires_an_object(self):
        with tempfile.TemporaryDirectory() as temporary:
            config = Path(temporary) / 'config.json'
            config.write_text('[]')
            with self.assertRaisesRegex(ValueError, 'JSON object'):
                load_config(config)

    def test_configuration_rejects_boolean_numbers(self):
        with self.assertRaises(ValueError):
            Config(minimum_evidence_coverage=True)
        with self.assertRaises(ValueError):
            Config(anomaly_threshold_pct=10 ** 1000)

    def test_incomplete_annotations_fail_validation(self):
        notes = load_notes(ROOT / 'data/context_notes.csv')
        for payload in ([], {'schema_version': 1}, {'schema_version': 1, 'annotations': {}},
                        {'schema_version': 1, 'annotations': [{'note_id': 'N001'}]}):
            with self.subTest(payload=payload), tempfile.TemporaryDirectory() as temporary:
                path = Path(temporary) / 'annotations.json'
                path.write_text(json.dumps(payload))
                with self.assertRaises(ValueError):
                    load_annotations(path, notes)

    def test_annotation_required_fields_cannot_be_wrong_types(self):
        document = json.loads((ROOT / 'data/note_annotations.json').read_text())
        document['annotations'][0]['evidence_quote'] = ['unsupported type']
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / 'annotations.json'
            path.write_text(json.dumps(document))
            with self.assertRaisesRegex(ValueError, 'nonempty strings'):
                load_annotations(path, load_notes(ROOT / 'data/context_notes.csv'))

    def test_incomplete_manifest_is_a_validation_error(self):
        for files in (None, [], {}):
            with self.subTest(files=files), tempfile.TemporaryDirectory() as temporary:
                model = Path(temporary) / f'minilm-onnx-{MODEL_REVISION}'
                model.mkdir()
                (model / 'artifact_manifest.json').write_text(json.dumps({'revision': MODEL_REVISION, 'files': files}))
                with self.assertRaisesRegex(ValueError, 'manifest'):
                    ensure_model(temporary, offline=True)


class NumericBoundaryTests(unittest.TestCase):
    def test_exact_fifteen_percent_decimal_rise_is_flagged(self):
        change = percent_change(2.3, 2)
        row = dict(vs_own_history_pct=change, vs_similar_routes_pct=None, vs_previous_observed_pct=change)
        self.assertTrue(is_candidate(row, Config()))

    def test_a_real_below_threshold_rise_is_not_rounded_into_an_anomaly(self):
        row = dict(vs_own_history_pct=14.999999, vs_similar_routes_pct=None, vs_previous_observed_pct=14.999999)
        self.assertFalse(is_candidate(row, Config()))

    def test_percentage_overflow_is_rejected(self):
        with self.assertRaisesRegex(ValueError, 'numeric range'):
            percent_change(1e308, 1e-300)

    def test_weekly_total_overflow_is_rejected_with_route_context(self):
        shipments = [Shipment(str(i), 'A', 'B', 'Short', 1, 1, 1e308, date(2025, 1, 6)) for i in range(2)]
        with self.assertRaisesRegex(ValueError, 'A-B'):
            weekly_metrics(shipments)

    def test_large_but_representable_history_mean(self):
        shipments = [Shipment(str(i), 'A', 'B', 'Short', 1, 1, 1e308,
                              date(2025, 1, 6) + timedelta(weeks=i)) for i in range(3)]
        row = weekly_metrics(shipments)[-1]
        self.assertTrue(math.isfinite(row['history_average']))
        self.assertEqual(row['history_average'], 1e308)


class SavedStateTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        for directory in ('data', 'freight_assistant'):
            shutil.copytree(ROOT / directory, self.root / directory, ignore=shutil.ignore_patterns('__pycache__'))
        shutil.copyfile(ROOT / 'config.json', self.root / 'config.json')
        rows, audit, cost = analyze(mode='lexical')
        save_analysis(self.root / 'results', rows, audit, cost)
        self.revision = analysis_revision(self.root)

    def test_unchanged_saved_results_load(self):
        self.assertEqual(len(load_saved(self.root, self.revision)['rows']), 728)

    def test_changed_shipment_input_does_not_load_old_results(self):
        path = self.root / 'data/shipment_records.csv'
        path.write_bytes(path.read_bytes() + b'\n')
        revision = analysis_revision(self.root)
        self.assertNotEqual(revision, self.revision)
        self.assertIsNone(load_saved(self.root, revision))

    def test_context_and_config_changes_invalidate_the_cache_key(self):
        for relative in ('data/context_notes.csv', 'data/note_annotations.json', 'config.json'):
            path = self.root / relative
            original = path.read_bytes()
            path.write_bytes(original + b'\n')
            self.assertNotEqual(analysis_revision(self.root), self.revision)
            path.write_bytes(original)

    def test_corrupt_saved_json_is_rejected(self):
        (self.root / 'results/audit.json').write_text('{broken')
        with self.assertRaises(ValueError):
            load_saved(self.root, self.revision)

    def test_incomplete_saved_envelope_is_a_clear_error(self):
        (self.root / 'results/audit.json').write_text('{"schema_version": 1}')
        with self.assertRaisesRegex(ValueError, 'incomplete'):
            load_saved(self.root, self.revision)

    def test_modified_saved_reason_does_not_match_the_recorded_export(self):
        path = self.root / 'results/audit.json'
        document = json.loads(path.read_text())
        document['rows'][0]['reason'] = 'changed reason'
        path.write_text(json.dumps(document))
        with self.assertRaisesRegex(ValueError, 'CSV hash'):
            load_saved(self.root, self.revision)

    def test_source_paths_are_portable_across_path_separators(self):
        path = self.root / 'results/audit.json'
        document = json.loads(path.read_text())
        document['source_sha256'] = {name.replace('\\', '/'): digest for name, digest in document['source_sha256'].items()}
        path.write_text(json.dumps(document))
        self.assertIsNotNone(load_saved(self.root, self.revision))


@unittest.skipUnless(importlib.util.find_spec('numpy'), 'Optional semantic-cache check needs NumPy')
class VectorCacheTests(unittest.TestCase):
    def test_corrupt_or_wrong_shape_vectors_are_discarded(self):
        import numpy as np
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / 'cache.npy'
            for vectors in (np.zeros((1, 384)), np.zeros((10, 384)), np.full((10, 384), np.nan),
                            np.zeros((10, 10)), np.zeros(10)):
                np.save(path, vectors)
                self.assertIsNone(load_cached_vectors(path, 10))
            path.write_bytes(b'incomplete npy file')
            self.assertIsNone(load_cached_vectors(path, 10))
            with path.open('wb') as stream:
                np.savez(stream, unexpected=np.ones((10, 384)))
            self.assertIsNone(load_cached_vectors(path, 10))

    def test_valid_unit_vectors_can_be_reused(self):
        import numpy as np
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / 'cache.npy'
            vectors = np.zeros((10, 384), dtype=np.float32)
            vectors[:, 0] = 1
            np.save(path, vectors)
            np.testing.assert_array_equal(load_cached_vectors(path, 10), vectors)
