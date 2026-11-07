import json
import subprocess
import unittest
from unittest.mock import patch
from app import providers
from app.tenant_ai import AIConfig
from app.usage import estimate, estimate_openai


class UsageTest(unittest.TestCase):
    def setUp(self):
        selected = patch.object(providers, 'configuration', return_value=AIConfig('codex', 'gpt-6.1-terra'))
        selected.start()
        self.addCleanup(selected.stop)

    def test_pricing_subtracts_cached_input_and_preserves_unknown(self):
        cost=estimate('gpt-6.1-sol',{'input_tokens':1000,'cached_input_tokens':800,'output_tokens':100})
        self.assertAlmostEqual(cost,0.00148)
        self.assertIsNone(estimate('unknown',{'input_tokens':1000,'output_tokens':100}))
        self.assertIsNone(estimate('gpt-6.1-sol',{}))

    def test_openai_standard_cost_includes_cache_writes_once_and_not_reasoning_twice(self):
        usage = {'input_tokens': 12000, 'cached_input_tokens': 4000, 'output_tokens': 1000,
                 'reasoning_output_tokens': 900, 'cache_write_tokens': 7000,
                 'cache_write_30m_tokens': 3000, 'cache_write_12h_tokens': 4000,
                 'service_tier': 'default'}
        self.assertAlmostEqual(estimate_openai('gpt-6-luna', usage), 0.002015)
        usage['reasoning_output_tokens'] = 0
        self.assertAlmostEqual(estimate_openai('gpt-6-luna', usage), 0.002015)
        self.assertAlmostEqual(estimate_openai('gpt-6.1-sol', usage), 0.0399)
        self.assertAlmostEqual(estimate_openai('gpt-6.1-terra', usage), 0.01995)

    def test_openai_long_context_rates_apply_after_272000_total_input_tokens(self):
        usage = {'input_tokens': 272000, 'cached_input_tokens': 0, 'output_tokens': 10,
                 'cache_write_tokens': 0, 'cache_write_30m_tokens': 0,
                 'cache_write_12h_tokens': 0, 'service_tier': 'default'}
        self.assertAlmostEqual(estimate_openai('gpt-6-luna', usage), 0.027205)
        usage.update(input_tokens=300000, cached_input_tokens=100000, output_tokens=1000,
                     cache_write_tokens=100000, cache_write_30m_tokens=50000, cache_write_12h_tokens=50000)
        self.assertAlmostEqual(estimate_openai('gpt-6-luna', usage), 0.06025)

    def test_openai_unknown_incomplete_or_inconsistent_usage_is_not_priced_as_zero(self):
        complete = {'input_tokens': 1000, 'cached_input_tokens': 200, 'output_tokens': 100,
                    'cache_write_tokens': 500, 'cache_write_30m_tokens': 500,
                    'cache_write_12h_tokens': 0, 'service_tier': 'default'}
        self.assertIsNone(estimate_openai('unknown-model', complete))
        self.assertIsNone(estimate_openai('gpt-6-luna', None))
        for name in complete:
            incomplete = {k: v for k, v in complete.items() if k != name}
            with self.subTest(missing=name):
                self.assertIsNone(estimate_openai('gpt-6-luna', incomplete))
        for changes in [{'service_tier': 'priority'}, {'cached_input_tokens': None},
                        {'input_tokens': -1}, {'output_tokens': True}, {'output_tokens': '100'},
                        {'cache_write_tokens': 501}, {'cached_input_tokens': 900}]:
            with self.subTest(changes=changes):
                self.assertIsNone(estimate_openai('gpt-6-luna', {**complete, **changes}))

    def test_codex_json_usage_is_collected_without_storing_prompt_or_raw_response(self):
        final={'reply':'Vejo o teste.','action':'none'}
        usage={'input_tokens':1000,'cached_input_tokens':800,'output_tokens':100,'reasoning_output_tokens':10}
        stream='\n'.join(json.dumps(x) for x in [
            {'type':'item.completed','item':{'type':'agent_message','text':json.dumps(final)}},
            {'type':'turn.completed','usage':usage}])
        with patch.object(providers.subprocess,'run',return_value=subprocess.CompletedProcess([],0,stream,'')) as run, \
                patch.object(providers,'record') as record:
            result=providers.reply('private-customer-text',images=[b'jpeg-test-bytes'])
        self.assertEqual(result['reply'],'Vejo o teste.')
        self.assertIn('--json',run.call_args.args[0]);self.assertIn('--image',run.call_args.args[0])
        command=run.call_args.args[0]
        self.assertEqual(command[command.index('--model')+1],'gpt-6.1-terra')
        self.assertIn('features.shell_tool=false',command)
        self.assertIn('features.view_image=false',command)
        self.assertIn('web_search="disabled"',command)
        self.assertTrue(any(value.startswith('model_instructions_file=') for value in command))
        self.assertEqual(run.call_args.kwargs['input'],'private-customer-text')
        self.assertEqual(record.call_args.kwargs['usage'],usage)
        self.assertNotIn('private-customer-text',str(record.call_args))

    def test_failure_keeps_missing_usage_as_unknown(self):
        with patch.object(providers.subprocess,'run',return_value=subprocess.CompletedProcess([],1,'','failure')),patch.object(providers,'record') as record:
            with self.assertRaises(RuntimeError):providers.reply('teste')
        self.assertEqual(record.call_args.args[2],'failed');self.assertIsNone(record.call_args.kwargs['usage'])
