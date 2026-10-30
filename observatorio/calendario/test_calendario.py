import json, unittest
from pathlib import Path
import ingest_calendario as m
class T(unittest.TestCase):
 def test_parse(self):
  b=(Path(__file__).with_name('fixtures')/'boe_rd806.xml').read_bytes(); d=m.parse(b)
  self.assertEqual(d['source']['documento'],'BOE-A-2026-20742')
  hitos={x['hito']:x['fecha'] for x in d['hitos']}
  self.assertEqual(hitos['Inicio de la campaña electoral'],'2026-11-13')
  self.assertEqual(hitos['Fin de la campaña electoral'],'2026-11-27')
  self.assertEqual(hitos['Jornada electoral'],'2026-11-29')
  self.assertEqual(hitos['Constitución de las Cámaras'],'2026-12-23')
if __name__=='__main__': unittest.main()
