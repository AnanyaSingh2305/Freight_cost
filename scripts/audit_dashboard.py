"""Exercise failure recovery in isolated copies; never alter the live input files."""
import json
from pathlib import Path
import shutil
import sys
import tempfile
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from streamlit.testing.v1 import AppTest
from freight_assistant.pipeline import analyze, save_analysis
from freight_assistant.reporting import file_hash


def clean(app):
    assert not app.exception, [str(error.value) for error in app.exception]


checks = []
with tempfile.TemporaryDirectory() as temporary:
    temporary = Path(temporary)
    for directory in ('assets', 'data', 'freight_assistant'):
        shutil.copytree(ROOT / directory, temporary / directory, ignore=shutil.ignore_patterns('__pycache__'))
    shutil.copyfile(ROOT / 'config.json', temporary / 'config.json')
    rows, audit, cost = analyze(data_dir=temporary / 'data', mode='lexical')
    save_analysis(temporary / 'results', rows, audit, cost)
    with patch('freight_assistant.pipeline.ROOT', temporary):
        app = AppTest.from_file(str(ROOT / 'app.py'), default_timeout=120).run()
        clean(app)
        assert len(app.metric) >= 4
        checks.append('valid saved results load')
        source = temporary / 'data/shipment_records.csv'
        source.write_bytes(source.read_bytes() + b'\n')
        app.run()
        clean(app)
        active = app.session_state['analysis']
        assert active['audit']['input_sha256']['shipment_records.csv'] == file_hash(source)
        assert active['audit']['retriever']['mode'] == 'lexical'
        checks.append('changed inputs recompute existing session instead of returning cached rows')
        # A fresh session must refuse saved results whose input hash is now stale.
        fresh = AppTest.from_file(str(ROOT / 'app.py'), default_timeout=120).run()
        clean(fresh)
        assert fresh.session_state['analysis'] is None
        checks.append('fresh session rejects stale saved inputs')
        (temporary / 'results/audit.json').write_text('{broken')
        recovered = AppTest.from_file(str(ROOT / 'app.py'), default_timeout=120).run()
        clean(recovered)
        assert recovered.warning and recovered.session_state['analysis'] is None
        checks.append('corrupt saved JSON displays a warning without an application exception')
        config = json.loads((temporary / 'config.json').read_text())
        config['minimum_evidence_coverage'] = 0.9
        (temporary / 'config.json').write_text(json.dumps(config))
        evidence = next(widget for widget in recovered.selectbox if widget.label == 'Evidence search')
        evidence.select('Lexical · offline baseline')
        next(button for button in recovered.button if button.label == 'Run analysis').click().run()
        clean(recovered)
        assert recovered.session_state['analysis']['audit']['configuration']['minimum_evidence_coverage'] == 0.9
        assert len(recovered.metric) >= 4
        checks.append('Run analysis recovers and respects config.json evidence settings')
        (temporary / 'results/evaluation.json').write_text('{broken')
        recovered.run()
        clean(recovered)
        assert recovered.warning
        checks.append('corrupt optional evaluation report does not crash the dashboard')

report = {'passed': True, 'checks': checks, 'application_exceptions': 0,
          'method': 'Streamlit AppTest with isolated source/data/results copies; real lexical recomputation.'}
(ROOT / 'results/robustness_checks.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
print(json.dumps(report, indent=2))
