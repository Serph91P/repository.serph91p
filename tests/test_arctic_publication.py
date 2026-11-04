"""Target-side policy for the new skin, without publishing empty packages."""
import unittest
from scripts import build_repository as b

class ArcticPolicyTests(unittest.TestCase):
    def test_exact_source_identity_and_workflow(self):
        config=b._source_config('Serph91P/skin.arctic.fuse.3')
        self.assertEqual(config['addon_id'],'skin.arctic.fuse.3')
        self.assertEqual(config['publication_branch'],'omega')
        self.assertEqual(config['branch'],'omega')
        self.assertEqual(config['validation_workflow_id'],406868734)
        self.assertEqual(config['runtime_entries'],('addon.xml','LICENSE.txt','1080i/','colors/','extras/','fanart.jpg','fonts/','icon.png','language/','media/','shortcuts/'))

    def test_bootstrap_exception_is_skin_only(self):
        pending=[c['addon_id'] for c in b.ADDONS if c.get('bootstrap_pending')]
        self.assertEqual(pending,['skin.arctic.fuse.3'])

    def test_no_leaf_repository_is_added_or_replaced(self):
        self.assertFalse(any(c['addon_id'].startswith('repository.') for c in b.ADDONS))

    def test_unvalidated_or_wrong_branch_skin_is_rejected(self):
        config=b._source_config('Serph91P/skin.arctic.fuse.3')
        run={'id':1,'head_sha':'a'*40,'name':'Add-on Validations','head_branch':'omega','path':'.github/workflows/addon-validations.yml','status':'completed','conclusion':'success','event':'push','repository':{'full_name':'Serph91P/skin.arctic.fuse.3'},'workflow_id':406868734}
        b.validate_github_run(run,1,'a'*40,config)
        for key,value in [('head_branch','develop'),('event','pull_request'),('conclusion','failure'),('workflow_id',1)]:
            with self.assertRaises(RuntimeError): b.validate_github_run(dict(run,**{key:value}),1,'a'*40,config)

if __name__=='__main__':unittest.main()
