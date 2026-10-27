"""Amber's real parallel widget-property families, not fabricated shelf keys."""
import ast
from pathlib import Path
import tempfile
import unittest
from xml.etree import ElementTree as ET
from tests.test_setup_wizard import seed_nodes
from resources.lib.setupwizard import navigation as n, config as c
from resources.lib.setupwizard.common_layouts import common_payloads


class AmberShelfTests(unittest.TestCase):
    def test_native_shelves_match_scoped_common_content(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);seed_nodes(root)
            bindings=n.library_bindings(root,lambda title,options:options.index('Serien') if 'Serien' in options else 0)
            menu=ET.fromstring(common_payloads(root,'amber',bindings)[c.AMBER_MENU])
            for node, group in zip(menu,n.groups(bindings)):
                props=dict(ast.literal_eval(node.findtext('additional-properties')))
                items=[i for i in group.items if i.target=='videos' and i.path is not None]
                for index,item in enumerate(items,1):
                    suffix='' if index==1 else '.'+str(index)
                    self.assertEqual(props['widgetPath'+suffix],item.path)
                    self.assertEqual(props['widgetName'+suffix],item.label)
                    self.assertEqual(props['widgetTarget'+suffix],'video')
                    self.assertIn(props['widget'+suffix],{'Library','Playlist','Addon'})
                    self.assertIn(props['widgetArtwork'+suffix],{'Poster','Thumb','Square'})
                    self.assertEqual(props['widgetLimit'+suffix],'$NUMBER[25]')
                self.assertFalse(any(key.startswith(('shelf','widgetContent')) for key in props))
            series=dict(ast.literal_eval(menu[1].findtext('additional-properties')))
            self.assertEqual(series['widgetType'],'episodes')
            self.assertEqual(series['widgetArtwork'],'Thumb')
            self.assertTrue(all('Twitch_VOD' not in v for k,v in series.items() if k.startswith('widgetPath')))

    def test_unlinked_series_does_not_fall_back_to_global_tvshow_shelves(self):
        with tempfile.TemporaryDirectory() as tmp:
            menu=ET.fromstring(common_payloads(Path(tmp),'amber',n.empty_bindings())[c.AMBER_MENU])
            props=dict(ast.literal_eval(menu[1].findtext('additional-properties')))
            paths=[v for k,v in props.items() if k.startswith('widgetPath') and v]
            self.assertEqual(len(paths),1)  # Only the independent TMDB catalogue is ready.
            self.assertIn('themoviedb.helper',paths[0])
            self.assertFalse(any('videodb://' in path for path in paths))
            self.assertEqual(props['widgetTarget.2'],'false')
            self.assertEqual(props['widgetType.2'],'none')


if __name__=='__main__':unittest.main()
