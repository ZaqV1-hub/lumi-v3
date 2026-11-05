import json
import subprocess
import unittest
from unittest.mock import patch
from app import providers
from app.usage import estimate


class UsageTest(unittest.TestCase):
    def test_pricing_subtracts_cached_input_and_preserves_unknown(self):
        cost=estimate('gpt-6.1-sol',{'input_tokens':1000,'cached_input_tokens':800,'output_tokens':100})
        self.assertAlmostEqual(cost,0.00148)
        self.assertIsNone(estimate('unknown',{'input_tokens':1000,'output_tokens':100}))
        self.assertIsNone(estimate('gpt-6.1-sol',{}))

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
