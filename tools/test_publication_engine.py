import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch
import publication_engine as engine


class PublicationRegression(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / 'gateway_source'
        self.source.mkdir()
        (self.source / 'index.html').write_text('<a href="{{ \'/laws.html\' | relative_url }}">Laws</a>')
        (self.source / 'terra.json').write_text('{"id":"terra"}')
        self.output = self.root / 'docs'
        (self.root / 'manifests').mkdir()
        self.module = dict(id='gateway', source='gateway_source', destination='gateway',
                           entrypoint='index.html', navigation_label='Gateway & Earth', homepage_label='Enter Gateway')
        self.manifest([self.module])

    def manifest(self, modules):
        (self.root / 'manifests/publication-manifest.json').write_text(json.dumps(dict(schema_version=1, modules=modules)))

    def stage(self, name='stage'):
        stage = self.root / name
        stage.mkdir()
        (stage / '_layouts').mkdir()
        (stage / '_layouts/default.html').write_text('<nav>\n      </nav>')
        (stage / 'index.md').write_text('<section>\n  <div>\n  </div>\n</section>\n\n<section class="registry-stats">')
        (stage / 'laws.md').write_text('canonical law projection')
        (stage / engine.MARKER).write_text('generated')
        return stage

    def assembled(self, name='stage'):
        stage = self.stage(name)
        engine.assemble(self.root, stage)
        return stage

    def publish(self):
        engine.promote(self.root, self.output, self.assembled())

    def test_module_copy_navigation_and_inventory(self):
        stage = self.assembled()
        self.assertEqual(engine.inventory(self.source), engine.inventory(stage / 'gateway'))
        self.assertIn('Gateway &amp; Earth', (stage / '_layouts/default.html').read_text())
        self.assertIn('Enter Gateway', (stage / 'index.md').read_text())
        recorded = json.loads((stage / engine.INVENTORY).read_text())['files']
        self.assertEqual(recorded, {k:v for k,v in engine.inventory(stage).items() if k != engine.INVENTORY})

    def test_deterministic_rebuild(self):
        self.assertEqual(engine.inventory(self.assembled('first')), engine.inventory(self.assembled('second')))

    def test_second_module(self):
        shutil.copytree(self.source, self.root / 'site_source/celestial')
        self.manifest([self.module, dict(self.module, id='celestial', source='site_source/celestial', destination='celestial', navigation_label='Celestial')])
        stage = self.assembled()
        self.assertTrue((stage / 'celestial/terra.json').is_file())
        self.assertIn('/celestial/', (stage / '_layouts/default.html').read_text())

    def test_duplicate_module_id(self):
        self.manifest([self.module, dict(self.module, destination='other')])
        with self.assertRaisesRegex(ValueError, 'duplicate module ID'):
            engine.modules(self.root)

    def test_overlapping_destinations(self):
        self.manifest([self.module, dict(self.module, id='other', destination='gateway/sub')])
        with self.assertRaisesRegex(ValueError, 'Overlapping destination'):
            engine.modules(self.root)

    def test_reserved_destination(self):
        self.manifest([dict(self.module, destination='records')])
        with self.assertRaisesRegex(ValueError, 'Reserved core destination'):
            engine.modules(self.root)

    def test_traversal_and_absolute_paths(self):
        for path in ('../canonical', '/tmp/out', 'site_source/../canonical', 'a\\b'):
            with self.subTest(path=path), self.assertRaises(ValueError):
                engine.relative_path(path)

    def test_source_outside_allowlist(self):
        self.manifest([dict(self.module, source='canonical')])
        with self.assertRaisesRegex(ValueError, 'Module sources'):
            engine.modules(self.root)

    def test_missing_entrypoint(self):
        (self.source / 'index.html').unlink()
        with self.assertRaisesRegex(ValueError, 'Missing entrypoint'):
            engine.modules(self.root)

    def test_source_symlink(self):
        (self.source / 'alias').symlink_to(self.source / 'terra.json')
        with self.assertRaisesRegex(ValueError, 'Symlink'):
            engine.modules(self.root)

    def test_broken_module_link(self):
        (self.source / 'index.html').write_text("{{ '/missing.html' | relative_url }}")
        with self.assertRaisesRegex(ValueError, 'Broken module link'):
            self.assembled()

    def test_collision_with_generated_output(self):
        stage = self.stage()
        (stage / 'gateway').mkdir()
        with self.assertRaisesRegex(ValueError, 'collides'):
            engine.assemble(self.root, stage)

    def test_unmarked_output_refused(self):
        self.output.mkdir()
        with self.assertRaisesRegex(ValueError, 'unmarked'):
            engine.promote(self.root, self.output, self.assembled())

    def test_unknown_file_not_deleted(self):
        self.publish()
        (self.output / 'extra.txt').write_text('keep')
        before = engine.inventory(self.output)
        with self.assertRaisesRegex(ValueError, 'Refusing to delete'):
            engine.promote(self.root, self.output, self.assembled('new'))
        self.assertEqual(before, engine.inventory(self.output))

    def test_output_drift_refused(self):
        self.publish()
        (self.output / 'gateway/terra.json').write_text('manual edit')
        with self.assertRaisesRegex(ValueError, 'differs from inventory'):
            engine.promote(self.root, self.output, self.assembled('new'))
        self.assertEqual('manual edit', (self.output / 'gateway/terra.json').read_text())

    def test_check_mode_leaves_output_unchanged(self):
        self.publish()
        before = engine.inventory(self.output)
        stage = self.assembled('new')
        engine.promote(self.root, self.output, stage, check=True)
        self.assertEqual(before, engine.inventory(self.output))
        self.assertTrue(stage.exists())
        self.assertFalse((self.root / '.publication-backups').exists())

    def test_backup_contains_previous_site(self):
        self.publish()
        before = engine.inventory(self.output)
        (self.source / 'terra.json').write_text('{"id":"new"}')
        engine.promote(self.root, self.output, self.assembled('new'))
        backups = list((self.root / '.publication-backups').glob('site-*/docs'))
        self.assertEqual(len(backups), 1)
        self.assertEqual(before, engine.inventory(backups[0]))
        self.assertIn('new', (self.output / 'gateway/terra.json').read_text())

    def test_failed_promotion_restores_original(self):
        self.publish()
        before = engine.inventory(self.output)
        stage = self.assembled('new')
        rename = Path.rename
        def fail_stage(path, target):
            if path == stage:
                raise OSError('simulated promotion failure')
            return rename(path, target)
        with patch.object(Path, 'rename', fail_stage), self.assertRaisesRegex(OSError, 'simulated'):
            engine.promote(self.root, self.output, stage)
        self.assertEqual(before, engine.inventory(self.output))


if __name__ == '__main__':
    unittest.main(verbosity=2)
