import json
import os
import unittest
from unittest.mock import patch

import httpx


class CallingGraphTest(unittest.TestCase):
    def setUp(self):
        from app.whatsapp import calling_graph
        self.graph = calling_graph
        self.requests = []
        self.response = httpx.Response(200, json={})
        original = httpx.Client

        def respond(request):
            self.requests.append(request)
            if isinstance(self.response, Exception):
                raise self.response
            return self.response

        for mock in [patch.object(calling_graph, 'access_token', return_value='synthetic-secret'),
                     patch.dict(os.environ, {'WHATSAPP_GRAPH_VERSION': 'v23.0'}),
                     patch.object(calling_graph.httpx, 'Client', side_effect=lambda **kw: original(transport=httpx.MockTransport(respond), **kw))]:
            mock.start()
            self.addCleanup(mock.stop)

    def test_connect_and_terminate_wire_contract(self):
        self.response = httpx.Response(200, json={'messaging_product':'whatsapp','calls':[{'id':'wacid.demo'}]})
        self.assertEqual(self.graph.connect('111', 'TOKEN', '15555550102', 'offer', 'operation'), 'wacid.demo')
        req = self.requests[0]
        self.assertEqual(str(req.url), 'https://graph.facebook.com/v23.0/111/calls')
        self.assertEqual(req.headers['authorization'], 'Bearer synthetic-secret')
        self.assertEqual(json.loads(req.content), {'messaging_product':'whatsapp','to':'15555550102',
            'action':'connect','session':{'sdp_type':'offer','sdp':'offer'},'biz_opaque_callback_data':'operation'})
        self.response = httpx.Response(200, json={'success':True})
        self.graph.terminate('111', 'TOKEN', 'wacid.demo')
        self.graph.reject('111', 'TOKEN', 'wacid.incoming')
        self.assertEqual(json.loads(self.requests[1].content), {'messaging_product':'whatsapp','call_id':'wacid.demo','action':'terminate'})
        self.assertEqual(json.loads(self.requests[2].content)['action'], 'reject')

    def test_permission_request_no_undocumented_correlation(self):
        self.response = httpx.Response(200, json={'messages':[{'id':'wamid.request'}]})
        self.assertEqual(self.graph.request_permission('111','TOKEN','15555550102','operation'), 'wamid.request')
        data = json.loads(self.requests[0].content)
        self.assertEqual(data['interactive'], {'type':'call_permission_request','action':{'name':'call_permission_request'}})
        self.assertNotIn('biz_opaque_callback_data', data)

    def test_permission_types_expiration_and_action_gate(self):
        for status, expiration, expected in [('temporary',4102444800,'granted'),('temporary',1,'expired'),
                                              ('permanent',None,'granted'),('no_permission',None,'absent')]:
            with self.subTest(status=status, expiration=expiration):
                permission = {'status':status}
                if expiration is not None:
                    permission['expiration_time'] = expiration
                self.response = httpx.Response(200, json={'permission':permission,'actions':[
                    {'action_name':'start_call','can_perform_action':True},
                    {'action_name':'send_call_permission_request','can_perform_action':True}]})
                result = self.graph.get_permission('111','TOKEN','15555550102')
                self.assertEqual(result['state'], expected)
                self.assertEqual(result['can_call'], expected == 'granted')
                self.assertTrue(result['can_request'])
                self.assertEqual(result['permanent'], status == 'permanent')
        self.assertEqual(self.requests[0].url.params['user_wa_id'], '15555550102')

    def test_permission_missing_actions_or_unknown_schema_fails_closed(self):
        self.response = httpx.Response(200, json={'permission':{'status':'permanent'}})
        result = self.graph.get_permission('111','TOKEN','15555550102')
        self.assertFalse(result['can_call'])
        self.assertFalse(result['can_request'])
        for permission in [{'status':'granted'}, {'status':[]}, {'status':'temporary'}, {'status':'temporary','expiration_time':True}]:
            self.response = httpx.Response(200, json={'permission':permission})
            with self.assertRaises(self.graph.GraphError) as error:
                self.graph.get_permission('111','TOKEN','15555550102')
            self.assertFalse(error.exception.uncertain)

    def test_uncertain_timeout_or_malformed_success_is_never_retried(self):
        for response in [httpx.ReadTimeout('private upstream body'), httpx.Response(200,json={}),
                         httpx.Response(200,text='private invalid json')]:
            self.requests.clear()
            self.response = response
            with self.assertRaises(self.graph.GraphError) as error:
                self.graph.connect('111','TOKEN','15555550102','private SDP','operation')
            self.assertTrue(error.exception.uncertain)
            self.assertEqual(len(self.requests),1)
            self.assertNotIn('private',str(error.exception))

    def test_rejected_http_is_sanitized_and_known_not_sent(self):
        self.response = httpx.Response(400,json={'error':{'code':138006,'message':'private secret'}})
        with self.assertRaises(self.graph.GraphError) as error:
            self.graph.connect('111','TOKEN','15555550102','offer','operation')
        self.assertEqual(error.exception.code, 'permission_required')
        self.assertFalse(error.exception.uncertain)
        self.assertNotIn('private',str(error.exception))

    def test_invalid_path_rejected_before_network(self):
        with self.assertRaises(self.graph.GraphError):
            self.graph.get_permission('../evil','TOKEN','15555550102')
        self.assertEqual(self.requests, [])

    def test_rejection_logs_only_numeric_diagnostics(self):
        for subcode, expected in [(2494000, '2494000'), ('private secret', 'None')]:
            self.response = httpx.Response(400, json={'error':{'code':100, 'error_subcode':subcode,
                'message':'synthetic-secret 15555550102 private SDP', 'error_data':{'details':'private'}}})
            with self.assertLogs('app.whatsapp.calling_graph', level='WARNING') as captured:
                with self.assertRaises(self.graph.GraphError):
                    self.graph.connect('111','TOKEN','15555550102','private SDP','operation')
            output = '\n'.join(captured.output)
            self.assertIn('endpoint=calls action=connect http_status=400 meta_code=100 meta_subcode='+expected, output)
            for private in ['synthetic-secret','15555550102','private','operation']:
                self.assertNotIn(private, output)

    def test_malformed_error_code_stays_public_and_server_failure_uncertain(self):
        self.response = httpx.Response(503,json={'error':{'code':['private']}})
        with self.assertRaises(self.graph.GraphError) as error:
            self.graph.connect('111','TOKEN','15555550102','offer','operation')
        self.assertTrue(error.exception.uncertain)
        self.assertEqual(error.exception.code,'service_unavailable')
