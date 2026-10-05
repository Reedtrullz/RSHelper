"""Actual killed writers and concurrent flock holders, on disposable state."""
import json
import os
from pathlib import Path
import selectors
import subprocess
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_realization as helpers
OP = helpers.OP

WORKER = r'''
import json,sys,time
from pathlib import Path
from rshelper import realization as api, positions, journal
root=Path(sys.argv[1])
positions.POSITIONS_PATH=root/'positions.json'
journal.TRADES_PATH=root/'trades.json'
api._intent_path=lambda profile:root/'realizations.json'
api._manifest_path=lambda profile:root/'identity-manifest.json'
lot,operation,mode=sys.argv[2:5]
if mode.startswith('kill:'):
    def checkpoint(step):
        if step==mode[5:]:
            print('checkpoint:'+step,flush=True)
            while True:time.sleep(1)
    api._checkpoint=checkpoint
else:
    print('ready',flush=True)
    if sys.stdin.readline()!='go\n':raise SystemExit(3)
try:
    print(json.dumps(api.close_and_realize('default',lot,10,120,operation,'manual')),flush=True)
except ValueError as exc:
    print(json.dumps({'error':str(exc)}),flush=True)
    raise SystemExit(2)
'''


class RealizationProcessTest(unittest.TestCase):
    def start(self, root, lot, operation, mode):
        environment = os.environ.copy()
        environment['PYTHONPATH'] = os.pathsep.join(filter(None, (
            environment.get('PYTHONPATH'), str(Path(__file__).resolve().parents[1] / 'src'))))
        environment['HOME'] = str(root)
        child = subprocess.Popen([sys.executable, '-c', WORKER, str(root), lot, operation, mode],
                                 stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                 stderr=subprocess.PIPE, text=True, env=environment)
        self.addCleanup(self.stop, child)
        return child

    @staticmethod
    def stop(child):
        if child.poll() is None:
            child.kill()
        child.communicate(timeout=5)

    def line(self, child):
        with selectors.DefaultSelector() as selector:
            selector.register(child.stdout, selectors.EVENT_READ)
            self.assertTrue(selector.select(10), 'child did not reach checkpoint')
            line = child.stdout.readline().strip()
        self.assertTrue(line, 'child exited before checkpoint')
        return line

    def assert_reconciled(self, root, rows):
        lots = json.loads((root / 'positions.json').read_text())['positions']
        trades = json.loads((root / 'trades.json').read_text())['trades']
        self.assertEqual(len(trades), 1)
        self.assertEqual((trades[0]['qty'], trades[0]['buy_price'], trades[0]['profit']), (10,100,180))
        self.assertEqual(trades[0]['closed_lot_uid'], rows[0]['lot_uid'])
        self.assertEqual([(lot['lot_uid'],lot['qty']) for lot in lots], [(rows[1]['lot_uid'],7)])
        self.assertEqual(sum(lot['qty'] for lot in lots)+sum(trade['qty'] for trade in trades),17)

    def test_killed_process_before_and_after_every_durable_step(self):
        fixture = helpers.RealizationTest()
        api = fixture.api()
        for checkpoint in ('before_intent','intent','before_journal','journal',
                           'before_positions','positions','before_receipt','receipt'):
            with self.subTest(checkpoint=checkpoint),fixture.fixture(api) as (root,rows):
                child=self.start(root,rows[0]['lot_uid'],OP,'kill:'+checkpoint)
                self.assertEqual(self.line(child),'checkpoint:'+checkpoint)
                child.kill()
                child.communicate(timeout=5)
                self.assertLess(child.returncode,0)
                # A fresh process reads disk and performs restart recovery.
                recovery = WORKER.split("lot,operation,mode=sys.argv[2:5]")[0] + "print(json.dumps(api.recover_pending('default')),flush=True)"
                environment = os.environ.copy()
                environment['PYTHONPATH']=os.pathsep.join(filter(None, (
                    environment.get('PYTHONPATH'), str(Path(__file__).resolve().parents[1]/'src'))))
                environment['HOME']=str(root)
                result=subprocess.run([sys.executable,'-c',recovery,str(root)],env=environment,
                                      capture_output=True,text=True,timeout=10)
                self.assertEqual(result.returncode,0,result.stderr)
                api.close_and_realize('default',rows[0]['lot_uid'],10,120,OP,'manual')
                self.assert_reconciled(root,rows)
                self.assertFalse(list(root.glob('.realization-*')))

    def test_two_processes_reuse_same_operation_once(self):
        self.race(same_operation=True)

    def test_two_processes_competing_operations_cannot_consume_same_units(self):
        self.race(same_operation=False)

    def race(self,same_operation):
        fixture=helpers.RealizationTest();api=fixture.api()
        with fixture.fixture(api) as (root,rows):
            other=OP if same_operation else '33333333-3333-4333-8333-333333333333'
            children=[self.start(root,rows[0]['lot_uid'],operation,'race') for operation in (OP,other)]
            for child in children:self.assertEqual(self.line(child),'ready')
            for child in children:child.stdin.write('go\n');child.stdin.flush()
            outcomes=[]
            for child in children:
                output,error=child.communicate(timeout=10)
                self.assertIn(child.returncode,(0,2),error)
                outcomes.append(json.loads(output))
            if same_operation:
                self.assertEqual(sorted(row['replayed'] for row in outcomes),[False,True])
                self.assertEqual(outcomes[0]['trade_ids'],outcomes[1]['trade_ids'])
            else:self.assertEqual(sum('error' in row for row in outcomes),1)
            self.assert_reconciled(root,rows)


if __name__ == '__main__':unittest.main()
