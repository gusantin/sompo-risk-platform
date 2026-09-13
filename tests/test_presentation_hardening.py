import json
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock, patch

import server
from scripts.seed_demo import preview, PROPERTY_ID, MACHINE_ID
from scripts.scenario_generator import SCENARIOS
from services.alert_service import AlertService, AlertValidationError
from services.firestore_service import FirestoreDocument, FirestoreConflictError, _documento_python, atualizar_documento
from services.recommendation_service import machine_recommendations
from services.sompo_agro_agent.tools import AgroRiskTools


class HardeningTests(unittest.TestCase):
    def test_all_scenarios_are_repeatable_without_firestore(self):
        now = datetime(2026, 9, 12, 12, tzinfo=timezone.utc)
        with patch('services.firebase_client.FirebaseClient.initialize', side_effect=AssertionError('No Firebase')):
            for scenario in SCENARIOS:
                a, b = preview(scenario, now), preview(scenario, now)
                self.assertEqual(a, b)
                state = a['responses'][f'/fazendas/{PROPERTY_ID}/maquinas/{MACHINE_ID}/status']
                self.assertTrue(a['demoData'])
                self.assertTrue(state['identity']['sensoresConfigurados'])
                self.assertTrue(all(item['demoData'] for item in a['alerts']))
                if scenario == 'normal':
                    self.assertEqual(a['alerts'], [])
                    self.assertEqual(state['machineRisk']['level'], 'low')
                if scenario == 'stale_device':
                    self.assertFalse(state['telemetryFreshness']['fresh'])
                    self.assertFalse(state['mapLocation']['current'])
                    self.assertEqual(state['machineRisk']['status'], 'insufficient_data')

    def test_version_is_not_serialized_and_precondition_blocks_lost_update(self):
        doc = _documento_python({'name': 'alerts/a1', 'updateTime': 'revision', 'fields': {'status': {'stringValue': 'open'}}})
        self.assertEqual(doc.update_time, 'revision')
        self.assertNotIn('revision', json.dumps(doc))
        response = Mock(status_code=412)
        with patch('services.firestore_service.requests.patch', return_value=response) as write:
            with self.assertRaises(FirestoreConflictError):
                atualizar_documento('https://fixture/documents', lambda: 'secret', 'alerts', 'a1', {'status': 'acknowledged'}, update_time='revision')
        self.assertEqual(write.call_args.kwargs['params'], {'currentDocument.updateTime': 'revision'})

    def test_alert_uses_revision_duplicate_and_invalid_transitions(self):
        service = AlertService(Mock())
        current = FirestoreDocument(alertId='a1', status='open')
        current.update_time = 'revision'
        with patch.object(service, 'get', return_value=current), patch('services.alert_service.atualizar_documento', side_effect=FirestoreConflictError) as write:
            with self.assertRaises(FirestoreConflictError):
                service.update_status('a1', 'acknowledged')
            self.assertEqual(write.call_args.kwargs['update_time'], 'revision')
        with patch.object(service, 'get', return_value={'status': 'resolved', 'resolvedAt': 'original'}), patch('services.alert_service.atualizar_documento') as write:
            self.assertEqual(service.update_status('a1', 'resolved')['resolvedAt'], 'original')
            with self.assertRaises(AlertValidationError): service.update_status('a1', 'acknowledged')
            write.assert_not_called()

    def test_status_and_copilot_share_recommendations_and_recompute_freshness(self):
        now = datetime.now(timezone.utc)
        bundle = preview('machine_overheat', now)
        machine_status = bundle['responses'][f'/fazendas/{PROPERTY_ID}/maquinas/{MACHINE_ID}/status']
        machine = {**machine_status['identity'], 'maquinaId': 'm1', 'fazendaId': 'f1', 'demoData': False, 'lastLocationAt': now - timedelta(hours=2)}
        state = {**machine_status, 'lastSeenAt': now, 'latestTelemetryAt': now - timedelta(hours=2),
                 'deviceHealth': {'status': 'online'}, 'location': {'locationCurrent': True, 'nearestHotspotDistanceKm': 2}}
        services = [Mock() for _ in range(7)]
        services[2].listar.return_value = [machine]
        services[1].get_machine.return_value = state
        services[4].list.return_value = []
        tools = AgroRiskTools(*services, lambda: {}, lambda: {})
        item = tools.machines_esp32('f1')['items'][0]
        self.assertEqual(item['telemetryFreshness']['status'], 'stale')
        self.assertNotIn('value', item['engineTemperature'])
        with patch.dict(server.app.config, {'TESTING': True}), patch.object(server.maquinas, 'obter', return_value=machine), patch.object(server.propriedades, 'obter', return_value={'fazendaId': 'f1'}), patch.object(server.snapshots, 'get_machine', return_value=state), patch.object(server.snapshots, 'get_property', return_value={}), patch.object(server.alerts, 'list', return_value=[]):
            response = server.app.test_client().get('/fazendas/f1/maquinas/m1/status')
        self.assertEqual(response.status_code, 200)
        status = response.get_json()
        self.assertEqual(status['recommendations'], item['recommendations'])
        self.assertEqual(status['telemetryFreshness']['status'], 'stale')
        self.assertFalse(status['mapLocation']['current'])
        self.assertIsNone(status['location']['nearestHotspotDistanceKm'])
        self.assertEqual(status['deviceHealth']['status'], 'online')

    def test_insufficient_machine_never_gets_overheat_guidance(self):
        guidance = machine_recommendations({'status': 'insufficient_data', 'level': 'critical'}, {'status': 'offline'})
        self.assertEqual([r['ruleId'] for r in guidance], ['device_offline'])
        self.assertTrue(all(r['version'] for r in guidance))


if __name__ == '__main__': unittest.main()
