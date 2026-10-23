import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import accounts
import freshness
import radar
from test_accounts import AccountsFixture, AccountsHTTPTest
from manual_delivery import ManualDelivery, refresh_notification_candidates
from test_radar import ISSUE, GOOD

class OnboardingTest(AccountsFixture, unittest.TestCase):
    def test_completion_requires_repos_level_and_preserves_personalization(self):
        self.login()
        with self.assertRaises(ValueError):
            accounts.save_preferences('10', '', False, complete=True)
        with patch.object(accounts, 'verified_repository', return_value='Owner/Repo'):
            accounts.subscribe('10', 'Owner/Repo')
        accounts.save_personalization('10', 2, 'project', ['dev-tools'])
        accounts.save_preferences('10', 'user@example.test', True, complete=True)
        saved = accounts.preferences('10')
        self.assertTrue(saved['onboarding_completed'])
        self.assertEqual(saved['difficulty'], 2)
        self.assertEqual(accounts.delivery_subscribers()[0]['difficulty'], 2)
        accounts.save_preferences('10', '', False)
        self.assertTrue(accounts.preferences('10')['onboarding_completed'])
        self.assertEqual(accounts.preferences('10')['topics'], ['dev-tools'])
        self.assertNotIn('difficulty', accounts.preferences('20'))

    def test_invalid_personalization_does_not_write(self):
        for level, experience, topics in [(True,'new',[]),(4,'new',[]),(1,'invalid',[]),(1,'new',['<script>'])]:
            with self.assertRaises(ValueError):
                accounts.save_personalization('10',level,experience,topics)
        self.assertNotIn('difficulty', accounts.preferences('10'))

class OnboardingHTTPTest(AccountsHTTPTest):
    def test_write_guards_and_returning_login(self):
        secret=self.login()
        payload={'expected_user_id':'10','difficulty':3,'experience':'experienced','topics':[]}
        self.assertEqual(self.request('personalization','POST',payload,secret,origin='https://other.test')[0],403)
        self.assertEqual(self.request('personalization','POST',{**payload,'expected_user_id':'20'},secret)[0],409)
        self.assertEqual(self.request('personalization','POST',payload,secret)[0],200)
        complete={'expected_user_id':'10','email':'','delivery_enabled':False}
        self.assertEqual(self.request('onboarding','POST',complete,secret)[0],400)
        with patch.object(accounts,'verified_repository',return_value='Owner/Repo'):
            accounts.subscribe('10','Owner/Repo')
        self.assertEqual(self.request('onboarding','POST',complete,secret)[0],200)
        _,state=accounts.start_login()
        with patch.object(accounts,'github_json',side_effect=[{'access_token':'test-value'},{'id':10,'login':'octocat'}]):
            status,_,headers=self.request('callback',extra_query='&code=code&state='+state,cookie=accounts.STATE_COOKIE+'='+state)
        self.assertEqual(status,302)
        self.assertEqual(dict(headers)['Location'],accounts.PUBLIC_ORIGIN+'/subscriptions.html')

class NotificationLevelTest(unittest.TestCase):
    def test_each_selected_level_and_legacy_default(self):
        with tempfile.TemporaryDirectory() as directory:
            store=ManualDelivery(Path(directory)/'delivery.sqlite')
            self.addCleanup(store.close)
            rows=[{**radar.normalize_issue('Owner/Repo',ISSUE),'number':level,'grade':{**GOOD,'difficulty':level},
                   'criteria_version':radar.CRITERIA_VERSION,'model':radar.MODEL,'reasoning_effort':radar.REASONING_EFFORT} for level in [1,2,3]]
            for level in [1,2,3]:
                subscribers=[{'user_id':'10','email':'a@example.test','subscriptions':['Owner/Repo'],'difficulty':level}]
                result=store.prepare(rows,subscribers,refresh=lambda r:[{**x,'freshness':{'eligible':True}} for x in r],public_check=lambda _:True)
                self.assertEqual(result[0]['count'],1)
                items=json.loads(store.db.execute('SELECT items FROM digests').fetchone()[0])
                self.assertEqual(items[0]['grade']['difficulty'],level)
            with patch.object(freshness,'apply_freshness',return_value=[]) as refresh:
                refresh_notification_candidates(rows)
                predicate=refresh.call_args.kwargs['candidate']
                self.assertTrue(predicate(rows[2]))
                self.assertFalse(freshness.is_candidate(rows[2]))
